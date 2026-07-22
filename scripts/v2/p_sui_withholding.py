"""DS4/DS5 — Withholding attacks on Sui/Mysticeti (silent-except-leader + SLW).

Three isolated TM-Solo cells, each varying exactly one dimension (all other
attacker hooks at baseline default), so each result is cleanly attributable:

    withhold_baseline  -- no hook armed (control; the lift reference)
    silent_except_leader (DS4) -- proposer speaks ONLY on its own leader rounds
    slw (DS5)                  -- proposer skips ONLY its own leader-round proposal

The hooks already live in proposer.rs (SILENT_EXCEPT_LEADER / mysticeti_slw); the
withholding_attack_test.rs tests drive them, and SuiLauncher wires them here.
Primary metric is Sui's all-pairs ASR (neutral ~50% baseline); same-round ASR is
kept as a diagnostic. n=13, alpha=0.308, 5 reps.

Usage:
    python -m scripts.v2.p_sui_withholding
    python -m scripts.v2.p_sui_withholding --reps 5
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

DEFAULT_CSV = "results/sui_withholding_results.csv"
DEFAULT_SUMMARY = "results/sui_withholding_summary.json"
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

# Attacker layout for n=13, alpha=0.308 -> the first 4 indices.
_ATTACKERS = [0, 1, 2, 3]

_LAUNCHER = SuiLauncher(use_coordinator=False)


def _cfg(strategy: str, reps: int) -> schema.V2Config:
    raw = {
        "protocol": {"name": "sui", "path": "sui"},
        "environment": dict(_BASE_ENV),
        "adversary": {
            "threat_model": "TM-Solo",
            "topology": {
                "policies": [
                    {
                        "group_id": "g0",
                        "members": _ATTACKERS,
                        "family": "frontrun",
                        "strategy": strategy,
                        "params": {},
                    }
                ]
            },
        },
        "victims": {
            "workload": "single",
            "count": 1,
            # Heavy-tailed profit so realized-MEV (T4) is the primary metric,
            # not just ASR. shape=1.16 is the plan default (mean ~7.25x scale).
            "profit": {"distribution": "pareto", "params": {"shape": 1.16, "scale": 1.0}},
        },
        "runtime": {"reps": reps, "seed": BASE_SEED},
    }
    return sweeper.expand_policy_vector(schema.parse_config(raw))


def build_cells(reps: int = DEFAULT_REPS) -> list[benchmark.Cell]:
    return [
        benchmark.Cell(
            name="withhold_baseline",
            config=_cfg("withhold_baseline", reps),
            launcher=_LAUNCHER,
        ),
        benchmark.Cell(
            name="silent_except_leader",
            config=_cfg("withhold_silent", reps),
            launcher=_LAUNCHER,
        ),
        benchmark.Cell(
            name="slw",
            config=_cfg("slw", reps),
            launcher=_LAUNCHER,
        ),
    ]


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="p_sui_withholding")
    parser.add_argument("--out-csv", default=DEFAULT_CSV)
    parser.add_argument("--out-summary", default=DEFAULT_SUMMARY)
    parser.add_argument("--reps", type=int, default=DEFAULT_REPS)
    args = parser.parse_args(list(argv) if argv is not None else None)

    csv_p = Path(args.out_csv)
    csv_p.parent.mkdir(parents=True, exist_ok=True)
    if csv_p.exists():
        csv_p.unlink()

    cells = build_cells(reps=args.reps)
    print(f"Sui Withholding (DS4/DS5): {len(cells)} cells × {args.reps} reps")

    summaries = benchmark.run_benchmark(
        cells=cells,
        out_csv=args.out_csv,
        out_summary_json=args.out_summary,
        reps=args.reps,
        progress_callback=lambda msg: print(msg, flush=True),
    )
    print("\nPer-cell summary (realized profit is primary; all-pairs ASR shown too):")
    for name, s in summaries.items():
        pw = f"{s.profit_weighted_asr_median:.2f}%" if s.profit_weighted_asr_median is not None else "n/a"
        rm = f"{s.realized_mev_mean:.1f}" if s.realized_mev_mean is not None else "n/a"
        print(
            f"  [{name:22s}] n={s.reps} "
            f"profit_wtd_asr={pw} realized_mev={rm} | asr_median={s.asr_median:.2f}%"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
