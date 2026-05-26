"""P6 Sui — Cross-cutting composite campaign (matching Bullshark P6 v3).

Combines modes: competition+bribery, collusion+adaptive, best-response.

Usage:
    python -m scripts.v2.p6_sui_crosscutting
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

DEFAULT_CSV = "results/sui_p6_crosscutting_results.csv"
DEFAULT_SUMMARY = "results/sui_p6_crosscutting_summary.json"
DEFAULT_REPS = 5
BASE_SEED = 500

_BASE_ENV = {
    "NUM_NODES": "13",
    "ATTACKER_RATIO": "0.308",
    "VICTIM_RATIO": "0.231",
    "GC_DEPTH": "10",
    "COLLECTION_DURATION": "45",
    "MIN_COMMITS": "25",
}


def _cfg(policies: list[dict], reps: int,
         threat_model: str = "TM-Solo",
         bribery: Optional[dict] = None,
         coordination: Optional[dict] = None,
         victim_profile: Optional[dict] = None,
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
    if coordination:
        coordination.setdefault("enabled", threat_model == "TM-Collude")
        adv["coordination"] = coordination
    victims: dict[str, Any] = {"workload": "single", "count": 1}
    if victim_profile:
        victims["workload"] = "multi_pareto"
        victims["profit"] = victim_profile
    raw = {
        "protocol": {"name": "sui", "path": "sui"},
        "environment": env,
        "adversary": adv,
        "victims": victims,
        "runtime": {"reps": reps, "seed": BASE_SEED},
    }
    return sweeper.expand_policy_vector(schema.parse_config(raw))


def build_cells(reps: int = DEFAULT_REPS) -> list[benchmark.Cell]:
    cells = []

    # Paper-1 baseline (f=4 fissure)
    cells.append(benchmark.Cell(
        name="c_paper1_baseline",
        config=_cfg([
            {"group_id": "g0", "members": [0, 1, 2, 3], "family": "frontrun",
             "strategy": "fissure", "params": {}}
        ], reps),
        launcher=SuiLauncher(use_coordinator=False),
    ))

    # Competition + bribery
    cells.append(benchmark.Cell(
        name="c_comp_no_bribery",
        config=_cfg([
            {"group_id": "g0", "members": [0, 1], "family": "frontrun",
             "strategy": "fissure", "params": {}},
            {"group_id": "g1", "members": [2, 3], "family": "frontrun",
             "strategy": "speculative", "params": {}},
        ], reps, threat_model="TM-Compete"),
        launcher=SuiLauncher(use_coordinator=False),
    ))

    cells.append(benchmark.Cell(
        name="c_comp_bribed",
        config=_cfg([
            {"group_id": "g0", "members": [0, 1], "family": "frontrun",
             "strategy": "fissure", "params": {}},
            {"group_id": "g1", "members": [2, 3], "family": "frontrun",
             "strategy": "fissure", "params": {}},
        ], reps, threat_model="TM-Bribe", bribery={
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

    # Collusion + adaptive targeting
    cells.append(benchmark.Cell(
        name="c_coll_uniform",
        config=_cfg([
            {"group_id": "g0", "members": [0, 1, 2, 3], "family": "frontrun",
             "strategy": "fissure", "params": {}}
        ], reps, threat_model="TM-Collude",
            coordination={"policy": "leader", "information": "local_dag_union"}),
        launcher=SuiLauncher(use_coordinator=True),
    ))

    cells.append(benchmark.Cell(
        name="c_coll_adaptive",
        config=_cfg([
            {"group_id": "g0", "members": [0, 1, 2, 3], "family": "frontrun",
             "strategy": "fissure", "params": {"profit_threshold": 5.0}}
        ], reps, threat_model="TM-Collude",
            coordination={"policy": "leader", "information": "local_dag_union"},
            victim_profile={"distribution": "pareto", "params": {"alpha": 1.5, "scale": 1.0}}),
        launcher=SuiLauncher(use_coordinator=True),
    ))

    # Collusion + bribery combo: coordinated attackers + bribed honest nodes.
    # Uses TM-Bribe (schema requires it for bribery.enabled=True). The
    # coordination effect comes from all attackers sharing the same
    # fissure exclusion logic (deterministic in block data) plus the
    # bribed honest nodes applying omit_reference. This is the strongest
    # combined attack: coordinated exclusion + honest-side omission.
    cells.append(benchmark.Cell(
        name="c_coll_bribed",
        config=_cfg([
            {"group_id": "g0", "members": [0, 1, 2, 3], "family": "frontrun",
             "strategy": "fissure", "params": {}}
        ], reps, threat_model="TM-Bribe",
            bribery={
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

    # Best response: f=4 + bribery $100 + omit (best config from Bullshark P4)
    cells.append(benchmark.Cell(
        name="c_best_response",
        config=_cfg([
            {"group_id": "g0", "members": [0, 1, 2, 3], "family": "frontrun",
             "strategy": "fissure", "params": {}}
        ], reps, threat_model="TM-Bribe", bribery={
            "enabled": True,
            "type": "effective",
            "settlement": "simulated",
            "budget": 100,
            "response_policy": "always_above_X",
            "response_policy_params": {"threshold": 0},
            "bribed_honest": [4, 5],
        }),
        launcher=SuiLauncher(use_coordinator=True),
    ))

    return cells


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="p6_sui_crosscutting")
    parser.add_argument("--out-csv", default=DEFAULT_CSV)
    parser.add_argument("--out-summary", default=DEFAULT_SUMMARY)
    parser.add_argument("--reps", type=int, default=DEFAULT_REPS)
    args = parser.parse_args(list(argv) if argv is not None else None)

    csv_p = Path(args.out_csv)
    csv_p.parent.mkdir(parents=True, exist_ok=True)
    if csv_p.exists():
        csv_p.unlink()

    cells = build_cells(reps=args.reps)
    print(f"P6 Sui Cross-cutting: {len(cells)} cells × {args.reps} reps")

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
