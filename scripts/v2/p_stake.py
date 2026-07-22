"""DS13 — skewed-stake deployment (Family D2).

Does lopsided voting weight amplify a validator's ordering advantage? Leader
election is stake-weighted, so a high-stake low-index validator leads more often
and its blocks anchor early. We run baseline + fissure + silent-except-leader
with ONE attacker under equal vs skewed stake (attacker index 0 gets 5x, the
rest 1x -> 5/17 = 29% < 1/3, so the Byzantine bound holds). All-pairs ASR.

DS19 (empty-cell prediction) rides on the silent x skewed cell: the design tree
predicts stake-concentration should amplify the strongest primitive (silent).

Usage:
    python -m scripts.v2.p_stake --protocol sui
    python -m scripts.v2.p_stake --protocol bullshark --reps 5
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Iterable, Optional

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from scripts.v2 import benchmark, schema, sweeper
from scripts.v2.launchers.bullshark import BullsharkLauncher
from scripts.v2.launchers.sui import SuiLauncher

DEFAULT_REPS = 5
BASE_SEED = 700
N = 13
# Attacker (index 0) 5x, rest 1x -> 5/17 = 29.4% < 1/3 (BFT-safe).
_SKEWED = ",".join(["5"] + ["1"] * (N - 1))
_ATTACKS = [("withhold_baseline", "baseline"), ("fissure", "fissure"), ("withhold_silent", "silent")]
_STAKES = [("equal", None), ("skewed", _SKEWED)]


def _cfg(protocol: str, strategy: str, stake_profile: Optional[str], reps: int) -> schema.V2Config:
    # 1 attacker so stake can be concentrated on it within the < 1/3 bound.
    env = {
        "NUM_NODES": str(N), "ATTACKER_RATIO": "0.077", "VICTIM_RATIO": "0.231",
        "GC_DEPTH": "10", "COLLECTION_DURATION": "45", "MIN_COMMITS": "23",
    }
    if stake_profile:
        # BFT guard: no single validator >= 1/3 of total stake.
        stakes = [int(x) for x in stake_profile.split(",")]
        assert max(stakes) < sum(stakes) / 3, f"stake {stake_profile} breaks BFT"
        env["STAKE_PROFILE"] = stake_profile
    raw: dict = {
        "protocol": {"name": protocol, "path": protocol},
        "environment": env,
        "adversary": {
            "threat_model": "TM-Solo",
            "topology": {"policies": [
                {"group_id": "g0", "members": [0], "family": "frontrun",
                 "strategy": strategy, "params": {}},
            ]},
        },
        "victims": {"workload": "single", "count": 1,
                    "profit": {"distribution": "pareto", "params": {"shape": 1.16, "scale": 1.0}}},
        "runtime": {"reps": reps, "seed": BASE_SEED},
    }
    if protocol == "bullshark":
        env["DAG_STATE_CACHED_ROUNDS"] = "5"
        env["SYNC_TIMEOUT_MS"] = "2000"
        env["ATTACK_TYPE"] = "frontrun"
        env["V2_ALL_PAIRS_ASR"] = "1"  # Bullshark headline = all-pairs
        raw["docker"] = {"tag": "mev-bullshark:latest", "cpus": "8.0", "memory": "16g"}
        raw["test"] = {"test_name": "test_fissure_attack_asr_dynamic", "REPETITIONS": 1}
    return sweeper.expand_policy_vector(schema.parse_config(raw))


def build_cells(protocol: str, reps: int = DEFAULT_REPS) -> list[benchmark.Cell]:
    launcher = (SuiLauncher(use_coordinator=False) if protocol == "sui"
                else BullsharkLauncher(local_mode=True, use_coordinator=False))
    cells = []
    for strategy, atag in _ATTACKS:
        for stag, profile in _STAKES:
            cells.append(benchmark.Cell(
                name=f"{atag}_{stag}",
                config=_cfg(protocol, strategy, profile, reps),
                launcher=launcher,
            ))
    return cells


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="p_stake")
    parser.add_argument("--protocol", choices=("sui", "bullshark"), required=True)
    parser.add_argument("--out-csv", default=None)
    parser.add_argument("--out-summary", default=None)
    parser.add_argument("--reps", type=int, default=DEFAULT_REPS)
    args = parser.parse_args(list(argv) if argv is not None else None)

    pfx = "sui" if args.protocol == "sui" else "v2"
    out_csv = args.out_csv or f"results/{pfx}_stake_results.csv"
    out_summary = args.out_summary or f"results/{pfx}_stake_summary.json"
    csv_p = Path(out_csv)
    csv_p.parent.mkdir(parents=True, exist_ok=True)
    if csv_p.exists():
        csv_p.unlink()

    cells = build_cells(args.protocol, reps=args.reps)
    print(f"{args.protocol} DS13 skewed-stake: {len(cells)} cells × {args.reps} reps")
    summaries = benchmark.run_benchmark(
        cells=cells, out_csv=out_csv, out_summary_json=out_summary,
        reps=args.reps, progress_callback=lambda m: print(m, flush=True))
    print("\nAll-pairs ASR (equal vs skewed stake):")
    for name, s in summaries.items():
        am = f"{s.asr_median:.1f}%" if s.asr_median is not None else "n/a"
        print(f"  [{name:18s}] all-pairs_asr={am:>7}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
