"""P3 v3 — Collusion campaign (H2.1 — H2.5).

Pre-registered in `paper_workspace/p3v3_preregistration.md`.
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


DEFAULT_CSV = "results/v2_p3v3_results.csv"
DEFAULT_SUMMARY = "results/v2_p3v3_summary.json"
DEFAULT_VERDICT = "results/v2_p3v3_verdict.json"
DEFAULT_REPS = 10
BASE_SEED = 0

_BASE_ENV = {
    "NUM_NODES": "13",
    "ATTACKER_RATIO": "0.308",
    "VICTIM_RATIO": "0.231",
    "SPECULATIVE_P_MAX": "50",
    "SLUGGISH_TIMEOUT_MULTIPLIER": "1.5",
    "DAG_STATE_CACHED_ROUNDS": "5",
    "SYNC_TIMEOUT_MS": "2000",
    "GC_DEPTH": "10",
}


def _cfg(threat_model: str, family: str, archetype: str, policies: list[dict],
         coord_policy: Optional[str] = None,
         defection_node_id: Optional[int] = None,
         reps: int = DEFAULT_REPS) -> schema.V2Config:
    env = dict(_BASE_ENV)
    env["ATTACK_MODE"] = "fissure"  # strategy
    env["ATTACK_TYPE"] = family
    coord_block: dict = {"enabled": threat_model == "TM-Collude"}
    if coord_policy:
        coord_block["policy"] = coord_policy
    if defection_node_id is not None:
        coord_block["defection_node_id"] = defection_node_id
    raw = {
        "protocol": {"name": "bullshark", "path": "bullshark"},
        "docker": {"tag": "mev-bullshark:latest", "cpus": "8.0", "memory": "16g"},
        "test": {"test_name": "test_fissure_attack_asr_dynamic", "REPETITIONS": 1},
        "environment": env,
        "adversary": {
            "threat_model": threat_model,
            "archetype": archetype,
            "topology": {"policies": policies},
            "coordination": coord_block,
        },
        "runtime": {"reps": reps, "seed": BASE_SEED},
    }
    return sweeper.expand_policy_vector(schema.parse_config(raw))


def _independent_policies(family: str) -> list[dict]:
    """4 independent groups of 1 node each."""
    return [
        {"group_id": f"g{i}", "members": [i], "family": family,
         "strategy": "fissure", "params": {}}
        for i in range(4)
    ]


def _coalition_policies(family: str) -> list[dict]:
    """1 group of all 4 Byzantine nodes."""
    return [
        {"group_id": "g0", "members": [0, 1, 2, 3], "family": family,
         "strategy": "fissure", "params": {}}
    ]


def _role_split_policies(family: str) -> list[dict]:
    """2 groups: one excluder, one amplifier."""
    return [
        {"group_id": "g_exclude", "members": [0, 1], "family": family,
         "strategy": "fissure", "params": {"role_action": "exclude"}},
        {"group_id": "g_amplify", "members": [2, 3], "family": family,
         "strategy": "fissure", "params": {"role_action": "amplify"}},
    ]


def _cell(name: str, threat_model: str, family: str,
          policies_fn, archetype: str = "same_family_split",
          coord_policy: Optional[str] = None,
          defection_node_id: Optional[int] = None,
          reps: int = DEFAULT_REPS) -> benchmark.Cell:
    return benchmark.Cell(
        name=name,
        config=_cfg(
            threat_model=threat_model, family=family, archetype=archetype,
            policies=policies_fn(family),
            coord_policy=coord_policy,
            defection_node_id=defection_node_id,
            reps=reps,
        ),
        paper1_lookup=benchmark.paper1_lookup_frontrun if family == "frontrun" else None,
    )


def build_cells(reps: int = DEFAULT_REPS) -> list[benchmark.Cell]:
    return [
        # H2.1, H2.2 — independent vs coordinated across families
        _cell("c_indep_frontrun", "TM-Compete", "frontrun", _independent_policies, reps=reps),
        _cell("c_coord_frontrun", "TM-Collude", "frontrun", _coalition_policies,
              archetype="homogeneous", coord_policy="leader", reps=reps),
        _cell("c_indep_backrun", "TM-Compete", "backrun", _independent_policies, reps=reps),
        _cell("c_coord_backrun", "TM-Collude", "backrun", _coalition_policies,
              archetype="homogeneous", coord_policy="leader", reps=reps),
        _cell("c_indep_sandwich", "TM-Compete", "sandwich", _independent_policies, reps=reps),
        _cell("c_coord_sandwich", "TM-Collude", "sandwich", _coalition_policies,
              archetype="homogeneous", coord_policy="leader", reps=reps),
        # H2.3 — role split
        _cell("c_role_split", "TM-Collude", "frontrun", _role_split_policies,
              archetype="same_family_split", coord_policy="leader", reps=reps),
        # H2.4 — rr_slot single-active
        _cell("c_rr_active", "TM-Collude", "frontrun", _coalition_policies,
              archetype="homogeneous", coord_policy="rr_slot", reps=reps),
        # H2.5 — defection
        _cell("c_defect_one", "TM-Collude", "frontrun", _coalition_policies,
              archetype="homogeneous", coord_policy="leader",
              defection_node_id=3, reps=reps),
    ]


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

    # H2.1 — max coordination gap across modes
    if "c_indep_frontrun" in by_cell:
        baseline = _asrs(by_cell["c_indep_frontrun"])
        gaps = {}
        for cand in ("c_coord_frontrun", "c_role_split", "c_rr_active"):
            if cand in by_cell:
                cmp_ = _compare(_asrs(by_cell[cand]), baseline)
                gaps[cand] = cmp_
        supported_modes = [k for k, v in gaps.items() if v.get("decision") == "supports" and v.get("cliff_delta", 0) > 0]
        findings["H2.1_max_coordination_gap"] = {
            "gaps_vs_indep_frontrun": gaps,
            "supported_modes": supported_modes,
            "verdict": "supported" if supported_modes else "rejected",
        }

    # H2.2 — family sensitivity (sandwich gap > frontrun gap)
    if all(c in by_cell for c in ("c_coord_frontrun", "c_indep_frontrun",
                                    "c_coord_sandwich", "c_indep_sandwich")):
        fr_gap = st.median(_asrs(by_cell["c_coord_frontrun"])) - st.median(_asrs(by_cell["c_indep_frontrun"]))
        sw_gap = st.median(_asrs(by_cell["c_coord_sandwich"])) - st.median(_asrs(by_cell["c_indep_sandwich"]))
        findings["H2.2_family_sensitivity"] = {
            "frontrun_gap_pp": fr_gap,
            "sandwich_gap_pp": sw_gap,
            "sandwich_minus_frontrun_pp": sw_gap - fr_gap,
            # Require the sandwich gap to exceed frontrun gap by >= 1.5 pp AND
            # both be positive for "supported."
            "verdict": (
                "supported" if (sw_gap > fr_gap + 1.5 and sw_gap > 0 and fr_gap > 0)
                else "rejected"
            ),
        }

    # H2.3 — role-split dominance
    if "c_role_split" in by_cell:
        rs = _asrs(by_cell["c_role_split"])
        # Compare role_split to the best of (c_coord_frontrun, c_rr_active)
        contenders = []
        for cand in ("c_coord_frontrun", "c_rr_active"):
            if cand in by_cell:
                contenders.append((cand, _asrs(by_cell[cand])))
        if contenders and rs:
            # Pick the contender with highest median
            contenders.sort(key=lambda x: st.median(x[1]) if x[1] else -1, reverse=True)
            best_contender = contenders[0]
            cmp_ = _compare(rs, best_contender[1])
            findings["H2.3_role_split_dominance"] = {
                "compared_to": best_contender[0],
                "result": cmp_,
                "verdict": "supported" if cmp_.get("decision") == "supports" and cmp_.get("cliff_delta", 0) > 0 else "rejected",
            }

    # H2.4 — rr_slot vs indep_frontrun
    if "c_rr_active" in by_cell and "c_indep_frontrun" in by_cell:
        cmp_ = _compare(_asrs(by_cell["c_rr_active"]), _asrs(by_cell["c_indep_frontrun"]))
        findings["H2.4_rr_slot_advantage"] = {
            "result": cmp_,
            "verdict": "supported" if cmp_.get("decision") == "supports" and cmp_.get("cliff_delta", 0) > 0 else "rejected",
        }

    # H2.5 — defection rationality. Per-policy ASR breakdown for the defector
    # (group g0 contains all 4 nodes in c_coord_frontrun and c_defect_one; we
    # cannot disaggregate by individual node from aggregate ASR alone.
    # For v1 we compare aggregate ASR of c_defect_one to c_coord_frontrun;
    # if defector lifts the team total, that's a partial signal. Per-node
    # defector vs coalition needs R-P2.1 per-policy with individual member
    # groups, which we don't have in this cell.)
    if "c_defect_one" in by_cell and "c_coord_frontrun" in by_cell:
        cmp_ = _compare(_asrs(by_cell["c_defect_one"]), _asrs(by_cell["c_coord_frontrun"]))
        findings["H2.5_defection_aggregate"] = {
            "note": (
                "Aggregate-ASR proxy for H2.5: defection-cell ASR vs "
                "coalition-no-defector ASR. Properly testing 'defector "
                "gains individually' requires per-node per-policy ASR "
                "which isn't fully wired for single-node defector groups; "
                "v2 task."
            ),
            "result": cmp_,
            "verdict": "inconclusive",
        }

    return {
        "campaign": "P3v3_collusion",
        "preregistration": "paper_workspace/p3v3_preregistration.md",
        "per_cell_medians": {name: st.median(_asrs(rows)) if _asrs(rows) else None
                              for name, rows in by_cell.items()},
        "findings": findings,
    }


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="p3v3_collusion")
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
        print(f"P3 v3 Collusion campaign: {len(cells)} cells × {args.reps} reps")
        def log(msg: str) -> None:
            print(msg, flush=True)
        benchmark.run_benchmark(
            cells=cells, out_csv=args.out_csv, out_summary_json=args.out_summary,
            reps=args.reps, progress_callback=log,
        )

    print("\n--- H2.x adjudication ---")
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
