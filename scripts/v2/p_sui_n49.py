"""Sui n=49 scaling fill — the one missing scaling point.

The full Sui scaling sweep (p_withholding_scaling) hit the launcher timeout at
n=49 in *debug*. This fills the point with a reduced commit target (MIN_COMMITS
lower) so a debug run finishes inside the timeout; the all-pairs ASR is a ratio,
so it stays comparable across commit counts. baseline + silent + slw at n=49,
alpha=0.308, all-pairs (Sui headline).

Usage:
    python -m scripts.v2.p_sui_n49 --reps 5
    python -m scripts.v2.p_sui_n49 --reps 1   # smoke first
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

DEFAULT_CSV = "results/sui_n49_results.csv"
DEFAULT_SUMMARY = "results/sui_n49_summary.json"
DEFAULT_REPS = 5
BASE_SEED = 400  # match the scaling sweep's seed base
N = 49
_ATTACKS = [("withhold_baseline", "baseline_n49"), ("withhold_silent", "silent_n49"), ("slw", "slw_n49")]
_LAUNCHER = SuiLauncher(use_coordinator=False)


def _cfg(strategy: str, reps: int) -> schema.V2Config:
    na = round(N * 0.308)
    raw = {
        "protocol": {"name": "sui", "path": "sui"},
        "environment": {
            "NUM_NODES": str(N), "ATTACKER_RATIO": "0.308", "VICTIM_RATIO": "0.231",
            "GC_DEPTH": "10",
            # Reduced so a debug n=49 run finishes inside the launcher timeout.
            "COLLECTION_DURATION": "30", "MIN_COMMITS": "12",
        },
        "adversary": {
            "threat_model": "TM-Solo",
            "topology": {"policies": [
                {"group_id": "g0", "members": list(range(na)), "family": "frontrun",
                 "strategy": strategy, "params": {}},
            ]},
        },
        "victims": {"workload": "single", "count": 1,
                    "profit": {"distribution": "pareto", "params": {"shape": 1.16, "scale": 1.0}}},
        "runtime": {"reps": reps, "seed": BASE_SEED},
    }
    return sweeper.expand_policy_vector(schema.parse_config(raw))


def build_cells(reps: int = DEFAULT_REPS) -> list[benchmark.Cell]:
    return [benchmark.Cell(name=tag, config=_cfg(strategy, reps), launcher=_LAUNCHER)
            for strategy, tag in _ATTACKS]


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="p_sui_n49")
    parser.add_argument("--out-csv", default=DEFAULT_CSV)
    parser.add_argument("--out-summary", default=DEFAULT_SUMMARY)
    parser.add_argument("--reps", type=int, default=DEFAULT_REPS)
    args = parser.parse_args(list(argv) if argv is not None else None)
    csv_p = Path(args.out_csv)
    csv_p.parent.mkdir(parents=True, exist_ok=True)
    if csv_p.exists():
        csv_p.unlink()
    cells = build_cells(reps=args.reps)
    print(f"Sui n=49 fill: {len(cells)} cells × {args.reps} reps")
    summaries = benchmark.run_benchmark(
        cells=cells, out_csv=args.out_csv, out_summary_json=args.out_summary,
        reps=args.reps, progress_callback=lambda m: print(m, flush=True))
    print("\nSui n=49 all-pairs ASR:")
    for name, s in summaries.items():
        am = f"{s.asr_median:.1f}%" if s.asr_median is not None else "n/a"
        print(f"  [{name:14s}] all-pairs_asr={am:>7}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
