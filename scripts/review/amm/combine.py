#!/usr/bin/env python3
"""Step 4: combine per-trade values (trade size, or sandwich profit) with the Bullshark race outcomes, as the
paper's in-round value analysis does (run bootstrap x i.i.d. value draws, B = 4,000, seed 7).
Inputs (in the repo): data/review/amm/trade_profit.jsonl, data/bullshark/bullshark_frontrun/txc_pertx.jsonl.
Usage: combine.py [B] [out.json]; default out data/review/amm/combine_B<B>.json (about 4 minutes at B = 4000).
"""
import json, os, random, statistics as st, sys
from pathlib import Path
REPO = Path(__file__).resolve().parents[3]
DATA = REPO / "data/review/amm"
RACES = REPO / "data/bullshark/bullshark_frontrun/txc_pertx.jsonl"   # per-tx race outcomes per run
ARMS = ("tbase1", "tsolo", "tbribe3", "tbase4", "tf4")
PAIRS = (("tsolo", "tbase1"), ("tbribe3", "tbase1"), ("tf4", "tbase4"), ("tbribe3", "tsolo"))
SEL = {"all": lambda t: True, "in_round": lambda t: t[3]}

def runs():
    out = {}
    for l in open(RACES):
        r = json.loads(l); out.setdefault(r["arm"], []).append(r["txs"])
    return out

def ci(x):
    x = sorted(x); return x[int(.025 * len(x))], x[int(.975 * len(x)) - 1]

def run_variant(V, R, sel, B, seed=7):
    rng = random.Random(seed)
    res = {}
    for a in ARMS:
        L = R[a]; usd, sh = [], []
        Ts = [[t for t in txs if sel(t)] for txs in L]
        for _ in range(B):
            u, s = [], []
            for T in (rng.choice(Ts) for _ in Ts):
                if not T: continue
                vals = rng.choices(V, k=len(T))
                won = sum(v for v, t in zip(vals, T) if t[2]); tot = sum(vals)
                u.append(won / len(T))
                if tot: s.append(100 * won / tot)
            usd.append(st.mean(u)); sh.append(st.mean(s) if s else float("nan"))
        cnt = st.mean(100 * sum(t[2] for t in T) / len(T) for T in Ts if T)
        res[a] = dict(races=cnt, usd=usd, share=sh)
    return res

def summarize(res):
    out = {"arms": {}, "diffs": {}}
    for a in ARMS:
        r = res[a]
        out["arms"][a] = dict(races=r["races"], usd_mean=st.mean(r["usd"]), usd_ci=ci(r["usd"]),
                              share_mean=st.mean(r["share"]), share_ci=ci(r["share"]))
    for x, y in PAIRS:
        du = [p - q for p, q in zip(res[x]["usd"], res[y]["usd"])]
        ds = [p - q for p, q in zip(res[x]["share"], res[y]["share"])]
        out["diffs"][f"{x}-{y}"] = dict(races=res[x]["races"] - res[y]["races"], usd_mean=st.mean(du), usd_ci=ci(du),
                                        share_mean=st.mean(ds), share_ci=ci(ds))
    return out

if __name__ == "__main__":
    B = int(sys.argv[1]) if len(sys.argv) > 1 else 4000
    R = runs()
    T = [json.loads(l) for l in open(DATA / "trade_profit.jsonl")]
    variants = {"trade size (paper's values)": [t["usd"] for t in T]}
    for tau in ("0.005", "0.01", "0.03"):
        variants[f"profit tau={tau}, all 1752 (0 where no model)"] = [t[f"profit_pre_{tau}"] for t in T]
    for tau in ("0.005", "0.01", "0.03"):
        variants[f"profit tau={tau}, modeled swaps only"] = [t[f"profit_pre_{tau}"] for t in T if t["category"] == "swap, modeled"]
    variants["profit tau=0.01, all 1752, trade-calibrated liquidity"] = [t["profit_cal_0.01"] for t in T]
    P = sorted(t["profit_pre_0.01"] for t in T); cap = P[int(.99 * (len(P) - 1))]
    variants["profit tau=0.01, all 1752, capped at p99"] = [min(t["profit_pre_0.01"], cap) for t in T]
    out = {}
    for name, V in variants.items():
        out[name] = {"n_values": len(V), "mean_value": st.mean(V)}
        for sname, sel in SEL.items():
            out[name][sname] = summarize(run_variant(V, R, sel, B))
        print("done", name, file=sys.stderr)
    json.dump(out, open(sys.argv[2] if len(sys.argv) > 2 else DATA / f"combine_B{B}.json", "w"), indent=1)
