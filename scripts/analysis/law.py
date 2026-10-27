#!/usr/bin/env python3
"""One law across the coalition/bribery arms: targeted committing-height rate against the number of
validators refusing each victim's block. Weighted least-squares slope over treated arms (pairs as
weights), run-label permutation test of the slope, and run-level tests between arms with equal
refusals per victim. Usage: python3 law.py"""
import random
import os
HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.environ.get("COAL_DATA", os.path.join(HERE, "../../data/bullshark/coal"))   # per-run score files
exec(open(os.path.join(HERE, "analyze.py")).read().split("for arm, rs in by.items():")[0].replace("sys.argv[1]", repr(os.path.join(DATA, "runs_pooled.jsonl"))))
R = {"solo": 1, "f6ind": 1, "bribe1": 2, "bribe2": 3, "f6rival": 3, "bribe": 4, "f4": 4, "f6": 6}
for a, b in [("solo", "f6ind"), ("bribe2", "f6rival"), ("bribe", "f4")]:
    d, p = perm(by[a], by[b]); print(f"equal refusals {R[a]}: {b}-{a} {d:+.2f} p={p:.3f}")
runs = [(R[a], r) for a in R for r in by[a]]
def fit(rs):
    X = sum(r["total"] for _, r in rs); mx = sum(k * r["total"] for k, r in rs) / X; my = sum(r["succ"] for _, r in rs) / X
    b = (sum(k * r["succ"] for k, r in rs) - mx * my * X) / (sum(k * k * r["total"] for k, r in rs) - mx * mx * X)
    return 100 * b, 100 * (my - b * mx)
b, a0 = fit(runs); print("slope %.2f points per refusal, intercept %.2f" % (b, a0))
random.seed(5); ks = [k for k, _ in runs]; rr = [r for _, r in runs]; c = 0; B = 20000
for _ in range(B):
    random.shuffle(ks)
    if abs(fit(list(zip(ks, rr)))[0]) >= abs(b): c += 1
print("slope run-level p=%.5f" % ((c + 1) / (B + 1)))
base = by["base1"] + by["base4"] + by["base6"]; print("pooled no-attack %.2f" % pooled(base), boot(base))
