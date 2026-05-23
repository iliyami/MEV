"""P4 v3 — Bribery campaign (H3.1 — H3.5).

Pre-registered in `paper_workspace/p4v3_preregistration.md`.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import statistics as st
import sys
import threading
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Optional

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from scripts.v2 import benchmark, schema, stats, sweeper
from scripts.v2.coordinator import CoordinatorServer
from scripts.v2.coordinator_client import CoordinatorClient


DEFAULT_CSV = "results/v2_p4v3_results.csv"
DEFAULT_SUMMARY = "results/v2_p4v3_summary.json"
DEFAULT_VERDICT = "results/v2_p4v3_verdict.json"
DEFAULT_REPS = 10
BASE_SEED = 0


# Note: when "Byzantine f" varies, we adjust ATTACKER_RATIO accordingly.
def _attacker_ratio(f: int, n: int = 13) -> str:
    return f"{f / n:.4f}"


def _cfg(f: int, bribed_honest: list[int], budget: float, action: Optional[str],
         response_policy: str, response_policy_params: Optional[dict] = None,
         reps: int = DEFAULT_REPS) -> schema.V2Config:
    env = {
        "NUM_NODES": "13",
        "ATTACKER_RATIO": _attacker_ratio(f),
        "VICTIM_RATIO": "0.231",
        "SPECULATIVE_P_MAX": "50",
        "SLUGGISH_TIMEOUT_MULTIPLIER": "1.5",
        "DAG_STATE_CACHED_ROUNDS": "5",
        "SYNC_TIMEOUT_MS": "2000",
        "GC_DEPTH": "10",
        "ATTACK_MODE": "fissure",
        "ATTACK_TYPE": "frontrun",
    }
    members = list(range(f))
    bribery_block: dict = {"enabled": False}
    if bribed_honest:
        bribery_block = {
            "enabled": True,
            "type": "guided",
            "settlement": "simulated",
            "budget": budget,
            "response_policy": response_policy,
            "response_policy_params": response_policy_params or {"threshold": 0.0},
            "bribed_honest": bribed_honest,
        }
    raw = {
        "protocol": {"name": "bullshark", "path": "bullshark"},
        "docker": {"tag": "mev-bullshark:latest", "cpus": "8.0", "memory": "16g"},
        "test": {"test_name": "test_fissure_attack_asr_dynamic", "REPETITIONS": 1},
        "environment": env,
        "adversary": {
            "threat_model": "TM-Bribe" if bribed_honest else "TM-Solo",
            "archetype": "homogeneous",
            "topology": {
                "policies": [
                    {"group_id": "g0", "members": members, "family": "frontrun",
                     "strategy": "fissure", "params": {}}
                ]
            },
            "bribery": bribery_block,
        },
        "runtime": {"reps": reps, "seed": BASE_SEED},
    }
    return sweeper.expand_policy_vector(schema.parse_config(raw))


def _make_publisher(action: str, victim_id: int = 12):
    """Build an on_coord_ready that pre-publishes one offer per bribed-honest node."""
    def _on_ready(coord: CoordinatorServer, cfg: schema.V2Config, rep: int):
        if not cfg.adversary.bribery.enabled:
            return None
        client = CoordinatorClient(coord.url)
        # We deliberately set a small payment so the budget arithmetic in H3.3
        # is meaningful; budgets of 25/50/100 limit total accepted offers.
        # We publish one offer per bribed-honest node; the total cost depends
        # on the response policy (always-accept burns budget faster).
        per_offer = max(1.0, cfg.adversary.bribery.budget / max(1, len(cfg.adversary.bribery.bribed_honest)))
        for node in cfg.adversary.bribery.bribed_honest:
            client.bribery_offer(
                recipient_node_id=node,
                infraction=action,
                target={"target_victim_id": victim_id,
                        "target_attacker_set": list(range(cfg.adversary.bribery.budget and 4 or 0))},
                payment=per_offer,
            )
        return None
    return _on_ready


_RE_ACCEPT = re.compile(r"V2_HONEST_ACCEPT: node=(\d+) offer_id=\S+ infraction=(\S+) payment=([\d.eE+-]+)")
_RE_OMIT = re.compile(r"V2_HONEST_OMIT: node=(\d+) target_victim_id=(\d+) removed=(\d+)")
_RE_PREFER = re.compile(r"V2_HONEST_PREFER: node=(\d+) attacker_set_size=(\d+)")


def _extract(raw_output: str, run_result) -> dict:
    accepts = list(_RE_ACCEPT.finditer(raw_output))
    omits = list(_RE_OMIT.finditer(raw_output))
    prefers = list(_RE_PREFER.finditer(raw_output))
    return {
        "honest_accept_markers": len(accepts),
        "honest_omit_markers": len(omits),
        "honest_prefer_markers": len(prefers),
        "unique_accepting_nodes": len({m.group(1) for m in accepts}),
        "total_omitted_references": sum(int(m.group(3)) for m in omits),
    }


_EXTRA = (
    "honest_accept_markers",
    "honest_omit_markers",
    "honest_prefer_markers",
    "unique_accepting_nodes",
    "total_omitted_references",
)


def build_cells(reps: int = DEFAULT_REPS) -> list[benchmark.Cell]:
    cells: list[benchmark.Cell] = []

    def add(name: str, f: int, bribed: list[int], budget: float, action: Optional[str],
            response: str = "always_above_X", response_params: Optional[dict] = None):
        cfg = _cfg(f, bribed, budget, action, response, response_params, reps)
        on_ready = _make_publisher(action) if action else None
        cells.append(benchmark.Cell(
            name=name, config=cfg, extra_columns=_EXTRA,
            marker_extractor=_extract, on_coord_ready=on_ready,
            paper1_lookup=benchmark.paper1_lookup_frontrun,
        ))

    # H3.1 baselines
    add("b_baseline_f4", f=4, bribed=[], budget=0, action=None)
    add("b_baseline_f2", f=2, bribed=[], budget=0, action=None)
    add("b_baseline_f1", f=1, bribed=[], budget=0, action=None)
    # H3.1 sub-f bribed (b=2 Byzantine + 2 bribed honest)
    add("b_b2_budget_50_omit", f=2, bribed=[10, 12], budget=50, action="omit_reference")
    add("b_b1_budget_50_omit", f=1, bribed=[10, 11, 12], budget=50, action="omit_reference")

    # H3.2 action ranking (f=4 baseline, +2 bribed honest)
    add("b_action_omit_budget_50", f=4, bribed=[10, 12], budget=50, action="omit_reference")
    add("b_action_prefer_budget_50", f=4, bribed=[10, 12], budget=50, action="select_candidate")
    add("b_action_noop_budget_50", f=4, bribed=[10, 12], budget=50, action="gas_style_incentive")

    # H3.3 budget scaling
    add("b_budget_25_omit", f=4, bribed=[10, 12], budget=25, action="omit_reference")
    add("b_budget_100_omit", f=4, bribed=[10, 12], budget=100, action="omit_reference")

    # H3.4 response policy ablation
    add("b_response_prob_omit", f=4, bribed=[10, 12], budget=50, action="omit_reference",
        response="prob_p", response_params={"p": 0.5})
    add("b_response_reject_omit", f=4, bribed=[10, 12], budget=50, action="omit_reference",
        response="reject_all")

    return cells


def _read_csv(p: str) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = defaultdict(list)
    with open(p) as fh:
        for row in csv.DictReader(fh):
            out[row["cell_name"]].append(row)
    return dict(out)


def _asrs(rows: list[dict]) -> list[float]:
    out = []
    for r in rows:
        try:
            out.append(float(r["asr"]))
        except (KeyError, ValueError):
            pass
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

    # H3.1 sub-f equivalence: each sub-f-with-bribery cell vs f=4 baseline
    if "b_baseline_f4" in by_cell:
        base_f4 = _asrs(by_cell["b_baseline_f4"])
        base_med = st.median(base_f4) if base_f4 else None
        gaps = {}
        for cand in ("b_b2_budget_50_omit", "b_b1_budget_50_omit"):
            if cand in by_cell:
                cand_asrs = _asrs(by_cell[cand])
                cmp_ = _compare(cand_asrs, base_f4)
                gaps[cand] = {
                    **cmp_,
                    # "equivalent" iff the difference is NOT notable (delta < 0.33)
                    "equivalent_to_baseline": (
                        not (abs(cmp_["cliff_delta"]) >= 0.33 and (cmp_["ci"][0] > 0 or cmp_["ci"][1] < 0))
                    ),
                }
        any_equivalent = any(g["equivalent_to_baseline"] for g in gaps.values())
        findings["H3.1_sub_f_equivalence"] = {
            "baseline_f4_median": base_med,
            "candidates": gaps,
            "verdict": "supported" if any_equivalent else "rejected",
        }

    # H3.2 action ranking: ASR-per-dollar
    if "b_baseline_f4" in by_cell:
        base_med = st.median(_asrs(by_cell["b_baseline_f4"]))
        ratios = {}
        for action_cell in ("b_action_omit_budget_50",
                            "b_action_prefer_budget_50",
                            "b_action_noop_budget_50"):
            if action_cell in by_cell:
                cand_med = st.median(_asrs(by_cell[action_cell]))
                lift = cand_med - base_med if base_med is not None else None
                # Budget is fixed at 50 for these cells; per-dollar = lift / 50.
                ratios[action_cell] = {
                    "median": cand_med, "lift_pp": lift,
                    "lift_per_dollar": (lift / 50.0) if lift is not None else None,
                }
        # Rank by lift_per_dollar descending
        ranked = sorted(
            [(k, v["lift_per_dollar"]) for k, v in ratios.items() if v["lift_per_dollar"] is not None],
            key=lambda x: x[1] or -999, reverse=True
        )
        omit_first = bool(ranked and ranked[0][0] == "b_action_omit_budget_50")
        findings["H3.2_action_ranking"] = {
            "ratios": ratios,
            "ranking_best_first": [r[0] for r in ranked],
            "omit_first": omit_first,
            "verdict": "supported" if omit_first else "rejected",
        }

    # H3.3 budget scaling: linear vs sqrt vs log
    budgets = []
    asrs_by_budget = []
    if "b_baseline_f4" in by_cell:
        base_med = st.median(_asrs(by_cell["b_baseline_f4"]))
        for budget, cell_name in [(25, "b_budget_25_omit"),
                                    (50, "b_action_omit_budget_50"),
                                    (100, "b_budget_100_omit")]:
            if cell_name in by_cell:
                ar = _asrs(by_cell[cell_name])
                if ar:
                    budgets.append(budget)
                    asrs_by_budget.append(st.median(ar) - base_med)
        if len(budgets) >= 3:
            # R² of linear, sqrt, log fits (against median ASR lift).
            import math
            def r_squared(xs, ys, transform):
                tx = [transform(x) for x in xs]
                mx = st.mean(tx); my = st.mean(ys)
                num = sum((tx[i] - mx) * (ys[i] - my) for i in range(len(tx)))
                dx = sum((t - mx) ** 2 for t in tx)
                dy = sum((y - my) ** 2 for y in ys)
                if dx == 0 or dy == 0:
                    return 0.0
                rho = num / ((dx * dy) ** 0.5)
                return rho * rho
            r2_linear = r_squared(budgets, asrs_by_budget, lambda x: x)
            r2_sqrt = r_squared(budgets, asrs_by_budget, lambda x: math.sqrt(x))
            r2_log = r_squared(budgets, asrs_by_budget, lambda x: math.log(x))
            concave = max(r2_sqrt, r2_log) > r2_linear + 0.05
            findings["H3.3_budget_scaling"] = {
                "budgets": budgets,
                "lifts_pp": asrs_by_budget,
                "r2_linear": r2_linear,
                "r2_sqrt": r2_sqrt,
                "r2_log": r2_log,
                "verdict": "supported" if concave else "rejected",
            }

    # H3.4 response policy ablation
    if all(c in by_cell for c in ("b_action_omit_budget_50", "b_response_prob_omit")):
        cmp_ = _compare(_asrs(by_cell["b_action_omit_budget_50"]),
                        _asrs(by_cell["b_response_prob_omit"]))
        findings["H3.4_response_policy"] = {
            "result": cmp_,
            "verdict": "supported" if cmp_.get("decision") == "supports" and cmp_.get("cliff_delta", 0) > 0 else "rejected",
        }

    # H3.5 detectability: per-cell unique_accepting_nodes vs # bribed
    if "b_action_omit_budget_50" in by_cell:
        accepts_per_rep = []
        for r in by_cell["b_action_omit_budget_50"]:
            try:
                accepts_per_rep.append(int(r.get("unique_accepting_nodes", 0)))
            except (TypeError, ValueError):
                pass
        # If accept count ≈ bribed_honest size, detection is trivial (perfect signal).
        expected = 2  # bribed_honest size in this cell
        median_accepting = st.median(accepts_per_rep) if accepts_per_rep else 0
        detectable = median_accepting >= 1  # at least one bribed node observable
        findings["H3.5_detectability"] = {
            "median_uniquely_accepting_nodes_per_rep": median_accepting,
            "expected_bribed": expected,
            "verdict": "supported" if detectable else "rejected",
        }

    return {
        "campaign": "P4v3_bribery",
        "preregistration": "paper_workspace/p4v3_preregistration.md",
        "per_cell_medians": {name: st.median(_asrs(rows)) if _asrs(rows) else None
                              for name, rows in by_cell.items()},
        "findings": findings,
    }


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="p4v3_bribery")
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
        print(f"P4 v3 Bribery campaign: {len(cells)} cells × {args.reps} reps")
        def log(msg: str) -> None:
            print(msg, flush=True)
        benchmark.run_benchmark(
            cells=cells, out_csv=args.out_csv, out_summary_json=args.out_summary,
            reps=args.reps, progress_callback=log,
        )

    print("\n--- H3.x adjudication ---")
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
