#!/usr/bin/env python3
"""Refusal law at n=25 (f=8): fissure on Bullshark with fa = 1, 2, 4, 6 (lsweep) and 8 (dsweep f25),
against the pooled no-attack control (dsweep b25 + lsweep b25x). Targeted committing-height (M3),
pooled per arm with a run bootstrap; weighted least-squares slope over treated arms (pairs as
weights, same fit as law.py) and a run-label permutation test of the slope. Usage: python3 law25.py"""
import json, random
import os
HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.environ.get("COAL_DATA", os.path.join(HERE, "../../data/bullshark/coal"))   # per-run score files
random.seed(5)
def runs(path, arm_of):
    out = {}
    for l in open(path):
        d = json.loads(l); m = d["m"]
        if not m or not m.get("cells"): continue
        c = list(m["cells"].values())[0]["M3_targeted_committing_height"]
        if c["total"]: out.setdefault(arm_of(d["run"]), []).append({"succ": c["succ"], "total": c["total"]})
    return out
after = lambda r, d: r.split("/")[r.split("/").index(d) + 1]   # the directory after lsweep/ or dsweep/
A = runs(os.path.join(DATA, "lsweep_scores.jsonl"), lambda r: after(r, "lsweep"))
D = runs(os.path.join(DATA, "dsweep_scores.jsonl"), lambda r: after(r, "dsweep"))
by = {"base": A.get("b25x", []) + D.get("b25", []), 1: A.get("f25a1", []), 2: A.get("f25a2", []),
      4: A.get("f25a4", []), 6: A.get("f25a6", []), 8: D.get("f25", [])}
pooled = lambda rs: 100 * sum(r["succ"] for r in rs) / sum(r["total"] for r in rs)
def boot(rs, B=4000):
    v = sorted(pooled([random.choice(rs) for _ in rs]) for _ in range(B)); return v[int(.025 * B)], v[int(.975 * B)]
for k, rs in by.items():
    lo, hi = boot(rs); print(f"{k!s:5s} runs={len(rs):2d} pairs={sum(r['total'] for r in rs):4d} {pooled(rs):5.1f} [{lo:5.1f},{hi:5.1f}]")
tr = [(k, r) for k in (1, 2, 4, 6, 8) for r in by[k]]
def fit(rs):
    X = sum(r["total"] for _, r in rs); mx = sum(k * r["total"] for k, r in rs) / X; my = sum(r["succ"] for _, r in rs) / X
    b = (sum(k * r["succ"] for k, r in rs) - mx * my * X) / (sum(k * k * r["total"] for k, r in rs) - mx * mx * X)
    return 100 * b, 100 * (my - b * mx)
b, a0 = fit(tr); print(f"n=25 slope {b:.2f} points per refusal, intercept {a0:.2f}; per committee share {b*25:.1f} (n=13: 3.63 -> {3.63*13:.1f})")
bs = sorted(fit([random.choice(tr) for _ in tr])[0] for _ in range(4000)); print(f"slope 95% [{bs[100]:.2f},{bs[3899]:.2f}]")
ks = [k for k, _ in tr]; rr = [r for _, r in tr]; c = 0; B = 20000
for _ in range(B):
    random.shuffle(ks)
    if abs(fit(list(zip(ks, rr)))[0]) >= abs(b): c += 1
print(f"slope run-level p={(c + 1) / (B + 1):.5f}")
# f = 8 attackers against the pooled 20-run control: bootstrap interval of the difference, one-sided run-label permutation
A8, B0 = by[8], by["base"]
dd = sorted(pooled([random.choice(A8) for _ in A8]) - pooled([random.choice(B0) for _ in B0]) for _ in range(4000))
obs = pooled(A8) - pooled(B0); allr = A8 + B0; c = 0
for _ in range(20000):
    random.shuffle(allr)
    if pooled(allr[:len(A8)]) - pooled(allr[len(A8):]) >= obs: c += 1
print(f"f=8 vs 20-run control: {obs:+.1f} [{dd[100]:+.1f},{dd[3899]:+.1f}] one-sided p={(c + 1) / 20001:.4f}")
