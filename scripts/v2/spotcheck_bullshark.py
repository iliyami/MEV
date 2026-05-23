"""P0 gate script: run three Bullshark cells through the v2 harness and
compare against paper-1 reference numbers from the manifest.

Cells:
    1. frontrun / fissure (paper-1 ref median ~92.30%)
    2. frontrun / speculative (~93.00%)
    3. frontrun / sluggish (~91.40%)

5 reps per cell (field convention). For each cell we compute the median ASR
across reps and ask `baselines.check_against_paper1` whether it sits within
the manifest's tolerance. A non-empty findings list = contradiction = the
gate is NOT met; investigate before admitting the data.

Usage:
    python -m scripts.v2.spotcheck_bullshark --out results/v2_p0_spotcheck.csv
    python -m scripts.v2.spotcheck_bullshark --dry-run
    python -m scripts.v2.spotcheck_bullshark --cells fissure  # subset

Invariant (CLAUDE.md): this script invokes the existing v1 test_runner only.
No Bullshark core logic is modified.
"""

from __future__ import annotations

import argparse
import json
import statistics as st
import sys
import time
from pathlib import Path
from typing import Iterable, Optional

# Editable import path
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from scripts.v2 import baselines as ref
from scripts.v2 import schema, sweeper
from scripts.v2.launchers.bullshark import BullsharkLauncher


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_REPS = 5

# n=13 + ATTACKER_RATIO=0.308 + VICTIM_RATIO=0.231 matches the paper-1
# default-config row in experiment_results.csv that we extracted.
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

CELLS = [
    ("frontrun", "fissure"),
    ("frontrun", "speculative"),
    ("frontrun", "sluggish"),
]


def _build_cfg(family: str, strategy: str, reps: int) -> schema.V2Config:
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
        "adversary": {"threat_model": "TM-Solo", "archetype": "homogeneous"},
        "victims": {"workload": "single", "count": 1},
        "runtime": {"reps": reps, "seed": 0},
    }
    return schema.parse_config(raw)


def run_cell(
    family: str,
    strategy: str,
    reps: int,
    launcher: BullsharkLauncher,
    dry_run: bool,
) -> tuple[list[float], list[float]]:
    """Run reps of (family, strategy) cell. Returns (asrs, durations)."""
    cfg = _build_cfg(family, strategy, reps)
    asrs: list[float] = []
    durations: list[float] = []
    for rep in range(reps):
        req = sweeper.RunRequest(
            config=cfg, rep=rep, seed=rep, run_id=sweeper.make_run_id(cfg, rep)
        )
        print(
            f"  rep={rep + 1}/{reps} cell=({family},{strategy}) "
            f"run_id={req.run_id} ...",
            flush=True,
        )
        if dry_run:
            print("    [dry-run] would invoke BullsharkLauncher.run(...)")
            continue
        t0 = time.time()
        result = launcher.run(req)
        durations.append(time.time() - t0)
        asr = result.metrics.get("asr")
        if asr is None:
            print(
                f"    !! ASR=None exit={result.exit_code} -- log lost in subprocess; "
                f"check {REPO_ROOT}/results/ for traces"
            )
        else:
            print(f"    asr={asr:.2f}% exit={result.exit_code} duration={durations[-1]:.1f}s")
            asrs.append(float(asr))
    return asrs, durations


def report_cell(family: str, strategy: str, asrs: list[float]) -> list[str]:
    if not asrs:
        return [f"({family},{strategy}): no successful reps; cannot compare"]
    median_pct = st.median(asrs)
    findings = ref.check_against_paper1(median_pct, family, strategy, metric="asr")
    label = "OK" if not findings else "CONTRADICTION"
    print(
        f"  → ({family},{strategy}): observed median {median_pct:.2f}% "
        f"(min {min(asrs):.2f}, max {max(asrs):.2f}, n={len(asrs)}) [{label}]"
    )
    for f in findings:
        print(f"     {f}")
    return findings


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="spotcheck_bullshark")
    parser.add_argument(
        "--reps", type=int, default=DEFAULT_REPS, help=f"reps per cell (default {DEFAULT_REPS})"
    )
    parser.add_argument(
        "--cells",
        nargs="*",
        choices=["fissure", "speculative", "sluggish"],
        help="DAG strategies to run (default: all three)",
    )
    parser.add_argument(
        "--out", default="results/v2_p0_spotcheck.json", help="JSON output path"
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--no-local",
        action="store_true",
        help="omit --local from the v1 runner invocation (Docker path)",
    )
    parser.add_argument(
        "--skip-build", action="store_true", help="pass --no-build to the v1 runner"
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    chosen = set(args.cells) if args.cells else {"fissure", "speculative", "sluggish"}
    cells = [(f, s) for (f, s) in CELLS if s in chosen]

    launcher = BullsharkLauncher(
        local_mode=not args.no_local, skip_build=args.skip_build
    )

    print(f"v2 P0 spot-check: {len(cells)} cell(s) x {args.reps} rep(s)")
    print(f"  reference manifest: scripts/v2/refs/paper1_bullshark_baselines.json")
    print(f"  invariant: no protocol-core modification (CLAUDE.md)")

    summary: dict = {"cells": [], "all_clean": True, "dry_run": args.dry_run}
    for family, strategy in cells:
        print(f"\nCell ({family}, {strategy}):")
        asrs, _durations = run_cell(family, strategy, args.reps, launcher, args.dry_run)
        if args.dry_run:
            summary["cells"].append(
                {"family": family, "strategy": strategy, "skipped": True}
            )
            continue
        findings = report_cell(family, strategy, asrs)
        cell_clean = not findings
        if not cell_clean:
            summary["all_clean"] = False
        summary["cells"].append(
            {
                "family": family,
                "strategy": strategy,
                "asrs": asrs,
                "median_pct": st.median(asrs) if asrs else None,
                "findings": findings,
                "clean": cell_clean,
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
        print("\nP0 GATE: FAILED -- contradiction(s) found above.")
        return 2
    if not args.dry_run:
        print("\nP0 GATE: PASSED -- all cells within paper-1 tolerance.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
