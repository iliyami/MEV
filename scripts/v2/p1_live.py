"""P1 live exercise — 5-rep benchmark for the three v2 mechanisms.

Cells:

  1. **multipolicy** (TM-Compete): two distinct policies (frontrun/fissure on
     nodes 0,1 + frontrun/speculative on nodes 2,3). Marker extractor parses
     `v2 coordinator assigned policy ...` lines and asserts every Byzantine
     node's assignment matches the YAML.

  2. **victim_gen** (TM-Solo + multi_pareto victims): four-node homogeneous
     fissure attack with a Pareto victim_profile. Marker extractor counts
     V2_VICTIM_PROFIT lines and the number of unique profit values.

  3. **briber** (TM-Bribe): four-node homogeneous fissure attack with an
     effective-bribery budget. The on_coord_ready hook spawns a thread that
     publishes offers, decides, accepts, and settles concurrently with
     Bullshark. Marker extractor reads the briber ledger via the captured
     Coordinator metrics snapshot.

Each cell runs 5 reps (distributed-systems convention). Results land in:
    results/v2_p1_live_results.csv     -- 5 reps x 3 cells = 15 rows
    results/v2_p1_live_summary.json    -- per-cell mean/median/IQR/min/max
                                          plus paper-1 tolerance check
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import threading
import time
from pathlib import Path
from typing import Any, Iterable, Optional

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from scripts.v2 import baselines, benchmark, schema, sweeper
from scripts.v2.coordinator import CoordinatorServer
from scripts.v2.coordinator_client import CoordinatorClient


REPO_ROOT = Path(__file__).resolve().parent.parent.parent


# ---------------------------------------------------------------------------
# Cell configs
# ---------------------------------------------------------------------------


def _multipolicy_cfg() -> schema.V2Config:
    import yaml as _yaml
    with open(REPO_ROOT / "config" / "v2" / "p1_multipolicy_live.yaml") as fh:
        raw = _yaml.safe_load(fh)
    # Override reps via runtime.reps -- 5 (already in YAML); explicit for clarity.
    raw.setdefault("runtime", {})["reps"] = 5
    return sweeper.expand_policy_vector(schema.parse_config(raw))


def _victim_gen_cfg() -> schema.V2Config:
    raw = {
        "protocol": {"name": "bullshark", "path": "bullshark"},
        "docker": {"tag": "mev-bullshark:latest", "cpus": "8.0", "memory": "16g"},
        "test": {"test_name": "test_fissure_attack_asr_dynamic", "REPETITIONS": 1},
        "environment": {
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
        },
        "adversary": {
            "threat_model": "TM-Solo",
            "topology": {
                "policies": [
                    {
                        "group_id": "g0",
                        "members": [0, 1, 2, 3],
                        "family": "frontrun",
                        "strategy": "fissure",
                        "params": {},
                    }
                ]
            },
        },
        "victims": {
            "workload": "multi_pareto",
            "count": 3,
            "profit": {"distribution": "pareto", "params": {"shape": 1.16, "scale": 1.0}},
        },
        "runtime": {"reps": 5, "seed": 42},
    }
    return sweeper.expand_policy_vector(schema.parse_config(raw))


def _briber_cfg() -> schema.V2Config:
    raw = {
        "protocol": {"name": "bullshark", "path": "bullshark"},
        "docker": {"tag": "mev-bullshark:latest", "cpus": "8.0", "memory": "16g"},
        "test": {"test_name": "test_fissure_attack_asr_dynamic", "REPETITIONS": 1},
        "environment": {
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
        },
        "adversary": {
            "threat_model": "TM-Bribe",
            "topology": {
                "policies": [
                    {
                        "group_id": "g0",
                        "members": [0, 1, 2, 3],
                        "family": "frontrun",
                        "strategy": "fissure",
                        "params": {},
                    }
                ]
            },
            "bribery": {
                "enabled": True,
                "type": "effective",
                "settlement": "simulated",
                "budget": 100.0,
                "response_policy": "always_above_X",
                "response_policy_params": {"threshold": 6.0},
                "bribed_honest": [10, 12],
            },
        },
        "runtime": {"reps": 5, "seed": 7},
    }
    return sweeper.expand_policy_vector(schema.parse_config(raw))


# ---------------------------------------------------------------------------
# Marker extractors
# ---------------------------------------------------------------------------


_RE_POLICY_ASSIGN = re.compile(
    r"v2 coordinator assigned policy to node (\d+): "
    r"family=(\w+), strategy=(\w+), group=(\w+)"
)
_RE_HONEST = re.compile(
    r"v2 coordinator marked node (\d+) as honest \(no attacker policy\)"
)
_RE_VICTIM_PROFIT = re.compile(
    r"V2_VICTIM_PROFIT: round=(\d+) author=(\d+) profit=([\d.eE+-]+)"
)


def extract_multipolicy_markers(raw_output: str, run_result) -> dict[str, Any]:
    expected = {
        0: ("frontrun", "fissure", "g1"),
        1: ("frontrun", "fissure", "g1"),
        2: ("frontrun", "speculative", "g2"),
        3: ("frontrun", "speculative", "g2"),
    }
    found: dict[int, tuple[str, str, str]] = {}
    honest: set[int] = set()
    for line in raw_output.splitlines():
        m = _RE_POLICY_ASSIGN.search(line)
        if m:
            found[int(m.group(1))] = (m.group(2), m.group(3), m.group(4))
        m2 = _RE_HONEST.search(line)
        if m2:
            honest.add(int(m2.group(1)))
    all_byz_correct = all(found.get(n) == exp for n, exp in expected.items())
    all_honest_logged = honest == set(range(4, 13))
    return {
        "byz_assignments_correct": bool(all_byz_correct),
        "honest_markers_complete": bool(all_honest_logged),
        "n_byz_assignments_logged": len(found),
        "n_honest_markers_logged": len(honest),
    }


def extract_victim_gen_markers(raw_output: str, run_result) -> dict[str, Any]:
    profits: list[tuple[int, int, float]] = []
    for line in raw_output.splitlines():
        m = _RE_VICTIM_PROFIT.search(line)
        if m:
            profits.append((int(m.group(1)), int(m.group(2)), float(m.group(3))))
    unique_blocks = {(r, a) for (r, a, _) in profits}
    unique_profits = {p for (_, _, p) in profits}
    return {
        "victim_profit_markers": len(profits),
        "unique_victim_blocks": len(unique_blocks),
        "unique_profit_values": len(unique_profits),
        "max_profit_seen": max((p for (_, _, p) in profits), default=0.0),
    }


def extract_briber_markers(raw_output: str, run_result) -> dict[str, Any]:
    coord_metrics = run_result.metrics.get("coordinator_metrics") or {}
    ledger = coord_metrics.get("briber_ledger") or {}
    return {
        "briber_n_offers": ledger.get("n_offers", 0),
        "briber_n_acceptances": ledger.get("n_acceptances", 0),
        "briber_n_paid": ledger.get("n_paid", 0),
        "briber_n_released": ledger.get("n_released", 0),
        "briber_budget_paid": ledger.get("budget_paid", 0.0),
        "briber_budget_remaining": ledger.get("budget_remaining", 0.0),
    }


# ---------------------------------------------------------------------------
# Briber on_coord_ready hook
# ---------------------------------------------------------------------------


def _briber_lifecycle(coord_url: str) -> None:
    """One-shot briber lifecycle. Deterministic across reps."""
    client = CoordinatorClient(coord_url)
    # Same fixed payments each rep so the ledger is reproducible.
    offers_plan = [(10, 5.0), (10, 8.0), (12, 12.0)]
    offer_ids: list[tuple[str, int, float]] = []
    for node, payment in offers_plan:
        r = client.bribery_offer(
            recipient_node_id=node,
            infraction="omit_reference",
            target={"victim_node_id": 11, "round": 5},
            payment=payment,
        )
        offer_ids.append((r["offer_id"], node, payment))
    accepts: list[tuple[str, int]] = []
    for oid, node, _payment in offer_ids:
        decision = client.bribery_decide(offer_id=oid, node_id=node)
        if decision["accept"]:
            client.bribery_accept(
                offer_id=oid, node_id=node, evidence={"omitted_round": 5}
            )
            accepts.append((oid, node))
    # Effective: 1st accepted offer succeeds, the rest fail. Deterministic.
    for i, (oid, _node) in enumerate(accepts):
        client.bribery_settle(offer_id=oid, attack_succeeded=(i == 0))


def briber_on_coord_ready(
    coord: CoordinatorServer, cfg: schema.V2Config, rep: int
) -> threading.Thread:
    t = threading.Thread(
        target=_briber_lifecycle,
        args=(coord.url,),
        name=f"briber-lifecycle-rep{rep}",
        daemon=True,
    )
    t.start()
    return t


# ---------------------------------------------------------------------------
# Cells
# ---------------------------------------------------------------------------


def build_cells() -> list[benchmark.Cell]:
    return [
        benchmark.Cell(
            name="multipolicy",
            config=_multipolicy_cfg(),
            extra_columns=(
                "byz_assignments_correct",
                "honest_markers_complete",
                "n_byz_assignments_logged",
                "n_honest_markers_logged",
            ),
            marker_extractor=extract_multipolicy_markers,
            paper1_lookup=None,  # mixed-strategy cell has no direct paper-1 reference
        ),
        benchmark.Cell(
            name="victim_gen",
            config=_victim_gen_cfg(),
            extra_columns=(
                "victim_profit_markers",
                "unique_victim_blocks",
                "unique_profit_values",
                "max_profit_seen",
            ),
            marker_extractor=extract_victim_gen_markers,
            # TM-Solo frontrun/fissure: directly comparable to paper-1.
            paper1_lookup=benchmark.paper1_lookup_frontrun,
        ),
        benchmark.Cell(
            name="briber",
            config=_briber_cfg(),
            extra_columns=(
                "briber_n_offers",
                "briber_n_acceptances",
                "briber_n_paid",
                "briber_n_released",
                "briber_budget_paid",
                "briber_budget_remaining",
            ),
            marker_extractor=extract_briber_markers,
            paper1_lookup=benchmark.paper1_lookup_frontrun,
            on_coord_ready=briber_on_coord_ready,
        ),
    ]


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="p1_live")
    parser.add_argument("--out-csv", default="results/v2_p1_live_results.csv")
    parser.add_argument("--out-summary", default="results/v2_p1_live_summary.json")
    parser.add_argument(
        "--reps", type=int, default=None, help="override per-cell reps (default: from config)"
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    cells = build_cells()

    # Clean up any prior results CSV so a fresh run produces a clean file.
    csv_p = Path(args.out_csv)
    if csv_p.exists():
        csv_p.unlink()

    def log(msg: str) -> None:
        print(msg, flush=True)

    summaries = benchmark.run_benchmark(
        cells=cells,
        out_csv=args.out_csv,
        out_summary_json=args.out_summary,
        reps=args.reps,
        progress_callback=log,
    )

    print("\n=== P1 live benchmark summary ===")
    all_ok = True
    for name, s in summaries.items():
        ok_signals = []
        if s.paper1_within_tolerance is False:
            ok_signals.append("paper1_OUT_OF_TOLERANCE")
            all_ok = False
        if any(ec != 0 for ec in s.all_exit_codes):
            ok_signals.append(f"non_zero_exits={s.all_exit_codes}")
            all_ok = False
        median_s = f"{s.asr_median:.2f}%" if s.asr_median is not None else "N/A"
        mean_s = f"{s.asr_mean:.2f}%" if s.asr_mean is not None else "N/A"
        iqr_s = f"{s.asr_iqr:.2f}" if s.asr_iqr is not None else "N/A"
        print(
            f"  [{name:14s}] n={s.reps} mean={mean_s} median={median_s} "
            f"min={s.asr_min} max={s.asr_max} IQR={iqr_s} "
            f"paper1_ref={s.paper1_ref_median} within_tol={s.paper1_within_tolerance} "
            f"flags={ok_signals or 'OK'}"
        )
    print(f"\nCSV:     {args.out_csv}")
    print(f"Summary: {args.out_summary}")
    return 0 if all_ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
