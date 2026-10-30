#!/usr/bin/env python3
"""Longest runs of consecutive honest omissions and per-run victim omission rates (no-attack runs), and
per-attacker omission rates (fissure runs). Input: parse_sui_ancestors.py outputs (not in the repo).
Usage: streaks.py <none.jsonl> <fissure.jsonl> <victims> <attackers> > data/review/bribe/<label>_streaks.txt
"""
import json, sys
sys.path.insert(0, __import__("os").path.dirname(__file__))
from omission_stats import load, streams


def longest(seq, val):
    best = cur = 0
    for x in seq:
        cur = cur + 1 if x == val else 0
        best = max(best, cur)
    return best


none_path, fiss_path, victims, attackers = sys.argv[1:5]
victims = set(int(x) for x in victims.split(","))
attackers = set(int(x) for x in attackers.split(","))
lv = la = 0
per_run = []
for run in load(none_path):
    per, _ = streams(run)
    o = n = 0
    for (i, j), s in per.items():
        if i == 0:
            continue
        seq = [1 if x[1] else 0 for x in s]
        la = max(la, longest(seq, 1))
        if j in victims:
            lv = max(lv, longest(seq, 1))
            o += sum(seq); n += len(seq)
    per_run.append((run["arm"], run["rep"], round(100 * o / n, 3) if n else None, n))
print("longest honest omission streak, victim:", lv, " any target:", la)
vals = sorted(p[2] for p in per_run)
print("per-run honest victim omission % (sorted):", vals)
print("runs with victim omission > 2%:", [p for p in per_run if p[2] > 2])
att = {}
for run in load(fiss_path):
    per, _ = streams(run)
    for (i, j), s in per.items():
        if i in attackers and j in victims:
            seq = [1 if x[1] else 0 for x in s]
            a = att.setdefault(i, [0, 0, 0])
            a[0] += len(seq); a[1] += sum(seq); a[2] = max(a[2], longest(seq, 0))
for i, (n, o, li) in sorted(att.items()):
    print(f"fissure attacker {i}: omits victim {100*o/n:.1f}% of {n} opportunities; longest inclusion streak {li}")
