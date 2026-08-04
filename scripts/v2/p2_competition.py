"""P2 — Competition campaign (H1).

Pre-registered in `paper_workspace/p2_preregistration.md`.

Primary cells (4):
    k=1: homogeneous all-fissure              (paper-1 baseline-equivalent)
    k=2: same_family_split, 2 groups of 2     (strategies = [fissure, speculative])
    k=3: same_family_split, 3 groups (2+1+1)  (strategies = [fissure, speculative, sluggish])
    k=4: same_family_split, 4 groups of 1     (strategies = [fissure, speculative, sluggish, fissure])

All cells: protocol=Bullshark, n=13, α=0.308, family=frontrun,
victim_workload=single uniform, coordination/bribery=disabled,
5 reps, seeds 0..4.

Usage:
    python -m scripts.v2.p2_competition --run        # run the campaign
    python -m scripts.v2.p2_competition --analyze    # adjudicate from CSV
    python -m scripts.v2.p2_competition              # run + analyze
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Optional

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from scripts.v2 import benchmark, schema, stats, sweeper


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_CSV = "results/v2_p2_competition_results.csv"
DEFAULT_SUMMARY = "results/v2_p2_competition_summary.json"
DEFAULT_VERDICT = "results/v2_p2_competition_h1_verdict.json"
DEFAULT_REPS = 5
BASE_SEED = 0


# ---------------------------------------------------------------------------
# Cell configs
# ---------------------------------------------------------------------------


_BASE_ENV = {
    "NUM_NODES": "13",
    "ATTACKER_RATIO": "0.308",
    "VICTIM_RATIO": "0.231",
    "SPECULATIVE_P_MAX": "50",
    "SLUGGISH_TIMEOUT_MULTIPLIER": "1.5",
    "DAG_STATE_CACHED_ROUNDS": "5",
    "SYNC_TIMEOUT_MS": "2000",
    "GC_DEPTH": "10",
    "ATTACK_MODE": "fissure",  # placeholder; Coordinator overrides per-node
    "ATTACK_TYPE": "frontrun",
}

# Opt-in all-pairs re-run: when V2_ALL_PAIRS_ASR is set in the process env, promote
# the neutral-baseline all-pairs metric to the headline `asr` for every cell. Default
# (env unset) keeps same-round so the paper-1 contradiction checks stay intact.
import os as _os
if _os.environ.get("V2_ALL_PAIRS_ASR"):
    _BASE_ENV["V2_ALL_PAIRS_ASR"] = _os.environ["V2_ALL_PAIRS_ASR"]

# REVERSE_LAYOUT: measure off the index-tax ceiling. Reflect every attacker index with
# r(i)=N-1-i so the competing groups sit at the HIGH (disadvantaged) block and the victim
# at the LOW block, matching the binary's REVERSE_LAYOUT. Default path is byte-identical.
_N_NODES = 13
_REV = bool(_os.environ.get("REVERSE_LAYOUT"))
def _r(i: int) -> int:
    return (_N_NODES - 1 - i) if _REV else i
def _rl(xs) -> list[int]:
    return sorted(_r(i) for i in xs) if _REV else list(xs)
for _k in ("REVERSE_LAYOUT", "V2_VICTIM_NODE_IDS"):
    if _os.environ.get(_k):
        _BASE_ENV[_k] = _os.environ[_k]


def _cfg(threat_model: str, archetype: str, policies: list[dict], reps: int) -> schema.V2Config:
    if _REV:
        policies = [{**p, "members": _rl(p["members"])} if "members" in p else p
                    for p in policies]
    raw = {
        "protocol": {"name": "bullshark", "path": "bullshark"},
        "docker": {"tag": "mev-bullshark:latest", "cpus": "8.0", "memory": "16g"},
        "test": {"test_name": "test_fissure_attack_asr_dynamic", "REPETITIONS": 1},
        "environment": dict(_BASE_ENV),
        "adversary": {
            "threat_model": threat_model,
            "archetype": archetype,
            "topology": {"policies": policies},
        },
        "victims": {"workload": "single", "count": 1},
        "runtime": {"reps": reps, "seed": BASE_SEED},
    }
    return sweeper.expand_policy_vector(schema.parse_config(raw))


def _cell_k1(reps: int) -> benchmark.Cell:
    """k=1: homogeneous all-fissure (paper-1 baseline-equivalent)."""
    policies = [
        {
            "group_id": "g0",
            "members": [0, 1, 2, 3],
            "family": "frontrun",
            "strategy": "fissure",
            "params": {},
        }
    ]
    return benchmark.Cell(
        name="k1_homogeneous_fissure",
        config=_cfg("TM-Solo", "homogeneous", policies, reps),
        paper1_lookup=benchmark.paper1_lookup_frontrun,
    )


def _cell_k2(reps: int) -> benchmark.Cell:
    """k=2: 2 groups of 2; strategies = [fissure, speculative]."""
    policies = [
        {
            "group_id": "g0",
            "members": [0, 1],
            "family": "frontrun",
            "strategy": "fissure",
            "params": {},
        },
        {
            "group_id": "g1",
            "members": [2, 3],
            "family": "frontrun",
            "strategy": "speculative",
            "params": {},
        },
    ]
    return benchmark.Cell(
        name="k2_same_family_split",
        config=_cfg("TM-Compete", "same_family_split", policies, reps),
        paper1_lookup=benchmark.paper1_lookup_frontrun,
    )


def _cell_k3(reps: int) -> benchmark.Cell:
    """k=3: 3 groups (2+1+1); strategies = [fissure, speculative, sluggish]."""
    policies = [
        {
            "group_id": "g0",
            "members": [0, 1],
            "family": "frontrun",
            "strategy": "fissure",
            "params": {},
        },
        {
            "group_id": "g1",
            "members": [2],
            "family": "frontrun",
            "strategy": "speculative",
            "params": {},
        },
        {
            "group_id": "g2",
            "members": [3],
            "family": "frontrun",
            "strategy": "sluggish",
            "params": {},
        },
    ]
    return benchmark.Cell(
        name="k3_same_family_split",
        config=_cfg("TM-Compete", "same_family_split", policies, reps),
        paper1_lookup=benchmark.paper1_lookup_frontrun,
    )


def _cell_k4(reps: int) -> benchmark.Cell:
    """k=4: 4 groups of 1; strategies = [fissure, speculative, sluggish, fissure]."""
    policies = [
        {
            "group_id": "g0",
            "members": [0],
            "family": "frontrun",
            "strategy": "fissure",
            "params": {},
        },
        {
            "group_id": "g1",
            "members": [1],
            "family": "frontrun",
            "strategy": "speculative",
            "params": {},
        },
        {
            "group_id": "g2",
            "members": [2],
            "family": "frontrun",
            "strategy": "sluggish",
            "params": {},
        },
        {
            "group_id": "g3",
            "members": [3],
            "family": "frontrun",
            "strategy": "fissure",
            "params": {},
        },
    ]
    return benchmark.Cell(
        name="k4_same_family_split",
        config=_cfg("TM-Compete", "same_family_split", policies, reps),
        paper1_lookup=benchmark.paper1_lookup_frontrun,
    )


def _cell_k2_fissure_sluggish(reps: int) -> benchmark.Cell:
    """Decomposition cell: k=2 with [fissure, sluggish] instead of [fissure, speculative].

    Tests whether the sluggish strategy alone in k=2 lifts ASR to k=3 levels.
    If yes -> sluggish does the work, not diversity per se.
    If no  -> the k=3 lift requires the broader diversity, not just sluggish.
    """
    policies = [
        {
            "group_id": "g0",
            "members": [0, 1],
            "family": "frontrun",
            "strategy": "fissure",
            "params": {},
        },
        {
            "group_id": "g1",
            "members": [2, 3],
            "family": "frontrun",
            "strategy": "sluggish",
            "params": {},
        },
    ]
    return benchmark.Cell(
        name="k2_fissure_sluggish",
        config=_cfg("TM-Compete", "same_family_split", policies, reps),
        paper1_lookup=benchmark.paper1_lookup_frontrun,
    )


def _cell_k3_no_sluggish(reps: int) -> benchmark.Cell:
    """Decomposition cell: k=3 WITHOUT sluggish; strategies = [fissure, speculative, fissure].

    Tests whether the k=3 lift survives if sluggish is removed.
    If yes -> diversity boost is real, not a sluggish artifact.
    If no  -> the k=3 lift is sluggish-driven; the diversity story is weak.
    """
    policies = [
        {
            "group_id": "g0",
            "members": [0, 1],
            "family": "frontrun",
            "strategy": "fissure",
            "params": {},
        },
        {
            "group_id": "g1",
            "members": [2],
            "family": "frontrun",
            "strategy": "speculative",
            "params": {},
        },
        {
            "group_id": "g2",
            "members": [3],
            "family": "frontrun",
            "strategy": "fissure",
            "params": {},
        },
    ]
    return benchmark.Cell(
        name="k3_no_sluggish",
        config=_cfg("TM-Compete", "same_family_split", policies, reps),
        paper1_lookup=benchmark.paper1_lookup_frontrun,
    )


def build_cells(reps: int = DEFAULT_REPS) -> list[benchmark.Cell]:
    return [
        _cell_k1(reps),
        _cell_k2(reps),
        _cell_k2_fissure_sluggish(reps),
        _cell_k3(reps),
        _cell_k3_no_sluggish(reps),
        _cell_k4(reps),
    ]


# ---------------------------------------------------------------------------
# Analysis — applies the pre-registered decision rule
# ---------------------------------------------------------------------------


# Cells in the H1 across-k sweep (used for the monotonicity adjudication).
# Decomposition cells (k2_fissure_sluggish, k3_no_sluggish) are NOT in this
# list — they exist for confound attribution and are reported separately.
CELL_K_ORDER = [
    ("k1_homogeneous_fissure", 1),
    ("k2_same_family_split", 2),
    ("k3_same_family_split", 3),
    ("k4_same_family_split", 4),
]
DECOMPOSITION_CELLS = ["k2_fissure_sluggish", "k3_no_sluggish"]


def _read_csv_asrs(csv_path: str) -> dict[str, list[float]]:
    """Return {cell_name: [asrs across reps]} from a P2 results CSV."""
    by_cell: dict[str, list[float]] = defaultdict(list)
    with open(csv_path, "r") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            try:
                asr = float(row["asr"])
            except (KeyError, ValueError):
                continue
            by_cell[row["cell_name"]].append(asr)
    return dict(by_cell)


def analyze_h1(csv_path: str) -> dict[str, Any]:
    """Compute the pre-registered H1 verdict from the results CSV."""
    by_cell = _read_csv_asrs(csv_path)
    missing = [name for name, _ in CELL_K_ORDER if name not in by_cell]
    if missing:
        raise ValueError(f"missing cells in {csv_path}: {missing}")

    per_cell = []
    for name, k in CELL_K_ORDER:
        asrs = by_cell[name]
        per_cell.append(
            {
                "cell_name": name,
                "k": k,
                "n": len(asrs),
                "mean": st.mean(asrs),
                "median": st.median(asrs),
                "min": min(asrs),
                "max": max(asrs),
                "asrs": asrs,
            }
        )

    # Adjacent-pair comparisons
    pair_results = []
    raw_pvalues = []
    for i in range(len(per_cell) - 1):
        a = per_cell[i]
        b = per_cell[i + 1]
        u = stats.mann_whitney_u(b["asrs"], a["asrs"])  # delta = b vs a
        delta, lo, hi = stats.cliff_delta_bootstrap_ci(
            b["asrs"], a["asrs"], n_boot=1000, seed=i
        )
        direction = (
            "increase" if delta > 0 else "decrease" if delta < 0 else "no_change"
        )
        magnitude = stats.cliff_delta_magnitude(delta)
        meets_threshold = abs(delta) >= 0.33
        raw_pvalues.append(u["p_two_sided"])
        pair_results.append(
            {
                "from_k": a["k"],
                "to_k": b["k"],
                "from_median": a["median"],
                "to_median": b["median"],
                "delta_median": b["median"] - a["median"],
                "cliff_delta": delta,
                "cliff_delta_ci": [lo, hi],
                "magnitude": magnitude,
                "direction": direction,
                "meets_0p33_threshold": meets_threshold,
                "u_statistic": u["u_min"],
                "p_two_sided_raw": u["p_two_sided"],
                # filled in below after Holm
                "p_two_sided_holm": None,
            }
        )

    holm_p = stats.holm_correction(raw_pvalues)
    for pr, hp in zip(pair_results, holm_p):
        pr["p_two_sided_holm"] = hp

    # Decision rule (pre-registered):
    notable_increases = [
        pr for pr in pair_results if pr["meets_0p33_threshold"] and pr["direction"] == "increase"
    ]
    notable_decreases = [
        pr for pr in pair_results if pr["meets_0p33_threshold"] and pr["direction"] == "decrease"
    ]
    if notable_increases and notable_decreases:
        verdict = "supported"
        verdict_explanation = (
            f"Non-monotonic: {len(notable_increases)} notable increase(s) AND "
            f"{len(notable_decreases)} notable decrease(s) among adjacent pairs "
            f"(Cliff's delta ≥ 0.33)."
        )
    elif notable_decreases:
        verdict = "inconclusive"
        verdict_explanation = (
            "Decrease(s) present but no notable increase. The curve trends "
            "down but the non-monotonic prediction is not directly supported."
        )
    elif notable_increases or any(pr["direction"] == "increase" for pr in pair_results):
        verdict = "rejected"
        verdict_explanation = (
            "Curve is monotone non-decreasing within our 0.33 effect-size "
            "threshold; H1 (non-monotonicity) is not supported by this data."
        )
    else:
        verdict = "inconclusive"
        verdict_explanation = (
            "All adjacent-pair effects are below the 0.33 threshold. N=5 "
            "did not separate cells from noise; consider extending reps."
        )

    # Attribution analysis using decomposition cells (if available)
    attribution = _attribute_h1(by_cell, per_cell)

    return {
        "campaign": "P2_competition_H1",
        "preregistration": "paper_workspace/p2_preregistration.md",
        "per_cell": per_cell,
        "pair_results": pair_results,
        "verdict": verdict,
        "verdict_explanation": verdict_explanation,
        "attribution": attribution,
    }


def _attribute_h1(by_cell: dict[str, list[float]], per_cell: list[dict]) -> dict[str, Any]:
    """Use decomposition cells to attribute the k=3 lift.

    Two diagnostic comparisons:

      (a) k2_fissure_sluggish vs k2_same_family_split:
          If sluggish in k=2 already reaches k=3 levels, the k=3 boost is
          sluggish-driven rather than diversity-driven.

      (b) k3_no_sluggish vs k3_same_family_split (with sluggish):
          If k=3 without sluggish still beats k=2, diversity matters.
          If k=3 without sluggish collapses to k=2 levels, sluggish carries it.
    """
    by_name = {c["cell_name"]: c for c in per_cell}
    out: dict[str, Any] = {"available": True, "diagnostics": []}

    def cmp(a_name: str, b_name: str, label: str) -> Optional[dict]:
        if a_name not in by_cell or b_name not in by_cell:
            return {"label": label, "skipped": True, "reason": "cell missing"}
        a_asrs = by_cell[a_name]
        b_asrs = by_cell[b_name]
        u = stats.mann_whitney_u(a_asrs, b_asrs)
        delta, lo, hi = stats.cliff_delta_bootstrap_ci(a_asrs, b_asrs, n_boot=1000, seed=0)
        return {
            "label": label,
            "left_cell": a_name,
            "right_cell": b_name,
            "left_median": st.median(a_asrs),
            "right_median": st.median(b_asrs),
            "delta_median": st.median(a_asrs) - st.median(b_asrs),
            "cliff_delta_left_vs_right": delta,
            "ci": [lo, hi],
            "magnitude": stats.cliff_delta_magnitude(delta),
            "p_two_sided_raw": u["p_two_sided"],
        }

    # (a) Does sluggish in k=2 reach k=3 levels?
    out["diagnostics"].append(
        cmp(
            "k2_fissure_sluggish", "k3_same_family_split",
            "k2_fissure_sluggish vs k3_with_sluggish (does sluggish alone match k=3?)",
        )
    )
    out["diagnostics"].append(
        cmp(
            "k2_fissure_sluggish", "k2_same_family_split",
            "k2_fissure_sluggish vs k2_with_speculative (effect of strategy choice at k=2)",
        )
    )

    # (b) Does k=3 still win without sluggish?
    out["diagnostics"].append(
        cmp(
            "k3_no_sluggish", "k2_same_family_split",
            "k3_no_sluggish vs k2_with_speculative (k=3 lift without sluggish)",
        )
    )
    out["diagnostics"].append(
        cmp(
            "k3_no_sluggish", "k3_same_family_split",
            "k3_no_sluggish vs k3_with_sluggish (cost of removing sluggish at k=3)",
        )
    )

    # Synthesis: what does the attribution data say?
    sluggish_in_k2 = next(
        (d for d in out["diagnostics"] if d and d.get("label", "").startswith("k2_fissure_sluggish vs k3_with_sluggish")),
        None,
    )
    k3_minus_sluggish = next(
        (d for d in out["diagnostics"] if d and d.get("label", "").startswith("k3_no_sluggish vs k2_with_speculative")),
        None,
    )

    interp_lines: list[str] = []
    if sluggish_in_k2 and not sluggish_in_k2.get("skipped"):
        delta_pp = sluggish_in_k2["delta_median"]  # k2_sluggish median - k3_with_sluggish median
        if abs(sluggish_in_k2["cliff_delta_left_vs_right"]) < 0.33:
            interp_lines.append(
                f"k2_fissure_sluggish median ≈ k3_with_sluggish median (Δ={delta_pp:+.2f}pp, "
                f"Cliff's δ={sluggish_in_k2['cliff_delta_left_vs_right']:+.3f}, "
                f"magnitude={sluggish_in_k2['magnitude']}). Suggests sluggish does the work, "
                "not diversity per se."
            )
        elif sluggish_in_k2["cliff_delta_left_vs_right"] < 0:
            interp_lines.append(
                f"k2_fissure_sluggish < k3_with_sluggish (Δ={delta_pp:+.2f}pp). "
                "Sluggish alone in k=2 does NOT reach k=3 levels."
            )
        else:
            interp_lines.append(
                f"k2_fissure_sluggish > k3_with_sluggish (Δ={delta_pp:+.2f}pp). "
                "Sluggish in k=2 beats full k=3."
            )

    if k3_minus_sluggish and not k3_minus_sluggish.get("skipped"):
        delta_pp = k3_minus_sluggish["delta_median"]  # k3_no_sluggish - k2_with_speculative
        if k3_minus_sluggish["cliff_delta_left_vs_right"] >= 0.33:
            interp_lines.append(
                f"k3_no_sluggish > k2_with_speculative (Δ={delta_pp:+.2f}pp, "
                f"Cliff's δ={k3_minus_sluggish['cliff_delta_left_vs_right']:+.3f}). "
                "The k=3 lift survives removal of sluggish — diversity matters."
            )
        elif abs(k3_minus_sluggish["cliff_delta_left_vs_right"]) < 0.33:
            interp_lines.append(
                f"k3_no_sluggish ≈ k2_with_speculative (Δ={delta_pp:+.2f}pp). "
                "Without sluggish, k=3 collapses to k=2 levels — sluggish carries the lift."
            )
        else:
            interp_lines.append(
                f"k3_no_sluggish < k2_with_speculative (Δ={delta_pp:+.2f}pp). "
                "Without sluggish, k=3 underperforms k=2; unusual."
            )

    out["interpretation"] = interp_lines
    return out


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="p2_competition")
    parser.add_argument("--out-csv", default=DEFAULT_CSV)
    parser.add_argument("--out-summary", default=DEFAULT_SUMMARY)
    parser.add_argument("--out-verdict", default=DEFAULT_VERDICT)
    parser.add_argument("--reps", type=int, default=DEFAULT_REPS)
    parser.add_argument(
        "--analyze-only", action="store_true", help="skip running; analyze existing CSV"
    )
    parser.add_argument(
        "--no-analyze", action="store_true", help="run only; skip verdict computation"
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    csv_p = Path(args.out_csv)

    if not args.analyze_only:
        if csv_p.exists():
            csv_p.unlink()
        cells = build_cells(reps=args.reps)
        print(
            f"P2 Competition campaign: {len(cells)} cells × {args.reps} reps "
            f"(pre-registered in paper_workspace/p2_preregistration.md)"
        )

        def log(msg: str) -> None:
            print(msg, flush=True)

        summaries = benchmark.run_benchmark(
            cells=cells,
            out_csv=args.out_csv,
            out_summary_json=args.out_summary,
            reps=args.reps,
            progress_callback=log,
        )
        print("\nPer-cell summary:")
        for name, s in summaries.items():
            print(
                f"  [{name}] n={s.reps} mean={s.asr_mean:.2f}% "
                f"median={s.asr_median:.2f}% IQR={s.asr_iqr} "
                f"exits={s.all_exit_codes}"
            )

    if args.no_analyze:
        return 0

    print("\n--- H1 adjudication ---")
    verdict = analyze_h1(args.out_csv)
    Path(args.out_verdict).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out_verdict, "w") as fh:
        json.dump(verdict, fh, indent=2, default=str)

    print(f"verdict: {verdict['verdict'].upper()}")
    print(f"  {verdict['verdict_explanation']}")
    print("\nPer-cell medians:")
    for c in verdict["per_cell"]:
        print(
            f"  k={c['k']:1d}  median={c['median']:6.2f}%  "
            f"(min={c['min']:.2f}, max={c['max']:.2f}, n={c['n']})"
        )
    print("\nAdjacent-pair comparisons:")
    for pr in verdict["pair_results"]:
        print(
            f"  k{pr['from_k']}→k{pr['to_k']}: "
            f"Δmedian={pr['delta_median']:+6.2f}pp  "
            f"Cliff's δ={pr['cliff_delta']:+.3f} [{pr['cliff_delta_ci'][0]:+.3f}, {pr['cliff_delta_ci'][1]:+.3f}] "
            f"({pr['magnitude']}, {pr['direction']})  "
            f"p_holm={pr['p_two_sided_holm']:.4f}  "
            f"≥0.33? {pr['meets_0p33_threshold']}"
        )
    if verdict.get("attribution") and verdict["attribution"].get("available"):
        print("\n--- Attribution (decomposition cells) ---")
        for d in verdict["attribution"]["diagnostics"]:
            if d is None or d.get("skipped"):
                continue
            print(
                f"  {d['label']}\n"
                f"    {d['left_cell']} median={d['left_median']:.2f}% vs "
                f"{d['right_cell']} median={d['right_median']:.2f}% "
                f"(Δ={d['delta_median']:+.2f}pp, Cliff's δ={d['cliff_delta_left_vs_right']:+.3f} "
                f"[{d['ci'][0]:+.3f}, {d['ci'][1]:+.3f}], {d['magnitude']})"
            )
        for line in verdict["attribution"]["interpretation"]:
            print(f"  → {line}")

    print(f"\nVerdict written to {args.out_verdict}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
