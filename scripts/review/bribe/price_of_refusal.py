#!/usr/bin/env python3
"""Price of one more refusal per victim transaction: at most s/100 x E[trade value] x kappa
(Proposition "The price of a refusal" (i)). Inputs, all in the repo: data/bullshark/coal/runs_pooled.jsonl,
data/sui_frontrun/mlaw_scores.jsonl, data/sui_value/sui_mainnet_trade_values.csv. Usage:
price_of_refusal.py [out.json]. Prints s per refusal with run-bootstrap CIs and the dollar table.
"""
import csv, json, random, statistics as st, sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
POOLED = REPO / "data/bullshark/coal/runs_pooled.jsonl"      # per-run targeted committing-height
MLAW = REPO / "data/sui_frontrun/mlaw_scores.jsonl"          # score_mlaw.py output
CSV = REPO / "data/sui_value/sui_mainnet_trade_values.csv"   # USD per trade, column 'usd'
B = 10000

# ---------------- Bullshark slopes ----------------
by = {}
for l in open(POOLED):
    if not l.startswith("{"):
        continue
    r = json.loads(l)
    if r["total"] > 0:
        by.setdefault(r["arm"], []).append((r["succ"], r["total"]))


def fit(groups):
    """groups: list of (k, [(succ,total), ...]); WLS of pair-level success on k (same as law.py)."""
    X = sum(t for _, rs in groups for _, t in rs)
    mx = sum(k * t for k, rs in groups for _, t in rs) / X
    my = sum(s for _, rs in groups for s, _ in rs) / X
    num = sum(k * s for k, rs in groups for s, _ in rs) - mx * my * X
    den = sum(k * k * t for k, rs in groups for _, t in rs) - mx * mx * X
    return 100 * num / den


def boot_slope(spec, seed=11):
    rng = random.Random(seed)
    obs = fit([(k, by[a]) for a, k in spec])
    v = []
    for _ in range(B):
        v.append(fit([(k, [rng.choice(by[a]) for _ in by[a]]) for a, k in spec]))
    v.sort()
    return obs, v[int(.025 * B)], v[int(.975 * B) - 1]


SPECS = {
    "all eight arms (law.py; paper 3.6)": [("solo", 1), ("f6ind", 1), ("bribe1", 2), ("bribe2", 3), ("f6rival", 3),
                                           ("bribe", 4), ("f4", 4), ("f6", 6)],
    "within f (law2.py; paper 4.2)": [("solo", 1), ("bribe1", 2), ("bribe2", 3), ("bribe", 4), ("f4", 4)],
    "per bribe, 0-3 bribes (trend.py; paper 3.9)": [("solo", 0), ("bribe1", 1), ("bribe2", 2), ("bribe", 3)],
}
bull = {name: boot_slope(spec) for name, spec in SPECS.items()}

# ---------------- Mysticeti gains ----------------
mby = {}
for l in open(MLAW):
    r = json.loads(l)
    mby.setdefault(r["arm"], []).append((r["succ"], r["pairs"]))
pooled = lambda rs: 100 * sum(s for s, _ in rs) / sum(t for _, t in rs)
REF = {"k1": 1, "b2": 2, "b4": 4, "c4": 4, "c6": 6}
rng = random.Random(12)
boots = {a: [] for a in mby}
for _ in range(B):
    for a, rs in mby.items():
        boots[a].append(pooled([rng.choice(rs) for _ in rs]))


def ci(v):
    v = sorted(v)
    return v[int(.025 * len(v))], v[int(.975 * len(v)) - 1]


myst = {"base": (pooled(mby["base"]), *ci(boots["base"]), len(mby["base"]))}
for a, k in REF.items():
    lift = pooled(mby[a]) - pooled(mby["base"])
    lb = [x - y for x, y in zip(boots[a], boots["base"])]
    myst[a] = {"refusals": k, "rate": pooled(mby[a]), "lift": lift, "lift_ci": ci(lb), "runs": len(mby[a]),
               "per_refusal_avg": lift / k, "per_refusal_avg_ci": tuple(x / k for x in ci(lb))}
# marginal per refusal between measured points (Prop. (i) prices the next refusal)
marg = {}
for lo, hi in (("b2", "b4"), ("b4", "c6"), ("c4", "c6")):
    d = (pooled(mby[hi]) - pooled(mby[lo])) / (REF[hi] - REF[lo])
    db = [(x - y) / (REF[hi] - REF[lo]) for x, y in zip(boots[hi], boots[lo])]
    marg[f"{lo}->{hi}"] = (d, *ci(db))

# ---------------- trade values ----------------
V = [float(r["usd"]) for r in csv.DictReader(open(CSV))]
V.sort()
n = len(V)
p99 = V[int(.99 * (n - 1))]          # same index rule as value/real_value.py
vals = {"n": n, "median": st.median(V), "mean": st.mean(V), "p99": p99, "max": V[-1],
        "mean_p99_capped": st.mean(min(x, p99) for x in V),
        "mean_p99_trimmed": st.mean(x for x in V if x <= p99)}

out = {"bullshark_slopes": {k: {"s": v[0], "ci95": [v[1], v[2]]} for k, v in bull.items()},
       "mysticeti": myst, "mysticeti_marginal_per_refusal": {k: {"s": v[0], "ci95": [v[1], v[2]]} for k, v in marg.items()},
       "values": vals}
if len(sys.argv) > 1:  # optional JSON dump of all numbers
    json.dump(out, open(sys.argv[1], "w"), indent=1)

# ---------------- table ----------------
KAPPA = (0.001, 0.005, 0.01)
rows = []
for name, (s, lo, hi) in bull.items():
    rows.append(("Bullshark", name, s, lo, hi))
# n=25 slope transcribed from the project log (law25.py); not recomputed here
rows.append(("Bullshark", "n=25 (law25.py, transcribed)", 2.52, 1.10, 3.92))
for a in ("k1", "b2", "b4", "c4", "c6"):
    m = myst[a]
    rows.append(("Mysticeti", f"{m['refusals']} refusals ({a}), average per refusal = lift {m['lift']:+.2f} / {m['refusals']}",
                 m["per_refusal_avg"], *m["per_refusal_avg_ci"]))
for k, (s, lo, hi) in marg.items():
    rows.append(("Mysticeti", f"marginal per refusal {k}", s, lo, hi))

mean, cap, med = vals["mean"], vals["mean_p99_capped"], vals["median"]
print(f"values: n={n} median={med:.2f} mean={mean:.2f} p99={p99:.0f} max={V[-1]:.0f} "
      f"p99-capped mean={cap:.2f} p99-trimmed mean={vals['mean_p99_trimmed']:.2f}")
print(f"check: 0.063*mean={0.063*mean:.2f}  0.063*capped={0.063*cap:.2f}")
print()
hdr = "| Protocol | s source | s (points/refusal) [95% CI] | s x mean ($) | x kappa 0.1% | 0.5% | 1% | s x capped mean ($) | x kappa 0.1% | 0.5% | 1% |"
print(hdr)
print("|" + "---|" * 11)
for proto, name, s, lo, hi in rows:
    a = s / 100 * mean
    c = s / 100 * cap
    print(f"| {proto} | {name} | {s:.2f} [{lo:.2f}, {hi:.2f}] | {a:.2f} | {a*KAPPA[0]:.3f} | {a*KAPPA[1]:.2f} | {a*KAPPA[2]:.2f} | "
          f"{c:.2f} | {c*KAPPA[0]:.3f} | {c*KAPPA[1]:.2f} | {c*KAPPA[2]:.2f} |")
print()
print("Mysticeti arms (pooled, run bootstrap 95% CI):")
print(f"  base {myst['base'][0]:.2f} [{myst['base'][1]:.2f},{myst['base'][2]:.2f}] runs={myst['base'][3]}")
for a in ("k1", "b2", "b4", "c4", "c6"):
    m = myst[a]
    print(f"  {a}: k={m['refusals']} rate {m['rate']:.2f} lift {m['lift']:+.2f} [{m['lift_ci'][0]:+.2f},{m['lift_ci'][1]:+.2f}] runs={m['runs']}")
