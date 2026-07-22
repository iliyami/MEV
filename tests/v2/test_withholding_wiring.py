"""Wiring tests for the DS4/DS5 withholding cells (silent-except-leader + SLW).

These lock the Python side of the port: schema acceptance of the new strategy
labels (without polluting the competition archetype set), both launchers'
strategy->test mapping, the Sui ATTACK_MODE translation, and the phase drivers'
cell isolation. They do NOT run cargo — the Rust behaviour is covered by
withholding_attack_test.rs in each fork.
"""

from __future__ import annotations

import pytest

from scripts.v2 import schema, p_withholding, p_sui_withholding
from scripts.v2.launchers.bullshark import _BULLSHARK_TEST_NAMES
from scripts.v2.launchers.sui import _SUI_TEST_NAMES, _SUI_ATTACK_MODE

_WITHHOLDING = ("withhold_baseline", "withhold_silent", "slw")


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


def test_schema_accepts_withholding_strategies():
    for s in _WITHHOLDING:
        assert s in schema.ALL_STRATEGIES


def test_competition_archetype_set_not_polluted():
    # policy.py rotates DAG_STRATEGIES to build competition splits; it must keep
    # seeing exactly the three core strategies so other experiments are unchanged.
    assert schema.DAG_STRATEGIES == ("fissure", "speculative", "sluggish")
    for s in _WITHHOLDING:
        assert s not in schema.DAG_STRATEGIES


@pytest.mark.parametrize("strategy", _WITHHOLDING)
def test_policy_strategy_parses(strategy):
    cfg = p_sui_withholding._cfg(strategy, 2)
    assert cfg.dag_strategy == strategy
    assert cfg.attack_family == "frontrun"
    assert cfg.adversary.threat_model == "TM-Solo"


def test_unknown_strategy_still_rejected():
    with pytest.raises(schema.SchemaError):
        p_sui_withholding._cfg("wormhole", 2)


# ---------------------------------------------------------------------------
# Launcher mapping
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("strategy", _WITHHOLDING)
def test_both_launchers_map_every_withholding_strategy(strategy):
    assert strategy in _BULLSHARK_TEST_NAMES
    assert strategy in _SUI_TEST_NAMES
    # Bullshark tests are bare fn names; Sui tests are module::fn paths.
    assert _BULLSHARK_TEST_NAMES[strategy].startswith("test_")
    assert _SUI_TEST_NAMES[strategy].startswith("withholding_attack_test::")


def test_sui_attack_mode_translation():
    # Only DS5 differs: bare "slw" is not a Sui-recognized ATTACK_MODE.
    assert _SUI_ATTACK_MODE.get("slw") == "mysticeti_slw"
    assert _SUI_ATTACK_MODE.get("withhold_silent", "withhold_silent") == "withhold_silent"
    assert _SUI_ATTACK_MODE.get("withhold_baseline", "withhold_baseline") == "withhold_baseline"


@pytest.mark.parametrize("strategy", _WITHHOLDING)
def test_bullshark_v1_yaml_sets_test_and_attack_mode(strategy):
    v1 = p_withholding._LAUNCHER._build_v1_yaml(p_withholding._cfg(strategy, 2))
    assert v1["test"]["test_name"] == _BULLSHARK_TEST_NAMES[strategy]
    assert v1["environment"]["ATTACK_MODE"] == strategy
    assert v1["environment"]["ATTACK_TYPE"] == "frontrun"


# ---------------------------------------------------------------------------
# Phase drivers — cell isolation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("driver", [p_withholding, p_sui_withholding])
def test_driver_builds_three_isolated_solo_cells(driver):
    cells = driver.build_cells(reps=2)
    assert [c.name for c in cells] == ["withhold_baseline", "silent_except_leader", "slw"]
    strategies = {c.config.dag_strategy for c in cells}
    assert strategies == {"withhold_baseline", "withhold_silent", "slw"}
    for c in cells:
        # Exactly one attacker policy (single group) — TM-Solo, isolated.
        assert c.config.adversary.threat_model == "TM-Solo"
        assert len(c.config.adversary.policies) == 1
        assert c.config.num_nodes == 13
