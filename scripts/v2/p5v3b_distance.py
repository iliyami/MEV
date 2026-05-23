"""P5 v3b — Distance × Profit extension.

Pre-registered in `paper_workspace/p5v3b_preregistration.md`.

2x2 matrix on network latency × victim-targeting strategy:

    cell                    latency           threshold
    mv_lat_low_uniform      LATENCY_MS=10     none (attack all)
    mv_lat_low_highval      LATENCY_MS=10     10.0 (attack heavy tail)
    mv_lat_high_uniform     LATENCY_MS=300    none
    mv_lat_high_highval     LATENCY_MS=300    10.0

Hypotheses:
  H_D1: high-latency hurts ASR
  H_D2: high-value targeting raises expected MEV under both latencies
  H_D3: latency × profit interaction (exploratory)

10 reps per cell; total 40 runs.
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


DEFAULT_CSV = "results/v2_p5v3b_results.csv"
DEFAULT_SUMMARY = "results/v2_p5v3b_summary.json"
DEFAULT_VERDICT = "results/v2_p5v3b_verdict.json"
DEFAULT_REPS = 10
BASE_SEED = 42

_RE_VICTIM_PROFIT = re.compile(
    r"V2_VICTIM_PROFIT: round=(\d+) author=(\d+) profit=([\d.eE+-]+)"
)
_RE_ADAPTIVE_SKIP = re.compile(
    r"V2_ADAPTIVE_SKIP: round=(\d+) author=(\d+) profit=([\d.eE+-]+) threshold=([\d.eE+-]+)"
)


def _cfg(latency_ms: int, jitter_ms: int, profit_threshold: Optional[float],
         reps: int = DEFAULT_REPS) -> schema.V2Config:
    env = {
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
        # The proxy "distance" knobs — environment-level latency.
        "LATENCY_MS": str(latency_ms),
        "JITTER_MS": str(jitter_ms),
        # High-latency cells need longer COLLECTION_DURATION to gather
        # comparable commit counts.
        "COLLECTION_DURATION": "120" if latency_ms >= 100 else "35",
    }
    params: dict = {}
    if profit_threshold is not None:
        params["profit_threshold"] = profit_threshold
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
                        "members": [0, 1, 2, 3],
                        "family": "frontrun",
                        "strategy": "fissure",
                        "params": params,
                    }
                ]
            },
        },
        "victims": {
            "workload": "multi_pareto",
            "count": 3,
            "profit": {
                "distribution": "pareto",
                "params": {"shape": 1.16, "scale": 1.0},
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
            profits.append({"round": int(m.group(1)), "author": int(m.group(2)),
                            "profit": float(m.group(3))})
        m = _RE_ADAPTIVE_SKIP.search(line)
        if m:
            skips.append({"round": int(m.group(1)), "author": int(m.group(2)),
                          "profit": float(m.group(3))})
    skipped_keys = {(s["round"], s["author"]) for s in skips}
    attacked = [p for p in profits if (p["round"], p["author"]) not in skipped_keys]
    return {
        "victim_profit_markers": len(profits),
        "adaptive_skip_markers": len(skips),
        "median_attacked_profit": (
            st.median([p["profit"] for p in attacked]) if attacked else None
        ),
        "skip_rate": (len(skips) / len(profits)) if profits else 0.0,
    }


_EXTRA = (
    "victim_profit_markers",
    "adaptive_skip_markers",
    "median_attacked_profit",
    "skip_rate",
)


def build_cells(reps: int = DEFAULT_REPS) -> list[benchmark.Cell]:
    return [
        benchmark.Cell(
            name="mv_lat_low_uniform",
            config=_cfg(latency_ms=10, jitter_ms=2, profit_threshold=None, reps=reps),
            extra_columns=_EXTRA, marker_extractor=_extract,
            paper1_lookup=benchmark.paper1_lookup_frontrun,
        ),
        benchmark.Cell(
            name="mv_lat_low_highval",
            config=_cfg(latency_ms=10, jitter_ms=2, profit_threshold=10.0, reps=reps),
            extra_columns=_EXTRA, marker_extractor=_extract,
            paper1_lookup=benchmark.paper1_lookup_frontrun,
        ),
        benchmark.Cell(
            name="mv_lat_high_uniform",
            config=_cfg(latency_ms=300, jitter_ms=50, profit_threshold=None, reps=reps),
            extra_columns=_EXTRA, marker_extractor=_extract,
            paper1_lookup=benchmark.paper1_lookup_frontrun,
        ),
        benchmark.Cell(
            name="mv_lat_high_highval",
            config=_cfg(latency_ms=300, jitter_ms=50, profit_threshold=10.0, reps=reps),
            extra_columns=_EXTRA, marker_extractor=_extract,
            paper1_lookup=benchmark.paper1_lookup_frontrun,
        ),
    ]


def _read_csv(p: str) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = defaultdict(list)
    with open(p) as fh:
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
    return [v for v in (_f(r, "asr") for r in rows) if v is not None]


def _attacked_profits(rows: list[dict]) -> list[float]:
    return [v for v in (_f(r, "median_attacked_profit") for r in rows) if v is not None]


def _expected_mevs(rows: list[dict]) -> list[float]:
    """Per-rep expected MEV = ASR * median attacked profit."""
    out = []
    for r in rows:
        asr = _f(r, "asr")
        prof = _f(r, "median_attacked_profit")
        if asr is not None and prof is not None:
            out.append(asr * prof / 100.0)
    return out


def _compare(a: list[float], b: list[float]) -> dict:
    if not a or not b:
        return {"skipped": True}
    delta, lo, hi = stats.cliff_delta_bootstrap_ci(a, b, n_boot=1000, seed=0)
    u = stats.mann_whitney_u(a, b)
    return {
        "left_median": st.median(a), "right_median": st.median(b),
        "delta_median": st.median(a) - st.median(b),
        "cliff_delta": delta, "ci": [lo, hi],
        "magnitude": stats.cliff_delta_magnitude(delta),
        "ci_excludes_zero": lo > 0.0 or hi < 0.0,
        "meets_0p33_threshold": abs(delta) >= 0.33,
        "p_two_sided": u["p_two_sided"],
        "decision": (
            "supports" if (abs(delta) >= 0.33 and (lo > 0.0 or hi < 0.0))
            else "rejects"
        ),
    }


def analyze(csv_path: str) -> dict[str, Any]:
    by_cell = _read_csv(csv_path)
    findings: dict[str, Any] = {}

    # H_D1: high-latency uniform vs low-latency uniform
    if all(c in by_cell for c in ("mv_lat_high_uniform", "mv_lat_low_uniform")):
        cmp_ = _compare(_asrs(by_cell["mv_lat_high_uniform"]),
                        _asrs(by_cell["mv_lat_low_uniform"]))
        findings["H_D1_latency_hurts_asr"] = {
            "result": cmp_,
            "verdict": (
                "supported" if cmp_.get("decision") == "supports"
                and cmp_.get("cliff_delta", 0) < 0 else "rejected"
            ),
        }

    # H_D2: expected MEV(highval) > expected MEV(uniform) at each latency
    expected_mev = {}
    for cell in ("mv_lat_low_uniform", "mv_lat_low_highval",
                 "mv_lat_high_uniform", "mv_lat_high_highval"):
        if cell in by_cell:
            mevs = _expected_mevs(by_cell[cell])
            expected_mev[cell] = {
                "median": st.median(mevs) if mevs else None,
                "mean": st.mean(mevs) if mevs else None,
                "n": len(mevs),
            }
    findings["expected_mev_per_cell"] = expected_mev

    # H_D2 sub-tests at each latency
    h_d2: dict[str, Any] = {"by_latency": {}}
    for lat_label, hv_cell, un_cell in [
        ("low_latency", "mv_lat_low_highval", "mv_lat_low_uniform"),
        ("high_latency", "mv_lat_high_highval", "mv_lat_high_uniform"),
    ]:
        if hv_cell in by_cell and un_cell in by_cell:
            cmp_ = _compare(_expected_mevs(by_cell[hv_cell]),
                            _expected_mevs(by_cell[un_cell]))
            h_d2["by_latency"][lat_label] = {
                "result": cmp_,
                "supports_h_d2": (
                    cmp_.get("decision") == "supports"
                    and cmp_.get("cliff_delta", 0) > 0
                ),
            }
    both_support = all(v.get("supports_h_d2") for v in h_d2["by_latency"].values())
    h_d2["verdict"] = "supported" if both_support else "rejected"
    findings["H_D2_highvalue_raises_mev"] = h_d2

    # H_D3: latency × profit interaction (exploratory)
    if all(c in by_cell for c in ("mv_lat_low_uniform", "mv_lat_low_highval",
                                    "mv_lat_high_uniform", "mv_lat_high_highval")):
        low_gap = (st.median(_expected_mevs(by_cell["mv_lat_low_highval"])) -
                   st.median(_expected_mevs(by_cell["mv_lat_low_uniform"])))
        high_gap = (st.median(_expected_mevs(by_cell["mv_lat_high_highval"])) -
                    st.median(_expected_mevs(by_cell["mv_lat_high_uniform"])))
        findings["H_D3_interaction_exploratory"] = {
            "low_latency_mev_gap_highval_minus_uniform": low_gap,
            "high_latency_mev_gap_highval_minus_uniform": high_gap,
            "diff_in_diff_high_minus_low": high_gap - low_gap,
            "note": "Exploratory; no acceptance rule.",
        }

    return {
        "campaign": "P5v3b_distance",
        "preregistration": "paper_workspace/p5v3b_preregistration.md",
        "per_cell_medians": {
            name: {
                "asr_median": st.median(_asrs(rows)) if _asrs(rows) else None,
                "attacked_profit_median": (
                    st.median(_attacked_profits(rows)) if _attacked_profits(rows) else None
                ),
                "expected_mev_median": (
                    st.median(_expected_mevs(rows)) if _expected_mevs(rows) else None
                ),
                "n": len(rows),
            }
            for name, rows in by_cell.items()
        },
        "findings": findings,
    }


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="p5v3b_distance")
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
        print(f"P5 v3b Distance extension: {len(cells)} cells × {args.reps} reps")

        def log(msg: str) -> None:
            print(msg, flush=True)

        benchmark.run_benchmark(
            cells=cells, out_csv=args.out_csv,
            out_summary_json=args.out_summary,
            reps=args.reps, progress_callback=log,
        )

    print("\n--- H_D adjudication ---")
    verdict = analyze(args.out_csv)
    Path(args.out_verdict).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out_verdict, "w") as fh:
        json.dump(verdict, fh, indent=2, default=str)
    for hyp_name, hyp_data in verdict["findings"].items():
        if hyp_name.startswith("H_D"):
            v = hyp_data.get("verdict", "?")
            print(f"  {hyp_name}: {v}")
        elif hyp_name == "expected_mev_per_cell":
            print("\nExpected MEV per cell (median per-rep ASR × median attacked profit):")
            for cell, st_ in hyp_data.items():
                med = st_.get("median")
                print(f"  {cell}: {med:.3f}" if med is not None else f"  {cell}: n/a")
    print(f"\nVerdict written to {args.out_verdict}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
