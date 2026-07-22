"""VictimGen — deterministic per-block profit generator for multi-victim runs.

A profit value `P(B)` is assigned to every victim block `B = (round, author)`.
Generation is:

  * **deterministic** — given (seed, round, author, distribution, params),
    `profit_for_block` returns the same number every time. The Coordinator can
    therefore serve it without holding per-block state, and the Python metrics
    layer can re-derive it from the run's seed alone.
  * **distribution-driven** — `uniform` (control: every block worth the same
    constant), `pareto` (heavy-tailed; the primary heterogeneous-profit model),
    and `lognormal` (a second heavy-tailed model for the value-distribution
    robustness sweep — guide T3/T4). Real DEX-replay traces are deferred to the
    Sui phase per `paper_workspace/plan_v2.md` §8.

Profit is treated as an abstract positive scalar. Comparisons across runs are
only meaningful when the same `seed` + `params` are used; this matches the
plan's reproducibility checklist (every randomized component is seed-driven).

For paper 1 reproducibility, the `uniform` distribution with scale=1.0 makes
profit-weighted ASR exactly equal to unweighted ASR — i.e., paper-1 metrics
remain a strict special case of the v2 metric.
"""

from __future__ import annotations

import dataclasses
import hashlib
import math
import statistics
import struct
from dataclasses import dataclass
from typing import Any


_UNIFORM = "uniform"
_PARETO = "pareto"
_LOGNORMAL = "lognormal"
ALLOWED_DISTRIBUTIONS = (_UNIFORM, _PARETO, _LOGNORMAL)


def _u_in_unit(seed: int, round_: int, author: int) -> float:
    """Map (seed, round, author) deterministically to U in [0, 1)."""
    h = hashlib.sha256()
    h.update(struct.pack(">qqq", int(seed), int(round_), int(author)))
    # First 8 bytes -> 64-bit unsigned int -> divide by 2**64 to land in [0, 1).
    raw = int.from_bytes(h.digest()[:8], "big")
    return raw / float(1 << 64)


def _profit_uniform(scale: float) -> float:
    if scale <= 0:
        raise ValueError(f"uniform scale must be positive, got {scale}")
    return float(scale)


def _profit_pareto(u: float, shape: float, scale: float) -> float:
    """Pareto Type I draw: P = scale * (1 - u)^(-1/shape) for u in [0, 1).

    Shape > 1 → finite mean = scale * shape / (shape - 1).
    The plan's default is shape=1.16 (heavy-tailed; mean ≈ 7.25 * scale).
    """
    if shape <= 0:
        raise ValueError(f"pareto shape must be positive, got {shape}")
    if scale <= 0:
        raise ValueError(f"pareto scale must be positive, got {scale}")
    # Clamp u away from 1.0 to avoid +inf from a perfectly-unlucky hash.
    u_safe = min(max(u, 0.0), 1.0 - 1e-12)
    return float(scale) * math.pow(1.0 - u_safe, -1.0 / float(shape))


def _profit_lognormal(u: float, mu: float, sigma: float, scale: float) -> float:
    """Log-normal draw via inverse-CDF: P = scale * exp(mu + sigma * z),
    where z = Phi^{-1}(u) is the standard-normal quantile.

    A second heavy-tailed model alongside Pareto, used for the value-distribution
    robustness sweep (guide T3/T4). Defaults mu=1.1, sigma=2.5 follow one empirical
    MEV fit; the exact source is to be confirmed before final (plan Q1 / C.7b).
    """
    if sigma <= 0:
        raise ValueError(f"lognormal sigma must be positive, got {sigma}")
    if scale <= 0:
        raise ValueError(f"lognormal scale must be positive, got {scale}")
    # Clamp u into the open unit interval so the probit is finite.
    u_safe = min(max(u, 1e-12), 1.0 - 1e-12)
    z = statistics.NormalDist(0.0, 1.0).inv_cdf(u_safe)
    return float(scale) * math.exp(float(mu) + float(sigma) * z)


@dataclass(frozen=True)
class VictimProfile:
    """Frozen configuration for a run's victim-profit assignment."""

    distribution: str
    params: dict[str, Any] = dataclasses.field(default_factory=dict)
    seed: int = 0

    def __post_init__(self) -> None:
        if self.distribution not in ALLOWED_DISTRIBUTIONS:
            raise ValueError(
                f"unknown distribution {self.distribution!r}; "
                f"expected one of {ALLOWED_DISTRIBUTIONS}"
            )

    def profit_for_block(self, round_: int, author: int) -> float:
        """Deterministic profit for victim block (round, author)."""
        if self.distribution == _UNIFORM:
            return _profit_uniform(scale=float(self.params.get("scale", 1.0)))
        if self.distribution == _PARETO:
            u = _u_in_unit(self.seed, round_, author)
            return _profit_pareto(
                u,
                shape=float(self.params.get("shape", 1.16)),
                scale=float(self.params.get("scale", 1.0)),
            )
        if self.distribution == _LOGNORMAL:
            u = _u_in_unit(self.seed, round_, author)
            return _profit_lognormal(
                u,
                mu=float(self.params.get("mu", 1.1)),
                sigma=float(self.params.get("sigma", 2.5)),
                scale=float(self.params.get("scale", 1.0)),
            )
        raise RuntimeError(f"unhandled distribution {self.distribution!r}")

    @classmethod
    def from_config(cls, profit_spec_dict: dict[str, Any], seed: int) -> "VictimProfile":
        """Build a VictimProfile from a VictimsSpec.profit-shaped mapping."""
        return cls(
            distribution=str(profit_spec_dict.get("distribution", _UNIFORM)),
            params=dict(profit_spec_dict.get("params") or {}),
            seed=int(seed),
        )


def profit_weighted_asr(
    blocks: list[dict[str, Any]],
    profile: VictimProfile,
) -> dict[str, float]:
    """Compute the profit-weighted ASR over a list of victim-block records.

    Each block record is expected to carry:
        round   : int
        author  : int
        attacked: bool  -- whether some attacker block was ordered before it

    Returns:
        {
          "unweighted_asr": frac of victims with attacked=True,
          "profit_weighted_asr": Σ P(B)·attacked(B) / Σ P(B),
          "total_profit": Σ P(B),
          "realized_mev": Σ P(B)·attacked(B),
          "n_victims": len(blocks),
        }

    When `profile.distribution == "uniform"`, `profit_weighted_asr` equals
    `unweighted_asr` (paper-1 metric, recovered as a special case).
    """
    if not blocks:
        return {
            "unweighted_asr": 0.0,
            "profit_weighted_asr": 0.0,
            "total_profit": 0.0,
            "realized_mev": 0.0,
            "n_victims": 0,
        }
    total_profit = 0.0
    realized_mev = 0.0
    attacks = 0
    for b in blocks:
        p = profile.profit_for_block(int(b["round"]), int(b["author"]))
        total_profit += p
        if bool(b.get("attacked", False)):
            realized_mev += p
            attacks += 1
    n = len(blocks)
    return {
        "unweighted_asr": attacks / n,
        "profit_weighted_asr": (realized_mev / total_profit) if total_profit > 0 else 0.0,
        "total_profit": total_profit,
        "realized_mev": realized_mev,
        "n_victims": n,
    }
