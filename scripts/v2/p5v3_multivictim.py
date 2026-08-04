"""P5 v3 — Multi-victim campaign (H4.1 — H4.4).

Pre-registered in `paper_workspace/p5v3_preregistration.md`.

Cells (10):
  mv_uniform_baseline       — no threshold; uniform-target control
  mv_threshold_0p5..10p0    — Pareto victims, 5 threshold sweep
  mv_uniform_dist_baseline  — uniform-scale-1 victims, no threshold
  mv_uniform_dist_thresh_*  — uniform victims, 3 threshold sweep

N=10 per cell.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Optional

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from scripts.v2 import benchmark, schema, stats, sweeper


DEFAULT_CSV = "results/v2_p5v3_results.csv"
DEFAULT_SUMMARY = "results/v2_p5v3_summary.json"
DEFAULT_VERDICT = "results/v2_p5v3_verdict.json"
DEFAULT_REPS = 10
BASE_SEED = 42

_BASE_ENV = {
    "NUM_NODES": "13",
    "ATTACKER_RATIO": "0.308",
    "VICTIM_RATIO": "0.231",
    "SPECULATIVE_P_MAX": "50",
    "SLUGGISH_TIMEOUT_MULTIPLIER": "1.5",
    "DAG_STATE_CACHED_ROUNDS": "5",
    "SYNC_TIMEOUT_MS": "2000",
    "GC_DEPTH": "10",
    "ATTACK_MODE": "fissure",
    "ATTACK_TYPE": "frontrun",
}


_RE_VICTIM_PROFIT = re.compile(
    r"V2_VICTIM_PROFIT: round=(\d+) author=(\d+) profit=([\d.eE+-]+)"
)
_RE_ADAPTIVE_SKIP = re.compile(
    r"V2_ADAPTIVE_SKIP: round=(\d+) author=(\d+) profit=([\d.eE+-]+) threshold=([\d.eE+-]+)"
)


import os as _os
_N_NODES = 13
_REV = bool(_os.environ.get("REVERSE_LAYOUT"))
def _rl(xs) -> list[int]:
    return sorted((_N_NODES - 1 - i) for i in xs) if _REV else list(xs)
_FWD_ENV = {k: _os.environ[k] for k in ("REVERSE_LAYOUT", "V2_VICTIM_NODE_IDS") if _os.environ.get(k)}


def _cfg(profit_threshold: Optional[float], distribution: str = "pareto",
         dist_params: Optional[dict] = None, reps: int = DEFAULT_REPS) -> schema.V2Config:
    params: dict = {}
    if profit_threshold is not None:
        params["profit_threshold"] = profit_threshold
    env = dict(_BASE_ENV)
    env.update(_FWD_ENV)
    raw = {
        "protocol": {"name": "bullshark", "path": "bullshark"},
        "docker": {"tag": "mev-bullshark:latest", "cpus": "8.0", "memory": "16g"},
        "test": {"test_name": "test_fissure_attack_asr_dynamic", "REPETITIONS": 1},
        "environment": env,
        "adversary": {
            "threat_model": "TM-Solo",
            "archetype": "homogeneous",
            "topology": {
                "policies": [
                    {
                        "group_id": "g0",
                        "members": _rl([0, 1, 2, 3]),
                        "family": "frontrun",
                        "strategy": "fissure",
                        "params": params,
                    }
                ]
            },
        },
        "victims": {
            "workload": "multi_pareto" if distribution == "pareto" else "single_with_profit",
            "count": 3 if distribution == "pareto" else 1,
            "profit": {
                "distribution": distribution,
                "params": dist_params or ({"shape": 1.16, "scale": 1.0} if distribution == "pareto" else {"scale": 1.0}),
            },
        },
        "runtime": {"reps": reps, "seed": BASE_SEED},
    }
    return sweeper.expand_policy_vector(schema.parse_config(raw))


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
    return {
        "victim_profit_markers": len(profits),
        "adaptive_skip_markers": len(skips),
        "median_attacked_profit": st.median([p["profit"] for p in attacked]) if attacked else None,
        "mean_attacked_profit": st.mean([p["profit"] for p in attacked]) if attacked else None,
        "skip_rate": (len(skips) / len(profits)) if profits else 0.0,
    }


_EXTRA_COLS = (
    "victim_profit_markers",
    "adaptive_skip_markers",
    "median_attacked_profit",
    "mean_attacked_profit",
    "skip_rate",
)


def build_cells(reps: int = DEFAULT_REPS) -> list[benchmark.Cell]:
    cells = []
    # Pareto cells with threshold sweep
    cells.append(benchmark.Cell(
        name="mv_uniform_baseline",
        config=_cfg(profit_threshold=None, distribution="pareto", reps=reps),
        extra_columns=_EXTRA_COLS,
        marker_extractor=_extract,
        paper1_lookup=benchmark.paper1_lookup_frontrun,
    ))
    for t in (0.5, 1.0, 2.0, 5.0, 10.0):
        cells.append(benchmark.Cell(
            name=f"mv_threshold_{str(t).replace('.', 'p')}",
            config=_cfg(profit_threshold=t, distribution="pareto", reps=reps),
            extra_columns=_EXTRA_COLS,
            marker_extractor=_extract,
            paper1_lookup=benchmark.paper1_lookup_frontrun,
        ))
    # Uniform-distribution cells (H4.3)
    cells.append(benchmark.Cell(
        name="mv_uniform_dist_baseline",
        config=_cfg(profit_threshold=None, distribution="uniform", reps=reps),
        extra_columns=_EXTRA_COLS,
        marker_extractor=_extract,
        paper1_lookup=benchmark.paper1_lookup_frontrun,
    ))
    for t in (0.5, 1.0, 2.0):
        cells.append(benchmark.Cell(
            name=f"mv_uniform_dist_thresh_{str(t).replace('.', 'p')}",
            config=_cfg(profit_threshold=t, distribution="uniform", reps=reps),
            extra_columns=_EXTRA_COLS,
            marker_extractor=_extract,
            paper1_lookup=benchmark.paper1_lookup_frontrun,
        ))
    return cells


def _read_csv(path: str) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = defaultdict(list)
    with open(path) as fh:
        for row in csv.DictReader(fh):
            out[row["cell_name"]].append(row)
    return dict(out)


def _f(row: dict, col: str) -> Optional[float]:
    try:
        v = row.get(col)
        if v is None or v == "":
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _asrs(rows: list[dict]) -> list[float]:
    out = []
    for r in rows:
        v = _f(r, "asr")
        if v is not None:
            out.append(v)
    return out


def _attacked_profits(rows: list[dict]) -> list[float]:
    out = []
    for r in rows:
        v = _f(r, "median_attacked_profit")
        if v is not None:
            out.append(v)
    return out


def _skip_rates(rows: list[dict]) -> list[float]:
    out = []
    for r in rows:
        v = _f(r, "skip_rate")
        if v is not None:
            out.append(v)
    return out


def _pearson(xs: list[float], ys: list[float]) -> Optional[float]:
    if len(xs) != len(ys) or len(xs) < 2:
        return None
    mx = st.mean(xs); my = st.mean(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = sum((x - mx) ** 2 for x in xs)
    dy = sum((y - my) ** 2 for y in ys)
    den = (dx * dy) ** 0.5
    return None if den == 0 else num / den


def analyze(csv_path: str) -> dict[str, Any]:
    by_cell = _read_csv(csv_path)
    findings: dict[str, Any] = {}

    # H4.1 — adaptive > uniform: mv_threshold_1p0 vs mv_uniform_baseline
    if "mv_threshold_1p0" in by_cell and "mv_uniform_baseline" in by_cell:
        a = _asrs(by_cell["mv_threshold_1p0"])
        b = _asrs(by_cell["mv_uniform_baseline"])
        delta, lo, hi = stats.cliff_delta_bootstrap_ci(a, b, n_boot=1000, seed=0)
        ci_excl = lo > 0.0 or hi < 0.0
        meets = abs(delta) >= 0.33
        findings["H4.1_adaptive_vs_uniform"] = {
            "left": "mv_threshold_1p0", "right": "mv_uniform_baseline",
            "left_median": st.median(a), "right_median": st.median(b),
            "delta_median": st.median(a) - st.median(b),
            "cliff_delta": delta, "ci": [lo, hi],
            "magnitude": stats.cliff_delta_magnitude(delta),
            "verdict": "supported" if (ci_excl and meets) else "rejected",
        }

    # H4.2 — threshold sensitivity (correlation between threshold and median attacked profit)
    threshold_cells = [("mv_threshold_0p5", 0.5), ("mv_threshold_1p0", 1.0),
                       ("mv_threshold_2p0", 2.0), ("mv_threshold_5p0", 5.0),
                       ("mv_threshold_10p0", 10.0)]
    thresholds = []
    profits = []
    asrs_means = []
    for name, t in threshold_cells:
        if name in by_cell:
            rows = by_cell[name]
            mp = _attacked_profits(rows)
            ar = _asrs(rows)
            if mp:
                thresholds.append(t)
                profits.append(st.median(mp))
                asrs_means.append(st.median(ar) if ar else 0.0)
    rho_profit = _pearson(thresholds, profits)
    findings["H4.2_threshold_sensitivity"] = {
        "thresholds": thresholds,
        "median_attacked_profits": profits,
        "median_asrs": asrs_means,
        "pearson_threshold_vs_profit": rho_profit,
        "verdict": "supported" if (rho_profit is not None and rho_profit > 0.5) else "rejected",
    }

    # H4.3 — distribution sensitivity: best-Pareto threshold vs best-uniform threshold
    # Best = highest median ASR. Compare positions of best thresholds.
    pareto_best = max(
        [(t, st.median(_asrs(by_cell.get(name, [])))) for name, t in threshold_cells if name in by_cell],
        key=lambda x: x[1] if x[1] is not None else -1,
        default=(None, None),
    )
    uniform_threshold_cells = [("mv_uniform_dist_thresh_0p5", 0.5),
                               ("mv_uniform_dist_thresh_1p0", 1.0),
                               ("mv_uniform_dist_thresh_2p0", 2.0)]
    uniform_best = max(
        [(t, st.median(_asrs(by_cell.get(name, [])))) for name, t in uniform_threshold_cells if name in by_cell],
        key=lambda x: x[1] if x[1] is not None else -1,
        default=(None, None),
    )
    if pareto_best[0] is not None and uniform_best[0] is not None:
        diff = abs(pareto_best[0] - uniform_best[0])
        findings["H4.3_distribution_sensitivity"] = {
            "pareto_best_threshold": pareto_best[0],
            "pareto_best_median_asr": pareto_best[1],
            "uniform_best_threshold": uniform_best[0],
            "uniform_best_median_asr": uniform_best[1],
            "threshold_difference": diff,
            "verdict": "supported" if diff >= 0.5 else "rejected",
        }

    # H4.4 — skip-rate vs attacked profit correlation
    skip_rates = []
    profits_per_cell = []
    for name, _t in threshold_cells:
        if name in by_cell:
            sr = _skip_rates(by_cell[name])
            mp = _attacked_profits(by_cell[name])
            if sr and mp:
                skip_rates.append(st.median(sr))
                profits_per_cell.append(st.median(mp))
    rho_skip = _pearson(skip_rates, profits_per_cell)
    findings["H4.4_skip_profit_correlation"] = {
        "skip_rates": skip_rates,
        "median_attacked_profits": profits_per_cell,
        "pearson": rho_skip,
        # We expect HIGHER skip rate → HIGHER attacked profit (selectivity yields better picks).
        "verdict": "supported" if (rho_skip is not None and rho_skip > 0.5) else "rejected",
    }

    return {
        "campaign": "P5v3_multivictim",
        "preregistration": "paper_workspace/p5v3_preregistration.md",
        "per_cell_medians": {name: st.median(_asrs(rows)) if _asrs(rows) else None
                              for name, rows in by_cell.items()},
        "findings": findings,
    }


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="p5v3_multivictim")
    parser.add_argument("--out-csv", default=DEFAULT_CSV)
    parser.add_argument("--out-summary", default=DEFAULT_SUMMARY)
    parser.add_argument("--out-verdict", default=DEFAULT_VERDICT)
    parser.add_argument("--reps", type=int, default=DEFAULT_REPS)
    parser.add_argument("--analyze-only", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)

    csv_p = Path(args.out_csv)
    if not args.analyze_only:
        if csv_p.exists():
            csv_p.unlink()
        cells = build_cells(reps=args.reps)
        print(f"P5 v3 Multi-victim campaign: {len(cells)} cells × {args.reps} reps")

        def log(msg: str) -> None:
            print(msg, flush=True)

        benchmark.run_benchmark(
            cells=cells, out_csv=args.out_csv, out_summary_json=args.out_summary,
            reps=args.reps, progress_callback=log,
        )

    print("\n--- H4.x adjudication ---")
    verdict = analyze(args.out_csv)
    Path(args.out_verdict).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out_verdict, "w") as fh:
        json.dump(verdict, fh, indent=2, default=str)
    for hyp_name, hyp_data in verdict["findings"].items():
        v = hyp_data.get("verdict", "?")
        print(f"  {hyp_name}: {v}")
    print(f"\nVerdict written to {args.out_verdict}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
