"""Tests for the per-policy ASR computation added in v3 R-P2.1."""

import pytest

from scripts.v2 import schema
from scripts.v2.launchers.bullshark import _compute_per_policy_asr, _grep_last_json_array


def _cfg(policies, n=13, victim_ratio="0.231", family="frontrun", strategy="fissure"):
    raw = {
        "protocol": {"name": "bullshark", "path": "bullshark"},
        "environment": {
            "NUM_NODES": str(n),
            "VICTIM_RATIO": victim_ratio,
            "ATTACK_MODE": strategy,
            "ATTACK_TYPE": family,
        },
        "adversary": {
            "threat_model": "TM-Compete" if len(policies) > 1 else "TM-Solo",
            "topology": {"policies": policies},
        },
        "runtime": {"reps": 1, "seed": 0},
    }
    return schema.parse_config(raw)


def test_grep_last_json_array_basic():
    out = "some noise\nFINAL_COMMITTED_ORDER: [{\"creator\":1,\"position\":0,\"round\":2}]\nmore\n"
    parsed = _grep_last_json_array("FINAL_COMMITTED_ORDER:", out)
    assert parsed == [{"creator": 1, "position": 0, "round": 2}]


def test_grep_last_json_array_returns_none_when_missing():
    assert _grep_last_json_array("FINAL_COMMITTED_ORDER:", "no marker here\n") is None


def test_grep_last_json_array_uses_last_when_multiple():
    out = (
        "FINAL_COMMITTED_ORDER: [{\"creator\":0,\"position\":0,\"round\":1}]\n"
        "FINAL_COMMITTED_ORDER: [{\"creator\":2,\"position\":3,\"round\":5}]\n"
    )
    parsed = _grep_last_json_array("FINAL_COMMITTED_ORDER:", out)
    assert parsed == [{"creator": 2, "position": 3, "round": 5}]


def test_per_policy_asr_simple_single_policy():
    """One Byzantine group (nodes 0,1); single victim node 10. Build a tiny order
    where the attacker block is always before the victim block.
    """
    cfg = _cfg(
        policies=[
            {
                "group_id": "g0",
                "members": [0, 1, 2, 3],
                "family": "frontrun",
                "strategy": "fissure",
                "params": {},
            }
        ],
        n=13,
        victim_ratio="0.0769",  # 13 * 0.0769 ≈ 1 victim
    )
    # Victim set: nodes [12, 13) = {12}
    order = [
        {"creator": 0, "position": 0, "round": 1},
        {"creator": 12, "position": 1, "round": 1},
        {"creator": 1, "position": 2, "round": 2},
        {"creator": 12, "position": 3, "round": 2},
    ]
    out = _compute_per_policy_asr(order, cfg)
    # Both rounds: attacker before victim → ASR = 100%
    assert out["g0"] == 100.0


def test_per_policy_asr_two_groups_different_outcomes():
    cfg = _cfg(
        policies=[
            {
                "group_id": "g0",
                "members": [0, 1],
                "family": "frontrun",
                "strategy": "fissure",
                "params": {},
            },
            {
                "group_id": "g1",
                "members": [2, 3],
                "family": "frontrun",
                "strategy": "speculative",
                "params": {},
            },
        ],
        n=13,
        victim_ratio="0.0769",  # 1 victim at index 12
    )
    order = [
        # round 1: g0 attacker before victim, g1 attacker after victim → g0 wins, g1 loses
        {"creator": 0, "position": 0, "round": 1},
        {"creator": 12, "position": 1, "round": 1},
        {"creator": 2, "position": 2, "round": 1},
        # round 2: same pattern → reinforces
        {"creator": 1, "position": 3, "round": 2},
        {"creator": 12, "position": 4, "round": 2},
        {"creator": 3, "position": 5, "round": 2},
    ]
    out = _compute_per_policy_asr(order, cfg)
    assert out["g0"] == 100.0  # both g0 attackers before victim
    assert out["g1"] == 0.0  # both g1 attackers after victim


def test_per_policy_asr_no_comparable_pairs():
    cfg = _cfg(
        policies=[
            {
                "group_id": "g0",
                "members": [0],
                "family": "frontrun",
                "strategy": "fissure",
                "params": {},
            }
        ],
        n=13,
        victim_ratio="0.0769",
    )
    # Victim in round 1; attacker in round 2; not same-round → not comparable
    order = [
        {"creator": 12, "position": 0, "round": 1},
        {"creator": 0, "position": 1, "round": 2},
    ]
    out = _compute_per_policy_asr(order, cfg)
    assert out["g0"] is None  # no comparable pairs


def test_per_policy_asr_backrun_success_after_victim():
    """v3 R-P2.2: backrun family success = attacker.position > victim.position."""
    cfg = _cfg(
        policies=[
            {
                "group_id": "g0",
                "members": [0, 1],
                "family": "backrun",
                "strategy": "fissure",
                "params": {},
            }
        ],
        family="backrun",
        n=13,
        victim_ratio="0.0769",  # 1 victim at index 12
    )
    order = [
        # round 1: attacker AFTER victim → backrun success
        {"creator": 12, "position": 0, "round": 1},
        {"creator": 0, "position": 1, "round": 1},
        # round 2: attacker BEFORE victim → backrun fail
        {"creator": 1, "position": 2, "round": 2},
        {"creator": 12, "position": 3, "round": 2},
    ]
    out = _compute_per_policy_asr(order, cfg)
    assert out["g0"] == 50.0  # 1 success / 2 comparable


def test_per_policy_asr_canonical_victim_set():
    """v3 R-P2.2: victims.victim_node_ids overrides the layout-derived set."""
    from scripts.v2 import sweeper
    raw = {
        "protocol": {"name": "bullshark"},
        "environment": {
            "NUM_NODES": "13",
            "VICTIM_RATIO": "0.231",  # would imply victims at [10,11,12]
            "ATTACK_MODE": "fissure",
            "ATTACK_TYPE": "frontrun",
        },
        "adversary": {
            "threat_model": "TM-Compete",
            "topology": {
                "policies": [
                    {"group_id": "g0", "members": [0, 1], "family": "frontrun",
                     "strategy": "fissure"},
                ]
            },
        },
        "victims": {
            "workload": "multi_pareto",
            "count": 1,
            "victim_node_ids": [7, 8],  # override: victims at {7, 8}
        },
        "runtime": {"reps": 1, "seed": 0},
    }
    cfg = sweeper.expand_policy_vector(schema.parse_config(raw))
    order = [
        # Attacker before node 7 (canonical victim) → success
        {"creator": 0, "position": 0, "round": 1},
        {"creator": 7, "position": 1, "round": 1},
        # Attacker before node 12 (NOT canonical victim) → not comparable
        {"creator": 1, "position": 2, "round": 2},
        {"creator": 12, "position": 3, "round": 2},
    ]
    out = _compute_per_policy_asr(order, cfg)
    # Only 1 comparable pair (round 1 vs node 7); attacker wins
    assert out["g0"] == 100.0


def test_per_policy_asr_mixed_families_compute_each_family_separately():
    """v3 R-P2.2: two policies with different families both get per-family ASRs."""
    from scripts.v2 import sweeper
    raw = {
        "protocol": {"name": "bullshark"},
        "environment": {"NUM_NODES": "13", "VICTIM_RATIO": "0.0769",
                         "ATTACK_MODE": "fissure", "ATTACK_TYPE": "frontrun"},
        "adversary": {
            "threat_model": "TM-Compete",
            "topology": {
                "policies": [
                    {"group_id": "g_front", "members": [0, 1], "family": "frontrun",
                     "strategy": "fissure"},
                    {"group_id": "g_back", "members": [2, 3], "family": "backrun",
                     "strategy": "fissure"},
                ]
            },
        },
        "victims": {"workload": "multi_pareto", "count": 1, "victim_node_ids": [12]},
        "runtime": {"reps": 1, "seed": 0},
    }
    cfg = sweeper.expand_policy_vector(schema.parse_config(raw))
    order = [
        # round 1: front attacker before victim (frontrun success);
        # back attacker before victim (backrun FAIL — needs AFTER)
        {"creator": 0, "position": 0, "round": 1},
        {"creator": 2, "position": 1, "round": 1},
        {"creator": 12, "position": 2, "round": 1},
        # round 2: front attacker after victim (frontrun FAIL);
        # back attacker after victim (backrun success)
        {"creator": 12, "position": 3, "round": 2},
        {"creator": 1, "position": 4, "round": 2},
        {"creator": 3, "position": 5, "round": 2},
    ]
    out = _compute_per_policy_asr(order, cfg)
    # g_front: round 1 success (0<2), round 2 fail (4>3) → 50%
    # g_back: round 1 fail (1<2), round 2 success (5>3) → 50%
    # Note: comparable pairs are per-attacker, both groups have 2 attackers
    # round 1: g_front has 2 attackers vs 1 victim = 2 pairs, both same logic
    # Wait, this is more subtle. Let me trace:
    # g_front members = [0, 1]. Attackers in order: node 0 round 1, node 1 round 2.
    #   For node 0 round 1: victim node 12 round 1 → frontrun: 0 < 2 = TRUE
    #   For node 1 round 2: victim node 12 round 2 → frontrun: 4 < 3 = FALSE
    #   → 1 success / 2 comparable = 50%
    # g_back members = [2, 3]. Attackers in order: node 2 round 1, node 3 round 2.
    #   For node 2 round 1: victim node 12 round 1 → backrun: 1 > 2 = FALSE
    #   For node 3 round 2: victim node 12 round 2 → backrun: 5 > 3 = TRUE
    #   → 1 success / 2 comparable = 50%
    assert out["g_front"] == 50.0
    assert out["g_back"] == 50.0


def test_per_policy_asr_empty_committed_order():
    cfg = _cfg(
        policies=[
            {
                "group_id": "g0",
                "members": [0],
                "family": "frontrun",
                "strategy": "fissure",
                "params": {},
            }
        ]
    )
    out = _compute_per_policy_asr([], cfg)
    assert out["g0"] is None


def test_per_policy_asr_skips_malformed_records():
    """A malformed record (missing or non-int fields) must not KeyError; it's silently skipped."""
    cfg = _cfg(
        policies=[
            {
                "group_id": "g0",
                "members": [0],
                "family": "frontrun",
                "strategy": "fissure",
                "params": {},
            }
        ],
        n=13,
        victim_ratio="0.0769",
    )
    order = [
        {"creator": 0, "position": 0, "round": 1},
        {"creator": 12, "position": 1, "round": 1},
        # Malformed entries below — should be silently skipped:
        {"creator": "not_an_int"},
        {"position": "missing-creator", "round": "x"},
        {"creator": 0},  # missing position/round
        None,
    ]
    # Should not raise, should still compute the well-formed pair.
    out = _compute_per_policy_asr(order, cfg)
    assert out["g0"] == 100.0


def test_parse_markers_with_no_committed_order_returns_none():
    """When the FINAL_COMMITTED_ORDER marker is absent (e.g. older Rust build,
    a crashed run, etc.), the launcher must still parse the other markers
    cleanly and return committed_order=None."""
    from scripts.v2.launchers.bullshark import BullsharkLauncher
    output = "Some logs\nFINAL_ASR_RESULT: 92.30%\nDone\n"
    metrics = BullsharkLauncher._parse_markers(output, "frontrun")
    assert metrics["asr"] == 92.30
    assert metrics["committed_order"] is None
    assert metrics["per_policy_asr"] is None  # not populated without committed_order


def test_parse_markers_with_committed_order_extracts_records():
    from scripts.v2.launchers.bullshark import BullsharkLauncher
    output = (
        "FINAL_ASR_RESULT: 92.30%\n"
        'FINAL_COMMITTED_ORDER: [{"creator":0,"position":0,"round":1},'
        '{"creator":12,"position":1,"round":1}]\n'
    )
    metrics = BullsharkLauncher._parse_markers(output, "frontrun")
    assert metrics["committed_order"] == [
        {"creator": 0, "position": 0, "round": 1},
        {"creator": 12, "position": 1, "round": 1},
    ]
