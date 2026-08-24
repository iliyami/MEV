#!/usr/bin/env python3
"""A1.4 — the censorship metric.

Censorship was scoped out of the positional framework for a good reason: a censored block
has no position, so every ordering metric in this project (all-pairs, same-round,
committing-height) is undefined for it. That is an argument against scoring censorship
*positionally*, not an argument that it cannot be measured.

What censorship does is deny a victim *inclusion*, so we score inclusion. For each run we
read `FINAL_COMMITTED_ORDER`, which already lists every committed block with its creator,
and compare how much the victims got committed against how much the honest non-victims did:

    censorship rate = 1 - (mean victim blocks committed / mean honest non-victim blocks)

0.0 means a victim is committed exactly as often as a typical honest validator, i.e. no
censorship. 1.0 means the victim is committed never. Negative values mean the victims were
committed *more* than honest nodes, which is possible and worth reporting rather than
clamping.

Two properties make this the right shape:
  * It is a ratio against peers in the same run, so it does not move with run length,
    commit count, or machine load - the failure mode that invalidated several cells here.
  * It has a natural fair line at 0.0, so it needs no separate calibration argument.

Roles follow the project convention: attackers are the first `round(n*ATTACKER_RATIO)`
indices, victims the last `round(n*VICTIM_RATIO)`.

Usage:
    score_censorship.py --log run.log --nodes 13 --attacker-ratio 0.308 --victim-ratio 0.231
    cat run.log | score_censorship.py
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys

ORDER_RE = re.compile(r"FINAL_COMMITTED_ORDER:\s*(\[.*?\])", re.S)


def score(text: str, n: int, attacker_ratio: float, victim_ratio: float) -> dict | None:
    m = ORDER_RE.findall(text)
    if not m:
        return None
    # Use the last emission; a run prints one final order.
    try:
        blocks = json.loads(m[-1])
    except json.JSONDecodeError:
        return None
    if not blocks:
        return None

    num_attacker = round(n * attacker_ratio)
    num_victim = round(n * victim_ratio)
    attackers = set(range(num_attacker))
    victims = set(range(n - num_victim, n))
    honest = set(range(n)) - attackers - victims
    if not honest or not victims:
        return None

    counts = {i: 0 for i in range(n)}
    for b in blocks:
        c = b.get("creator")
        if isinstance(c, int) and c in counts:
            counts[c] += 1

    victim_mean = statistics.mean(counts[i] for i in victims)
    honest_mean = statistics.mean(counts[i] for i in honest)
    if honest_mean == 0:
        return None

    rate = 1.0 - (victim_mean / honest_mean)
    return {
        "censorship_rate_pct": round(rate * 100.0, 2),
        "victim_mean_blocks": round(victim_mean, 2),
        "honest_mean_blocks": round(honest_mean, 2),
        "attacker_mean_blocks": round(
            statistics.mean(counts[i] for i in attackers) if attackers else 0.0, 2
        ),
        "total_committed": len(blocks),
        "victims": sorted(victims),
        "honest": sorted(honest),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", help="run log; omit to read stdin")
    ap.add_argument("--nodes", type=int, default=13)
    ap.add_argument("--attacker-ratio", type=float, default=0.308)
    ap.add_argument("--victim-ratio", type=float, default=0.231)
    args = ap.parse_args()

    text = open(args.log, encoding="utf-8", errors="replace").read() if args.log else sys.stdin.read()
    out = score(text, args.nodes, args.attacker_ratio, args.victim_ratio)
    if out is None:
        # Refuse to emit a number rather than report a misleading 0.0.
        print(json.dumps({"error": "no FINAL_COMMITTED_ORDER found or empty order"}))
        return 1
    print("FINAL_CENSORSHIP_STATS: " + json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
