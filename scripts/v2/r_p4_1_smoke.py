"""R-P4.1 verification smoke.

Runs two Bullshark cells:

    cell A (control)    -- no bribery; paper-1 honest behaviour
    cell B (bribed)     -- 2 honest nodes bribed (always-accept offers
                            with infraction=omit_reference); each is
                            asked to omit references from victim node 12.

Verifies:

  1. cell A emits ZERO V2_HONEST_ACCEPT markers (hook silent without bribery).
  2. cell B emits AT LEAST ONE V2_HONEST_ACCEPT marker (hook fires).
  3. cell B emits at least one V2_HONEST_OMIT marker (the infraction
     was actually applied, not just accepted).
  4. The two cells' aggregate ASRs are reported (no specific direction
     asserted — bribery's ASR effect is the campaign question, not the
     smoke question).
"""

from __future__ import annotations

import re
import sys
import threading
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from scripts.v2 import benchmark, schema, sweeper
from scripts.v2.coordinator import CoordinatorServer
from scripts.v2.coordinator_client import CoordinatorClient


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


def _cfg_control(reps: int = 3) -> schema.V2Config:
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
                        "params": {},
                    }
                ]
            },
        },
        "victims": {"workload": "single", "count": 1},
        "runtime": {"reps": reps, "seed": 0},
    }
    return sweeper.expand_policy_vector(schema.parse_config(raw))


def _cfg_bribed(reps: int = 3) -> schema.V2Config:
    raw = {
        "protocol": {"name": "bullshark", "path": "bullshark"},
        "docker": {"tag": "mev-bullshark:latest", "cpus": "8.0", "memory": "16g"},
        "test": {"test_name": "test_fissure_attack_asr_dynamic", "REPETITIONS": 1},
        "environment": dict(_BASE_ENV),
        "adversary": {
            "threat_model": "TM-Bribe",
            "archetype": "homogeneous",
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
                "type": "guided",
                "settlement": "simulated",
                "budget": 100.0,
                "response_policy": "always_above_X",
                "response_policy_params": {"threshold": 0.0},
                "bribed_honest": [10, 12],
            },
        },
        "victims": {"workload": "single", "count": 1},
        "runtime": {"reps": reps, "seed": 0},
    }
    return sweeper.expand_policy_vector(schema.parse_config(raw))


_RE_ACCEPT = re.compile(r"V2_HONEST_ACCEPT: node=(\d+) offer_id=(\w+)")
_RE_OMIT = re.compile(r"V2_HONEST_OMIT: node=(\d+) target_victim_id=(\d+) removed=(\d+)")


def _publish_offers(coord: CoordinatorServer, cfg: schema.V2Config, rep: int) -> None:
    """on_coord_ready hook: pre-publish omit_reference offers for the
    bribed-honest set, then wait briefly so that Bullshark sees them."""
    client = CoordinatorClient(coord.url)
    for node in cfg.adversary.bribery.bribed_honest:
        client.bribery_offer(
            recipient_node_id=node,
            infraction="omit_reference",
            target={"target_victim_id": 12},  # victim node id
            payment=10.0,
        )
    # Note: This is synchronous — no thread spawned; offers are visible
    # immediately when Bullshark starts.


def _extract_bribery_markers(raw_output: str, run_result) -> dict:
    accepts = list(_RE_ACCEPT.finditer(raw_output))
    omits = list(_RE_OMIT.finditer(raw_output))
    return {
        "honest_accept_markers": len(accepts),
        "honest_omit_markers": len(omits),
        "unique_accepting_nodes": len({m.group(1) for m in accepts}),
        "total_references_omitted": sum(int(m.group(3)) for m in omits),
    }


def main() -> int:
    out_csv = "results/r_p4_1_smoke.csv"
    out_summary = "results/r_p4_1_smoke_summary.json"
    Path(out_csv).unlink(missing_ok=True)

    cells = [
        benchmark.Cell(
            name="A_control_no_bribery",
            config=_cfg_control(),
            extra_columns=(
                "honest_accept_markers",
                "honest_omit_markers",
                "unique_accepting_nodes",
                "total_references_omitted",
            ),
            marker_extractor=_extract_bribery_markers,
        ),
        benchmark.Cell(
            name="B_bribed_2nodes",
            config=_cfg_bribed(),
            extra_columns=(
                "honest_accept_markers",
                "honest_omit_markers",
                "unique_accepting_nodes",
                "total_references_omitted",
            ),
            marker_extractor=_extract_bribery_markers,
            on_coord_ready=_publish_offers,
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

    a = summaries["A_control_no_bribery"]
    b = summaries["B_bribed_2nodes"]
    a_accepts = a.extras_aggregated.get("honest_accept_markers", {}).get("raw", [])
    b_accepts = b.extras_aggregated.get("honest_accept_markers", {}).get("raw", [])
    b_omits = b.extras_aggregated.get("honest_omit_markers", {}).get("raw", [])

    print("\n--- R-P4.1 smoke verdict ---")
    print(f"  cell A control  median ASR = {a.asr_median} accept_markers = {a_accepts}")
    print(f"  cell B bribed   median ASR = {b.asr_median} accept_markers = {b_accepts}  omit_markers = {b_omits}")

    failures: list[str] = []

    # (1) cell A must have ZERO accept markers (hook silent).
    if any(int(n) > 0 for n in a_accepts):
        failures.append(
            f"FAIL: cell A (no bribery) emitted V2_HONEST_ACCEPT markers ({a_accepts}); "
            f"hook should be silent without bribery."
        )

    # (2) cell B must have AT LEAST ONE accept marker across reps.
    if not any(int(n) > 0 for n in b_accepts):
        failures.append(
            f"FAIL: cell B (bribery enabled) emitted no V2_HONEST_ACCEPT markers; "
            f"hook did not fire. Possible causes: V2_BRIBED_HONEST not exported, "
            f"offers not published, response policy rejecting all, "
            f"or the hook isn't being called."
        )

    # (3) cell B must apply the omit_reference infraction at least once.
    if not any(int(n) > 0 for n in b_omits):
        failures.append(
            f"FAIL: cell B emitted no V2_HONEST_OMIT markers; the omit_reference "
            f"infraction was accepted but not applied."
        )

    if failures:
        for f in failures:
            print(f"  {f}")
        print("\nR-P4.1 SMOKE: FAILED")
        return 2
    print("\nR-P4.1 SMOKE: PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
