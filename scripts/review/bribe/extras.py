#!/usr/bin/env python3
"""Small checks behind the refusal analysis: rounds to flag an every-round refuser as a function of the
honest omission rate p0 (two rounds at p0 = 1%), and the dollar worth of one refusal at s = 4.22 and
6.56 points. Input: data/sui_value/sui_mainnet_trade_values.csv (in the repo). Usage: extras.py
"""
import math, csv, statistics as st
from pathlib import Path
# rounds to flag an always-refuser at 1% false alarm, binomial, as a function of the honest omission rate p0
print("p0 -> rounds (p0^N <= 0.01)")
for p0 in (0.0003, 0.01, 0.03, 0.05, 0.1, 0.2, 0.3, 0.5, 0.7):
    print(f"  {p0}: {math.ceil(math.log(0.01)/math.log(p0))}")
# per-trade-size worth of one refusal at s = 4.22 (Bullshark within f) and 6.56 (Mysticeti marginal 4->6)
V = sorted(float(r["usd"]) for r in csv.DictReader(open(Path(__file__).resolve().parents[3] / "data/sui_value/sui_mainnet_trade_values.csv")))
n = len(V); p99 = V[int(.99*(n-1))]
pts = {"median": st.median(V), "mean": st.mean(V), "p99-capped mean": st.mean(min(x, p99) for x in V), "p99": p99, "max": V[-1]}
for s in (4.22, 6.56):
    print(f"s={s}: worth of one refusal = s/100 x kappa x T")
    for k, T in pts.items():
        print(f"  {k:16s} T=${T:,.2f}: s x T = ${s/100*T:,.2f}; kappa 0.1% ${s/100*T*0.001:,.4f}, 0.5% ${s/100*T*0.005:,.4f}, 1% ${s/100*T*0.01:,.4f}")
# executed-transaction in-round cross-check (txc campaign, values transcribed): solo 76.61, bribe3 80.37 -> per bribe
d = (80.37 - 76.61) / 3
print(f"in-round per bribe {d:.3f} points; x mean ${d/100*st.mean(V):.2f}; kappa 1% ${d/100*st.mean(V)*0.01:.3f}; x capped ${d/100*pts['p99-capped mean']:.2f}")
dv = (10.0 - 6.3) / 3
print(f"in-round value gain per bribe {dv:.3f} points; x mean ${dv/100*st.mean(V):.2f}")
