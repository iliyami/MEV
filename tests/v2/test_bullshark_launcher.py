"""BullsharkLauncher unit tests.

These tests do not invoke the real Bullshark binary. They verify the v2 -> v1
translation, marker parsing, and TM-Solo enforcement using subprocess mocks.
End-to-end execution against the real Bullshark fork is exercised by the
spot-check script (scripts/v2/spotcheck_bullshark.py), which is run manually.
"""

from __future__ import annotations

import json
import subprocess
from unittest import mock

import pytest
import yaml as _yaml

from scripts.v2 import schema
from scripts.v2.launchers.bullshark import BullsharkLauncher
from scripts.v2.sweeper import RunRequest


def _make_cfg(family: str = "frontrun", strategy: str = "fissure") -> schema.V2Config:
    raw = {
        "protocol": {"name": "bullshark", "path": "bullshark"},
        "docker": {"tag": "mev-bullshark:latest", "cpus": "2.0", "memory": "4g"},
        "environment": {
            "ATTACK_MODE": strategy,
            "ATTACK_FAMILY": family,
            "DAG_STRATEGY": strategy,
            "NUM_NODES": "13",
            "ATTACKER_RATIO": "0.308",
            "VICTIM_RATIO": "0.231",
        },
        "adversary": {"threat_model": "TM-Solo", "archetype": "homogeneous"},
        "runtime": {"reps": 1, "seed": 0},
    }
    return schema.parse_config(raw)


def _request(cfg: schema.V2Config, rep: int = 0) -> RunRequest:
    return RunRequest(config=cfg, rep=rep, seed=0, run_id="testid01234567")


def _fake_completed(stdout: str, returncode: int = 0) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=[], returncode=returncode, stdout=stdout, stderr=""
    )


def test_accepts_tm_collude_now_that_p3_wires_it():
    """TM-Collude was deferred at P0/P1 with NotImplementedError; P3 lifts that gate."""
    raw = {
        "protocol": {"name": "bullshark"},
        "environment": {"NUM_NODES": "13"},
        "adversary": {
            "threat_model": "TM-Collude",
            "topology": {
                "policies": [
                    {"group_id": "g1", "members": [3, 5], "family": "frontrun", "strategy": "fissure"},
                ]
            },
            "coordination": {"enabled": True, "policy": "leader"},
        },
    }
    cfg = schema.parse_config(raw)
    launcher = BullsharkLauncher()
    # TM-Collude should now pass _validate_threat_model.
    launcher._validate_threat_model(cfg)  # does not raise


def test_rejects_multi_policy_without_coordinator():
    raw = {
        "protocol": {"name": "bullshark"},
        "environment": {"NUM_NODES": "13"},
        "adversary": {
            "threat_model": "TM-Solo",
            "topology": {
                "policies": [
                    {"group_id": "g1", "members": [3, 5], "family": "frontrun", "strategy": "fissure"},
                    {"group_id": "g2", "members": [7], "family": "backrun", "strategy": "sluggish"},
                ]
            },
        },
    }
    cfg = schema.parse_config(raw)
    # Force coordinator off; multi-policy then requires it.
    launcher = BullsharkLauncher(use_coordinator=False)
    with pytest.raises(NotImplementedError, match="single policy"):
        launcher.run(_request(cfg))


def test_v1_yaml_translation_sets_attack_mode_and_type():
    launcher = BullsharkLauncher()
    cfg = _make_cfg(family="backrun", strategy="sluggish")
    v1 = launcher._build_v1_yaml(cfg)
    assert v1["environment"]["ATTACK_MODE"] == "sluggish"
    assert v1["environment"]["ATTACK_TYPE"] == "backrun"
    assert v1["test"]["test_name"] == "test_sluggish_attack_asr_dynamic"
    assert v1["environment"]["NUM_NODES"] == "13"
    # raw environment keys preserved
    assert v1["environment"]["ATTACKER_RATIO"] == "0.308"


def test_v1_yaml_translation_preserves_docker_block():
    launcher = BullsharkLauncher()
    cfg = _make_cfg()
    v1 = launcher._build_v1_yaml(cfg)
    assert v1["docker"]["tag"] == "mev-bullshark:latest"


def test_v1_yaml_translation_for_all_strategies():
    launcher = BullsharkLauncher()
    for strat, expected_test in [
        ("fissure", "test_fissure_attack_asr_dynamic"),
        ("speculative", "test_speculative_attack_asr_dynamic"),
        ("sluggish", "test_sluggish_attack_asr_dynamic"),
    ]:
        cfg = _make_cfg(strategy=strat)
        v1 = launcher._build_v1_yaml(cfg)
        assert v1["test"]["test_name"] == expected_test
        assert v1["environment"]["ATTACK_MODE"] == strat


def test_parse_markers_extracts_frontrun_asr():
    output = "some logs\nFINAL_ASR_RESULT: 93.45%\nmore logs\n"
    metrics = BullsharkLauncher._parse_markers(output, "frontrun")
    assert metrics["asr"] == 93.45
    assert metrics["asr_l1"] is None
    assert metrics["asr_l2"] is None


def test_parse_markers_extracts_backrun_stats():
    output = (
        "FINAL_ASR_RESULT: 98.50\n"
        'FINAL_BACKRUN_STATS: {"l1_asr": 33.33, "l2_asr": 66.67, "histogram": {"1": 22, "2": 22, "3": 22}}\n'
    )
    metrics = BullsharkLauncher._parse_markers(output, "backrun")
    assert metrics["asr"] == 98.50
    assert metrics["asr_l1"] == 33.33
    assert metrics["asr_l2"] == 66.67
    assert '"1": 22' in metrics["asr_histogram"]


def test_parse_markers_prefers_sesr_for_sandwich():
    output = (
        "FINAL_ASR_RESULT: 50.00\n"
        'FINAL_SANDWICH_STATS: {"sesr": 81.82, "triplets": 11}\n'
    )
    metrics = BullsharkLauncher._parse_markers(output, "sandwich")
    assert metrics["asr"] == 81.82


def test_parse_markers_returns_none_on_missing():
    metrics = BullsharkLauncher._parse_markers("garbage output\n", "frontrun")
    assert metrics["asr"] is None


def test_parse_markers_uses_last_marker_when_multiple():
    output = "FINAL_ASR_RESULT: 10.00\nFINAL_ASR_RESULT: 92.30\n"
    metrics = BullsharkLauncher._parse_markers(output, "frontrun")
    assert metrics["asr"] == 92.30


def test_run_invokes_test_runner_and_parses_output(tmp_path):
    """End-to-end with mocked subprocess: launcher invokes test_runner, parses ASR, returns RunResult."""
    captured: dict = {}

    def fake_run(cmd, capture_output, text, cwd, timeout, check, env=None):
        # Verify command shape.
        assert cmd[0].endswith("python") or cmd[0].endswith("python3") or "python" in cmd[0]
        assert cmd[1].endswith("test_runner.py")
        temp_yaml = cmd[2]
        # The launcher should have written the temp yaml.
        with open(temp_yaml) as fh:
            v1 = _yaml.safe_load(fh)
        captured["yaml"] = v1
        captured["cmd"] = cmd
        return _fake_completed("FINAL_ASR_RESULT: 92.30\n", returncode=0)

    launcher = BullsharkLauncher(local_mode=True)
    cfg = _make_cfg(family="frontrun", strategy="fissure")

    with mock.patch("scripts.v2.launchers.bullshark.subprocess.run", side_effect=fake_run):
        result = launcher.run(_request(cfg))

    assert result.exit_code == 0
    assert result.metrics["asr"] == 92.30
    # --local flag forwarded
    assert "--local" in captured["cmd"]
    # YAML carries the expected translation
    assert captured["yaml"]["environment"]["ATTACK_MODE"] == "fissure"
    assert captured["yaml"]["environment"]["ATTACK_TYPE"] == "frontrun"
    assert captured["yaml"]["test"]["test_name"] == "test_fissure_attack_asr_dynamic"


def test_run_handles_timeout_gracefully():
    launcher = BullsharkLauncher()
    cfg = _make_cfg()

    def fake_run(cmd, **kwargs):
        _ = kwargs  # accept env=, capture_output=, etc.
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=1, output="partial\n")

    with mock.patch("scripts.v2.launchers.bullshark.subprocess.run", side_effect=fake_run):
        result = launcher.run(_request(cfg))
    assert result.exit_code == -124  # timeout marker
    assert result.metrics["asr"] is None
