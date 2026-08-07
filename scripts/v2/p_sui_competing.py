"""A3.2 — competing attackers on Sui/Mysticeti (isolating competition from
collusion for the DS4 silent-except-leader withholding attack).

Three cells, same topology (single TM-Solo group, members=[0,1,2,3]),
differing only in which test (and therefore which env) drives the run:

    withhold_baseline          -- no hook armed (control; the lift reference)
    withhold_silent            -- DS4, pooled scoring (coordinated reference;
                                   already measured at 76.09%, kept here as a
                                   regression check -- see PROVENANCE §2.5/§2.13)
    withhold_silent_independent -- DS4, INDEPENDENT=1 scoring (the A3.2
                                   treatment)

`SILENT_EXCEPT_LEADER` has no victim-exclusion mechanism (unlike Bullshark's
fissure, an attacker never chooses *which* validator to target, only *when*
to broadcast), so there is no attacker-behavior knob to flip between the
"withhold_silent" and "withhold_silent_independent" cells -- attacker wire
behavior is byte-identical between them. The Bullshark-style collusion trap
(every attacker already shares victims()[0], so the naive control already
colludes; PROVENANCE §2.5) has a direct analog one layer up, at scoring: by
default every attacker's blocks are pooled against the whole victim pool.
INDEPENDENT=1 (read in withholding_attack_test.rs::calculate_asr) restricts
scoring to disjoint one-to-one attacker-victim pairs instead, isolating
whether the pooled number is a genuine per-relationship effect or an
artifact of aggregating many attacker-victim pairs together. This is a
scoring-only change in the test file; it does not touch proposer.rs.

Consequence for the value-metric family (profit_weighted_asr, realized_mev):
those are computed generically in benchmark.py from the raw committed order
and the full attacker/victim sets (the same-round frontrun predicate),
independent of calculate_asr's INDEPENDENT-gated pairing restriction. They
should therefore track the coordinated arm closely regardless of
INDEPENDENT, since attacker wire behavior does not change -- report this
explicitly rather than reading any movement there as a competition signal.

Usage:
    python -m scripts.v2.p_sui_competing
    python -m scripts.v2.p_sui_competing --reps 5
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

DEFAULT_CSV = "results/sui_competing_results.csv"
DEFAULT_SUMMARY = "results/sui_competing_summary.json"
DEFAULT_REPS = 5
BASE_SEED = 950

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
            # Same profit profile as p_sui_withholding.py so the value-metric
            # family is comparable across the two campaigns.
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
            name="withhold_silent",
            config=_cfg("withhold_silent", reps),
            launcher=_LAUNCHER,
        ),
        benchmark.Cell(
            name="withhold_silent_independent",
            config=_cfg("withhold_silent_independent", reps),
            launcher=_LAUNCHER,
        ),
    ]


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="p_sui_competing")
    parser.add_argument("--out-csv", default=DEFAULT_CSV)
    parser.add_argument("--out-summary", default=DEFAULT_SUMMARY)
    parser.add_argument("--reps", type=int, default=DEFAULT_REPS)
    args = parser.parse_args(list(argv) if argv is not None else None)

    csv_p = Path(args.out_csv)
    csv_p.parent.mkdir(parents=True, exist_ok=True)
    if csv_p.exists():
        csv_p.unlink()

    cells = build_cells(reps=args.reps)
    print(f"Sui Competing (A3.2): {len(cells)} cells x {args.reps} reps")

    summaries = benchmark.run_benchmark(
        cells=cells,
        out_csv=args.out_csv,
        out_summary_json=args.out_summary,
        reps=args.reps,
        progress_callback=lambda msg: print(msg, flush=True),
    )
    print("\nPer-cell summary (positional all-pairs ASR + value metrics):")
    for name, s in summaries.items():
        pw = f"{s.profit_weighted_asr_median:.2f}%" if s.profit_weighted_asr_median is not None else "n/a"
        rm = f"{s.realized_mev_mean:.1f}" if s.realized_mev_mean is not None else "n/a"
        print(
            f"  [{name:28s}] n={s.reps} "
            f"asr_median={s.asr_median:.2f}% "
            f"profit_wtd_asr={pw} realized_mev={rm}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
