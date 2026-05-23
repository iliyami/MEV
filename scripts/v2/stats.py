"""Small statistics module for the v2 campaign-analysis layer.

Pure Python (no scipy, no numpy). Implements:

  * Mann-Whitney U with normal approximation (continuity-corrected).
  * Cliff's delta + bootstrap CI.
  * Holm step-down correction for multiple comparisons.

All functions are testable against textbook examples; we do not rely on
external implementations matching exactly.

For the v2 campaigns we use Cliff's delta (effect size) as the primary
adjudication signal — Mann-Whitney's p-value is reported alongside but
not gated on (statistical power with N=5 per cell is too low to trust
a 0.05 cutoff). See `paper_workspace/p2_preregistration.md` §5.
"""

from __future__ import annotations

import math
import random
from typing import Optional


# ---------------------------------------------------------------------------
# Mann-Whitney U
# ---------------------------------------------------------------------------


def _rankdata(values: list[float]) -> list[float]:
    """Average-rank tie handling (matches the standard rankdata convention)."""
    n = len(values)
    indexed = sorted(range(n), key=lambda i: values[i])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        # Find the run of equal values
        while j + 1 < n and values[indexed[j + 1]] == values[indexed[i]]:
            j += 1
        avg_rank = (i + j) / 2.0 + 1.0  # 1-indexed
        for k in range(i, j + 1):
            ranks[indexed[k]] = avg_rank
        i = j + 1
    return ranks


def mann_whitney_u(x: list[float], y: list[float]) -> dict[str, float]:
    """Two-sided Mann-Whitney U with normal approximation.

    Returns:
        u_x         -- U-statistic from x's perspective
        u_y         -- U-statistic from y's perspective (= n1*n2 - u_x)
        u_min       -- min(u_x, u_y)
        z           -- continuity-corrected z-score under H0
        p_two_sided -- two-sided p-value from the normal approximation
        n1, n2      -- sample sizes

    Notes:
        For tiny samples (N≤8 each) the exact null distribution would be
        more accurate, but the normal approximation with continuity
        correction is acceptable for N≥5 in practice; the v2 campaigns
        use Cliff's delta as the load-bearing metric so the exact p
        matters less than the effect-size measurement.
    """
    n1, n2 = len(x), len(y)
    if n1 < 1 or n2 < 1:
        raise ValueError("both samples must be non-empty")
    combined = list(x) + list(y)
    ranks = _rankdata(combined)
    r1 = sum(ranks[:n1])
    u_x = r1 - n1 * (n1 + 1) / 2.0
    u_y = n1 * n2 - u_x
    u = min(u_x, u_y)

    # Mean and SD of U under H0 with continuity correction
    mean_u = n1 * n2 / 2.0
    # Compute SD with tie correction
    tie_term = 0.0
    sorted_combined = sorted(combined)
    i = 0
    while i < len(sorted_combined):
        j = i
        while j + 1 < len(sorted_combined) and sorted_combined[j + 1] == sorted_combined[i]:
            j += 1
        t = j - i + 1
        if t > 1:
            tie_term += (t**3 - t)
        i = j + 1
    n_total = n1 + n2
    var_u = (n1 * n2 / 12.0) * ((n_total + 1) - tie_term / (n_total * (n_total - 1)))
    sd_u = math.sqrt(max(var_u, 0.0))
    if sd_u == 0:
        z = 0.0
        p = 1.0
    else:
        # Continuity correction: pull u toward the mean by 0.5
        diff = abs(u - mean_u) - 0.5
        diff = max(diff, 0.0)
        z = diff / sd_u
        # Two-sided p from standard normal:
        p = 2.0 * (1.0 - _phi(z))
        p = min(max(p, 0.0), 1.0)
    return {
        "u_x": u_x,
        "u_y": u_y,
        "u_min": u,
        "z": z,
        "p_two_sided": p,
        "n1": n1,
        "n2": n2,
    }


def _phi(z: float) -> float:
    """CDF of the standard normal at z (via the error function)."""
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


# ---------------------------------------------------------------------------
# Cliff's delta
# ---------------------------------------------------------------------------


def cliff_delta(x: list[float], y: list[float]) -> float:
    """Cliff's delta = P(X > Y) - P(X < Y), naive O(n*m) implementation.

    Ranges in [-1, 1]. Magnitude conventions (Romano et al. 2006):
        |δ| < 0.147 -- negligible
        |δ| < 0.33  -- small
        |δ| < 0.474 -- medium
        |δ| ≥ 0.474 -- large
    """
    if not x or not y:
        raise ValueError("both samples must be non-empty")
    greater = 0
    less = 0
    for xi in x:
        for yj in y:
            if xi > yj:
                greater += 1
            elif xi < yj:
                less += 1
    n = len(x) * len(y)
    return (greater - less) / n


def cliff_delta_bootstrap_ci(
    x: list[float],
    y: list[float],
    n_boot: int = 1000,
    confidence: float = 0.95,
    seed: int = 0,
) -> tuple[float, float, float]:
    """Bootstrap CI for Cliff's delta. Returns (delta, lo, hi)."""
    rng = random.Random(seed)
    deltas = []
    nx, ny = len(x), len(y)
    for _ in range(n_boot):
        xs = [x[rng.randrange(nx)] for _ in range(nx)]
        ys = [y[rng.randrange(ny)] for _ in range(ny)]
        deltas.append(cliff_delta(xs, ys))
    deltas.sort()
    alpha = (1.0 - confidence) / 2.0
    lo_idx = int(math.floor(alpha * n_boot))
    hi_idx = int(math.ceil((1.0 - alpha) * n_boot)) - 1
    lo_idx = max(0, min(lo_idx, n_boot - 1))
    hi_idx = max(0, min(hi_idx, n_boot - 1))
    return cliff_delta(x, y), deltas[lo_idx], deltas[hi_idx]


def cliff_delta_magnitude(delta: float) -> str:
    """Romano et al. 2006 magnitude labels."""
    a = abs(delta)
    if a < 0.147:
        return "negligible"
    if a < 0.33:
        return "small"
    if a < 0.474:
        return "medium"
    return "large"


# ---------------------------------------------------------------------------
# Holm step-down correction
# ---------------------------------------------------------------------------


def holm_correction(p_values: list[float]) -> list[float]:
    """Holm step-down adjustment for a list of raw p-values.

    Returns the adjusted p-values in the original order. An adjusted p
    of `p_adj` controls the family-wise error rate at level α when we
    reject all comparisons with `p_adj < α`.
    """
    n = len(p_values)
    if n == 0:
        return []
    indexed = sorted(range(n), key=lambda i: p_values[i])
    adjusted = [0.0] * n
    running_max = 0.0
    for rank, orig_idx in enumerate(indexed):
        m = n - rank
        adj = min(1.0, p_values[orig_idx] * m)
        # Enforce monotonicity (the step-down "max" sweep)
        adj = max(adj, running_max)
        running_max = adj
        adjusted[orig_idx] = adj
    return adjusted
