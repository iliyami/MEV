#!/usr/bin/env python3
"""Copies of a victim tx inside the commit that holds its first copy (Sui v1.74 harness).
Input: the same raw logs as sui_copies.py (scripts/frontrun_sui/runs_vbcast/*_rep*.log, not in
the repo). Usage: python3 sui_first_commit.py <log> ...
Prints per-run and pooled counts (92.7% of victim txs have one copy in that commit).
"""
import json, sys, collections
agg = collections.defaultdict(collections.Counter)
for p in sys.argv[1:]:
    arm = p.rsplit("/", 1)[-1].rsplit("_rep", 1)[0]
    order = None
    for line in open(p, errors="replace"):
        if "FINAL_TX_ORDER:" in line:
            order = json.loads(line.split("FINAL_TX_ORDER:", 1)[1].strip())
    by = collections.defaultdict(list)
    for e in order:
        if e["tag"] == "V":
            by[e["id"]].append(e)
    run = collections.Counter()
    for v in by.values():
        f = min(v, key=lambda e: e["pos"])
        c = sum(1 for e in v if e["subdag"] == f["subdag"])
        agg[arm][c] += 1; run[c] += 1
    n = sum(run.values()); gt2 = sum(k for c, k in run.items() if c > 2)
    print(p.rsplit("/", 1)[-1], "n", n, "first-commit copies > 2:", gt2, f"({100*gt2/n:.1f}%)", dict(sorted(run.items())))
for arm, c in agg.items():
    n = sum(c.values()); gt2 = sum(k for x, k in c.items() if x > 2)
    print("POOLED", arm, "n", n, "first-commit copies > 2:", gt2, f"({100*gt2/n:.1f}%)", dict(sorted(c.items())))
