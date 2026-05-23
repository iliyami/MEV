"""P2 v3c — Family-mix campaign (H_FM1-H_FM3).

Pre-registered in `paper_workspace/p2v3c_preregistration.md`.
Tests "K attackers each choosing attack family" via R-P2.2 canonical
victim set + per-policy family-aware success scoring.
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


DEFAULT_CSV = "results/v2_p2v3c_results.csv"
DEFAULT_SUMMARY = "results/v2_p2v3c_summary.json"
DEFAULT_VERDICT = "results/v2_p2v3c_verdict.json"
DEFAULT_REPS = 10
BASE_SEED = 0


_BASE_ENV = {
    "NUM_NODES": "13",
    "ATTACKER_RATIO": "0.308",
    "VICTIM_RATIO": "0.231",  # would imply victims [10,11,12]; we override via V2_VICTIM_NODE_IDS
    "SPECULATIVE_P_MAX": "50",
    "SLUGGISH_TIMEOUT_MULTIPLIER": "1.5",
    "DAG_STATE_CACHED_ROUNDS": "5",
    "SYNC_TIMEOUT_MS": "2000",
    "GC_DEPTH": "10",
    "ATTACK_MODE": "fissure",
    "ATTACK_TYPE": "frontrun",  # Rust scorer uses this; per-attacker family is coord-driven
}

_VICTIM_SET = [10, 11, 12]


def _cfg(policies: list[dict], threat_model: str, archetype: str,
         reps: int = DEFAULT_REPS) -> schema.V2Config:
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
        "victims": {
            "workload": "multi_pareto",
            "count": 3,
            "victim_node_ids": _VICTIM_SET,
            "profit": {"distribution": "uniform", "params": {"scale": 1.0}},
        },
        "runtime": {"reps": reps, "seed": BASE_SEED},
    }
    return sweeper.expand_policy_vector(schema.parse_config(raw))


def build_cells(reps: int = DEFAULT_REPS) -> list[benchmark.Cell]:
    return [
        # fm_same_family_2front: 2 groups, both frontrun
        benchmark.Cell(
            name="fm_same_family_2front",
            config=_cfg(
                policies=[
                    {"group_id": "g0", "members": [0, 1], "family": "frontrun",
                     "strategy": "fissure", "params": {}},
                    {"group_id": "g1", "members": [2, 3], "family": "frontrun",
                     "strategy": "fissure", "params": {}},
                ],
                threat_model="TM-Compete", archetype="same_strategy_split", reps=reps,
            ),
            paper1_lookup=benchmark.paper1_lookup_frontrun,
        ),
        # fm_mixed_2front_2back: 2 frontrun + 2 backrun
        benchmark.Cell(
            name="fm_mixed_2front_2back",
            config=_cfg(
                policies=[
                    {"group_id": "g_front", "members": [0, 1], "family": "frontrun",
                     "strategy": "fissure", "params": {}},
                    {"group_id": "g_back", "members": [2, 3], "family": "backrun",
                     "strategy": "fissure", "params": {}},
                ],
                threat_model="TM-Compete", archetype="same_strategy_split", reps=reps,
            ),
            paper1_lookup=benchmark.paper1_lookup_frontrun,
        ),
        # fm_same_family_4front: all 4 in one group, frontrun (paper-1 equivalent)
        benchmark.Cell(
            name="fm_same_family_4front",
            config=_cfg(
                policies=[
                    {"group_id": "g0", "members": [0, 1, 2, 3], "family": "frontrun",
                     "strategy": "fissure", "params": {}},
                ],
                threat_model="TM-Solo", archetype="homogeneous", reps=reps,
            ),
            paper1_lookup=benchmark.paper1_lookup_frontrun,
        ),
        # fm_mixed_3way: 2 frontrun + 1 backrun + 1 sandwich
        benchmark.Cell(
            name="fm_mixed_3way",
            config=_cfg(
                policies=[
                    {"group_id": "g_front", "members": [0, 1], "family": "frontrun",
                     "strategy": "fissure", "params": {}},
                    {"group_id": "g_back", "members": [2], "family": "backrun",
                     "strategy": "fissure", "params": {}},
                    {"group_id": "g_sand", "members": [3], "family": "sandwich",
                     "strategy": "fissure", "params": {}},
                ],
                threat_model="TM-Compete", archetype="same_strategy_split", reps=reps,
            ),
            paper1_lookup=benchmark.paper1_lookup_frontrun,
        ),
    ]


# ---------------------------------------------------------------------------
# Combined per-victim success (Python-side)
# ---------------------------------------------------------------------------


def _success_predicate(family: str, a_pos: int, v_pos: int) -> bool:
    if family == "frontrun":
        return a_pos < v_pos
    if family == "backrun":
        return a_pos > v_pos
    if family == "sandwich":
        return a_pos != v_pos
    return False


def _combined_success_per_rep(committed_order: list[dict], cfg: schema.V2Config) -> Optional[float]:
    """Fraction of victim blocks attacked successfully by AT LEAST ONE attacker
    under that attacker's own family predicate."""
    if not committed_order or not cfg.adversary.policies:
        return None
    victim_set = set(int(x) for x in cfg.victims.victim_node_ids) if cfg.victims.victim_node_ids else set()
    if not victim_set:
        return None
    # Index policies by member for fast lookup
    member_to_policy = {}
    for p in cfg.adversary.policies:
        for m in p.members:
            member_to_policy[int(m)] = p

    victims = [r for r in committed_order if int(r.get("creator", -1)) in victim_set]
    if not victims:
        return None
    successful = 0
    for v in victims:
        v_round = int(v["round"])
        v_pos = int(v["position"])
        attacked = False
        # check every attacker block in the same round
        for r in committed_order:
            creator = int(r.get("creator", -1))
            if creator not in member_to_policy:
                continue
            if int(r["round"]) != v_round:
                continue
            policy = member_to_policy[creator]
            if _success_predicate(policy.family, int(r["position"]), v_pos):
                attacked = True
                break
        if attacked:
            successful += 1
    return (successful / len(victims)) * 100.0


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
        "decision": "supports" if (abs(delta) >= 0.33 and (lo > 0.0 or hi < 0.0)) else "rejects",
    }


def analyze(csv_path: str) -> dict[str, Any]:
    by_cell = _read_csv(csv_path)
    findings: dict[str, Any] = {}

    # Extract per-policy ASRs from the per_policy_asr_json column
    per_policy_by_cell: dict[str, dict[str, list[float]]] = {}
    for name, rows in by_cell.items():
        per_policy_lists: dict[str, list[float]] = defaultdict(list)
        for r in rows:
            try:
                pp = json.loads(r.get("per_policy_asr_json", "{}"))
            except json.JSONDecodeError:
                pp = {}
            for gid, val in pp.items():
                if val is not None:
                    try:
                        per_policy_lists[gid].append(float(val))
                    except (TypeError, ValueError):
                        pass
        per_policy_by_cell[name] = dict(per_policy_lists)

    # H_FM2: per-policy specialization
    # In fm_mixed_2front_2back: g_front should show high frontrun ASR;
    # g_back should show backrun ASR > 0.
    if "fm_mixed_2front_2back" in per_policy_by_cell:
        mixed_pp = per_policy_by_cell["fm_mixed_2front_2back"]
        g_front_median = st.median(mixed_pp.get("g_front", [])) if mixed_pp.get("g_front") else None
        g_back_median = st.median(mixed_pp.get("g_back", [])) if mixed_pp.get("g_back") else None
        findings["H_FM2_per_policy_specialization"] = {
            "g_front_median_asr": g_front_median,
            "g_back_median_asr": g_back_median,
            "g_back_above_zero": (g_back_median is not None and g_back_median > 10.0),
            "verdict": (
                "supported"
                if (g_front_median and g_front_median > 50.0
                    and g_back_median is not None and g_back_median > 10.0)
                else "rejected"
            ),
        }

    # H_FM3: same-family vs mixed aggregate (Rust frontrun-style)
    if "fm_same_family_2front" in by_cell and "fm_mixed_2front_2back" in by_cell:
        cmp_ = _compare(_asrs(by_cell["fm_same_family_2front"]),
                        _asrs(by_cell["fm_mixed_2front_2back"]))
        findings["H_FM3_same_vs_mixed_frontrun_aggregate"] = {
            "result": cmp_,
            "note": (
                "Rust scorer uses ATTACK_TYPE=frontrun → only counts frontrun-style "
                "(position<position) successes. In mixed cell, 2 backrun attackers' "
                "post-victim wins are NOT counted by this metric. So this comparison "
                "expects: same-family has HIGHER aggregate (4 frontrun attackers > "
                "2 frontrun attackers). The combined-success metric in H_FM1 tells "
                "the full story."
            ),
            "verdict": cmp_.get("decision"),
        }

    # H_FM1: combined per-victim success rate
    # Need to read raw committed_order from CSV — it's not stored directly,
    # but coord_metrics_json has decisions_made. The committed_order itself
    # is in the raw_output which isn't persisted by benchmark.py.
    # As a fallback, we report per-policy ASR breakdown.
    findings["H_FM1_combined_per_victim_success_NOTE"] = {
        "verdict": "deferred",
        "note": (
            "The combined-per-victim success metric requires the raw "
            "FINAL_COMMITTED_ORDER marker per rep, which isn't currently "
            "persisted to the CSV. We capture per-policy ASR per family in "
            "per_policy_asr_json; that decomposition is in the CSV. A future "
            "v2 of this analysis would store committed_order per rep for "
            "post-hoc combined-success computation."
        ),
    }

    findings["per_policy_asr_by_cell"] = {
        name: {gid: {"median": st.median(vals) if vals else None,
                      "mean": st.mean(vals) if vals else None,
                      "n": len(vals)}
                for gid, vals in pp.items()}
        for name, pp in per_policy_by_cell.items()
    }

    return {
        "campaign": "P2v3c_familymix",
        "preregistration": "paper_workspace/p2v3c_preregistration.md",
        "per_cell_medians": {
            name: {"asr_median": st.median(_asrs(rows)) if _asrs(rows) else None,
                    "n": len(rows)}
            for name, rows in by_cell.items()
        },
        "findings": findings,
    }


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="p2v3c_familymix")
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
        print(f"P2 v3c Family-mix: {len(cells)} cells × {args.reps} reps")
        def log(msg: str) -> None:
            print(msg, flush=True)
        benchmark.run_benchmark(
            cells=cells, out_csv=args.out_csv, out_summary_json=args.out_summary,
            reps=args.reps, progress_callback=log,
        )

    print("\n--- H_FM adjudication ---")
    verdict = analyze(args.out_csv)
    Path(args.out_verdict).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out_verdict, "w") as fh:
        json.dump(verdict, fh, indent=2, default=str)
    for hyp_name, hyp_data in verdict["findings"].items():
        if hyp_name.startswith("H_FM"):
            v = hyp_data.get("verdict", "?")
            print(f"  {hyp_name}: {v}")
    print(f"\nVerdict written to {args.out_verdict}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
