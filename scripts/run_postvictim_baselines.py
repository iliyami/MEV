#!/usr/bin/env python3
"""R6 — the post-victim baselines paper 1 never measured.

`run_backrun_sandwich_simple_campaign.py` hard-codes
`ATTACK_MODES = ["fissure", "speculative", "sluggish"]` with no baseline arm, so the
back-run and sandwich results in paper 1 have no control. `sec_exp.tex` falls back on the
*pairwise frontrun* ~50% reference, which is not a neutral reference for an L1 back-run rate
or a triplet sandwich rate: with 4 attackers among 13 validators a back-run has a large
chance component, so an unanchored "L1 = 34.81%" cannot be read as an attack effect.

HOW THE CONTROL IS BUILT (this took one wrong attempt to get right).
The protocols' own *baseline* tests cannot be used: they compute frontrun ASR only and ignore
`ATTACK_TYPE` entirely, so running them with `ATTACK_TYPE=backrun` silently returns the
frontrun baseline. Verified directly: `test_baseline_13_nodes_no_attack` has no `ATTACK_TYPE`
branch, and its "backrun" and "sandwich" runs returned the same ~51.5 number.

Instead we run the *attack* test with `ATTACK_MODE=none`. `is_mev_attack_mode()`
(`mysticeti-core/src/core.rs:147`) matches only fissure/speculative/sluggish/certification_race,
so "none" leaves `is_attacker = false` and the attacker does nothing, while `calculate_asr()`
still reads `ATTACK_TYPE` and runs the post-victim measurement. That yields the post-victim
metrics with nothing armed, which is exactly the missing control, with no protocol code change.

Every A1 row is then reported as a lift over this control. If the lift is near zero, that is
the finding, and it is a stronger one than an unanchored 100%.

Usage (on the node, inside the container):
    python3 scripts/run_postvictim_baselines.py --reps 5
    python3 scripts/run_postvictim_baselines.py --reps 5 --protocols mysticeti,bullshark
"""

from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CODE = ROOT / "code"

# protocol -> (tree, cargo package, baseline test name, rust toolchain)
#
# NOTE ON LABELS: `code/bullshark` is Sui v1.58 (Mysticeti consensus), NOT classic Bullshark
# -- see the protocol-identity audit. Paper 1's post-victim "Bullshark" column is this tree,
# so results from it must carry the corrected label wherever they are published.
PROTOCOLS = {
    "bullshark": ("bullshark", "consensus-core", "test_fissure_attack_asr_dynamic", "1.92"),
    "mysticeti": ("mysticeti", "mysticeti-core", "test_fissure_attack_asr_13_nodes", "1.72.1"),
    "alephbft": ("alephbft", "aleph-bft", "test_fissure_attack_asr_13_nodes", "1.85"),
    "autobahn": ("autobahn-artifact", "primary", "test_autobahn_asr", "1.97.0"),
}

ATTACK_TYPES = ["backrun", "sandwich"]

BASE_ENV = {
    "NUM_NODES": "13",
    "ATTACKER_RATIO": "0.308",
    "VICTIM_RATIO": "0.231",
}

# The protocols print their post-victim scores with these markers. We capture every one we
# find rather than assuming a single format, and record which matched, so a silent format
# drift shows up as "no metrics parsed" instead of a wrong number.
PATTERNS = {
    "l1": re.compile(r'"l1_asr"\s*:\s*([0-9]+\.?[0-9]*)'),
    "l2": re.compile(r'"l2_asr"\s*:\s*([0-9]+\.?[0-9]*)'),
    "cumulative": re.compile(r'"cumulative_asr"\s*:\s*([0-9]+\.?[0-9]*)'),
    "sandwich": re.compile(r'"sandwich_asr"\s*:\s*([0-9]+\.?[0-9]*)|FINAL_SANDWICH[_A-Z]*:\s*\{?[^0-9]*([0-9]+\.?[0-9]*)'),
    "final_asr": re.compile(r"FINAL_ASR_RESULT[:=]\s*([0-9]+\.?[0-9]*)", re.I),
}


def run_one(protocol: str, attack_type: str, rep: int, timeout: int) -> dict:
    tree, package, test_name, toolchain = PROTOCOLS[protocol]
    cwd = CODE / tree
    if not cwd.is_dir():
        return {"error": f"tree missing: {cwd}"}

    env = os.environ.copy()
    env.update(BASE_ENV)
    env["ATTACK_TYPE"] = attack_type
    env["RUSTUP_TOOLCHAIN"] = toolchain
    env["CARGO_BUILD_JOBS"] = "4"
    env["RUST_TEST_THREADS"] = "1"
    # The baseline tests clear these themselves; clearing here too means a stale value in the
    # parent environment can never reach the run.
    for k in ("EXCLUSION_PROBABILITY", "VICTIM_DELAY_MS",
              "SPECULATIVE_P_MAX", "SLUGGISH_TIMEOUT_MULTIPLIER", "NO_ATTACK"):
        env.pop(k, None)
    env["ATTACK_MODE"] = "none"   # not in is_mev_attack_mode() => attacker does nothing
    env["BASELINE_SEED"] = str(900 + rep)

    cmd = ["nice", "-n", "15", "cargo", "test", "-p", package, "--lib", test_name,
           "--", "--nocapture"]
    try:
        proc = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True,
                              text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"error": "timeout"}

    out = proc.stdout + proc.stderr
    metrics = {}
    for name, pat in PATTERNS.items():
        m = pat.findall(out)
        if not m:
            continue
        last = m[-1]
        # A pattern with alternation yields tuples from findall; take the group that matched.
        if isinstance(last, tuple):
            last = next((g for g in last if g), "")
        if last:
            metrics[name] = float(last)
    return {"exit": proc.returncode, "metrics": metrics,
            "parsed": bool(metrics), "tail": out[-1500:] if not metrics else ""}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=5)
    ap.add_argument("--protocols", default=",".join(PROTOCOLS))
    ap.add_argument("--timeout", type=int, default=1800)
    ap.add_argument("--out", default="results/postvictim_baselines.json")
    args = ap.parse_args()

    selected = [p.strip() for p in args.protocols.split(",") if p.strip()]
    results: dict = {}

    for protocol in selected:
        if protocol not in PROTOCOLS:
            print(f"unknown protocol {protocol!r}, skipping", flush=True)
            continue
        for attack_type in ATTACK_TYPES:
            key = f"{protocol}/{attack_type}"
            print(f"\n=== {key} : {args.reps} reps (NO ATTACK ARMED) ===", flush=True)
            reps = []
            for rep in range(args.reps):
                r = run_one(protocol, attack_type, rep, args.timeout)
                reps.append(r)
                if r.get("error"):
                    print(f"  rep {rep+1}/{args.reps}  ERROR: {r['error']}", flush=True)
                elif not r["parsed"]:
                    print(f"  rep {rep+1}/{args.reps}  NO METRICS PARSED "
                          f"(exit={r['exit']}) -- format drift, see tail in JSON", flush=True)
                else:
                    print(f"  rep {rep+1}/{args.reps}  {r['metrics']}", flush=True)
            results[key] = reps

            # Median and range per metric, so the control is reported exactly the way the
            # attack cells are.
            agg = {}
            for name in PATTERNS:
                vals = [r["metrics"][name] for r in reps
                        if r.get("parsed") and name in r["metrics"]]
                if vals:
                    agg[name] = {"median": statistics.median(vals),
                                 "range": [min(vals), max(vals)],
                                 "n": len(vals), "reps": vals}
            results[key + "/agg"] = agg
            if agg:
                print(f"  -> {json.dumps(agg)}", flush=True)
            else:
                print("  -> NO AGGREGATE: nothing parsed. Do not report a number for this "
                      "cell; fix the marker pattern first.", flush=True)

    out_path = ROOT / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(results, indent=2))
    print(f"\nwrote {out_path}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
