#!/usr/bin/env python3
"""Run-level statistics for the coalition cells: pooled rate (the published estimator), median of
per-run rates, a cluster bootstrap 95% CI of the pooled rate (resampling runs), and run-level
permutation tests of the pooled-rate difference between arms (labels shuffled across runs).
Usage: python3 analyze.py ../../data/bullshark/coal/runs_pooled.jsonl"""
import json, random, statistics as st, sys
rows = [json.loads(l) for l in open(sys.argv[1]) if l.startswith("{")]
by = {}
for r in rows:
    if r["total"] > 0: by.setdefault(r["arm"], []).append(r)
pooled = lambda rs: 100.0 * sum(r["succ"] for r in rs) / sum(r["total"] for r in rs)
def boot(rs, B=10000, seed=1):
    random.seed(seed); v = sorted(pooled([random.choice(rs) for _ in rs]) for _ in range(B))
    return v[int(.025 * B)], v[int(.975 * B)]
def perm(a, b, B=20000, seed=2):
    random.seed(seed); obs = pooled(b) - pooled(a); allr = a + b; c = 0
    for _ in range(B):
        random.shuffle(allr)
        if abs(pooled(allr[len(a):]) - pooled(allr[:len(a)])) >= abs(obs) - 1e-12: c += 1
    return obs, (c + 1) / (B + 1)
for arm, rs in by.items():
    lo, hi = boot(rs)
    print(f"{arm:8s} runs={len(rs):2d} pairs={sum(r['total'] for r in rs):4d} pooled={pooled(rs):6.2f} [{lo:5.1f},{hi:5.1f}] "
          f"median-run={st.median(100*r['succ']/r['total'] for r in rs):6.2f}")
for a, b in [("base1", "solo"), ("solo", "bribe"), ("base4", "f4"), ("f4", "bribe"), ("f6ind", "f6"), ("base6", "f6"), ("base6", "f6rival"), ("base6", "f6ind")]:
    if a in by and b in by:
        d, p = perm(by[a], by[b]); print(f"{b} - {a}: {d:+6.2f}  run-level p={p:.3f}")
