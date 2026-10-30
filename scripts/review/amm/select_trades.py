#!/usr/bin/env python3
"""Step 1: reproduce the 1,752-trade selection of the paper's trade values (n = 1,752, median $21.59,
mean $6,795.91) from the Sui mainnet census files census_seed1/2.jsonl and census_6mo_seed3.jsonl,
which are not in the repo. Usage: select_trades.py <census_dir> [out.jsonl]
Default output data/review/amm/trades.jsonl (shipped). Reads local files only.
"""
import json, os, sys, statistics as st
from pathlib import Path
CEN = sys.argv[1]
OUT = sys.argv[2] if len(sys.argv) > 2 else Path(__file__).resolve().parents[3] / "data/review/amm/trades.jsonl"
seen, rows = set(), []
for f in ("census_seed1.jsonl", "census_seed2.jsonl", "census_6mo_seed3.jsonl"):
    for l in open(os.path.join(CEN, f)):
        r = json.loads(l)
        if r.get("kind") == "meta" or not r.get("ok") or r["digest"] in seen:
            continue
        if not any("pool" in s[1].lower() for s in r.get("shared", [])):
            continue
        for coin, amt in r.get("bal", []):
            if coin.split("::")[-1] in ("USDC", "USDT"):
                seen.add(r["digest"])
                rows.append(dict(i=len(rows), digest=r["digest"], file=f, ck=r["ck"], ts=r["ts"],
                                 usd=abs(amt) / 1e6, stable_coin=coin, stable_amt=amt,
                                 bal=r["bal"], shared=r["shared"],
                                 pools=[s for s in r["shared"] if "pool" in s[1].lower()]))
                break
with open(OUT, "w") as o:
    for r in rows:
        o.write(json.dumps(r) + "\n")
V = [r["usd"] for r in rows]
print(f"n={len(V)} median={st.median(V):.2f} mean={st.mean(V):.2f} p99={sorted(V)[int(.99*(len(V)-1))]:.0f} max={max(V):.0f}")
