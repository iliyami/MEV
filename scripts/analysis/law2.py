#!/usr/bin/env python3
"""Law checks: (1) the same-round metric (m2) from m2_all_runs.jsonl, (2) lifts over each arm's own
no-attack control on the targeted metric, (3) bootstrap 95% intervals of equal-refusal differences."""
import json, random
import os
HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.environ.get("COAL_DATA", os.path.join(HERE, "../../data/bullshark/coal"))   # per-run score files
R = {"solo": 1, "f6ind": 1, "bribe1": 2, "bribe2": 3, "f6rival": 3, "bribe": 4, "f4": 4, "f6": 6}
CTL = {"solo": "base1", "bribe1": "base1", "bribe2": "base1", "bribe": "base1", "f4": "base4", "f6": "base6", "f6ind": "base6", "f6rival": "base6"}
def load(path, key):
    by = {}
    for l in open(path):
        if not l.startswith("{"): continue
        r = json.loads(l)
        if key in r and r[key][1] > 0: by.setdefault(r["arm"], []).append({"succ": r[key][0], "total": r[key][1]})
        elif key == "m3" and r.get("total", 0) > 0: by.setdefault(r["arm"], []).append({"succ": r["succ"], "total": r["total"]})
    return by
pooled = lambda rs: 100.0 * sum(r["succ"] for r in rs) / sum(r["total"] for r in rs)
def fit(pts):  # pts: (k, rate, weight)
    W = sum(w for _, _, w in pts); mx = sum(k * w for k, _, w in pts) / W; my = sum(y * w for _, y, w in pts) / W
    b = sum(w * (k - mx) * (y - my) for k, y, w in pts) / sum(w * (k - mx) ** 2 for k, _, w in pts); return b, my - b * mx
def runpts(by, lift):
    pts = []
    for a in R:
        c = pooled(by[CTL[a]]) if lift else 0.0
        for r in by[a]: pts.append((R[a], 100 * r["succ"] / r["total"] - c, r["total"]))
    return pts
def perm_slope(pts, B=20000, seed=5):
    b, _ = fit(pts); random.seed(seed); ks = [k for k, _, _ in pts]; c = 0
    for _ in range(B):
        random.shuffle(ks)
        if abs(fit([(k, y, w) for k, (_, y, w) in zip(ks, pts)])[0]) >= abs(b): c += 1
    return (c + 1) / (B + 1)
def bootdiff(a, b, B=10000, seed=1):
    random.seed(seed); v = sorted(pooled([random.choice(b) for _ in b]) - pooled([random.choice(a) for _ in a]) for _ in range(B))
    return pooled(b) - pooled(a), v[int(.025 * B)], v[int(.975 * B)]
m3 = load(os.path.join(DATA, "runs_pooled.jsonl"), "m3"); m2 = load(os.path.join(DATA, "m2_all_runs.jsonl"), "m2")
for name, by in [("targeted", m3), ("same-round", m2)]:
    print("==", name, {a: round(pooled(by[a]), 2) for a in list(R) + ["base1", "base4", "base6"] if a in by})
    for lift in ((False, True) if "base1" in by else (False,)):
        pts = runpts(by, lift); b, a0 = fit(pts)
        print(f"  {'lift' if lift else 'rate'}: slope {b:.2f}/refusal intercept {a0:.2f} p={perm_slope(pts):.5f}")
    for x, y in [("solo", "f6ind"), ("bribe2", "f6rival"), ("bribe", "f4")]:
        d, lo, hi = bootdiff(by[x], by[y]); print(f"  {y}-{x}: {d:+.2f} [{lo:+.2f},{hi:+.2f}]")
# Within f (at most four refusers: solo, bribe1-3, f4)
W = ["solo", "bribe1", "bribe2", "bribe", "f4"]
for name, by in [("targeted", m3), ("same-round", m2)]:
    pts = [(R[a], 100 * r["succ"] / r["total"], r["total"]) for a in W for r in by[a]]
    b, a0 = fit(pts); print(f"{name} within f: slope {b:.2f} intercept {a0:.2f} p={perm_slope(pts):.5f}")
