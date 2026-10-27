#!/usr/bin/env python3
"""Front-running value on Bullshark with real trade sizes.

Values: |USDC/USDT leg| of successful Sui mainnet transactions that touch a DEX pool, deduplicated
by digest. They were extracted once from our read-only census of mainnet transactions (about 80 MB,
not shipped) by census_values() below, and the 1,752 amounts are shipped in that order in
data/sui_value/sui_mainnet_trade_values.csv, which values() reads.
Outcomes: per-transaction results of the Bullshark front-running campaign (txc, 16 runs per arm),
data/bullshark/bullshark_frontrun/txc_pertx.jsonl. A victim transaction is won when the attacker's
copy commits first. Bullshark's order never reads a transaction's value, so values are assigned i.i.d.
Usage: python3 real_value.py [bootstrap resamples, default 2000]
"""
import json, random, statistics as st, sys, os
H = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(H, "../../data")

def values():
    """The shipped trade sizes (USD), in the order census_values() produced them."""
    with open(os.path.join(DATA, "sui_value/sui_mainnet_trade_values.csv")) as f:
        next(f)                                  # header: usd
        return [float(l) for l in f if l.strip()]

def census_values(CEN):
    """How the shipped values were extracted (needs the census files, which are not shipped)."""
    seen, v = set(), []
    for f in ("census_seed1.jsonl", "census_seed2.jsonl", "census_6mo_seed3.jsonl"):
        for l in open(os.path.join(CEN, f)):
            r = json.loads(l)
            if r.get("kind") == "meta" or not r.get("ok") or r["digest"] in seen:
                continue
            if not any("pool" in s[1].lower() for s in r.get("shared", [])):
                continue
            for coin, amt in r.get("bal", []):
                if coin.split("::")[-1] in ("USDC", "USDT"):
                    seen.add(r["digest"]); v.append(abs(amt) / 1e6); break
    return v

def runs():
    out = {}
    for l in open(os.path.join(DATA, "bullshark/bullshark_frontrun/txc_pertx.jsonl")):
        r = json.loads(l)
        out.setdefault(r["arm"], []).append(r["txs"])
    return out

ARMS = {"tbase1": "no attack (1 attacker)", "tsolo": "fissure, 1 attacker", "tbribe3": "fissure, 1 attacker + 3 bribes",
        "tbase4": "no attack (4 attackers)", "tf4": "fissure, 4 attackers"}

def stats(R, V, cap=None, B=4000, seed=1):
    rng = random.Random(seed)
    Vc = [min(x, cap) for x in V] if cap else V
    def arm_stat(txs_list, draw):
        sh, vpt = [], []
        for txs in txs_list:
            vals = [draw() for _ in txs]
            tot = sum(vals); won = sum(v for v, t in zip(vals, txs) if t[2])
            sh.append(100 * won / tot if tot else 0); vpt.append(won / len(txs) if txs else 0)
        return st.mean(sh), st.mean(vpt)
    res = {}
    for a, L in R.items():
        cnt = st.mean(100 * sum(t[2] for t in txs) / len(txs) for txs in L)
        boots = []
        for _ in range(B):
            Lb = [rng.choice(L) for _ in L]
            boots.append(arm_stat(Lb, lambda: rng.choice(Vc)))
        res[a] = {"count_share": cnt, "boots": boots}
    return res

if __name__ == "__main__":
    V = values(); R = runs()
    print(f"values n={len(V)} median={st.median(V):.2f} mean={st.mean(V):.2f} p99={sorted(V)[int(.99*(len(V)-1))]:.0f} max={max(V):.0f}")
    for cap in (None, sorted(V)[int(.99 * (len(V) - 1))]):
        res = stats(R, V, cap=cap, B=int(sys.argv[1]) if len(sys.argv) > 1 else 2000)
        print("\n== cap", cap)
        def ci(xs): xs = sorted(xs); return xs[int(.025 * len(xs))], xs[int(.975 * len(xs)) - 1]
        for a in ARMS:
            b = res[a]["boots"]; sh = [x[0] for x in b]; vp = [x[1] for x in b]
            print(f"{a:8s} count {res[a]['count_share']:.1f}  value-share {st.mean(sh):.1f} {tuple(round(x,1) for x in ci(sh))}  USD/victim-tx {st.mean(vp):.0f} {tuple(round(x) for x in ci(vp))}")
        for x, y in (("tsolo", "tbase1"), ("tbribe3", "tbase1"), ("tbribe3", "tsolo"), ("tf4", "tbase4")):
            d = [p[0] - q[0] for p, q in zip(res[x]["boots"], res[y]["boots"])]
            dv = [p[1] - q[1] for p, q in zip(res[x]["boots"], res[y]["boots"])]
            print(f"  {x}-{y}: share {st.mean(d):+.1f} {tuple(round(v,1) for v in ci(d))}  USD/tx {st.mean(dv):+.0f} {tuple(round(v) for v in ci(dv))}")
