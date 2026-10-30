#!/usr/bin/env python3
"""Whole-run separation of honest proposers and fissure attackers by their victim omission rate.
Input: parse_sui_ancestors.py outputs (not in the repo).
Usage: perrun_sep.py none.jsonl fissure.jsonl victims attackers
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from omission_stats import load, streams
none_p, fiss_p, vic, att = sys.argv[1:5]
vic = set(map(int, vic.split(","))); att = set(map(int, att.split(",")))
def rates(path, keep):
    out = []
    for run in load(path):
        per, _ = streams(run)
        acc = {}
        for (i, j), s in per.items():
            if j in vic and keep(i):
                a = acc.setdefault(i, [0, 0]); a[0] += len(s); a[1] += sum(1 for x in s if x[1])
        out += [(100 * o / n, n, run["arm"], run["rep"], i) for i, (n, o) in acc.items() if n]
    return sorted(out)
h = rates(none_p, lambda i: i != 0)
a = rates(fiss_p, lambda i: i in att)
print(f"honest (run, proposer) streams: {len(h)}; max {h[-1][0]:.2f}% ({h[-1][2]} rep{h[-1][3]} proposer {h[-1][4]}, {h[-1][1]} opps); "
      f"99th pct {h[int(.99*(len(h)-1))][0]:.2f}%; median {h[len(h)//2][0]:.3f}%")
print(f"attacker (run, proposer) streams: {len(a)}; min {a[0][0]:.2f}% ({a[0][2]} rep{a[0][3]} proposer {a[0][4]}, {a[0][1]} opps); "
      f"median {a[len(a)//2][0]:.2f}%")
print("separated over a whole run:", a[0][0] > h[-1][0])
