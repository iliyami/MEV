"""DS16 — value-model robustness sweep.

Runs baseline + silent-except-leader (the strong withholding attack) under three
victim value models — uniform (control), pareto (heavy-tailed, primary), and
log-normal (second heavy-tailed model) — to check that the realized-profit
finding is robust to how victim value is distributed. Profit is computed
Python-side from the committed order, so the three models weight the *same* DAG
differently; realized_mev and profit-weighted ASR are the observables.

Sui/Mysticeti, n=13, alpha=0.308, 5 reps.

Usage:
    python -m scripts.v2.p_valuemodel
    python -m scripts.v2.p_valuemodel --reps 5
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

DEFAULT_CSV = "results/sui_valuemodel_results.csv"
DEFAULT_SUMMARY = "results/sui_valuemodel_summary.json"
DEFAULT_REPS = 5
BASE_SEED = 600
_ATTACKERS = [0, 1, 2, 3]

# (label, victims.profit spec) — heavy-tailed models per the plan; never Gaussian.
_MODELS = [
    ("uniform", {"distribution": "uniform", "params": {"scale": 1.0}}),
    ("pareto", {"distribution": "pareto", "params": {"shape": 1.16, "scale": 1.0}}),
    ("lognormal", {"distribution": "lognormal", "params": {"mu": 1.1, "sigma": 2.5}}),
]
_ATTACKS = [("withhold_baseline", "baseline"), ("withhold_silent", "silent")]

_LAUNCHER = SuiLauncher(use_coordinator=False)


def _cfg(strategy: str, profit: dict, reps: int) -> schema.V2Config:
    raw = {
        "protocol": {"name": "sui", "path": "sui"},
        "environment": {
            "NUM_NODES": "13", "ATTACKER_RATIO": "0.308", "VICTIM_RATIO": "0.231",
            "GC_DEPTH": "10", "COLLECTION_DURATION": "45", "MIN_COMMITS": "25",
        },
        "adversary": {
            "threat_model": "TM-Solo",
            "topology": {"policies": [
                {"group_id": "g0", "members": _ATTACKERS, "family": "frontrun",
                 "strategy": strategy, "params": {}},
            ]},
        },
        "victims": {"workload": "single", "count": 1, "profit": profit},
        "runtime": {"reps": reps, "seed": BASE_SEED},
    }
    return sweeper.expand_policy_vector(schema.parse_config(raw))


def build_cells(reps: int = DEFAULT_REPS) -> list[benchmark.Cell]:
    cells = []
    for strategy, atag in _ATTACKS:
        for mlabel, profit in _MODELS:
            cells.append(benchmark.Cell(
                name=f"{atag}_{mlabel}",
                config=_cfg(strategy, profit, reps),
                launcher=_LAUNCHER,
            ))
    return cells


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="p_valuemodel")
    parser.add_argument("--out-csv", default=DEFAULT_CSV)
    parser.add_argument("--out-summary", default=DEFAULT_SUMMARY)
    parser.add_argument("--reps", type=int, default=DEFAULT_REPS)
    args = parser.parse_args(list(argv) if argv is not None else None)

    csv_p = Path(args.out_csv)
    csv_p.parent.mkdir(parents=True, exist_ok=True)
    if csv_p.exists():
        csv_p.unlink()

    cells = build_cells(reps=args.reps)
    print(f"DS16 value-model sweep: {len(cells)} cells × {args.reps} reps")

    summaries = benchmark.run_benchmark(
        cells=cells, out_csv=args.out_csv, out_summary_json=args.out_summary,
        reps=args.reps, progress_callback=lambda m: print(m, flush=True),
    )
    print("\nRealized-profit by value model (asr is all-pairs, distribution-independent):")
    for name, s in summaries.items():
        am = f"{s.asr_median:.1f}%" if s.asr_median is not None else "n/a"
        pw = f"{s.profit_weighted_asr_median:.1f}%" if s.profit_weighted_asr_median is not None else "n/a"
        rm = f"{s.realized_mev_mean:.1f}" if s.realized_mev_mean is not None else "n/a"
        print(f"  [{name:18s}] asr={am:>7}  pwasr={pw:>7}  realized_mev={rm}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
