"""P2 Sui — Competition campaign (matching Bullshark P2 v3 cells).

Cells mirror p2v3_competition.py but target Sui/Mysticeti via SuiLauncher.
Expected result: all cells produce ~52% all-pairs ASR (Mysticeti resilience).

Usage:
    python -m scripts.v2.p2_sui_competition
    python -m scripts.v2.p2_sui_competition --reps 5
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Iterable, Optional

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from scripts.v2 import benchmark, schema, sweeper
from scripts.v2.launchers.sui import SuiLauncher

DEFAULT_CSV = "results/sui_p2_competition_results.csv"
DEFAULT_SUMMARY = "results/sui_p2_competition_summary.json"
DEFAULT_REPS = 5
BASE_SEED = 100

_BASE_ENV = {
    "NUM_NODES": "13",
    "ATTACKER_RATIO": "0.308",
    "VICTIM_RATIO": "0.231",
    "SPECULATIVE_P_MAX": "50",
    "SLUGGISH_TIMEOUT_MULTIPLIER": "2.0",
    "GC_DEPTH": "10",
    "COLLECTION_DURATION": "45",
    "MIN_COMMITS": "25",
}

_LAUNCHER = SuiLauncher(use_coordinator=False)


def _cfg(policies: list[dict], reps: int,
         threat_model: str = "TM-Compete",
         env_overrides: Optional[dict] = None) -> schema.V2Config:
    env = dict(_BASE_ENV)
    if env_overrides:
        env.update(env_overrides)
    strategy = policies[0]["strategy"] if policies else "fissure"
    raw = {
        "protocol": {"name": "sui", "path": "sui"},
        "environment": env,
        "adversary": {
            "threat_model": threat_model,
            "topology": {"policies": policies},
        },
        "victims": {"workload": "single", "count": 1},
        "runtime": {"reps": reps, "seed": BASE_SEED},
    }
    return sweeper.expand_policy_vector(schema.parse_config(raw))


def build_cells(reps: int = DEFAULT_REPS) -> list[benchmark.Cell]:
    cells = []

    # H1.1 k-curve
    cells.append(benchmark.Cell(
        name="k1_homo_fissure",
        config=_cfg([
            {"group_id": "g0", "members": [0, 1, 2, 3], "family": "frontrun",
             "strategy": "fissure", "params": {}}
        ], reps, threat_model="TM-Solo"),
        launcher=_LAUNCHER,
    ))

    cells.append(benchmark.Cell(
        name="k2_split",
        config=_cfg([
            {"group_id": "g0", "members": [0, 1], "family": "frontrun",
             "strategy": "fissure", "params": {}},
            {"group_id": "g1", "members": [2, 3], "family": "frontrun",
             "strategy": "speculative", "params": {}},
        ], reps),
        launcher=_LAUNCHER,
    ))

    cells.append(benchmark.Cell(
        name="k3_split",
        config=_cfg([
            {"group_id": "g0", "members": [0, 1], "family": "frontrun",
             "strategy": "fissure", "params": {}},
            {"group_id": "g1", "members": [2], "family": "frontrun",
             "strategy": "speculative", "params": {}},
            {"group_id": "g2", "members": [3], "family": "frontrun",
             "strategy": "sluggish", "params": {}},
        ], reps),
        launcher=_LAUNCHER,
    ))

    cells.append(benchmark.Cell(
        name="k4_split",
        config=_cfg([
            {"group_id": "g0", "members": [0], "family": "frontrun",
             "strategy": "fissure", "params": {}},
            {"group_id": "g1", "members": [1], "family": "frontrun",
             "strategy": "speculative", "params": {}},
            {"group_id": "g2", "members": [2], "family": "frontrun",
             "strategy": "sluggish", "params": {}},
            {"group_id": "g3", "members": [3], "family": "frontrun",
             "strategy": "fissure", "params": {}},
        ], reps),
        launcher=_LAUNCHER,
    ))

    # H1.2 same-victim overlap
    cells.append(benchmark.Cell(
        name="overlap_same_victim",
        config=_cfg([
            {"group_id": "g0", "members": [0, 1], "family": "frontrun",
             "strategy": "fissure", "params": {}},
            {"group_id": "g1", "members": [2, 3], "family": "frontrun",
             "strategy": "fissure", "params": {}},
        ], reps),
        launcher=_LAUNCHER,
    ))

    cells.append(benchmark.Cell(
        name="overlap_diff_victims",
        config=_cfg([
            {"group_id": "g0", "members": [0, 1], "family": "frontrun",
             "strategy": "fissure", "params": {}},
            {"group_id": "g1", "members": [2, 3], "family": "frontrun",
             "strategy": "fissure", "params": {}},
        ], reps, env_overrides={"VICTIM_RATIO": "0.154"}),
        launcher=_LAUNCHER,
    ))

    # Baseline (no attack)
    cells.append(benchmark.Cell(
        name="baseline_no_attack",
        config=_cfg([
            {"group_id": "g0", "members": [0, 1, 2, 3], "family": "frontrun",
             "strategy": "fissure", "params": {}}
        ], reps, threat_model="TM-Solo"),
        launcher=SuiLauncher(use_coordinator=False),
    ))

    return cells


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="p2_sui_competition")
    parser.add_argument("--out-csv", default=DEFAULT_CSV)
    parser.add_argument("--out-summary", default=DEFAULT_SUMMARY)
    parser.add_argument("--reps", type=int, default=DEFAULT_REPS)
    args = parser.parse_args(list(argv) if argv is not None else None)

    csv_p = Path(args.out_csv)
    csv_p.parent.mkdir(parents=True, exist_ok=True)
    if csv_p.exists():
        csv_p.unlink()

    cells = build_cells(reps=args.reps)
    print(f"P2 Sui Competition: {len(cells)} cells × {args.reps} reps")

    summaries = benchmark.run_benchmark(
        cells=cells,
        out_csv=args.out_csv,
        out_summary_json=args.out_summary,
        reps=args.reps,
        progress_callback=lambda msg: print(msg, flush=True),
    )
    print("\nPer-cell summary:")
    for name, s in summaries.items():
        print(f"  [{name:24s}] n={s.reps} mean={s.asr_mean:.2f}% "
              f"median={s.asr_median:.2f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
