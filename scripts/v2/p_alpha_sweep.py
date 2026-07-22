"""Attacker-fraction sweep — distinguishing the Bullshark attack primitives.

Bullshark same-round ASR saturates (~92%+) for *any* attack because of the
low-index head start, so attack categories are indistinguishable. This sweeps
the solo primitives at alpha in {1, 2, 4 attackers} using the ALL-PAIRS metric
(neutral ~50% baseline, promoted via V2_ALL_PAIRS_ASR): fewer attackers + the
un-saturated metric spread the attacks out so their impact becomes comparable.

Bullshark only (competition/collusion need >=2 attackers by definition; the
solo primitives are the point). n=13, pareto profit, 5 reps.

Usage:
    python -m scripts.v2.p_alpha_sweep
    python -m scripts.v2.p_alpha_sweep --reps 5
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

DEFAULT_CSV = "results/v2_alpha_sweep_results.csv"
DEFAULT_SUMMARY = "results/v2_alpha_sweep_summary.json"
DEFAULT_REPS = 5
BASE_SEED = 500
N = 13
# (attacker_ratio, k attackers) — round(13*ratio) = k.
_ALPHAS = [("0.077", 1), ("0.154", 2), ("0.308", 4)]
# (campaign strategy label, short tag)
_ATTACKS = [
    ("withhold_baseline", "baseline"),
    ("fissure", "fissure"),
    ("speculative", "speculative"),
    ("sluggish", "sluggish"),
    ("withhold_silent", "silent"),
    ("slw", "slw"),
]
_LAUNCHER = BullsharkLauncher(local_mode=True, use_coordinator=False)


def _cfg(strategy: str, attacker_ratio: str, reps: int) -> schema.V2Config:
    na = round(N * float(attacker_ratio))
    attackers = list(range(na))
    env = {
        "NUM_NODES": str(N),
        "ATTACKER_RATIO": attacker_ratio,
        "VICTIM_RATIO": "0.231",
        "GC_DEPTH": "10",
        "DAG_STATE_CACHED_ROUNDS": "5",
        "SYNC_TIMEOUT_MS": "2000",
        "COLLECTION_DURATION": "45",
        "MIN_COMMITS": "23",
        "ATTACK_TYPE": "frontrun",
        "SPECULATIVE_P_MAX": "50",
        "SLUGGISH_TIMEOUT_MULTIPLIER": "1.5",
        # Headline = all-pairs ASR (neutral ~50% baseline, un-saturated).
        "V2_ALL_PAIRS_ASR": "1",
    }
    raw = {
        "protocol": {"name": "bullshark", "path": "bullshark"},
        "docker": {"tag": "mev-bullshark:latest", "cpus": "8.0", "memory": "16g"},
        "test": {"test_name": "test_fissure_attack_asr_dynamic", "REPETITIONS": 1},
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
    return sweeper.expand_policy_vector(schema.parse_config(raw))


def build_cells(reps: int = DEFAULT_REPS) -> list[benchmark.Cell]:
    cells = []
    for ratio, k in _ALPHAS:
        for strategy, tag in _ATTACKS:
            cells.append(benchmark.Cell(
                name=f"{tag}_a{k}",
                config=_cfg(strategy, ratio, reps),
                launcher=_LAUNCHER,
            ))
    return cells


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="p_alpha_sweep")
    parser.add_argument("--out-csv", default=DEFAULT_CSV)
    parser.add_argument("--out-summary", default=DEFAULT_SUMMARY)
    parser.add_argument("--reps", type=int, default=DEFAULT_REPS)
    args = parser.parse_args(list(argv) if argv is not None else None)

    csv_p = Path(args.out_csv)
    csv_p.parent.mkdir(parents=True, exist_ok=True)
    if csv_p.exists():
        csv_p.unlink()

    cells = build_cells(reps=args.reps)
    print(f"Bullshark alpha-sweep: {len(cells)} cells × {args.reps} reps "
          f"(all-pairs metric, k in [1,2,4] attackers)")

    summaries = benchmark.run_benchmark(
        cells=cells,
        out_csv=args.out_csv,
        out_summary_json=args.out_summary,
        reps=args.reps,
        progress_callback=lambda m: print(m, flush=True),
    )
    print("\nAll-pairs ASR (baseline ~50%; higher = more attack impact):")
    for name, s in summaries.items():
        am = f"{s.asr_median:.1f}%" if s.asr_median is not None else "n/a"
        rm = f"{s.realized_mev_mean:.0f}" if s.realized_mev_mean is not None else "n/a"
        print(f"  [{name:16s}] all-pairs_asr={am:>7}  realized_mev={rm}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
