#!/usr/bin/env python3
"""Value share with real trade sizes, over (i) all committed victim txs and (ii) races decided in the
victim's round (attacker copy in the same round), run bootstrap x value draws; permutation p over runs
for the count share. Usage: python3 inround_value.py [bootstrap resamples, default 2000]"""
import json, random, statistics as st, sys
from real_value import values, runs
V = values(); R = runs(); rng = random.Random(7); B = int(sys.argv[1]) if len(sys.argv) > 1 else 2000
def share(txs, sel, draw):
    T = [t for t in txs if sel(t)]
    vals = [draw() for _ in T]; tot = sum(vals)
    return 100 * sum(v for v, t in zip(vals, T) if t[2]) / tot if tot else None
def cnt(txs, sel):
    T = [t for t in txs if sel(t)]; return 100 * sum(t[2] for t in T) / len(T) if T else None
SEL = {"all": lambda t: True, "in_round": lambda t: t[3]}
def ci(x): x = sorted(x); return round(x[int(.025*len(x))],1), round(x[int(.975*len(x))-1],1)
for name, sel in SEL.items():
    print("==", name)
    boot = {}
    for a, L in R.items():
        bs = []
        for _ in range(B):
            Lb = [rng.choice(L) for _ in L]
            xs = [s for s in (share(t, sel, lambda: rng.choice(V)) for t in Lb) if s is not None]
            bs.append(st.mean(xs))
        boot[a] = bs
        c = [x for x in (cnt(t, sel) for t in L) if x is not None]
        print(f"  {a:8s} races {st.mean(c):.1f}  value {st.mean(bs):.1f} {ci(bs)}")
    for x, y in (("tsolo","tbase1"),("tbribe3","tbase1"),("tbribe3","tsolo"),("tf4","tbase4")):
        d = [p-q for p,q in zip(boot[x], boot[y])]
        cx = [v for v in (cnt(t, sel) for t in R[x]) if v is not None]; cy = [v for v in (cnt(t, sel) for t in R[y]) if v is not None]
        obs = st.mean(cx)-st.mean(cy); pool = cx+cy; k=0
        for _ in range(20000):
            rng.shuffle(pool); k += abs(st.mean(pool[:len(cx)])-st.mean(pool[len(cx):])) >= abs(obs)-1e-9
        print(f"    {x}-{y}: races {obs:+.1f} (perm p={k/20000:.3f})  value {st.mean(d):+.1f} {ci(d)}")
