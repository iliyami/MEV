"""P4 Sui — Bribery campaign (matching Bullshark P4 v3 cells).

Tests whether bribery lifts ASR on Mysticeti. Uses honest-side bribery
hooks via the v2 Coordinator for omit_reference infractions.

Usage:
    python -m scripts.v2.p4_sui_bribery
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

DEFAULT_CSV = "results/sui_p4_bribery_results.csv"
DEFAULT_SUMMARY = "results/sui_p4_bribery_summary.json"
DEFAULT_REPS = 5
BASE_SEED = 300

_BASE_ENV = {
    "NUM_NODES": "13",
    "ATTACKER_RATIO": "0.308",
    "VICTIM_RATIO": "0.231",
    "GC_DEPTH": "10",
    "COLLECTION_DURATION": "45",
    "MIN_COMMITS": "25",
}


def _cfg(policies: list[dict], reps: int,
         threat_model: str = "TM-Bribe",
         bribery: Optional[dict] = None,
         env_overrides: Optional[dict] = None) -> schema.V2Config:
    env = dict(_BASE_ENV)
    if env_overrides:
        env.update(env_overrides)
    adv: dict[str, Any] = {
        "threat_model": threat_model,
        "topology": {"policies": policies},
    }
    if bribery:
        adv["bribery"] = bribery
    raw = {
        "protocol": {"name": "sui", "path": "sui"},
        "environment": env,
        "adversary": adv,
        "victims": {"workload": "single", "count": 1},
        "runtime": {"reps": reps, "seed": BASE_SEED},
    }
    return sweeper.expand_policy_vector(schema.parse_config(raw))


_FISSURE_4 = [
    {"group_id": "g0", "members": [0, 1, 2, 3], "family": "frontrun",
     "strategy": "fissure", "params": {}}
]

_FISSURE_2 = [
    {"group_id": "g0", "members": [0, 1], "family": "frontrun",
     "strategy": "fissure", "params": {}}
]


def build_cells(reps: int = DEFAULT_REPS) -> list[benchmark.Cell]:
    cells = []

    # Baselines at different f levels
    cells.append(benchmark.Cell(
        name="b_baseline_f4",
        config=_cfg(_FISSURE_4, reps, threat_model="TM-Solo"),
        launcher=SuiLauncher(use_coordinator=False),
    ))

    cells.append(benchmark.Cell(
        name="b_baseline_f2",
        config=_cfg(_FISSURE_2, reps, threat_model="TM-Solo",
                     env_overrides={"ATTACKER_RATIO": "0.154"}),
        launcher=SuiLauncher(use_coordinator=False),
    ))

    # Sub-f bribery: f=2 + b=2 bribed honest
    cells.append(benchmark.Cell(
        name="b_b2_budget_50_omit",
        config=_cfg(_FISSURE_2, reps, bribery={
            "enabled": True,
            "type": "effective",
            "settlement": "simulated",
            "budget": 50,
            "response_policy": "always_above_X",
            "response_policy_params": {"threshold": 0},
            "bribed_honest": [2, 3],
        }),
        launcher=SuiLauncher(use_coordinator=True),
    ))

    # Full-f + bribery: f=4 + b=2
    cells.append(benchmark.Cell(
        name="b_action_omit_budget_50",
        config=_cfg(_FISSURE_4, reps, bribery={
            "enabled": True,
            "type": "effective",
            "settlement": "simulated",
            "budget": 50,
            "response_policy": "always_above_X",
            "response_policy_params": {"threshold": 0},
            "bribed_honest": [4, 5],
        }),
        launcher=SuiLauncher(use_coordinator=True),
    ))

    # Budget scaling: $25 vs $50 vs $100
    for budget in [25, 100]:
        cells.append(benchmark.Cell(
            name=f"b_budget_{budget}_omit",
            config=_cfg(_FISSURE_4, reps, bribery={
                "enabled": True,
                "type": "effective",
                "settlement": "simulated",
                "budget": budget,
                "response_policy": "always_above_X",
                "response_policy_params": {"threshold": 0},
                "bribed_honest": [4, 5],
            }),
            launcher=SuiLauncher(use_coordinator=True),
        ))

    # Response policy: reject_all (control)
    cells.append(benchmark.Cell(
        name="b_response_reject_omit",
        config=_cfg(_FISSURE_4, reps, bribery={
            "enabled": True,
            "type": "effective",
            "settlement": "simulated",
            "budget": 50,
            "response_policy": "reject_all",
            "response_policy_params": {},
            "bribed_honest": [4, 5],
        }),
        launcher=SuiLauncher(use_coordinator=True),
    ))

    return cells


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="p4_sui_bribery")
    parser.add_argument("--out-csv", default=DEFAULT_CSV)
    parser.add_argument("--out-summary", default=DEFAULT_SUMMARY)
    parser.add_argument("--reps", type=int, default=DEFAULT_REPS)
    args = parser.parse_args(list(argv) if argv is not None else None)

    csv_p = Path(args.out_csv)
    csv_p.parent.mkdir(parents=True, exist_ok=True)
    if csv_p.exists():
        csv_p.unlink()

    cells = build_cells(reps=args.reps)
    print(f"P4 Sui Bribery: {len(cells)} cells × {args.reps} reps")

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
