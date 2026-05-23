"""Paper-1 reference manifest tests + contradiction-detection logic."""

import pytest

from scripts.v2 import baselines


def test_manifest_loads_with_required_blocks():
    # If the manifest file is malformed, _load_manifest raises at import.
    assert baselines._MANIFEST["_meta"]["protocol"] == "bullshark"
    assert "pure_baseline" in baselines._MANIFEST
    assert "frontrun_default_config_n13" in baselines._MANIFEST
    assert "backrun_cumulative_n13" in baselines._MANIFEST
    assert "sandwich_triplet_n13" in baselines._MANIFEST


def test_frontrun_reference_cells_present():
    for strat in ("fissure", "speculative", "sluggish"):
        ref = baselines.reference_cell("frontrun", strat, "asr")
        assert ref is not None
        assert 80.0 <= ref.median_pct <= 100.0


def test_backrun_l1_l2_le_cum():
    """Sanity property of the manifest itself: L1 <= L2 <= cumulative."""
    for strat in ("fissure", "speculative", "sluggish"):
        cum = baselines.reference_cell("backrun", strat, "cum_asr")
        l1 = baselines.reference_cell("backrun", strat, "asr_l1")
        l2 = baselines.reference_cell("backrun", strat, "asr_l2")
        assert l1.median_pct <= l2.median_pct + 1e-6
        assert l2.median_pct <= cum.median_pct + 1e-6


def test_check_against_paper1_within_tolerance_passes():
    ref = baselines.reference_cell("frontrun", "fissure", "asr")
    assert ref is not None
    findings = baselines.check_against_paper1(
        observed_median_pct=ref.median_pct + ref.tolerance_pp - 0.1,
        family="frontrun",
        strategy="fissure",
    )
    assert findings == []


def test_check_against_paper1_outside_tolerance_flags_contradiction():
    findings = baselines.check_against_paper1(
        observed_median_pct=40.0,  # way below paper-1's ~92%
        family="frontrun",
        strategy="fissure",
    )
    assert len(findings) == 1
    assert "CONTRADICTION" in findings[0]


def test_pure_baseline_check_within_range():
    findings = baselines.check_pure_baseline(observed_pct=51.0)
    assert findings == []


def test_pure_baseline_check_outside_range():
    findings = baselines.check_pure_baseline(observed_pct=30.0)
    assert len(findings) == 1
    assert "CONTRADICTION" in findings[0]


def test_unknown_cell_returns_skip_finding():
    findings = baselines.check_against_paper1(
        observed_median_pct=50.0,
        family="frontrun",
        strategy="fissure",
        metric="asr_l1",  # not defined for frontrun
    )
    assert len(findings) == 1
    assert "no paper-1 reference" in findings[0]
