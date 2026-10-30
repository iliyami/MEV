#!/usr/bin/env python3
"""Selective omission: a block leaves out the victim's previous-round block while including every
non-victim's. Input: parse_sui_ancestors.py outputs (not in the repo); usage: selective.py none.jsonl
fissure.jsonl victims attackers > data/review/bribe/<label>_selective.txt.
Paper: 0.03% of rounds (108 of 383,384), never more than two consecutive rounds.
"""
import sys, os, math, json
from collections import Counter
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from omission_stats import load, binom_rounds, all_omit_rounds, windows, wilson

none_p, fiss_p, vic, att = sys.argv[1:5]
vic = set(map(int, vic.split(","))); att = set(map(int, att.split(",")))

def seqs(path, keep):
    """per (run, proposer, victim): list of 0/1 selective-omission flags in round order."""
    out = []
    for run in load(path):
        have = set((a, r) for a, r, _, _ in run["blocks"])
        st = {}
        for a, r, ts, anc in sorted(run["blocks"], key=lambda b: (b[0], b[1])):
            if not keep(a):
                continue
            ancset = set((x[0], x[1]) for x in anc)
            omitted = [j for j in range(13) if j != a and (j, r - 1) in have and (j, r - 1) not in ancset]
            for v in vic:
                if v == a or (v, r - 1) not in have:
                    continue
                sel = 1 if (v in omitted and all(o in vic for o in omitted)) else 0
                st.setdefault(v, []).append(sel)
        for v, s in st.items():
            out.append(((run["arm"], run["rep"], v), s))
    return out

def per_proposer(path, keep):
    res = []
    for run in load(path):
        have = set((a, r) for a, r, _, _ in run["blocks"])
        acc = {}
        for a, r, ts, anc in run["blocks"]:
            if not keep(a):
                continue
            ancset = set((x[0], x[1]) for x in anc)
            omitted = [j for j in range(13) if j != a and (j, r - 1) in have and (j, r - 1) not in ancset]
            for v in vic:
                if v == a or (v, r - 1) not in have:
                    continue
                c = acc.setdefault(a, [0, 0]); c[0] += 1; c[1] += (v in omitted and all(o in vic for o in omitted))
        res += [(100 * o / n, n, run["arm"], run["rep"], a) for a, (n, o) in acc.items()]
    return sorted(res)

H = [s for _, s in seqs(none_p, lambda a: a != 0)]
A = [s for _, s in seqs(fiss_p, lambda a: a in att)]
hn, ho = sum(map(len, H)), sum(map(sum, H)); an, ao = sum(map(len, A)), sum(map(sum, A))
p0, q = ho / hn, ao / an
def longest(s):
    b = c = 0
    for x in s:
        c = c + 1 if x else 0; b = max(b, c)
    return b
print(f"honest selective omission of victim: {ho}/{hn} = {100*p0:.3f}% wilson95 {[round(100*x,3) for x in wilson(ho,hn)]}; longest streak {max(map(longest,H))}")
print(f"fissure attacker selective omission of victim: {ao}/{an} = {100*q:.2f}%")
print(f"binomial: always-refuser flagged after {all_omit_rounds(p0)} rounds (FA {p0**all_omit_rounds(p0):.2e}); "
      f"vs measured attacker 99% power: N,c={binom_rounds(p0, q, power=0.99)}; 95%: {binom_rounds(p0, q, power=0.95)}")
for N in (1, 2, 3, 4, 5, 6, 8, 10, 15, 20, 30, 50):
    hw = [x for s in H for x in windows(s, N)]; aw = [x for s in A for x in windows(s, N)]
    hc, ac = Counter(hw), Counter(aw)
    c = next((cc for cc in range(N + 1) if sum(v for k, v in hc.items() if k >= cc) / len(hw) <= 0.01), None)
    fa = sum(v for k, v in hc.items() if k >= c) / len(hw) if c is not None else None
    pw = sum(v for k, v in ac.items() if k >= c) / len(aw) if c is not None else None
    print(f"  N={N:3d} honest windows {len(hw)} all-omitted FA {hc.get(N,0)/len(hw):.2e} | threshold c={c} FA {fa} power(measured attacker) {pw}")
hp = per_proposer(none_p, lambda a: a != 0); ap = per_proposer(fiss_p, lambda a: a in att)
print(f"per (run, proposer): honest max {hp[-1][0]:.2f}% {hp[-1][2:]} ; attacker min {ap[0][0]:.2f}% {ap[0][2:]} ; separated: {ap[0][0] > hp[-1][0]}")
