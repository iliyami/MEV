"""P3 Sui — Collusion campaign (matching Bullshark P3 v3 cells).

Tests whether explicit coordination among Byzantine nodes lifts ASR
on Mysticeti. Uses the v2 Coordinator for per-node policy and
shared-seed coordination.

Usage:
    python -m scripts.v2.p3_sui_collusion
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

DEFAULT_CSV = "results/sui_p3_collusion_results.csv"
DEFAULT_SUMMARY = "results/sui_p3_collusion_summary.json"
DEFAULT_REPS = 5
BASE_SEED = 200

_BASE_ENV = {
    "NUM_NODES": "13",
    "ATTACKER_RATIO": "0.308",
    "VICTIM_RATIO": "0.231",
    "GC_DEPTH": "10",
    "COLLECTION_DURATION": "45",
    "MIN_COMMITS": "25",
}


def _cfg(policies: list[dict], reps: int,
         threat_model: str = "TM-Collude",
         coordination_policy: str = "leader",
         env_overrides: Optional[dict] = None) -> schema.V2Config:
    env = dict(_BASE_ENV)
    if env_overrides:
        env.update(env_overrides)
    raw = {
        "protocol": {"name": "sui", "path": "sui"},
        "environment": env,
        "adversary": {
            "threat_model": threat_model,
            "coordination": {
                "enabled": threat_model == "TM-Collude",
                "policy": coordination_policy,
                "information": "local_dag_union",
            },
            "topology": {"policies": policies},
        },
        "victims": {"workload": "single", "count": 1},
        "runtime": {"reps": reps, "seed": BASE_SEED},
    }
    return sweeper.expand_policy_vector(schema.parse_config(raw))


_FISSURE_POLICIES = [
    {"group_id": "g0", "members": [0, 1, 2, 3], "family": "frontrun",
     "strategy": "fissure", "params": {}}
]


def build_cells(reps: int = DEFAULT_REPS) -> list[benchmark.Cell]:
    cells = []

    # Independent baseline (no coordination)
    cells.append(benchmark.Cell(
        name="c_indep_fissure",
        config=_cfg(_FISSURE_POLICIES, reps,
                     threat_model="TM-Compete",
                     coordination_policy="role_specialization"),
        launcher=SuiLauncher(use_coordinator=True),
    ))

    # Coordinated (shared seed)
    cells.append(benchmark.Cell(
        name="c_coord_fissure",
        config=_cfg(_FISSURE_POLICIES, reps,
                     coordination_policy="leader"),
        launcher=SuiLauncher(use_coordinator=True),
    ))

    # Role split: exclude + amplify
    cells.append(benchmark.Cell(
        name="c_role_split",
        config=_cfg([
            {"group_id": "g0", "members": [0, 1], "family": "frontrun",
             "strategy": "fissure", "params": {"role_action": "exclude"}},
            {"group_id": "g1", "members": [2, 3], "family": "frontrun",
             "strategy": "fissure", "params": {"role_action": "amplify"}},
        ], reps, coordination_policy="leader"),
        launcher=SuiLauncher(use_coordinator=True),
    ))

    # Round-robin active/passive
    cells.append(benchmark.Cell(
        name="c_rr_active",
        config=_cfg(_FISSURE_POLICIES, reps,
                     coordination_policy="rr_slot"),
        launcher=SuiLauncher(use_coordinator=True),
    ))

    # MLVW under coordination
    cells.append(benchmark.Cell(
        name="c_coord_mlvw",
        config=_cfg([
            {"group_id": "g0", "members": [0, 1, 2, 3], "family": "frontrun",
             "strategy": "fissure", "params": {}}
        ], reps, coordination_policy="leader",
            env_overrides={"ATTACK_MODE": "mysticeti_lvw"}),
        launcher=SuiLauncher(use_coordinator=True),
    ))

    return cells


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="p3_sui_collusion")
    parser.add_argument("--out-csv", default=DEFAULT_CSV)
    parser.add_argument("--out-summary", default=DEFAULT_SUMMARY)
    parser.add_argument("--reps", type=int, default=DEFAULT_REPS)
    args = parser.parse_args(list(argv) if argv is not None else None)

    csv_p = Path(args.out_csv)
    csv_p.parent.mkdir(parents=True, exist_ok=True)
    if csv_p.exists():
        csv_p.unlink()

    cells = build_cells(reps=args.reps)
    print(f"P3 Sui Collusion: {len(cells)} cells × {args.reps} reps")

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
