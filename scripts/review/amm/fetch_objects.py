#!/usr/bin/env python3
"""Step 2c: fetch historical pool objects at given versions from Sui mainnet (read-only GraphQL, cached).
Input: a JSON list of [object_id, version_or_null], e.g. data/review/amm/obj_req1.json, obj_req2.json,
obj_req3.json (the lists we used). Output: $AMM_CACHE/objects/<id>@<ver>.json. Usage: fetch_objects.py <pairs.json>
"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gql
from pathlib import Path
REPO = Path(__file__).resolve().parents[3]
DATA = REPO / "data/review/amm"                              # shipped inputs and regenerated outputs
CACHE = Path(os.environ.get("AMM_CACHE", DATA / "cache"))   # downloaded chain data (not shipped)
OUTD = str(CACHE / "objects"); os.makedirs(OUTD, exist_ok=True)
def fname(oid, ver): return os.path.join(OUTD, f"{oid}@{ver}.json")
def fetch(pairs, B=10):
    todo = [(o, v) for o, v in pairs if not os.path.exists(fname(o, v))]
    for k in range(0, len(todo), B):
        ch = todo[k:k + B]
        parts = []
        for i, (o, v) in enumerate(ch):
            vv = f", version:{int(v)}" if v is not None else ""
            parts.append(f'o{i}: object(address:"{o}"{vv}){{ version asMoveObject{{ contents{{ type{{repr}} json }} }} }}')
        d = gql.q("query{ " + " ".join(parts) + " }")
        data = d.get("data") or {}
        for i, (o, v) in enumerate(ch):
            with open(fname(o, v), "w") as f:
                json.dump(data.get(f"o{i}"), f)
    return {(o, v): json.load(open(fname(o, v))) for o, v in pairs}
if __name__ == "__main__":
    pairs = json.load(open(sys.argv[1]))
    r = fetch([tuple(p) for p in pairs])
    print("fetched", len(r), "requests", gql.NREQ[0], "missing", sum(1 for v in r.values() if not v))
