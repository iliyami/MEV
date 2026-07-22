"""Exp3b — is the FIX_TIEBREAK digest tiebreak grindable?

Under FIX_TIEBREAK the within-round order is `sort by block digest` (the consensus
runs confirmed this makes ordering a uniform lottery: flat ~50% win-rate, Gini
0.03). A proposer controls its block content, hence its digest: it can try G
candidate blocks and keep the one with the smallest digest, jumping toward the
front. This models that grind and measures the resulting win-rate vs G.

Model (faithful to sort-by-uniform-digest): each of m validators draws a uniform
digest per round; the GRINDER keeps the min of G i.i.d. uniforms; sort ascending;
the grinder's win-rate = fraction of the other m-1 blocks it is ordered before.

Analytical: P(min of G uniforms < one uniform) = G/(G+1). So win-rate -> G/(G+1),
independent of m. The Monte Carlo validates this and reports value captured.

Deterministic (no RNG calls — a linear-congruential stream seeded by a fixed
constant, since the harness forbids Math.random-style nondeterminism). Usage:
    python -m scripts.v2.tiebreak_grind_sim --m 13 --rounds 20000
"""

from __future__ import annotations

import argparse


class _LCG:
    """Tiny deterministic uniform stream in [0,1). Fixed seed -> reproducible."""
    def __init__(self, seed: int = 2463534242):
        self.s = seed & 0xFFFFFFFF

    def u(self) -> float:
        # xorshift32
        x = self.s
        x ^= (x << 13) & 0xFFFFFFFF
        x ^= x >> 17
        x ^= (x << 5) & 0xFFFFFFFF
        self.s = x & 0xFFFFFFFF
        return self.s / 0xFFFFFFFF


def simulate(m: int, rounds: int, grind_attempts: list[int], seed: int = 2463534242):
    rng = _LCG(seed)
    out = []
    for g in grind_attempts:
        wins = 0
        pairs = 0
        value_captured = 0.0
        value_total = 0.0
        for _ in range(rounds):
            # others: m-1 uniform digests, each with a uniform "value" behind it
            others = [(rng.u(), rng.u()) for _ in range(m - 1)]
            # grinder: best (min) of g uniform digests
            gd = min(rng.u() for _ in range(g))
            # win-rate: grinder ordered before other iff gd < other_digest
            for od, ov in others:
                pairs += 1
                value_total += ov
                if gd < od:
                    wins += 1
                    value_captured += ov  # grinder frontruns that block's value
        out.append({
            "grind_attempts": g,
            "winrate_pct": round(100 * wins / pairs, 2),
            "analytic_pct": round(100 * g / (g + 1), 2),
            "value_captured_pct": round(100 * value_captured / value_total, 2),
        })
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="tiebreak_grind_sim")
    ap.add_argument("--m", type=int, default=13, help="validators per round")
    ap.add_argument("--rounds", type=int, default=20000)
    ap.add_argument("--seed", type=int, default=2463534242)
    args = ap.parse_args(argv)
    grid = [1, 2, 4, 8, 16, 32, 64, 128, 256, 1024]
    res = simulate(args.m, args.rounds, grid, args.seed)
    print(f"\n=== FIX_TIEBREAK grindability (m={args.m} validators, {args.rounds} rounds) ===")
    print(f"{'grind tries G':>13} {'winrate(MC)':>12} {'winrate G/(G+1)':>16} {'value captured':>15}")
    for r in res:
        print(f"{r['grind_attempts']:>13} {r['winrate_pct']:>11.1f}% {r['analytic_pct']:>15.1f}% {r['value_captured_pct']:>14.1f}%")
    print("\n  G=1 is the honest no-grind lottery (~50%, fair). Grinding is cheap:")
    print("  ~a few dozen hash tries per block buys near-total front-running.")
    print("  => the naive digest fix is a GRINDABLE lottery. A grind-resistant fix")
    print("     must seed the tiebreak with a per-commit value unpredictable at")
    print("     block-creation time (VRF / consensus randomness beacon).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
