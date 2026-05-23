"""P6 v3 — Cross-cutting composite-mode campaign.

Pre-registered in `paper_workspace/p6v3_preregistration.md`.

The c_best_response cell's per-node configuration is built post-hoc
from P2–P5 oracle data. To run only the H_PX1 / H_PX2 cells:
    python -m scripts.v2.p6v3_crosscutting --no-best-response

To run the full set including best-response (requires P2–P5 CSVs to
exist):
    python -m scripts.v2.p6v3_crosscutting
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
from scripts.v2.coordinator import CoordinatorServer
from scripts.v2.coordinator_client import CoordinatorClient


DEFAULT_CSV = "results/v2_p6v3_results.csv"
DEFAULT_SUMMARY = "results/v2_p6v3_summary.json"
DEFAULT_VERDICT = "results/v2_p6v3_verdict.json"
DEFAULT_REPS = 10
BASE_SEED = 0


def _base_env(family: str = "frontrun") -> dict:
    return {
        "NUM_NODES": "13",
        "ATTACKER_RATIO": "0.308",
        "VICTIM_RATIO": "0.231",
        "SPECULATIVE_P_MAX": "50",
        "SLUGGISH_TIMEOUT_MULTIPLIER": "1.5",
        "DAG_STATE_CACHED_ROUNDS": "5",
        "SYNC_TIMEOUT_MS": "2000",
        "GC_DEPTH": "10",
        "ATTACK_MODE": "fissure",
        "ATTACK_TYPE": family,
    }


def _cfg_comp_no_bribery(reps: int) -> schema.V2Config:
    """k=2 competing attackers (no bribery)."""
    raw = {
        "protocol": {"name": "bullshark", "path": "bullshark"},
        "docker": {"tag": "mev-bullshark:latest", "cpus": "8.0", "memory": "16g"},
        "test": {"test_name": "test_fissure_attack_asr_dynamic", "REPETITIONS": 1},
        "environment": _base_env(),
        "adversary": {
            "threat_model": "TM-Compete",
            "archetype": "same_family_split",
            "topology": {
                "policies": [
                    {"group_id": "g0", "members": [0, 1], "family": "frontrun",
                     "strategy": "fissure", "params": {}},
                    {"group_id": "g1", "members": [2, 3], "family": "frontrun",
                     "strategy": "fissure", "params": {}},
                ]
            },
        },
        "runtime": {"reps": reps, "seed": BASE_SEED},
    }
    return sweeper.expand_policy_vector(schema.parse_config(raw))


def _cfg_comp_bribed(reps: int) -> schema.V2Config:
    """k=2 competing + 2 honest bribed; one competing group benefits."""
    raw = {
        "protocol": {"name": "bullshark", "path": "bullshark"},
        "docker": {"tag": "mev-bullshark:latest", "cpus": "8.0", "memory": "16g"},
        "test": {"test_name": "test_fissure_attack_asr_dynamic", "REPETITIONS": 1},
        "environment": _base_env(),
        "adversary": {
            "threat_model": "TM-Bribe",
            "archetype": "same_family_split",
            "topology": {
                "policies": [
                    {"group_id": "g0", "members": [0, 1], "family": "frontrun",
                     "strategy": "fissure", "params": {}},
                    {"group_id": "g1", "members": [2, 3], "family": "frontrun",
                     "strategy": "fissure", "params": {}},
                ]
            },
            "bribery": {
                "enabled": True, "type": "guided", "settlement": "simulated",
                "budget": 50.0, "response_policy": "always_above_X",
                "response_policy_params": {"threshold": 0.0},
                "bribed_honest": [10, 12],
            },
        },
        "runtime": {"reps": reps, "seed": BASE_SEED},
    }
    return sweeper.expand_policy_vector(schema.parse_config(raw))


def _cfg_coll_uniform(reps: int) -> schema.V2Config:
    """TM-Collude leader, uniform victim profile (no threshold gate)."""
    raw = {
        "protocol": {"name": "bullshark", "path": "bullshark"},
        "docker": {"tag": "mev-bullshark:latest", "cpus": "8.0", "memory": "16g"},
        "test": {"test_name": "test_fissure_attack_asr_dynamic", "REPETITIONS": 1},
        "environment": _base_env(),
        "adversary": {
            "threat_model": "TM-Collude", "archetype": "homogeneous",
            "topology": {
                "policies": [
                    {"group_id": "g0", "members": [0, 1, 2, 3], "family": "frontrun",
                     "strategy": "fissure", "params": {}}
                ]
            },
            "coordination": {"enabled": True, "policy": "leader"},
        },
        "victims": {"workload": "single", "count": 1},
        "runtime": {"reps": reps, "seed": BASE_SEED},
    }
    return sweeper.expand_policy_vector(schema.parse_config(raw))


def _cfg_coll_adaptive(reps: int) -> schema.V2Config:
    """TM-Collude leader, Pareto victims + profit_threshold gate."""
    raw = {
        "protocol": {"name": "bullshark", "path": "bullshark"},
        "docker": {"tag": "mev-bullshark:latest", "cpus": "8.0", "memory": "16g"},
        "test": {"test_name": "test_fissure_attack_asr_dynamic", "REPETITIONS": 1},
        "environment": _base_env(),
        "adversary": {
            "threat_model": "TM-Collude", "archetype": "homogeneous",
            "topology": {
                "policies": [
                    {"group_id": "g0", "members": [0, 1, 2, 3], "family": "frontrun",
                     "strategy": "fissure", "params": {"profit_threshold": 1.0}}
                ]
            },
            "coordination": {"enabled": True, "policy": "leader"},
        },
        "victims": {
            "workload": "multi_pareto", "count": 3,
            "profit": {"distribution": "pareto", "params": {"shape": 1.16, "scale": 1.0}},
        },
        "runtime": {"reps": reps, "seed": BASE_SEED},
    }
    return sweeper.expand_policy_vector(schema.parse_config(raw))


def _cfg_paper1_baseline(reps: int) -> schema.V2Config:
    """f=4 homogeneous fissure (paper-1 reference) — no v2 mechanisms."""
    raw = {
        "protocol": {"name": "bullshark", "path": "bullshark"},
        "docker": {"tag": "mev-bullshark:latest", "cpus": "8.0", "memory": "16g"},
        "test": {"test_name": "test_fissure_attack_asr_dynamic", "REPETITIONS": 1},
        "environment": _base_env(),
        "adversary": {
            "threat_model": "TM-Solo", "archetype": "homogeneous",
            "topology": {
                "policies": [
                    {"group_id": "g0", "members": [0, 1, 2, 3], "family": "frontrun",
                     "strategy": "fissure", "params": {}}
                ]
            },
        },
        "runtime": {"reps": reps, "seed": BASE_SEED},
    }
    return sweeper.expand_policy_vector(schema.parse_config(raw))


def _make_bribery_publisher(action: str = "omit_reference", victim_id: int = 12):
    def _on_ready(coord: CoordinatorServer, cfg: schema.V2Config, rep: int):
        if not cfg.adversary.bribery.enabled:
            return None
        client = CoordinatorClient(coord.url)
        for node in cfg.adversary.bribery.bribed_honest:
            client.bribery_offer(
                recipient_node_id=node,
                infraction=action,
                target={"target_victim_id": victim_id,
                        "target_attacker_set": [0, 1, 2, 3]},
                payment=cfg.adversary.bribery.budget / max(1, len(cfg.adversary.bribery.bribed_honest)),
            )
        return None
    return _on_ready


def build_cells(reps: int = DEFAULT_REPS, include_best_response: bool = False) -> list[benchmark.Cell]:
    cells = [
        benchmark.Cell(
            name="c_comp_no_bribery",
            config=_cfg_comp_no_bribery(reps),
            paper1_lookup=benchmark.paper1_lookup_frontrun,
        ),
        benchmark.Cell(
            name="c_comp_bribed",
            config=_cfg_comp_bribed(reps),
            paper1_lookup=benchmark.paper1_lookup_frontrun,
            on_coord_ready=_make_bribery_publisher(),
        ),
        benchmark.Cell(
            name="c_coll_uniform",
            config=_cfg_coll_uniform(reps),
            paper1_lookup=benchmark.paper1_lookup_frontrun,
        ),
        benchmark.Cell(
            name="c_coll_adaptive",
            config=_cfg_coll_adaptive(reps),
            paper1_lookup=benchmark.paper1_lookup_frontrun,
        ),
        benchmark.Cell(
            name="c_paper1_baseline",
            config=_cfg_paper1_baseline(reps),
            paper1_lookup=benchmark.paper1_lookup_frontrun,
        ),
    ]
    if include_best_response:
        # The best single configuration observed in v3 P2-P5 is the
        # bribery cell at budget=100, omit_reference action, always_above_X
        # response. Median 94.60 vs paper-1 baseline 89.75. We re-run that
        # config as `c_best_response` to test H_PX3 against fresh data.
        raw = {
            "protocol": {"name": "bullshark", "path": "bullshark"},
            "docker": {"tag": "mev-bullshark:latest", "cpus": "8.0", "memory": "16g"},
            "test": {"test_name": "test_fissure_attack_asr_dynamic", "REPETITIONS": 1},
            "environment": _base_env(),
            "adversary": {
                "threat_model": "TM-Bribe",
                "archetype": "homogeneous",
                "topology": {
                    "policies": [
                        {"group_id": "g0", "members": [0, 1, 2, 3],
                         "family": "frontrun", "strategy": "fissure",
                         "params": {}}
                    ]
                },
                "bribery": {
                    "enabled": True, "type": "guided", "settlement": "simulated",
                    "budget": 100.0,
                    "response_policy": "always_above_X",
                    "response_policy_params": {"threshold": 0.0},
                    "bribed_honest": [10, 12],
                },
            },
            "runtime": {"reps": reps, "seed": BASE_SEED},
        }
        cells.append(benchmark.Cell(
            name="c_best_response",
            config=sweeper.expand_policy_vector(schema.parse_config(raw)),
            paper1_lookup=benchmark.paper1_lookup_frontrun,
            on_coord_ready=_make_bribery_publisher(action="omit_reference"),
        ))
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

    # H_PX1
    if "c_comp_bribed" in by_cell and "c_comp_no_bribery" in by_cell:
        cmp_ = _compare(_asrs(by_cell["c_comp_bribed"]), _asrs(by_cell["c_comp_no_bribery"]))
        findings["H_PX1_competition_bribery"] = {
            "result": cmp_,
            "verdict": "supported" if cmp_.get("decision") == "supports" and cmp_.get("cliff_delta", 0) > 0 else "rejected",
        }

    # H_PX2 — adaptive collusion vs uniform collusion baseline
    if "c_coll_adaptive" in by_cell and "c_coll_uniform" in by_cell:
        cmp_ = _compare(_asrs(by_cell["c_coll_adaptive"]), _asrs(by_cell["c_coll_uniform"]))
        findings["H_PX2_collusion_multivictim"] = {
            "result": cmp_,
            "verdict": "supported" if cmp_.get("decision") == "supports" and cmp_.get("cliff_delta", 0) > 0 else "rejected",
        }

    # H_PX3 — best-response vs paper-1 baseline
    if "c_best_response" in by_cell and "c_paper1_baseline" in by_cell:
        cmp_ = _compare(_asrs(by_cell["c_best_response"]), _asrs(by_cell["c_paper1_baseline"]))
        findings["H_PX3_best_response"] = {
            "result": cmp_,
            "verdict": "supported" if cmp_.get("decision") == "supports" and cmp_.get("cliff_delta", 0) > 0 else "rejected",
        }

    return {
        "campaign": "P6v3_crosscutting",
        "preregistration": "paper_workspace/p6v3_preregistration.md",
        "per_cell_medians": {name: st.median(_asrs(rows)) if _asrs(rows) else None
                              for name, rows in by_cell.items()},
        "findings": findings,
    }


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="p6v3_crosscutting")
    parser.add_argument("--out-csv", default=DEFAULT_CSV)
    parser.add_argument("--out-summary", default=DEFAULT_SUMMARY)
    parser.add_argument("--out-verdict", default=DEFAULT_VERDICT)
    parser.add_argument("--reps", type=int, default=DEFAULT_REPS)
    parser.add_argument("--no-best-response", action="store_true",
                        help="skip the c_best_response cell")
    parser.add_argument("--analyze-only", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)

    csv_p = Path(args.out_csv)
    if not args.analyze_only:
        if csv_p.exists():
            csv_p.unlink()
        cells = build_cells(reps=args.reps, include_best_response=not args.no_best_response)
        print(f"P6 v3 Cross-cutting: {len(cells)} cells × {args.reps} reps")
        def log(msg: str) -> None:
            print(msg, flush=True)
        benchmark.run_benchmark(
            cells=cells, out_csv=args.out_csv, out_summary_json=args.out_summary,
            reps=args.reps, progress_callback=log,
        )

    print("\n--- H_PX adjudication ---")
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
