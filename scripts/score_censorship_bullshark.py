#!/usr/bin/env python3
"""A1.4 censorship on the certified DAG (Bullshark / Narwhal).

Companion to score_censorship.py, which reads Sui's `FINAL_COMMITTED_ORDER`. Bullshark
instead emits one `FairDag CommitMeta <digest> author <author> round <r> height <h>` line per
committed block, and identifies victim-created headers with
`FairDag Created a victim header <digest> in round <r>`. Roles are therefore inferred from the
logs, exactly as our_harness/measure.py does, with no committee file needed.

Metric, identical in shape to the Sui version so the two are comparable:

    censorship rate = 1 - (mean victim blocks committed / mean honest non-victim blocks)

0.0 means a victim is committed as often as a typical honest validator. 1.0 means never.

WHY THIS PROTOCOL MATTERS. On an uncertified DAG a block is committed once referenced, so no
parent- or vote-withholding can deny inclusion, and censorship measured there is ~0 (verified:
fissure +0.53, MLVW +1.10, MLVW+bribed +2.65). A certified DAG has an admission gate: a block
needs a quorum of 2f+1 certificates. At n=13 the quorum is 9, so 4 refusing attackers leave
exactly 9 certifiers, just enough. One more refuser (5 = n - quorum + 1) makes the quorum
unreachable and censorship should become total. This scorer is what tests that threshold.

Usage:
    score_censorship_bullshark.py --logdir /app/rl3_one/fissure_f4_n13
    (scans every run*/primary-*.log beneath it, scores each run, prints per-run and median)
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import statistics
import sys

RE_META = re.compile(r"FairDag CommitMeta (\S+) author (\S+) round (\d+) height (\d+)")
# Roles come from the logged ATTACK PAIRS, exactly as our_harness/measure.py does. An earlier
# version keyed off "Created a victim header", which every non-attacker emits, so it labelled
# all nine honest nodes as victims and compared honest-vs-attacker (censorship read -738%).
RE_PAIRS = [
    re.compile(r"FairDag Created a fissure attacking header (\S+), victim header (\S+), in round (\d+)"),
    re.compile(r"FairDag Created a sluggish attacking header (\S+), victim header (\S+), in round (\d+)"),
    re.compile(r"FairDag Created a speculative attacking header (\S+), victim header (\S+), in round (\d+)"),
    re.compile(r"FairDag Monitor attacking header (\S+), victim header (\S+), in round (\d+)"),
]


def score_run(run_dir: str) -> dict | None:
    meta: dict[str, dict] = {}
    victim_digests: set[str] = set()
    attacker_digests: set[str] = set()

    for path in glob.glob(os.path.join(run_dir, "primary-*.log")):
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                m = RE_META.search(line)
                if m:
                    d, author, rnd, h = m.groups()
                    meta[d] = {"author": author, "round": int(rnd), "height": int(h)}
                    continue
                for rx in RE_PAIRS:
                    m = rx.search(line)
                    if m:
                        attacker_digests.add(m.group(1))
                        victim_digests.add(m.group(2))
                        break

    if not meta:
        return None

    # Victim authors: whoever created a block flagged as a victim header. Fall back to
    # nothing rather than guessing, so a missing marker is visible instead of silently
    # producing a wrong denominator.
    victim_authors = {meta[d]["author"] for d in victim_digests if d in meta}
    if not victim_authors:
        return {"error": "no victim headers matched committed blocks", "committed": len(meta)}

    attacker_authors = {meta[d]["author"] for d in attacker_digests if d in meta}

    counts: dict[str, int] = {}
    for b in meta.values():
        counts[b["author"]] = counts.get(b["author"], 0) + 1

    # Compare the targeted victim against HONEST non-victim, non-attacker nodes. Including
    # attackers in the denominator would let their own deadlock (they commit ~35 blocks where
    # honest nodes commit ~293) masquerade as victim censorship.
    victim_counts = [counts.get(a, 0) for a in victim_authors]
    others = [c for a, c in counts.items()
              if a not in victim_authors and a not in attacker_authors]
    if not others:
        return {"error": "no non-victim authors", "committed": len(meta)}

    # MEDIAN, not mean, for the denominator. Only the delegate attacker logs attack pairs, so
    # the other attackers are indistinguishable from honest nodes here and land in `others`.
    # When they deadlock they commit ~35 blocks against an honest ~293, and a mean denominator
    # turns that into a spurious -31% "censorship". With 9 honest against 3 deadlocked
    # attackers the median is an honest value, so the metric measures the victim rather than
    # the attackers' self-inflicted stall.
    victim_mean = statistics.median(victim_counts)
    other_mean = statistics.median(others)
    if other_mean == 0:
        return {"error": "no blocks from non-victims", "committed": len(meta)}

    return {
        "censorship_rate_pct": round((1.0 - victim_mean / other_mean) * 100.0, 2),
        "victim_median_blocks": round(victim_mean, 2),
        "other_median_blocks": round(other_mean, 2),
        "n_victim_authors": len(victim_authors),
        "n_attacker_authors": len(attacker_authors),
        "attacker_mean_blocks": round(statistics.mean([counts.get(a,0) for a in attacker_authors]),2) if attacker_authors else None,
        "total_committed": len(meta),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--logdir", required=True, help="dir containing run*/ subdirs")
    args = ap.parse_args()

    runs = sorted(glob.glob(os.path.join(args.logdir, "run*")))
    if not runs:
        runs = [args.logdir]

    rates, rows = [], []
    for r in runs:
        out = score_run(r)
        if out is None:
            print(f"{os.path.basename(r)}: no CommitMeta found", flush=True)
            continue
        if "error" in out:
            print(f"{os.path.basename(r)}: {out['error']}", flush=True)
            continue
        rows.append(out)
        rates.append(out["censorship_rate_pct"])
        print(f"{os.path.basename(r)}: {json.dumps(out)}", flush=True)

    if not rates:
        print(json.dumps({"error": "no run produced a censorship rate"}))
        return 1
    print("FINAL_CENSORSHIP_MEDIAN: " + json.dumps({
        "median_pct": round(statistics.median(rates), 2),
        "range": [min(rates), max(rates)],
        "n_runs": len(rates),
        "reps": rates,
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
