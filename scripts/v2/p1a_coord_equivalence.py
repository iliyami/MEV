"""P1a equivalence check: with the Coordinator configured to a single
homogeneous policy that *exactly* mirrors paper-1's attacker set, the
Bullshark result must match the paper-1 env-var-only path within the
existing per-cell tolerance from `paper1_bullshark_baselines.json`.

This is the load-bearing regression contract for the Rust edit: it proves
that turning the Coordinator path *on* with paper-1-equivalent settings is
behaviorally a no-op, so any later multi-policy result is attributable to
the actual multi-policy configuration, not to harness drift.

Usage:
    python -m scripts.v2.p1a_coord_equivalence --reps 5 \\
        --out results/v2_p1a_coord_equivalence.json
    python -m scripts.v2.p1a_coord_equivalence --dry-run

Invariant: no protocol-core modification.
"""

from __future__ import annotations

import argparse
import json
import statistics as st
import sys
import time
from pathlib import Path
from typing import Iterable, Optional

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from scripts.v2 import baselines as ref
from scripts.v2 import schema, sweeper
from scripts.v2.launchers.bullshark import BullsharkLauncher


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_REPS = 5

# Paper-1 default config knobs (same as scripts/v2/spotcheck_bullshark.py).
DEFAULT_ENV = {
    "NUM_NODES": "13",
    "ATTACKER_RATIO": "0.308",
    "VICTIM_RATIO": "0.231",
    "SPECULATIVE_P_MAX": "50",
    "SLUGGISH_TIMEOUT_MULTIPLIER": "1.5",
    "DAG_STATE_CACHED_ROUNDS": "5",
    "SYNC_TIMEOUT_MS": "2000",
    "GC_DEPTH": "10",
}


def _byzantine_ids(n: int, attacker_ratio: float, family: str) -> list[int]:
    """Mirror Bullshark's paper-1 index-range layout."""
    attacker_count = round(n * attacker_ratio)
    if family == "frontrun":
        return list(range(attacker_count))
    if family == "backrun":
        victim_count = round(n * float(DEFAULT_ENV["VICTIM_RATIO"]))
        return list(range(victim_count, victim_count + attacker_count))
    if family == "sandwich":
        front_count = attacker_count // 2
        back_count = attacker_count - front_count
        victim_count = round(n * float(DEFAULT_ENV["VICTIM_RATIO"]))
        back_start = front_count + victim_count
        return list(range(front_count)) + list(range(back_start, back_start + back_count))
    raise ValueError(family)


def _build_cfg(family: str, strategy: str, reps: int) -> schema.V2Config:
    """Build a v2 config that mirrors paper-1's attacker set as a single homogeneous policy.

    The Coordinator will be initialized with this policy. Bullshark replicas
    whose own_index is in the Byzantine list get the same (family, strategy)
    they would have gotten via env vars. Honest replicas get a 404 -> no
    attack code runs (matching the env-var path).
    """
    n = int(DEFAULT_ENV["NUM_NODES"])
    attacker_ratio = float(DEFAULT_ENV["ATTACKER_RATIO"])
    byz_ids = _byzantine_ids(n, attacker_ratio, family)
    raw = {
        "protocol": {"name": "bullshark", "path": "bullshark"},
        "docker": {"tag": "mev-bullshark:latest", "cpus": "8.0", "memory": "16g"},
        "test": {"test_name": f"test_{strategy}_attack_asr_dynamic", "REPETITIONS": 1},
        "environment": {
            **DEFAULT_ENV,
            "ATTACK_MODE": strategy,
            "ATTACK_FAMILY": family,
            "DAG_STRATEGY": strategy,
            "ATTACK_TYPE": family,
        },
        "adversary": {
            "threat_model": "TM-Solo",
            "topology": {
                "policies": [
                    {
                        "group_id": "g0",
                        "members": byz_ids,
                        "family": family,
                        "strategy": strategy,
                        "params": {},
                    }
                ]
            },
        },
        "victims": {"workload": "single", "count": 1},
        "runtime": {"reps": reps, "seed": 0},
    }
    return schema.parse_config(raw)


def run_cell(
    family: str, strategy: str, reps: int, launcher: BullsharkLauncher, dry_run: bool
) -> list[float]:
    cfg = _build_cfg(family, strategy, reps)
    asrs: list[float] = []
    for rep in range(reps):
        req = sweeper.RunRequest(
            config=cfg, rep=rep, seed=rep, run_id=sweeper.make_run_id(cfg, rep)
        )
        print(f"  rep={rep + 1}/{reps} cell=({family},{strategy}) ...", flush=True)
        if dry_run:
            print("    [dry-run] would run with V2_COORDINATOR_URL set")
            continue
        t0 = time.time()
        result = launcher.run(req)
        dur = time.time() - t0
        asr = result.metrics.get("asr")
        if asr is None:
            print(f"    !! ASR=None exit={result.exit_code} (duration {dur:.1f}s)")
        else:
            print(f"    asr={asr:.2f}% exit={result.exit_code} duration={dur:.1f}s")
            asrs.append(float(asr))
    return asrs


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="p1a_coord_equivalence")
    parser.add_argument("--reps", type=int, default=DEFAULT_REPS)
    parser.add_argument(
        "--cells",
        nargs="*",
        choices=["fissure", "speculative", "sluggish"],
        help="DAG strategies to run (default: all three)",
    )
    parser.add_argument(
        "--out", default="results/v2_p1a_coord_equivalence.json", help="JSON output path"
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)

    chosen = set(args.cells) if args.cells else {"fissure", "speculative", "sluggish"}
    cells = [("frontrun", s) for s in ("fissure", "speculative", "sluggish") if s in chosen]

    # Force the Coordinator ON, even though policies materialize for TM-Solo.
    launcher = BullsharkLauncher(use_coordinator=True)

    print(f"v2 P1a coordinator-equivalence: {len(cells)} cell(s) x {args.reps} rep(s)")
    print("  Coordinator forced ON; single homogeneous policy mirrors paper 1's attacker set.")
    print("  Acceptance: each cell's median ASR within paper-1 tolerance.")

    summary: dict = {"cells": [], "all_clean": True, "dry_run": args.dry_run}
    for family, strategy in cells:
        print(f"\nCell ({family}, {strategy}):")
        asrs = run_cell(family, strategy, args.reps, launcher, args.dry_run)
        if args.dry_run:
            summary["cells"].append(
                {"family": family, "strategy": strategy, "skipped": True}
            )
            continue
        if not asrs:
            print(f"  → ({family},{strategy}): no successful reps")
            summary["all_clean"] = False
            summary["cells"].append(
                {"family": family, "strategy": strategy, "error": "no_runs"}
            )
            continue
        median_pct = st.median(asrs)
        findings = ref.check_against_paper1(median_pct, family, strategy, metric="asr")
        label = "OK" if not findings else "CONTRADICTION"
        print(
            f"  → ({family},{strategy}): observed median {median_pct:.2f}% "
            f"(min {min(asrs):.2f}, max {max(asrs):.2f}, n={len(asrs)}) [{label}]"
        )
        for f in findings:
            print(f"     {f}")
        if findings:
            summary["all_clean"] = False
        summary["cells"].append(
            {
                "family": family,
                "strategy": strategy,
                "asrs": asrs,
                "median_pct": median_pct,
                "findings": findings,
                "clean": not findings,
                "ref": {
                    "median_pct": ref.reference_cell(family, strategy, "asr").median_pct,
                    "tolerance_pp": ref.reference_cell(family, strategy, "asr").tolerance_pp,
                },
            }
        )

    out_path = Path(args.out)
    if not args.dry_run:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w") as fh:
            json.dump(summary, fh, indent=2)
        print(f"\nwrote {out_path}")

    if not summary["all_clean"]:
        print("\nP1a EQUIVALENCE: FAILED -- coord-on path diverges from paper 1.")
        return 2
    if not args.dry_run:
        print("\nP1a EQUIVALENCE: PASSED -- coord-on path matches paper 1 within tolerance.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
