"""P2c Sui — Family-mix campaign (matching Bullshark P2 v3c cells).

Tests per-attacker family selection on Mysticeti: frontrun vs backrun
vs sandwich attackers on a shared victim set.

Usage:
    python -m scripts.v2.p2c_sui_familymix
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Iterable, Optional

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from scripts.v2 import benchmark, schema, sweeper
from scripts.v2.launchers.sui import SuiLauncher

DEFAULT_CSV = "results/sui_p2c_familymix_results.csv"
DEFAULT_SUMMARY = "results/sui_p2c_familymix_summary.json"
DEFAULT_REPS = 5
BASE_SEED = 150

_BASE_ENV = {
    "NUM_NODES": "13",
    "ATTACKER_RATIO": "0.308",
    "VICTIM_RATIO": "0.231",
    "GC_DEPTH": "10",
    "COLLECTION_DURATION": "45",
    "MIN_COMMITS": "25",
}

_VICTIM_SET = [10, 11, 12]
_LAUNCHER = SuiLauncher(use_coordinator=False)


def _cfg(policies: list[dict], reps: int,
         threat_model: str = "TM-Compete") -> schema.V2Config:
    raw = {
        "protocol": {"name": "sui", "path": "sui"},
        "environment": dict(_BASE_ENV),
        "adversary": {
            "threat_model": threat_model,
            "topology": {"policies": policies},
        },
        "victims": {
            "workload": "multi_pareto",
            "count": 3,
            "victim_node_ids": _VICTIM_SET,
            "profit": {"distribution": "uniform", "params": {"scale": 1.0}},
        },
        "runtime": {"reps": reps, "seed": BASE_SEED},
    }
    return sweeper.expand_policy_vector(schema.parse_config(raw))


def build_cells(reps: int = DEFAULT_REPS) -> list[benchmark.Cell]:
    return [
        benchmark.Cell(
            name="fm_same_family_2front",
            config=_cfg([
                {"group_id": "g0", "members": [0, 1], "family": "frontrun",
                 "strategy": "fissure", "params": {}},
                {"group_id": "g1", "members": [2, 3], "family": "frontrun",
                 "strategy": "fissure", "params": {}},
            ], reps),
            launcher=_LAUNCHER,
        ),
        benchmark.Cell(
            name="fm_mixed_2front_2back",
            config=_cfg([
                {"group_id": "g_front", "members": [0, 1], "family": "frontrun",
                 "strategy": "fissure", "params": {}},
                {"group_id": "g_back", "members": [2, 3], "family": "backrun",
                 "strategy": "fissure", "params": {}},
            ], reps),
            launcher=_LAUNCHER,
        ),
        benchmark.Cell(
            name="fm_same_family_4front",
            config=_cfg([
                {"group_id": "g0", "members": [0, 1, 2, 3], "family": "frontrun",
                 "strategy": "fissure", "params": {}},
            ], reps, threat_model="TM-Solo"),
            launcher=_LAUNCHER,
        ),
        benchmark.Cell(
            name="fm_mixed_3way",
            config=_cfg([
                {"group_id": "g_front", "members": [0, 1], "family": "frontrun",
                 "strategy": "fissure", "params": {}},
                {"group_id": "g_back", "members": [2], "family": "backrun",
                 "strategy": "fissure", "params": {}},
                {"group_id": "g_sand", "members": [3], "family": "sandwich",
                 "strategy": "fissure", "params": {}},
            ], reps),
            launcher=_LAUNCHER,
        ),
    ]


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="p2c_sui_familymix")
    parser.add_argument("--out-csv", default=DEFAULT_CSV)
    parser.add_argument("--out-summary", default=DEFAULT_SUMMARY)
    parser.add_argument("--reps", type=int, default=DEFAULT_REPS)
    args = parser.parse_args(list(argv) if argv is not None else None)

    csv_p = Path(args.out_csv)
    csv_p.parent.mkdir(parents=True, exist_ok=True)
    if csv_p.exists():
        csv_p.unlink()

    cells = build_cells(reps=args.reps)
    print(f"P2c Sui Family-mix: {len(cells)} cells × {args.reps} reps")

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
