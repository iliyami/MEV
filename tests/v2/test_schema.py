"""Schema validation tests for the v2 YAML format."""

import pytest

from scripts.v2 import schema


def test_paper1_minimal_config_parses_as_tm_solo():
    """A paper-1-style YAML with no adversary/victims block resolves to TM-Solo."""
    raw = {
        "protocol": {"name": "bullshark"},
        "environment": {
            "ATTACK_MODE": "fissure",
            "NUM_NODES": "13",
            "ATTACKER_RATIO": "0.308",
        },
    }
    cfg = schema.parse_config(raw)
    assert cfg.protocol == "bullshark"
    assert cfg.num_nodes == 13
    assert cfg.adversary.threat_model == "TM-Solo"
    assert cfg.adversary.policies == ()
    assert cfg.adversary.coordination.enabled is False
    assert cfg.adversary.bribery.enabled is False
    assert cfg.victims.workload == "single"
    assert cfg.victims.count == 1


def test_tm_compete_with_multiple_policies():
    raw = {
        "protocol": {"name": "bullshark"},
        "environment": {"NUM_NODES": "13"},
        "adversary": {
            "threat_model": "TM-Compete",
            "topology": {
                "policies": [
                    {
                        "group_id": "g1",
                        "members": [3, 5],
                        "family": "frontrun",
                        "strategy": "fissure",
                    },
                    {
                        "group_id": "g2",
                        "members": [7],
                        "family": "backrun",
                        "strategy": "sluggish",
                    },
                ]
            },
        },
    }
    cfg = schema.parse_config(raw)
    assert cfg.adversary.threat_model == "TM-Compete"
    assert len(cfg.adversary.policies) == 2
    assert cfg.adversary.policies[0].family == "frontrun"
    assert cfg.adversary.policies[1].strategy == "sluggish"
    # Global family/strategy default to the first policy's
    assert cfg.attack_family == "frontrun"
    assert cfg.dag_strategy == "fissure"


def test_tm_collude_requires_coordination_enabled():
    raw = {
        "protocol": {"name": "bullshark"},
        "environment": {"NUM_NODES": "13"},
        "adversary": {
            "threat_model": "TM-Collude",
            "topology": {
                "policies": [
                    {
                        "group_id": "g1",
                        "members": [3, 5, 7, 9],
                        "family": "frontrun",
                        "strategy": "fissure",
                    }
                ]
            },
            "coordination": {"enabled": False},
        },
    }
    with pytest.raises(schema.SchemaError, match="TM-Collude"):
        schema.parse_config(raw)


def test_coordination_enabled_outside_collude_is_rejected():
    raw = {
        "protocol": {"name": "bullshark"},
        "environment": {"NUM_NODES": "13"},
        "adversary": {
            "threat_model": "TM-Solo",
            "coordination": {"enabled": True, "policy": "leader"},
        },
    }
    with pytest.raises(schema.SchemaError):
        schema.parse_config(raw)


def test_bribery_enabled_outside_bribe_is_rejected():
    raw = {
        "protocol": {"name": "bullshark"},
        "environment": {"NUM_NODES": "13"},
        "adversary": {
            "threat_model": "TM-Solo",
            "bribery": {"enabled": True, "type": "guided"},
        },
    }
    with pytest.raises(schema.SchemaError):
        schema.parse_config(raw)


def test_invalid_family_rejected_with_path():
    raw = {
        "protocol": {"name": "bullshark"},
        "environment": {"NUM_NODES": "13"},
        "adversary": {
            "threat_model": "TM-Compete",
            "topology": {
                "policies": [
                    {
                        "group_id": "g1",
                        "members": [3],
                        "family": "not_a_family",
                        "strategy": "fissure",
                    }
                ]
            },
        },
    }
    with pytest.raises(schema.SchemaError, match="family"):
        schema.parse_config(raw)


def test_victims_single_with_count_mismatch_rejected():
    raw = {
        "protocol": {"name": "bullshark"},
        "environment": {"NUM_NODES": "13"},
        "victims": {"workload": "single", "count": 3},
    }
    with pytest.raises(schema.SchemaError):
        schema.parse_config(raw)


def test_runtime_defaults():
    raw = {"protocol": {"name": "bullshark"}, "environment": {"NUM_NODES": "13"}}
    cfg = schema.parse_config(raw)
    assert cfg.runtime.reps == 5  # field convention
    assert cfg.runtime.invariant_audit is True
