#!/usr/bin/env python3
"""Step 2a: fetch the events of each selected transaction from Sui mainnet (read-only GraphQL, cached).
Input: data/review/amm/trades.jsonl. Output: $AMM_CACHE/events/<digest>.json (untrusted data).
Not needed to rerun the paper numbers: trade_profit.jsonl is shipped. Usage: fetch_events.py
"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gql
from pathlib import Path
REPO = Path(__file__).resolve().parents[3]
DATA = REPO / "data/review/amm"                              # shipped inputs and regenerated outputs
CACHE = Path(os.environ.get("AMM_CACHE", DATA / "cache"))   # downloaded chain data (not shipped)
OUTD = str(CACHE / "events"); os.makedirs(OUTD, exist_ok=True)
FIELDS = "digest effects{ status timestamp events(first:50, after:%s){ pageInfo{hasNextPage endCursor} nodes{ contents{ type{ repr } json } } } }"
rows = [json.loads(l) for l in open(DATA / "trades.jsonl")]
todo = [r["digest"] for r in rows if not os.path.exists(os.path.join(OUTD, r["digest"] + ".json"))]
print("todo", len(todo), file=sys.stderr)
B = 10
for k in range(0, len(todo), B):
    chunk = todo[k:k + B]
    parts = [f't{i}: transaction(digest:"{d}"){{ {FIELDS % "null"} }}' for i, d in enumerate(chunk)]
    d = gql.q("query{ " + " ".join(parts) + " }")
    data = d.get("data") or {}
    for i, dg in enumerate(chunk):
        t = data.get(f"t{i}")
        if not t:
            print("missing", dg, json.dumps(d.get("errors"))[:300], file=sys.stderr); continue
        ev = t["effects"]["events"]
        nodes = list(ev["nodes"])
        while ev["pageInfo"]["hasNextPage"]:
            cur = json.dumps(ev["pageInfo"]["endCursor"])
            t2 = gql.q("query{ t0: transaction(digest:\"%s\"){ %s } }" % (dg, FIELDS % cur))["data"]["t0"]
            ev = t2["effects"]["events"]; nodes += ev["nodes"]
        out = dict(digest=dg, status=t["effects"]["status"], timestamp=t["effects"]["timestamp"], events=nodes)
        with open(os.path.join(OUTD, dg + ".json"), "w") as f:
            json.dump(out, f)
    if (k // B) % 10 == 0:
        print(k + len(chunk), "/", len(todo), "requests", gql.NREQ[0], file=sys.stderr)
print("done; requests", gql.NREQ[0], file=sys.stderr)
