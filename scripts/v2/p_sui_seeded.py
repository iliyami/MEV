"""P3.3 -- Seeded intra-round tiebreak on Sui/Mysticeti.

P3 is the intra-round tiebreak dimension: Sui sorts same-round blocks by
`(round, author)`, which hands low-index validators free ordering priority
(the "index tax", baseline all-pairs ASR 56.30% against a fair 50%).
`FIX_TIEBREAK=1` swaps the author key for the block digest and only moves the
baseline to 54.29% -- it removes ~2 pp of the ~6.3 pp advantage, leaving an
unidentified ~4.3 pp residual. This driver asks whether an unpredictable-but-
deterministic tiebreak (hash of TIEBREAK_SEED + block digest, see
`sort_sub_dag_blocks` in commit.rs) removes the rest.

This cell runs NO attack -- all three arms are `withhold_baseline` (the
structural ordering bias itself is what's being measured), and differ in
exactly one thing: which env var selects the tiebreak rule.

    author     -- no tiebreak env set (production default: (round, author))
    digest     -- FIX_TIEBREAK=1                ((round, digest))
    seeded     -- SEEDED_TIEBREAK=1 TIEBREAK_SEED=7  ((round, hash(seed, digest)))

Regression gate (brief Step 5): author must reproduce ~56.30% and digest must
reproduce ~54.29% (PROVENANCE.md Sec 2.13). If either drifts more than ~0.5 pp,
the harness has changed and the new seeded number is not comparable to the
recorded ones -- stop and investigate rather than recording past a failed gate.

n=13, alpha=0.308, 5 reps minimum.

Usage:
    python -m scripts.v2.p_sui_seeded
    python -m scripts.v2.p_sui_seeded --reps 5
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Iterable, Optional

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from scripts.v2 import benchmark, schema, sweeper
from scripts.v2.launchers.sui import SuiLauncher

DEFAULT_CSV = "results/sui_seeded_results.csv"
DEFAULT_SUMMARY = "results/sui_seeded_summary.json"
DEFAULT_REPS = 5
BASE_SEED = 700

# Gate references, PROVENANCE.md Sec 2.13 (§2.13 "full arm set"). Drift beyond
# ~0.5pp means the harness changed and the seeded arm isn't comparable.
GATE_AUTHOR_ASR = 56.30
GATE_DIGEST_ASR = 54.29
GATE_TOLERANCE_PP = 0.5

_BASE_ENV = {
    "NUM_NODES": "13",
    "ATTACKER_RATIO": "0.308",
    "VICTIM_RATIO": "0.231",
    "GC_DEPTH": "10",
    "COLLECTION_DURATION": "45",
    "MIN_COMMITS": "25",
}

# Attacker layout for n=13, alpha=0.308 -> the first 4 indices. Unused by the
# scoring here (no attack runs), kept for parity with the matched-baseline
# topology used across the other Sui P-cells.
_ATTACKERS = [0, 1, 2, 3]

_LAUNCHER = SuiLauncher(use_coordinator=False)


def _cfg(reps: int, extra_env: dict) -> schema.V2Config:
    env = dict(_BASE_ENV)
    env.update(extra_env)
    raw = {
        "protocol": {"name": "sui", "path": "sui"},
        "environment": env,
        "adversary": {
            "threat_model": "TM-Solo",
            "topology": {
                "policies": [
                    {
                        "group_id": "g0",
                        "members": _ATTACKERS,
                        "family": "frontrun",
                        "strategy": "withhold_baseline",
                        "params": {},
                    }
                ]
            },
        },
        "victims": {
            "workload": "single",
            "count": 1,
            # Heavy-tailed profit so realized-MEV (T4) is reported alongside
            # ASR, per the report contract (both metric families).
            "profit": {"distribution": "pareto", "params": {"shape": 1.16, "scale": 1.0}},
        },
        "runtime": {"reps": reps, "seed": BASE_SEED},
    }
    return sweeper.expand_policy_vector(schema.parse_config(raw))


def build_cells(reps: int = DEFAULT_REPS) -> list[benchmark.Cell]:
    return [
        benchmark.Cell(
            name="author",
            config=_cfg(reps, {}),
            launcher=_LAUNCHER,
        ),
        benchmark.Cell(
            name="digest",
            config=_cfg(reps, {"FIX_TIEBREAK": "1"}),
            launcher=_LAUNCHER,
        ),
        benchmark.Cell(
            name="seeded",
            config=_cfg(reps, {"SEEDED_TIEBREAK": "1", "TIEBREAK_SEED": "7"}),
            launcher=_LAUNCHER,
        ),
    ]


def _check_gate(name: str, observed: Optional[float], expected: float) -> bool:
    if observed is None:
        print(f"  GATE [{name}] FAIL: no ASR median observed")
        return False
    drift = observed - expected
    ok = abs(drift) <= GATE_TOLERANCE_PP
    status = "PASS" if ok else "FAIL"
    print(
        f"  GATE [{name}] {status}: observed={observed:.2f}% expected={expected:.2f}% "
        f"drift={drift:+.2f}pp (tolerance {GATE_TOLERANCE_PP}pp)"
    )
    return ok


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="p_sui_seeded")
    parser.add_argument("--out-csv", default=DEFAULT_CSV)
    parser.add_argument("--out-summary", default=DEFAULT_SUMMARY)
    parser.add_argument("--reps", type=int, default=DEFAULT_REPS)
    args = parser.parse_args(list(argv) if argv is not None else None)

    csv_p = Path(args.out_csv)
    csv_p.parent.mkdir(parents=True, exist_ok=True)
    if csv_p.exists():
        csv_p.unlink()

    cells = build_cells(reps=args.reps)
    print(f"Sui Seeded Tiebreak (P3.3): {len(cells)} cells x {args.reps} reps")

    summaries = benchmark.run_benchmark(
        cells=cells,
        out_csv=args.out_csv,
        out_summary_json=args.out_summary,
        reps=args.reps,
        progress_callback=lambda msg: print(msg, flush=True),
    )
    print("\nPer-cell summary (all-pairs ASR is primary for this cell; value metrics shown too):")
    for name, s in summaries.items():
        pw = f"{s.profit_weighted_asr_median:.2f}%" if s.profit_weighted_asr_median is not None else "n/a"
        rm = f"{s.realized_mev_mean:.1f}" if s.realized_mev_mean is not None else "n/a"
        rng = (
            f"[{s.asr_min:.2f}, {s.asr_max:.2f}]"
            if s.asr_min is not None and s.asr_max is not None
            else "n/a"
        )
        print(
            f"  [{name:8s}] n={s.reps} "
            f"asr_median={s.asr_median:.2f}% range={rng} profit_wtd_asr={pw} realized_mev={rm} "
            f"raw={[f'{x:.2f}' for x in s.asrs]}"
        )

    print("\nRegression gate (PROVENANCE.md Sec 2.13):")
    author_asr = summaries["author"].asr_median if "author" in summaries else None
    digest_asr = summaries["digest"].asr_median if "digest" in summaries else None
    author_ok = _check_gate("author", author_asr, GATE_AUTHOR_ASR)
    digest_ok = _check_gate("digest", digest_asr, GATE_DIGEST_ASR)
    if not (author_ok and digest_ok):
        print(
            "\nGATE FAILED: at least one recorded baseline drifted >0.5pp. "
            "Do not treat the seeded arm as comparable -- investigate before reporting."
        )
        return 1

    seeded_asr = summaries["seeded"].asr_median if "seeded" in summaries else None
    if seeded_asr is not None:
        print(
            f"\nP3.3 headline: seeded={seeded_asr:.2f}% vs digest={digest_asr:.2f}% "
            f"vs fair=50.00%"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
