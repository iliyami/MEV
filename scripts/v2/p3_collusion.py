"""P3 — Collusion campaign (H2).

Pre-registered in `paper_workspace/p3_preregistration.md`.

Primary v1 cells (2):
    c_independent: TM-Compete, 4 groups of 1 node each, all frontrun/fissure.
                   Coordinator returns no shared_exclusion_seed (policy =
                   role_specialization, the default for TM-Compete).
    c_coordinated: TM-Collude, 1 group of 4 nodes, leader policy.
                   Coordinator returns shared_exclusion_seed per round.

Same family, strategy, Byzantine count, victim layout. Only the
coordination flag and the Rust seed-XOR differ.

N = 10 reps each (lesson learned from P2: N=5 is below resolution).

Usage:
    python -m scripts.v2.p3_collusion              # run + analyze
    python -m scripts.v2.p3_collusion --analyze-only
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
DEFAULT_CSV = "results/v2_p3_collusion_results.csv"
DEFAULT_SUMMARY = "results/v2_p3_collusion_summary.json"
DEFAULT_VERDICT = "results/v2_p3_collusion_h2_verdict.json"
DEFAULT_REPS = 10  # P2 lesson learned: N=5 was below resolution.
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
    "ATTACK_MODE": "fissure",
    "ATTACK_TYPE": "frontrun",
}

# Opt-in all-pairs re-run: when V2_ALL_PAIRS_ASR is set in the process env, promote
# the neutral-baseline all-pairs metric to the headline `asr` for every cell. Default
# (env unset) keeps same-round so the paper-1 contradiction checks stay intact.
import os as _os
if _os.environ.get("V2_ALL_PAIRS_ASR"):
    _BASE_ENV["V2_ALL_PAIRS_ASR"] = _os.environ["V2_ALL_PAIRS_ASR"]

# REVERSE_LAYOUT: place the coordinating attackers at HIGH (index-tax-disadvantaged) indices so
# the coordination effect is measured off the index-tax ceiling. Reverses policy members and
# forwards the env so core.rs is_attacker/coordinator + the metric layout agree; victims go low.
_N, _NA = 13, 4
_REV = bool(_os.environ.get("REVERSE_LAYOUT"))
def _rev(ms):
    return [_N - _NA + m for m in ms] if _REV else ms
for _k in ("REVERSE_LAYOUT", "V2_VICTIM_NODE_IDS"):
    if _os.environ.get(_k):
        _BASE_ENV[_k] = _os.environ[_k]


def _cfg_independent(reps: int) -> schema.V2Config:
    """4 independent Byzantine attackers; coordinator does /policy/lookup but
    returns no shared_exclusion_seed (coordination_policy is role_specialization)."""
    raw = {
        "protocol": {"name": "bullshark", "path": "bullshark"},
        "docker": {"tag": "mev-bullshark:latest", "cpus": "8.0", "memory": "16g"},
        "test": {"test_name": "test_fissure_attack_asr_dynamic", "REPETITIONS": 1},
        "environment": dict(_BASE_ENV),
        "adversary": {
            "threat_model": "TM-Compete",
            "archetype": "same_family_split",
            "topology": {
                "policies": [
                    {"group_id": f"g{i}", "members": _rev([i]), "family": "frontrun",
                     "strategy": "fissure", "params": {}}
                    for i in range(4)
                ]
            },
        },
        "victims": {"workload": "single", "count": 1},
        "runtime": {"reps": reps, "seed": BASE_SEED},
    }
    return sweeper.expand_policy_vector(schema.parse_config(raw))


def _cfg_coordinated(reps: int) -> schema.V2Config:
    """4 Byzantine attackers coordinating via leader policy; coordinator
    returns shared_exclusion_seed each round (run-seed XOR round)."""
    raw = {
        "protocol": {"name": "bullshark", "path": "bullshark"},
        "docker": {"tag": "mev-bullshark:latest", "cpus": "8.0", "memory": "16g"},
        "test": {"test_name": "test_fissure_attack_asr_dynamic", "REPETITIONS": 1},
        "environment": dict(_BASE_ENV),
        "adversary": {
            "threat_model": "TM-Collude",
            "archetype": "homogeneous",
            "topology": {
                "policies": [
                    {"group_id": "g0", "members": _rev([0, 1, 2, 3]),
                     "family": "frontrun", "strategy": "fissure", "params": {}}
                ]
            },
            "coordination": {
                "enabled": True,
                "policy": "leader",
                "information": "local_dag_union",
            },
        },
        "victims": {"workload": "single", "count": 1},
        "runtime": {"reps": reps, "seed": BASE_SEED},
    }
    return sweeper.expand_policy_vector(schema.parse_config(raw))


def build_cells(reps: int = DEFAULT_REPS) -> list[benchmark.Cell]:
    return [
        benchmark.Cell(
            name="c_independent",
            config=_cfg_independent(reps),
            paper1_lookup=benchmark.paper1_lookup_frontrun,
        ),
        benchmark.Cell(
            name="c_coordinated",
            config=_cfg_coordinated(reps),
            paper1_lookup=benchmark.paper1_lookup_frontrun,
        ),
    ]


# ---------------------------------------------------------------------------
# H2 adjudication
# ---------------------------------------------------------------------------


def _read_csv_asrs(csv_path: str) -> dict[str, list[float]]:
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


def analyze_h2(csv_path: str) -> dict[str, Any]:
    by_cell = _read_csv_asrs(csv_path)
    for name in ("c_independent", "c_coordinated"):
        if name not in by_cell:
            raise ValueError(f"missing cell {name} in {csv_path}")

    ind = by_cell["c_independent"]
    coo = by_cell["c_coordinated"]

    per_cell = []
    for name, asrs in (("c_independent", ind), ("c_coordinated", coo)):
        per_cell.append(
            {
                "cell_name": name,
                "n": len(asrs),
                "mean": st.mean(asrs),
                "median": st.median(asrs),
                "min": min(asrs),
                "max": max(asrs),
                "asrs": asrs,
            }
        )

    # delta defined as P(coordinated > independent) - P(coordinated < independent)
    u = stats.mann_whitney_u(coo, ind)
    delta, lo, hi = stats.cliff_delta_bootstrap_ci(coo, ind, n_boot=1000, seed=0)
    magnitude = stats.cliff_delta_magnitude(delta)
    ci_excludes_zero = lo > 0.0 or hi < 0.0
    delta_median = st.median(coo) - st.median(ind)

    # Pre-registered decision rule (§5.2 of p3_preregistration.md):
    if abs(delta) >= 0.33 and ci_excludes_zero:
        if delta > 0:
            verdict = "supported"
            explanation = (
                f"Cliff's δ={delta:+.3f} [{lo:+.3f}, {hi:+.3f}] (magnitude={magnitude}); "
                "CI excludes zero. Coordinated f extracts strictly more ASR than f independent."
            )
        else:
            verdict = "rejected_with_negative_effect"
            explanation = (
                f"Cliff's δ={delta:+.3f} [{lo:+.3f}, {hi:+.3f}]; CI excludes zero with negative "
                "effect. Coordinated extracts strictly LESS than independent — opposite of H2."
            )
    elif abs(delta) < 0.33 and not ci_excludes_zero:
        verdict = "rejected"
        explanation = (
            f"Cliff's δ={delta:+.3f} [{lo:+.3f}, {hi:+.3f}] (magnitude={magnitude}); "
            "CI straddles zero with small effect — no detectable difference."
        )
    elif abs(delta) >= 0.33 and not ci_excludes_zero:
        verdict = "inconclusive"
        explanation = (
            f"Cliff's δ={delta:+.3f} [{lo:+.3f}, {hi:+.3f}]; point estimate suggests an effect "
            "but bootstrap CI includes zero. N=10 too few to distinguish from noise."
        )
    else:
        verdict = "inconclusive"
        explanation = (
            f"Cliff's δ={delta:+.3f} [{lo:+.3f}, {hi:+.3f}] (magnitude={magnitude}); "
            "ambiguous combination of small effect and tight CI excluding zero."
        )

    return {
        "campaign": "P3_collusion_H2",
        "preregistration": "paper_workspace/p3_preregistration.md",
        "per_cell": per_cell,
        "comparison": {
            "delta_median_coordinated_minus_independent": delta_median,
            "cliff_delta_coordinated_vs_independent": delta,
            "cliff_delta_ci": [lo, hi],
            "magnitude": magnitude,
            "ci_excludes_zero": ci_excludes_zero,
            "u_statistic": u["u_min"],
            "p_two_sided": u["p_two_sided"],
        },
        "verdict": verdict,
        "explanation": explanation,
    }


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="p3_collusion")
    parser.add_argument("--out-csv", default=DEFAULT_CSV)
    parser.add_argument("--out-summary", default=DEFAULT_SUMMARY)
    parser.add_argument("--out-verdict", default=DEFAULT_VERDICT)
    parser.add_argument("--reps", type=int, default=DEFAULT_REPS)
    parser.add_argument("--analyze-only", action="store_true")
    parser.add_argument("--no-analyze", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)

    csv_p = Path(args.out_csv)
    if not args.analyze_only:
        if csv_p.exists():
            csv_p.unlink()
        cells = build_cells(reps=args.reps)
        print(
            f"P3 Collusion campaign: {len(cells)} cells × {args.reps} reps "
            f"(pre-registered in paper_workspace/p3_preregistration.md)"
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
                f"  [{name:14s}] n={s.reps} mean={s.asr_mean:.2f}% "
                f"median={s.asr_median:.2f}% IQR={s.asr_iqr} "
                f"exits={s.all_exit_codes}"
            )

    if args.no_analyze:
        return 0

    print("\n--- H2 adjudication ---")
    verdict = analyze_h2(args.out_csv)
    Path(args.out_verdict).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out_verdict, "w") as fh:
        json.dump(verdict, fh, indent=2, default=str)

    print(f"verdict: {verdict['verdict'].upper()}")
    print(f"  {verdict['explanation']}")
    print("\nPer-cell medians:")
    for c in verdict["per_cell"]:
        print(
            f"  {c['cell_name']:14s}  median={c['median']:6.2f}%  "
            f"(min={c['min']:.2f}, max={c['max']:.2f}, n={c['n']})"
        )
    cmp_ = verdict["comparison"]
    print("\nComparison (coordinated vs independent):")
    print(f"  Δ median       = {cmp_['delta_median_coordinated_minus_independent']:+.2f} pp")
    print(f"  Cliff's δ      = {cmp_['cliff_delta_coordinated_vs_independent']:+.3f} ({cmp_['magnitude']})")
    print(f"  Cliff's δ CI   = [{cmp_['cliff_delta_ci'][0]:+.3f}, {cmp_['cliff_delta_ci'][1]:+.3f}]")
    print(f"  CI ⊅ 0?        = {cmp_['ci_excludes_zero']}")
    print(f"  MWU U          = {cmp_['u_statistic']}")
    print(f"  p (two-sided)  = {cmp_['p_two_sided']:.4f}")
    print(f"\nVerdict written to {args.out_verdict}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
