"""DS14 — WAN latency deployment (Family D3).

Inject a real per-send delay (env LATENCY_MS, delay-only in tonic_network.rs)
and measure whether network latency changes the attack. LAN (no delay) is the
guardrail: all-pairs baseline should stay ~50%. WAN adds uniform 100ms; ASYM
doubles it toward high-index peers (a regional split where the victim tier 9-12
is far), which should let the on-time low-index attacker land ahead more.

baseline + fissure + silent-except-leader x {LAN, WAN, asymmetric}, 4 attackers
(alpha=0.308), all-pairs ASR.

Usage:
    python -m scripts.v2.p_latency --protocol sui
    python -m scripts.v2.p_latency --protocol bullshark --reps 5
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
BASE_SEED = 800
N = 13
_LAT = [
    ("lan", {}),
    ("wan", {"LATENCY_MS": "100"}),
    ("asym", {"LATENCY_MS": "100", "ASYMMETRIC_LATENCY": "1"}),
]
_ATTACKS = [("withhold_baseline", "baseline"), ("fissure", "fissure"), ("withhold_silent", "silent")]
_ATTACKERS = [0, 1, 2, 3]


def _cfg(protocol: str, strategy: str, lat_env: dict, reps: int) -> schema.V2Config:
    env = {
        "NUM_NODES": str(N), "ATTACKER_RATIO": "0.308", "VICTIM_RATIO": "0.231",
        "GC_DEPTH": "10", "COLLECTION_DURATION": "45", "MIN_COMMITS": "20",
    }
    env.update(lat_env)
    raw: dict = {
        "protocol": {"name": protocol, "path": protocol},
        "environment": env,
        "adversary": {
            "threat_model": "TM-Solo",
            "topology": {"policies": [
                {"group_id": "g0", "members": _ATTACKERS, "family": "frontrun",
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
        env["V2_ALL_PAIRS_ASR"] = "1"
        raw["docker"] = {"tag": "mev-bullshark:latest", "cpus": "8.0", "memory": "16g"}
        raw["test"] = {"test_name": "test_fissure_attack_asr_dynamic", "REPETITIONS": 1}
    return sweeper.expand_policy_vector(schema.parse_config(raw))


def build_cells(protocol: str, reps: int = DEFAULT_REPS) -> list[benchmark.Cell]:
    launcher = (SuiLauncher(use_coordinator=False) if protocol == "sui"
                else BullsharkLauncher(local_mode=True, use_coordinator=False))
    cells = []
    for strategy, atag in _ATTACKS:
        for ltag, lenv in _LAT:
            cells.append(benchmark.Cell(
                name=f"{atag}_{ltag}",
                config=_cfg(protocol, strategy, lenv, reps),
                launcher=launcher,
            ))
    return cells


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="p_latency")
    parser.add_argument("--protocol", choices=("sui", "bullshark"), required=True)
    parser.add_argument("--out-csv", default=None)
    parser.add_argument("--out-summary", default=None)
    parser.add_argument("--reps", type=int, default=DEFAULT_REPS)
    args = parser.parse_args(list(argv) if argv is not None else None)

    pfx = "sui" if args.protocol == "sui" else "v2"
    out_csv = args.out_csv or f"results/{pfx}_latency_results.csv"
    out_summary = args.out_summary or f"results/{pfx}_latency_summary.json"
    csv_p = Path(out_csv)
    csv_p.parent.mkdir(parents=True, exist_ok=True)
    if csv_p.exists():
        csv_p.unlink()

    cells = build_cells(args.protocol, reps=args.reps)
    print(f"{args.protocol} DS14 WAN-latency: {len(cells)} cells × {args.reps} reps")
    summaries = benchmark.run_benchmark(
        cells=cells, out_csv=out_csv, out_summary_json=out_summary,
        reps=args.reps, progress_callback=lambda m: print(m, flush=True))
    print("\nAll-pairs ASR (LAN guardrail ~50% | WAN | asymmetric):")
    for name, s in summaries.items():
        am = f"{s.asr_median:.1f}%" if s.asr_median is not None else "n/a"
        print(f"  [{name:18s}] all-pairs_asr={am:>7}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
