"""A2.7 — Proposal-timestamp attack on Sui/Mysticeti.

One isolated TM-Solo cell pair, varying exactly one dimension (all other
attacker hooks at baseline default), so the result is cleanly attributable:

    timestamp_baseline -- no hook armed (control; the lift reference)
    timestamp           -- attacker overrides its own block timestamp by
                            BYZANTINE_TIMESTAMP_OFFSET_MS

The hook already lives in proposer.rs (ATTACK_TIMESTAMP /
BYZANTINE_TIMESTAMP_OFFSET_MS); timestamp_attack_test.rs drives it, and
SuiLauncher wires it here. Primary metric is Sui's all-pairs ASR (neutral
~50-56% baseline, see PROVENANCE.md §2.13); same-round ASR is kept as a
diagnostic. n=13, alpha=0.308, 5 reps.

Operating point: BYZANTINE_TIMESTAMP_OFFSET_MS = 5000 (+5s, a FUTURE
timestamp). A 1-rep direction/magnitude sweep (see PROVENANCE.md A2.7) showed
the offset's sign matters: negative (past) offsets backfire (-500ms read
53.5% all-pairs, below the ~56.4% baseline), while positive (future) offsets
lift it (+500ms -> 64.4%, +5s -> 89.7%, +60s -> 91.7%, +1yr -> 91.4%).
Same-round ASR saturates at 100.0% and all-pairs plateaus around 90-92% from
+5s onward, so larger offsets buy nothing further. +5s is the smallest offset
that reaches the plateau, so it is the headline operating point rather than
the largest value tried.

Usage:
    python -m scripts.v2.p_sui_timestamp
    python -m scripts.v2.p_sui_timestamp --reps 5
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

DEFAULT_CSV = "results/sui_timestamp_results.csv"
DEFAULT_SUMMARY = "results/sui_timestamp_summary.json"
DEFAULT_REPS = 5
BASE_SEED = 900

_BASE_ENV = {
    "NUM_NODES": "13",
    "ATTACKER_RATIO": "0.308",
    "VICTIM_RATIO": "0.231",
    "GC_DEPTH": "10",
    "COLLECTION_DURATION": "45",
    "MIN_COMMITS": "25",
    # Operating point: +5s future timestamp, the smallest offset that reaches
    # the ASR plateau (see module docstring / PROVENANCE.md A2.7 sweep). The
    # baseline test clears BYZANTINE_TIMESTAMP_OFFSET_MS by name regardless of
    # what is forwarded here, so it is safe to set for both cells.
    "BYZANTINE_TIMESTAMP_OFFSET_MS": "5000",
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
            name="timestamp_baseline",
            config=_cfg("timestamp_baseline", reps),
            launcher=_LAUNCHER,
        ),
        benchmark.Cell(
            name="timestamp",
            config=_cfg("timestamp", reps),
            launcher=_LAUNCHER,
        ),
    ]


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="p_sui_timestamp")
    parser.add_argument("--out-csv", default=DEFAULT_CSV)
    parser.add_argument("--out-summary", default=DEFAULT_SUMMARY)
    parser.add_argument("--reps", type=int, default=DEFAULT_REPS)
    args = parser.parse_args(list(argv) if argv is not None else None)

    csv_p = Path(args.out_csv)
    csv_p.parent.mkdir(parents=True, exist_ok=True)
    if csv_p.exists():
        csv_p.unlink()

    cells = build_cells(reps=args.reps)
    print(f"Sui Timestamp (A2.7): {len(cells)} cells × {args.reps} reps")

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
