"""Withholding scaling probe — does the leader-skip (SLW) lever grow with n?

DS5 (SLW) was near-neutral at n=13. This runs baseline + silent-except-leader +
SLW at committee sizes n in {13, 25, 49} (the 3f+1 sizes) for one protocol, to
see whether the withholding levers strengthen or stay flat as the committee
grows. alpha=0.308, victim_ratio=0.231, pareto profit, 5 reps.

Both ASR and realized-MEV (T4) are reported per cell, so this doubles as a
metric-divergence-vs-n view.

Usage:
    python -m scripts.v2.p_withholding_scaling --protocol sui
    python -m scripts.v2.p_withholding_scaling --protocol bullshark --reps 5
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Iterable, Optional

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from scripts.v2 import benchmark, schema, sweeper
from scripts.v2.launchers.bullshark import BullsharkLauncher
from scripts.v2.launchers.sui import SuiLauncher

DEFAULT_REPS = 5
BASE_SEED = 400
N_VALUES = (13, 25, 49)
# (campaign strategy label, short cell tag)
_STRATEGIES = (
    ("withhold_baseline", "baseline"),
    ("withhold_silent", "silent"),
    ("slw", "slw"),
)
_ATTACKER_RATIO = 0.308
_VICTIM_RATIO = 0.231


def _cfg(protocol: str, n: int, strategy: str, reps: int) -> schema.V2Config:
    attacker_count = round(n * _ATTACKER_RATIO)
    attackers = list(range(attacker_count))
    env = {
        "NUM_NODES": str(n),
        "ATTACKER_RATIO": str(_ATTACKER_RATIO),
        "VICTIM_RATIO": str(_VICTIM_RATIO),
        "GC_DEPTH": "10",
        "COLLECTION_DURATION": "45",
        "MIN_COMMITS": str(n + 10),
    }
    raw: dict = {
        "protocol": {"name": protocol, "path": protocol},
        "environment": env,
        "adversary": {
            "threat_model": "TM-Solo",
            "topology": {
                "policies": [
                    {"group_id": "g0", "members": attackers, "family": "frontrun",
                     "strategy": strategy, "params": {}},
                ]
            },
        },
        "victims": {
            "workload": "single", "count": 1,
            "profit": {"distribution": "pareto", "params": {"shape": 1.16, "scale": 1.0}},
        },
        "runtime": {"reps": reps, "seed": BASE_SEED},
    }
    if protocol == "bullshark":
        env["DAG_STATE_CACHED_ROUNDS"] = "5"
        env["SYNC_TIMEOUT_MS"] = "2000"
        env["ATTACK_TYPE"] = "frontrun"
        raw["docker"] = {"tag": "mev-bullshark:latest", "cpus": "8.0", "memory": "16g"}
        raw["test"] = {"test_name": "test_withhold_baseline_asr_dynamic", "REPETITIONS": 1}
    return sweeper.expand_policy_vector(schema.parse_config(raw))


def build_cells(protocol: str, reps: int = DEFAULT_REPS) -> list[benchmark.Cell]:
    launcher = (
        SuiLauncher(use_coordinator=False)
        if protocol == "sui"
        else BullsharkLauncher(local_mode=True, use_coordinator=False)
    )
    cells = []
    for n in N_VALUES:
        for strategy, tag in _STRATEGIES:
            cells.append(benchmark.Cell(
                name=f"{tag}_n{n}",
                config=_cfg(protocol, n, strategy, reps),
                launcher=launcher,
            ))
    return cells


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="p_withholding_scaling")
    parser.add_argument("--protocol", choices=("sui", "bullshark"), required=True)
    parser.add_argument("--out-csv", default=None)
    parser.add_argument("--out-summary", default=None)
    parser.add_argument("--reps", type=int, default=DEFAULT_REPS)
    args = parser.parse_args(list(argv) if argv is not None else None)

    pfx = "sui" if args.protocol == "sui" else "v2"
    out_csv = args.out_csv or f"results/{pfx}_withholding_scaling_results.csv"
    out_summary = args.out_summary or f"results/{pfx}_withholding_scaling_summary.json"

    csv_p = Path(out_csv)
    csv_p.parent.mkdir(parents=True, exist_ok=True)
    if csv_p.exists():
        csv_p.unlink()

    cells = build_cells(args.protocol, reps=args.reps)
    print(f"{args.protocol} withholding scaling: {len(cells)} cells × {args.reps} reps "
          f"(n in {list(N_VALUES)})")

    summaries = benchmark.run_benchmark(
        cells=cells,
        out_csv=out_csv,
        out_summary_json=out_summary,
        reps=args.reps,
        progress_callback=lambda msg: print(msg, flush=True),
    )
    print("\nPer-cell summary (asr | realized-MEV pwasr):")
    for name, s in summaries.items():
        pw = f"{s.profit_weighted_asr_median:.1f}%" if s.profit_weighted_asr_median is not None else "n/a"
        rm = f"{s.realized_mev_mean:.1f}" if s.realized_mev_mean is not None else "n/a"
        am = f"{s.asr_median:.1f}%" if s.asr_median is not None else "n/a"
        print(f"  [{name:14s}] asr={am:>7} | realized_mev={rm:>8} pwasr={pw:>7}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
