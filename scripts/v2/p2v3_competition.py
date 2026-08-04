"""P2 v3 — Competition campaign (H1.1 — H1.5).

Pre-registered in `paper_workspace/p2v3_preregistration.md`.

Cells (10 primary + 2 creative):

  k1_homo_fissure        — k=1 homogeneous fissure (H1.1 anchor)
  k2_split               — k=2 [fissure, speculative] (H1.1)
  k3_split               — k=3 [fissure, speculative, sluggish] (H1.1)
  k4_split               — k=4 round-robin (H1.1, H1.4)
  overlap_same_victim    — k=2 both fissure same victim node (H1.2)
  overlap_diff_victims   — k=2 both fissure different victim nodes (H1.2)
  mix_amplify            — k=2 [fissure exclude, fissure amplify] (H1.3)
  mix_control            — k=2 both fissure default (H1.3 control)
  decoy_primary          — k=2 fissure(victim_A) + fissure(victim_B) (H1.5)
  decoy_baseline         — k=1 fissure(victim_A) only (H1.5 baseline)
  entropy_random_latin_k4 — creative: random_latin_square k=4
  sacrifice_k2           — creative: one attacker self-sacrifices

Reps = 10 per cell (P3 lesson). 12 × 10 = 120 Bullshark runs.

Usage:
    python -m scripts.v2.p2v3_competition          # run + analyze
    python -m scripts.v2.p2v3_competition --analyze-only
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


DEFAULT_CSV = "results/v2_p2v3_results.csv"
DEFAULT_SUMMARY = "results/v2_p2v3_summary.json"
DEFAULT_VERDICT = "results/v2_p2v3_verdict.json"
DEFAULT_REPS = 10
BASE_SEED = 0


_BASE_ENV = {
    "NUM_NODES": "13",
    "ATTACKER_RATIO": "0.308",
    "VICTIM_RATIO": "0.231",  # ~3 victims at n=13
    "SPECULATIVE_P_MAX": "50",
    "SLUGGISH_TIMEOUT_MULTIPLIER": "1.5",
    "DAG_STATE_CACHED_ROUNDS": "5",
    "SYNC_TIMEOUT_MS": "2000",
    "GC_DEPTH": "10",
    "ATTACK_MODE": "fissure",
    "ATTACK_TYPE": "frontrun",
}


import os as _os
_N_NODES = 13
_REV = bool(_os.environ.get("REVERSE_LAYOUT"))
def _r(i: int) -> int:
    return (_N_NODES - 1 - i) if _REV else i
def _rl(xs) -> list[int]:
    return sorted(_r(i) for i in xs) if _REV else list(xs)
_FWD_ENV = {k: _os.environ[k] for k in ("REVERSE_LAYOUT", "V2_VICTIM_NODE_IDS") if _os.environ.get(k)}


def _cfg(name: str, policies: list[dict], reps: int,
         threat_model: str = "TM-Compete",
         archetype: str = "same_family_split",
         env_overrides: Optional[dict] = None) -> schema.V2Config:
    env = dict(_BASE_ENV)
    env.update(_FWD_ENV)
    if env_overrides:
        env.update(env_overrides)
    if _REV:
        policies = [{**p, "members": _rl(p["members"])} if "members" in p else p
                    for p in policies]
    raw = {
        "protocol": {"name": "bullshark", "path": "bullshark"},
        "docker": {"tag": "mev-bullshark:latest", "cpus": "8.0", "memory": "16g"},
        "test": {"test_name": "test_fissure_attack_asr_dynamic", "REPETITIONS": 1},
        "environment": env,
        "adversary": {
            "threat_model": threat_model,
            "archetype": archetype,
            "topology": {"policies": policies},
        },
        "victims": {"workload": "single", "count": 1},
        "runtime": {"reps": reps, "seed": BASE_SEED},
    }
    return sweeper.expand_policy_vector(schema.parse_config(raw))


# ---------------------------------------------------------------------------
# Cells
# ---------------------------------------------------------------------------


def _cell_k1_homo_fissure(reps: int) -> benchmark.Cell:
    policies = [
        {"group_id": "g0", "members": [0, 1, 2, 3], "family": "frontrun",
         "strategy": "fissure", "params": {}}
    ]
    return benchmark.Cell(
        name="k1_homo_fissure",
        config=_cfg("k1_homo_fissure", policies, reps,
                    threat_model="TM-Solo", archetype="homogeneous"),
        paper1_lookup=benchmark.paper1_lookup_frontrun,
    )


def _cell_k2_split(reps: int) -> benchmark.Cell:
    policies = [
        {"group_id": "g0", "members": [0, 1], "family": "frontrun",
         "strategy": "fissure", "params": {}},
        {"group_id": "g1", "members": [2, 3], "family": "frontrun",
         "strategy": "speculative", "params": {}},
    ]
    return benchmark.Cell(
        name="k2_split",
        config=_cfg("k2_split", policies, reps),
        paper1_lookup=benchmark.paper1_lookup_frontrun,
    )


def _cell_k3_split(reps: int) -> benchmark.Cell:
    policies = [
        {"group_id": "g0", "members": [0, 1], "family": "frontrun",
         "strategy": "fissure", "params": {}},
        {"group_id": "g1", "members": [2], "family": "frontrun",
         "strategy": "speculative", "params": {}},
        {"group_id": "g2", "members": [3], "family": "frontrun",
         "strategy": "sluggish", "params": {}},
    ]
    return benchmark.Cell(
        name="k3_split",
        config=_cfg("k3_split", policies, reps),
        paper1_lookup=benchmark.paper1_lookup_frontrun,
    )


def _cell_k4_split(reps: int) -> benchmark.Cell:
    policies = [
        {"group_id": "g0", "members": [0], "family": "frontrun",
         "strategy": "fissure", "params": {}},
        {"group_id": "g1", "members": [1], "family": "frontrun",
         "strategy": "speculative", "params": {}},
        {"group_id": "g2", "members": [2], "family": "frontrun",
         "strategy": "sluggish", "params": {}},
        {"group_id": "g3", "members": [3], "family": "frontrun",
         "strategy": "fissure", "params": {}},
    ]
    return benchmark.Cell(
        name="k4_split",
        config=_cfg("k4_split", policies, reps),
        paper1_lookup=benchmark.paper1_lookup_frontrun,
    )


def _cell_overlap_same_victim(reps: int) -> benchmark.Cell:
    """H1.2: 2 attackers, both fissure, same victim."""
    policies = [
        {"group_id": "g0", "members": [0, 1], "family": "frontrun",
         "strategy": "fissure", "params": {}},
        {"group_id": "g1", "members": [2, 3], "family": "frontrun",
         "strategy": "fissure", "params": {}},
    ]
    return benchmark.Cell(
        name="overlap_same_victim",
        config=_cfg("overlap_same_victim", policies, reps,
                    archetype="same_strategy_split"),
        paper1_lookup=benchmark.paper1_lookup_frontrun,
    )


def _cell_overlap_diff_victims(reps: int) -> benchmark.Cell:
    """H1.2: 2 attackers, both fissure, but the victim_count is 2
    so they spread their attention across 2 victims (Bullshark's
    layout naturally exposes multiple victims when VICTIM_RATIO > 1/n)."""
    # VICTIM_RATIO=0.154 → ~2 victims; attackers naturally target both.
    policies = [
        {"group_id": "g0", "members": [0, 1], "family": "frontrun",
         "strategy": "fissure", "params": {}},
        {"group_id": "g1", "members": [2, 3], "family": "frontrun",
         "strategy": "fissure", "params": {}},
    ]
    return benchmark.Cell(
        name="overlap_diff_victims",
        config=_cfg("overlap_diff_victims", policies, reps,
                    archetype="same_strategy_split",
                    env_overrides={"VICTIM_RATIO": "0.154"}),  # 2 victims
        paper1_lookup=benchmark.paper1_lookup_frontrun,
    )


def _cell_mix_amplify(reps: int) -> benchmark.Cell:
    """H1.3: one excluder + one amplifier (R-P3.1 amplify role)."""
    policies = [
        {"group_id": "g0", "members": [0, 1], "family": "frontrun",
         "strategy": "fissure", "params": {"role_action": "exclude"}},
        {"group_id": "g1", "members": [2, 3], "family": "frontrun",
         "strategy": "fissure", "params": {"role_action": "amplify"}},
    ]
    return benchmark.Cell(
        name="mix_amplify",
        config=_cfg("mix_amplify", policies, reps),
        paper1_lookup=benchmark.paper1_lookup_frontrun,
    )


def _cell_mix_control(reps: int) -> benchmark.Cell:
    """H1.3 control: same 2-group split but both groups default fissure."""
    policies = [
        {"group_id": "g0", "members": [0, 1], "family": "frontrun",
         "strategy": "fissure", "params": {}},
        {"group_id": "g1", "members": [2, 3], "family": "frontrun",
         "strategy": "fissure", "params": {}},
    ]
    return benchmark.Cell(
        name="mix_control",
        config=_cfg("mix_control", policies, reps,
                    archetype="same_strategy_split"),
        paper1_lookup=benchmark.paper1_lookup_frontrun,
    )


def _cell_decoy_primary(reps: int) -> benchmark.Cell:
    """H1.5: primary attacker + decoy attacker, 2 victims layout."""
    policies = [
        {"group_id": "g0", "members": [0, 1], "family": "frontrun",
         "strategy": "fissure", "params": {}},  # primary
        {"group_id": "g1", "members": [2, 3], "family": "frontrun",
         "strategy": "fissure", "params": {}},  # "decoy" — same strategy but on diff victim by layout
    ]
    return benchmark.Cell(
        name="decoy_primary",
        config=_cfg("decoy_primary", policies, reps,
                    archetype="same_strategy_split",
                    env_overrides={"VICTIM_RATIO": "0.154"}),
        paper1_lookup=benchmark.paper1_lookup_frontrun,
    )


def _cell_decoy_baseline(reps: int) -> benchmark.Cell:
    """H1.5 baseline: only the primary attacker, 1 victim layout."""
    policies = [
        {"group_id": "g0", "members": [0, 1], "family": "frontrun",
         "strategy": "fissure", "params": {}},
    ]
    return benchmark.Cell(
        name="decoy_baseline",
        config=_cfg("decoy_baseline", policies, reps,
                    threat_model="TM-Solo", archetype="homogeneous"),
        paper1_lookup=benchmark.paper1_lookup_frontrun,
    )


def _cell_entropy_random_latin_k4(reps: int) -> benchmark.Cell:
    """Creative add-on: random Latin-square k=4 to test policy entropy."""
    # Latin square at k=4: families/strategies drawn from {frontrun} × {fissure, speculative, sluggish, fissure}
    # Constrain to frontrun family so victim layout stays coherent.
    policies = [
        {"group_id": "g0", "members": [0], "family": "frontrun",
         "strategy": "fissure", "params": {}},
        {"group_id": "g1", "members": [1], "family": "frontrun",
         "strategy": "sluggish", "params": {}},
        {"group_id": "g2", "members": [2], "family": "frontrun",
         "strategy": "speculative", "params": {}},
        {"group_id": "g3", "members": [3], "family": "frontrun",
         "strategy": "fissure", "params": {}},
    ]
    return benchmark.Cell(
        name="entropy_random_latin_k4",
        config=_cfg("entropy_random_latin_k4", policies, reps,
                    archetype="random_latin_square"),
        paper1_lookup=benchmark.paper1_lookup_frontrun,
    )


def _cell_sacrifice_k2(reps: int) -> benchmark.Cell:
    """Creative add-on: 1 amplifier + 1 fissure (the amplifier "sacrifices"
    its own ASR to feed the fissure attacker by preferentially including
    its blocks)."""
    policies = [
        {"group_id": "g0", "members": [0, 1], "family": "frontrun",
         "strategy": "fissure", "params": {}},  # main attacker
        {"group_id": "g1", "members": [2, 3], "family": "frontrun",
         "strategy": "fissure", "params": {"role_action": "amplify"}},  # sacrifice
    ]
    return benchmark.Cell(
        name="sacrifice_k2",
        config=_cfg("sacrifice_k2", policies, reps),
        paper1_lookup=benchmark.paper1_lookup_frontrun,
    )


def build_cells(reps: int = DEFAULT_REPS) -> list[benchmark.Cell]:
    return [
        _cell_k1_homo_fissure(reps),
        _cell_k2_split(reps),
        _cell_k3_split(reps),
        _cell_k4_split(reps),
        _cell_overlap_same_victim(reps),
        _cell_overlap_diff_victims(reps),
        _cell_mix_amplify(reps),
        _cell_mix_control(reps),
        _cell_decoy_primary(reps),
        _cell_decoy_baseline(reps),
        _cell_entropy_random_latin_k4(reps),
        _cell_sacrifice_k2(reps),
    ]


# ---------------------------------------------------------------------------
# Adjudication
# ---------------------------------------------------------------------------


def _read_csv(csv_path: str) -> dict[str, list[dict]]:
    """Return {cell_name: [rows]}."""
    by_cell: dict[str, list[dict]] = defaultdict(list)
    with open(csv_path, "r") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            by_cell[row["cell_name"]].append(row)
    return dict(by_cell)


def _asrs(rows: list[dict]) -> list[float]:
    out = []
    for r in rows:
        try:
            out.append(float(r["asr"]))
        except (KeyError, ValueError):
            pass
    return out


def _gini(values: list[float]) -> float:
    """Gini coefficient over non-negative values."""
    if not values or sum(values) == 0:
        return 0.0
    sorted_v = sorted(values)
    n = len(sorted_v)
    cum = 0.0
    for i, v in enumerate(sorted_v, 1):
        cum += i * v
    return (2 * cum) / (n * sum(sorted_v)) - (n + 1) / n


def _per_policy_gini_per_rep(rows: list[dict]) -> list[float]:
    """For each rep, compute the Gini over its per-policy ASR values."""
    out = []
    for r in rows:
        try:
            pp = json.loads(r["per_policy_asr_json"])
        except (KeyError, json.JSONDecodeError):
            continue
        vals = [float(v) for v in pp.values() if v is not None]
        if len(vals) >= 2:
            out.append(_gini(vals))
    return out


def _compare(a: list[float], b: list[float], label: str) -> dict:
    """Cliff's δ with bootstrap CI; locked decision rule applied."""
    if not a or not b:
        return {"label": label, "skipped": True}
    delta, lo, hi = stats.cliff_delta_bootstrap_ci(a, b, n_boot=1000, seed=0)
    u = stats.mann_whitney_u(a, b)
    ci_excludes_zero = lo > 0.0 or hi < 0.0
    meets_threshold = abs(delta) >= 0.33
    decision = "supports" if (ci_excludes_zero and meets_threshold) else "rejects"
    return {
        "label": label,
        "left_median": st.median(a),
        "right_median": st.median(b),
        "delta_median": st.median(a) - st.median(b),
        "cliff_delta_left_vs_right": delta,
        "ci": [lo, hi],
        "magnitude": stats.cliff_delta_magnitude(delta),
        "ci_excludes_zero": ci_excludes_zero,
        "meets_0p33_threshold": meets_threshold,
        "p_two_sided": u["p_two_sided"],
        "decision": decision,
    }


def analyze(csv_path: str) -> dict[str, Any]:
    by_cell = _read_csv(csv_path)
    cells_present = set(by_cell.keys())

    per_cell_summary = {}
    for name, rows in by_cell.items():
        asrs = _asrs(rows)
        per_cell_summary[name] = {
            "n": len(asrs),
            "mean": st.mean(asrs) if asrs else None,
            "median": st.median(asrs) if asrs else None,
            "min": min(asrs) if asrs else None,
            "max": max(asrs) if asrs else None,
        }

    findings: dict[str, Any] = {}

    # H1.1 — k-curve shape: adjacent-pair Cliff's δ
    h11_pairs = []
    for a_name, b_name in [
        ("k1_homo_fissure", "k2_split"),
        ("k2_split", "k3_split"),
        ("k3_split", "k4_split"),
    ]:
        if a_name in cells_present and b_name in cells_present:
            cmp_result = _compare(
                _asrs(by_cell[b_name]),
                _asrs(by_cell[a_name]),
                f"{b_name} vs {a_name}",
            )
            h11_pairs.append(cmp_result)
    inc = [c for c in h11_pairs if c.get("cliff_delta_left_vs_right", 0) >= 0.33 and c.get("ci_excludes_zero")]
    dec = [c for c in h11_pairs if c.get("cliff_delta_left_vs_right", 0) <= -0.33 and c.get("ci_excludes_zero")]
    h11_verdict = "supported" if (inc and dec) else "rejected"
    findings["H1.1_k_curve_non_monotonic"] = {
        "verdict": h11_verdict,
        "pairs": h11_pairs,
        "explanation": (
            f"{len(inc)} notable increase(s) AND {len(dec)} notable decrease(s) "
            "at the locked rule."
        ),
    }

    # H1.2 — same-victim overlap
    if "overlap_same_victim" in cells_present and "overlap_diff_victims" in cells_present:
        cmp_aggregate = _compare(
            _asrs(by_cell["overlap_same_victim"]),
            _asrs(by_cell["overlap_diff_victims"]),
            "overlap_same_victim vs overlap_diff_victims (aggregate)",
        )
        # per-attacker mean
        same_per = []
        for r in by_cell["overlap_same_victim"]:
            try:
                pp = json.loads(r["per_policy_asr_json"])
                vals = [float(v) for v in pp.values() if v is not None]
                if vals:
                    same_per.append(st.mean(vals))
            except Exception:
                pass
        diff_per = []
        for r in by_cell["overlap_diff_victims"]:
            try:
                pp = json.loads(r["per_policy_asr_json"])
                vals = [float(v) for v in pp.values() if v is not None]
                if vals:
                    diff_per.append(st.mean(vals))
            except Exception:
                pass
        cmp_per = _compare(same_per, diff_per, "overlap_same vs diff (per-attacker mean)")
        findings["H1.2_same_victim_overlap"] = {
            "aggregate": cmp_aggregate,
            "per_attacker": cmp_per,
            "verdict": (
                "supported"
                if (cmp_aggregate.get("decision") == "supports"
                    and cmp_per.get("decision") == "supports"
                    and cmp_per.get("cliff_delta_left_vs_right", 0) < 0)
                else "rejected"
            ),
        }

    # H1.3 — family-mix amplification (mix_amplify vs mix_control)
    if "mix_amplify" in cells_present and "mix_control" in cells_present:
        cmp_h13 = _compare(
            _asrs(by_cell["mix_amplify"]),
            _asrs(by_cell["mix_control"]),
            "mix_amplify vs mix_control",
        )
        findings["H1.3_family_mix"] = cmp_h13

    # H1.4 — Gini concentration at k=4
    if "k4_split" in cells_present:
        ginis = _per_policy_gini_per_rep(by_cell["k4_split"])
        if ginis:
            mean_gini = st.mean(ginis)
            # Bootstrap CI for mean Gini
            import random as _rand
            rng = _rand.Random(0)
            boots = []
            for _ in range(1000):
                sample = [ginis[rng.randrange(len(ginis))] for _ in range(len(ginis))]
                boots.append(st.mean(sample))
            boots.sort()
            lo = boots[24]   # 2.5%
            hi = boots[975]  # 97.5%
            verdict = "supported" if lo > 0.10 else "rejected"
        else:
            mean_gini = None
            lo = hi = None
            verdict = "skipped"
        findings["H1.4_gini_concentration"] = {
            "mean_gini": mean_gini,
            "ci": [lo, hi],
            "ginis_per_rep": ginis,
            "verdict": verdict,
        }

    # H1.5 — decoy effectiveness
    if "decoy_primary" in cells_present and "decoy_baseline" in cells_present:
        cmp_h15 = _compare(
            _asrs(by_cell["decoy_primary"]),
            _asrs(by_cell["decoy_baseline"]),
            "decoy_primary vs decoy_baseline",
        )
        findings["H1.5_decoy"] = cmp_h15

    # Creative add-on summaries (not adjudicated as hypotheses)
    creative = {}
    for name in ("entropy_random_latin_k4", "sacrifice_k2"):
        if name in cells_present:
            asrs = _asrs(by_cell[name])
            creative[name] = {
                "median": st.median(asrs) if asrs else None,
                "mean": st.mean(asrs) if asrs else None,
                "n": len(asrs),
            }

    return {
        "campaign": "P2v3_competition",
        "preregistration": "paper_workspace/p2v3_preregistration.md",
        "per_cell_summary": per_cell_summary,
        "findings": findings,
        "creative_add_ons": creative,
    }


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="p2v3_competition")
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
            f"P2 v3 Competition campaign: {len(cells)} cells × {args.reps} reps "
            f"(pre-registered in paper_workspace/p2v3_preregistration.md)"
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
                f"  [{name:24s}] n={s.reps} mean={s.asr_mean:.2f}% "
                f"median={s.asr_median:.2f}% IQR={s.asr_iqr}"
            )

    if args.no_analyze:
        return 0

    print("\n--- H1.x adjudication ---")
    verdict = analyze(args.out_csv)
    Path(args.out_verdict).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out_verdict, "w") as fh:
        json.dump(verdict, fh, indent=2, default=str)

    for hyp_name, hyp_data in verdict["findings"].items():
        v = hyp_data.get("verdict") or hyp_data.get("decision") or "?"
        print(f"  {hyp_name}: {v}")
    print(f"\nVerdict written to {args.out_verdict}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
