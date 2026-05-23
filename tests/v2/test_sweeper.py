"""End-to-end sweeper smoke tests using the StubLauncher.

These tests verify the orchestration end-to-end without touching any protocol
fork (P0 invariant). They drive the v2 YAML through schema validation, policy
materialization, auditor checks, launcher dispatch, and CSV write.
"""

import csv
from pathlib import Path

import pytest

from scripts.v2 import sweeper


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SOLO_CFG = REPO_ROOT / "config" / "v2" / "sample_tm_solo_bullshark.yaml"
COMPETE_CFG = REPO_ROOT / "config" / "v2" / "sample_tm_compete_bullshark.yaml"


def test_tm_solo_sample_config_runs_end_to_end(tmp_path):
    out = tmp_path / "out.csv"
    results = sweeper.run_config(
        config_path=str(SOLO_CFG),
        out_csv=str(out),
        launcher=sweeper.StubLauncher(),
        static_auditor=None,
    )
    assert len(results) == 5  # default reps per the v2 sample config
    with open(out) as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 5
    assert all(r["protocol"] == "bullshark" for r in rows)
    assert all(r["threat_model"] == "TM-Solo" for r in rows)
    assert all(r["archetype"] == "homogeneous" for r in rows)
    assert all(r["num_policies"] == "1" for r in rows)
    # Stub launcher returns ASR around 95 for Bullshark frontrun cells.
    asrs = [float(r["asr"]) for r in rows]
    assert min(asrs) > 90.0


def test_tm_compete_sample_config_materializes_two_groups(tmp_path):
    out = tmp_path / "out.csv"
    results = sweeper.run_config(
        config_path=str(COMPETE_CFG),
        out_csv=str(out),
        launcher=sweeper.StubLauncher(),
        static_auditor=None,
    )
    assert len(results) == 5
    with open(out) as f:
        rows = list(csv.DictReader(f))
    assert all(r["threat_model"] == "TM-Compete" for r in rows)
    assert all(r["num_policies"] == "2" for r in rows)
    # Per-policy ASRs recorded
    import json as _json
    for r in rows:
        per_policy = _json.loads(r["per_policy_asr_json"])
        assert set(per_policy.keys()) == {"g1", "g2"}


def test_dry_run_does_not_write_csv(tmp_path):
    out = tmp_path / "out.csv"
    results = sweeper.run_config(
        config_path=str(SOLO_CFG),
        out_csv=str(out),
        launcher=sweeper.StubLauncher(),
        static_auditor=None,
        dry_run=True,
    )
    assert results == []
    assert not out.exists()


def test_make_run_id_deterministic():
    from scripts.v2 import schema
    raw = {
        "protocol": {"name": "bullshark"},
        "environment": {"NUM_NODES": "13"},
        "adversary": {"threat_model": "TM-Solo", "archetype": "homogeneous"},
    }
    cfg = schema.parse_config(raw)
    id1 = sweeper.make_run_id(cfg, rep=0)
    id2 = sweeper.make_run_id(cfg, rep=0)
    id3 = sweeper.make_run_id(cfg, rep=1)
    assert id1 == id2
    assert id1 != id3
