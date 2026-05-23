"""Tests for the small statistics module.

Where possible, expected values are textbook examples or hand-computed
on small inputs.
"""

import math

import pytest

from scripts.v2 import stats


# ---------------------------------------------------------------------------
# rankdata
# ---------------------------------------------------------------------------


def test_rankdata_no_ties():
    assert stats._rankdata([10.0, 5.0, 20.0, 15.0]) == [2.0, 1.0, 4.0, 3.0]


def test_rankdata_with_ties_uses_average():
    # values: [10, 10, 20]; tied 10s get rank (1+2)/2 = 1.5
    assert stats._rankdata([10.0, 10.0, 20.0]) == [1.5, 1.5, 3.0]


# ---------------------------------------------------------------------------
# Mann-Whitney U
# ---------------------------------------------------------------------------


def test_mann_whitney_identical_distributions_high_p():
    """Identical samples → U is at the mean → p close to 1."""
    x = [1.0, 2.0, 3.0, 4.0, 5.0]
    y = [1.0, 2.0, 3.0, 4.0, 5.0]
    res = stats.mann_whitney_u(x, y)
    assert res["u_min"] == pytest.approx(12.5, abs=0.1)
    assert res["p_two_sided"] > 0.5  # cannot reject H0


def test_mann_whitney_clear_separation_low_p():
    """x clearly larger than y → small p."""
    x = [10.0, 11.0, 12.0, 13.0, 14.0]
    y = [1.0, 2.0, 3.0, 4.0, 5.0]
    res = stats.mann_whitney_u(x, y)
    # U_min = 0 (every x beats every y)
    assert res["u_min"] == 0.0
    assert res["p_two_sided"] < 0.05


def test_mann_whitney_u_x_plus_u_y_equals_n1_n2():
    x = [1.0, 3.0, 5.0, 7.0]
    y = [2.0, 4.0, 6.0]
    res = stats.mann_whitney_u(x, y)
    assert res["u_x"] + res["u_y"] == pytest.approx(len(x) * len(y))


def test_mann_whitney_empty_rejected():
    with pytest.raises(ValueError):
        stats.mann_whitney_u([], [1.0])


# ---------------------------------------------------------------------------
# Cliff's delta
# ---------------------------------------------------------------------------


def test_cliff_delta_all_greater():
    x = [10, 11, 12]
    y = [1, 2, 3]
    assert stats.cliff_delta(x, y) == 1.0


def test_cliff_delta_all_less():
    x = [1, 2, 3]
    y = [10, 11, 12]
    assert stats.cliff_delta(x, y) == -1.0


def test_cliff_delta_identical_zero():
    x = [1, 2, 3]
    y = [1, 2, 3]
    # Each value matches one in the other sample (ties), the rest split 50/50
    assert stats.cliff_delta(x, y) == 0.0


def test_cliff_delta_partial_overlap():
    # x = [3, 4, 5], y = [1, 2, 3]
    # greater = (3>1)+(3>2)+(3>3=0)+(4>1)+(4>2)+(4>3)+(5>1)+(5>2)+(5>3) = 2+3+3 = 8
    # less = 0
    # delta = (8 - 0) / 9 = 0.888...
    x = [3, 4, 5]
    y = [1, 2, 3]
    assert stats.cliff_delta(x, y) == pytest.approx(8 / 9)


def test_cliff_delta_magnitude_labels():
    assert stats.cliff_delta_magnitude(0.10) == "negligible"
    assert stats.cliff_delta_magnitude(0.20) == "small"
    assert stats.cliff_delta_magnitude(0.40) == "medium"
    assert stats.cliff_delta_magnitude(0.60) == "large"
    assert stats.cliff_delta_magnitude(-0.60) == "large"


def test_cliff_delta_bootstrap_ci_contains_point_estimate_for_large_separation():
    x = [10, 11, 12, 13, 14]
    y = [1, 2, 3, 4, 5]
    delta, lo, hi = stats.cliff_delta_bootstrap_ci(x, y, n_boot=500, seed=42)
    assert delta == 1.0
    assert lo <= delta <= hi
    assert lo > 0.5  # well above zero


# ---------------------------------------------------------------------------
# Holm correction
# ---------------------------------------------------------------------------


def test_holm_correction_preserves_order():
    """The smallest raw p stays the smallest after Holm."""
    raw = [0.001, 0.04, 0.03, 0.005]
    adj = stats.holm_correction(raw)
    # Smallest raw is at index 0, should be smallest adjusted too
    assert adj[0] == min(adj)


def test_holm_correction_smallest_multiplied_by_m():
    """Holm: smallest p gets multiplied by m (the number of tests)."""
    raw = [0.01, 0.04, 0.03]
    adj = stats.holm_correction(raw)
    assert adj[0] == pytest.approx(0.01 * 3)  # 0.03


def test_holm_correction_monotonicity():
    """Adjusted p-values in the sorted order must be non-decreasing."""
    raw = [0.001, 0.04, 0.03, 0.005, 0.02]
    adj = stats.holm_correction(raw)
    # Sort by raw p
    pairs = sorted(zip(raw, adj))
    sorted_adj = [a for _, a in pairs]
    for i in range(len(sorted_adj) - 1):
        assert sorted_adj[i] <= sorted_adj[i + 1] + 1e-12


def test_holm_correction_clamped_to_one():
    raw = [0.6, 0.7, 0.8]
    adj = stats.holm_correction(raw)
    assert all(0 <= p <= 1 for p in adj)


def test_holm_correction_empty():
    assert stats.holm_correction([]) == []
