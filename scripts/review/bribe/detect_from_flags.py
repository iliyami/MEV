#!/usr/bin/env python3
"""Refusal detectability from the shipped victim-omission flags (make_victim_flags.py output).
Input: data/review/bribe/p1_victim_flags.json.gz (40 no-attack runs, Sui v1.74), or another flags file.
Usage: detect_from_flags.py [flags.json.gz]. Prints the paper numbers: selective omission 0.03% of rounds,
longest honest streak 2 rounds, every-round refuser flagged after 2 rounds at 1% false alarm.
"""
import gzip, json, os, sys
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from omission_stats import all_omit_rounds, binom_rounds, wilson

PATH = sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parents[3] / "data/review/bribe/p1_victim_flags.json.gz"
d = json.load(gzip.open(PATH, "rt"))


def longest(s, ch):
    best = cur = 0
    for c in s:
        cur = cur + 1 if c == ch else 0
        best = max(best, cur)
    return best


H = [x["flags"] for x in d["honest"]]
A = [x["flags"] for x in d["attacker"]]
n = sum(map(len, H))
k_any = sum(s.count("1") + s.count("2") for s in H)
k_sel = sum(s.count("2") for s in H)
an = sum(map(len, A))
a_any = sum(s.count("1") + s.count("2") for s in A)
a_sel = sum(s.count("2") for s in A)
runs = {(x["arm"], x["rep"]) for x in d["honest"]}
p_any, p_sel, q_any, q_sel = k_any / n, k_sel / n, a_any / an, a_sel / an
print(f"{d['label']}: victims {d['victims']}, no-attack runs {len(runs)}, honest proposers 1..12, opportunities {n}")
print(f"honest omission of the victim, any: {k_any}/{n} = {100*p_any:.2f}% wilson95 {[round(100*x, 2) for x in wilson(k_any, n)]}")
print(f"honest omission of the victim alone (selective): {k_sel}/{n} = {100*p_sel:.3f}% "
      f"wilson95 {[round(100*x, 3) for x in wilson(k_sel, n)]}; longest run of consecutive rounds {max(longest(s, '2') for s in H)}")
N = all_omit_rounds(p_any)
print(f"every-round refuser flagged after {N} rounds at 1% false alarm (p0 = any-omission rate; "
      f"false alarm p0^{N} = {p_any**N:.2e}); with the selective rate: {all_omit_rounds(p_sel)} round")
print(f"fissure attackers {d['attackers']}: omit the victim {100*q_any:.1f}% (any), {100*q_sel:.2f}% (selective) of {an} opportunities")
print(f"rounds to flag the measured attacker with 99% power at 1% false alarm: any {binom_rounds(p_any, q_any)}, "
      f"selective {binom_rounds(p_sel, q_sel)}  (N, threshold)")
