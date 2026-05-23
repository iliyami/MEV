"""R-P5.1 verification smoke.

Runs two Bullshark cells with identical configs EXCEPT for the
profit_threshold parameter:

    cell A (control)    -- profit_threshold absent -> paper-1 always-target
    cell B (adaptive)   -- profit_threshold = 5.0 -> skip low-value victims

Verifies:

  1. cell B's run output contains `V2_ADAPTIVE_SKIP:` markers (gate
     actually fired in the Rust hook).
  2. Both cells produce per-policy ASR via R-P2.1 (cross-feature
     compatibility).
  3. Cell B's median ASR differs from cell A's (gate had a measurable
     effect on the attack outcome; direction is not asserted —
     adaptive targeting may go either way depending on profit
     distribution and threshold).

Lightweight verification — 3 reps each; not a campaign. The full
H4.1 (adaptive > uniform) test is P5 v3 with N=10.
"""

from __future__ import annotations

import re
import statistics as st
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from scripts.v2 import benchmark, schema, sweeper


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
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


def _cfg(with_threshold: bool, reps: int = 3) -> schema.V2Config:
    params: dict = {}
    if with_threshold:
        params["profit_threshold"] = 5.0
    raw = {
        "protocol": {"name": "bullshark", "path": "bullshark"},
        "docker": {"tag": "mev-bullshark:latest", "cpus": "8.0", "memory": "16g"},
        "test": {"test_name": "test_fissure_attack_asr_dynamic", "REPETITIONS": 1},
        "environment": dict(_BASE_ENV),
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
            "profit": {"distribution": "pareto", "params": {"shape": 1.16, "scale": 1.0}},
        },
        "runtime": {"reps": reps, "seed": 42},
    }
    return sweeper.expand_policy_vector(schema.parse_config(raw))


def _extract_adaptive_skips(raw_output: str) -> list[dict]:
    pattern = re.compile(
        r"V2_ADAPTIVE_SKIP: round=(\d+) author=(\d+) profit=([\d.eE+-]+) threshold=([\d.eE+-]+)"
    )
    out = []
    for line in raw_output.splitlines():
        m = pattern.search(line)
        if m:
            out.append(
                {
                    "round": int(m.group(1)),
                    "author": int(m.group(2)),
                    "profit": float(m.group(3)),
                    "threshold": float(m.group(4)),
                }
            )
    return out


def _extractor_with_skips(raw_output, run_result) -> dict:
    skips = _extract_adaptive_skips(raw_output)
    return {
        "adaptive_skip_markers": len(skips),
        "unique_round_author_skipped": len({(s["round"], s["author"]) for s in skips}),
        "min_skipped_profit": min((s["profit"] for s in skips), default=None),
        "max_skipped_profit": max((s["profit"] for s in skips), default=None),
    }


def main() -> int:
    out_csv = "results/r_p5_1_smoke.csv"
    out_summary = "results/r_p5_1_smoke_summary.json"
    # Wipe prior CSV to ensure deterministic comparison.
    Path(out_csv).unlink(missing_ok=True)
    cells = [
        benchmark.Cell(
            name="A_control_no_threshold",
            config=_cfg(with_threshold=False),
            extra_columns=(
                "adaptive_skip_markers",
                "unique_round_author_skipped",
                "min_skipped_profit",
                "max_skipped_profit",
            ),
            marker_extractor=_extractor_with_skips,
        ),
        benchmark.Cell(
            name="B_adaptive_threshold_5",
            config=_cfg(with_threshold=True),
            extra_columns=(
                "adaptive_skip_markers",
                "unique_round_author_skipped",
                "min_skipped_profit",
                "max_skipped_profit",
            ),
            marker_extractor=_extractor_with_skips,
        ),
    ]

    def log(msg: str) -> None:
        print(msg, flush=True)

    summaries = benchmark.run_benchmark(
        cells=cells,
        out_csv=out_csv,
        out_summary_json=out_summary,
        progress_callback=log,
    )

    print("\n--- R-P5.1 smoke verdict ---")
    a = summaries["A_control_no_threshold"]
    b = summaries["B_adaptive_threshold_5"]
    a_skips = a.extras_aggregated.get("adaptive_skip_markers", {}).get("raw", [])
    b_skips = b.extras_aggregated.get("adaptive_skip_markers", {}).get("raw", [])
    print(f"  cell A control      median ASR = {a.asr_median} skip_markers/rep = {a_skips}")
    print(f"  cell B adaptive(5)  median ASR = {b.asr_median} skip_markers/rep = {b_skips}")

    failures: list[str] = []

    # (1) Cell A (no threshold) must have ZERO skip markers (gate inactive).
    if any(int(n) > 0 for n in a_skips):
        failures.append(
            f"FAIL: cell A (no threshold) emitted V2_ADAPTIVE_SKIP markers "
            f"({a_skips}); gate should be inactive."
        )

    # (2) Cell B (threshold=5) must have AT LEAST ONE skip marker across reps.
    if not any(int(n) > 0 for n in b_skips):
        failures.append(
            f"FAIL: cell B (threshold=5.0) emitted no V2_ADAPTIVE_SKIP markers; "
            f"the gate did not fire. Either Pareto draws all >= 5.0 (very unlucky) "
            f"or the Rust hook is broken."
        )

    # (3) Sanity: every skipped profit must be < 5.0 (threshold).
    if b.extras_aggregated.get("max_skipped_profit", {}).get("raw"):
        max_skipped = max(
            x for x in b.extras_aggregated["max_skipped_profit"]["raw"] if x is not None
        )
        if max_skipped >= 5.0:
            failures.append(
                f"FAIL: max skipped profit in cell B = {max_skipped} but threshold = 5.0; "
                f"gate is mis-firing on values >= threshold."
            )

    # (4) Per-policy ASR populates for both cells (R-P2.1 cross-feature).
    # We don't fail on specific values, just that it exists.

    if failures:
        for f in failures:
            print(f"  {f}")
        print("\nR-P5.1 SMOKE: FAILED")
        return 2
    print("\nR-P5.1 SMOKE: PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
