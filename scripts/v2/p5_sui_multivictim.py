"""P5 Sui — Multi-victim campaign (matching Bullshark P5 v3 cells).

Tests adaptive victim targeting on Mysticeti: does profit-aware
targeting change ASR?

Usage:
    python -m scripts.v2.p5_sui_multivictim
"""

from __future__ import annotations

import argparse
import json
import re
import statistics as st
import sys
from pathlib import Path
from typing import Any, Iterable, Optional

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from scripts.v2 import benchmark, schema, sweeper
from scripts.v2.launchers.sui import SuiLauncher

_RE_VICTIM_PROFIT = re.compile(
    r"V2_VICTIM_PROFIT: round=(\d+) author=(\d+) profit=([\d.eE+-]+)"
)
_RE_ADAPTIVE_SKIP = re.compile(
    r"V2_ADAPTIVE_SKIP: round=(\d+) author=(\d+) profit=([\d.eE+-]+) threshold=([\d.eE+-]+)"
)


def _extract(raw_output: str, _run_result) -> dict:
    profits = []
    skips = []
    for line in raw_output.splitlines():
        m = _RE_VICTIM_PROFIT.search(line)
        if m:
            profits.append({"round": int(m.group(1)), "author": int(m.group(2)), "profit": float(m.group(3))})
        m = _RE_ADAPTIVE_SKIP.search(line)
        if m:
            skips.append({"round": int(m.group(1)), "author": int(m.group(2)), "profit": float(m.group(3))})
    skipped_keys = {(s["round"], s["author"]) for s in skips}
    attacked = [p for p in profits if (p["round"], p["author"]) not in skipped_keys]
    asr = _run_result.metrics.get("asr") if _run_result else None
    median_profit = st.median([p["profit"] for p in attacked]) if attacked else None
    expected_mev = (asr * median_profit / 100.0) if (asr is not None and median_profit is not None) else None
    return {
        "victim_profit_markers": len(profits),
        "adaptive_skip_markers": len(skips),
        "median_attacked_profit": median_profit,
        "mean_attacked_profit": st.mean([p["profit"] for p in attacked]) if attacked else None,
        "skip_rate": (len(skips) / len(profits)) if profits else 0.0,
        "expected_mev": round(expected_mev, 4) if expected_mev is not None else None,
    }


_EXTRA_COLS = (
    "victim_profit_markers",
    "adaptive_skip_markers",
    "median_attacked_profit",
    "mean_attacked_profit",
    "skip_rate",
    "expected_mev",
)

DEFAULT_CSV = "results/sui_p5_multivictim_results.csv"
DEFAULT_SUMMARY = "results/sui_p5_multivictim_summary.json"
DEFAULT_REPS = 5
BASE_SEED = 400

_BASE_ENV = {
    "NUM_NODES": "13",
    "ATTACKER_RATIO": "0.308",
    "VICTIM_RATIO": "0.231",
    "GC_DEPTH": "10",
    "COLLECTION_DURATION": "45",
    "MIN_COMMITS": "25",
}


def _cfg(policies: list[dict], reps: int,
         victim_profile: Optional[dict] = None,
         env_overrides: Optional[dict] = None) -> schema.V2Config:
    env = dict(_BASE_ENV)
    if env_overrides:
        env.update(env_overrides)
    victims: dict[str, Any] = {"workload": "single", "count": 1}
    if victim_profile:
        victims["workload"] = "multi_pareto"
        victims["profit"] = victim_profile
    raw = {
        "protocol": {"name": "sui", "path": "sui"},
        "environment": env,
        "adversary": {
            "threat_model": "TM-Solo",
            "topology": {"policies": policies},
        },
        "victims": victims,
        "runtime": {"reps": reps, "seed": BASE_SEED},
    }
    return sweeper.expand_policy_vector(schema.parse_config(raw))


_FISSURE = [
    {"group_id": "g0", "members": [0, 1, 2, 3], "family": "frontrun",
     "strategy": "fissure", "params": {}}
]


def _fissure_with_threshold(threshold: float) -> list[dict]:
    return [
        {"group_id": "g0", "members": [0, 1, 2, 3], "family": "frontrun",
         "strategy": "fissure", "params": {"profit_threshold": threshold}}
    ]


def build_cells(reps: int = DEFAULT_REPS) -> list[benchmark.Cell]:
    cells = []

    _launcher = SuiLauncher(use_coordinator=True)

    # Uniform baseline (Pareto victims, no threshold)
    cells.append(benchmark.Cell(
        name="mv_uniform_baseline",
        config=_cfg(_FISSURE, reps, victim_profile={
            "distribution": "pareto", "params": {"alpha": 1.5, "scale": 1.0}
        }),
        extra_columns=_EXTRA_COLS,
        marker_extractor=_extract,
        launcher=_launcher,
    ))

    # Threshold sweep
    for thresh in [0.5, 1.0, 2.0, 5.0, 10.0]:
        cells.append(benchmark.Cell(
            name=f"mv_threshold_{thresh}",
            config=_cfg(_fissure_with_threshold(thresh), reps, victim_profile={
                "distribution": "pareto", "params": {"alpha": 1.5, "scale": 1.0}
            }),
            extra_columns=_EXTRA_COLS,
            marker_extractor=_extract,
            launcher=_launcher,
        ))

    # Uniform distribution baseline
    cells.append(benchmark.Cell(
        name="mv_uniform_dist_baseline",
        config=_cfg(_FISSURE, reps, victim_profile={
            "distribution": "uniform", "params": {"low": 0.0, "high": 10.0}
        }),
        extra_columns=_EXTRA_COLS,
        marker_extractor=_extract,
        launcher=_launcher,
    ))

    return cells


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="p5_sui_multivictim")
    parser.add_argument("--out-csv", default=DEFAULT_CSV)
    parser.add_argument("--out-summary", default=DEFAULT_SUMMARY)
    parser.add_argument("--reps", type=int, default=DEFAULT_REPS)
    args = parser.parse_args(list(argv) if argv is not None else None)

    csv_p = Path(args.out_csv)
    csv_p.parent.mkdir(parents=True, exist_ok=True)
    if csv_p.exists():
        csv_p.unlink()

    cells = build_cells(reps=args.reps)
    print(f"P5 Sui Multi-victim: {len(cells)} cells × {args.reps} reps")

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
