"""Read-only Sui GraphQL client for the public mainnet endpoint, with an on-disk cache and a rate limit
(at most 4 requests/s). Only `query` operations are sent; mutations, execute, dry-run and simulate are
refused. Cache: $AMM_CACHE/gql (default data/review/amm/cache/gql, not shipped).
"""
import json, os, re, time, urllib.request, urllib.error, hashlib
from pathlib import Path
REPO = Path(__file__).resolve().parents[3]
DATA = REPO / "data/review/amm"                              # shipped inputs and regenerated outputs
CACHE = Path(os.environ.get("AMM_CACHE", DATA / "cache"))   # downloaded chain data (not shipped)
URL = "https://graphql.mainnet.sui.io/graphql"
CACHE = str(CACHE / "gql")
os.makedirs(CACHE, exist_ok=True)
_last = [0.0]
MIN_GAP = 0.25
NREQ = [0]

def q(query, variables=None, tries=8, use_cache=True):
    s = query.strip()
    if re.search(r"\bmutation\b", s) or "executeTransaction" in s or "dryRun" in s or "simulate" in s.lower():
        raise RuntimeError("refusing non-read GraphQL operation")
    key = hashlib.sha256(json.dumps([s, variables or {}], sort_keys=True).encode()).hexdigest()
    p = os.path.join(CACHE, key[:2], key + ".json")
    if use_cache and os.path.exists(p):
        with open(p) as f:
            return json.load(f)
    body = json.dumps({"query": s, "variables": variables or {}}).encode()
    delay, last = 1.0, None
    for _ in range(tries):
        gap = time.time() - _last[0]
        if gap < MIN_GAP:
            time.sleep(MIN_GAP - gap)
        _last[0] = time.time(); NREQ[0] += 1
        try:
            req = urllib.request.Request(URL, body, {"Content-Type": "application/json"})
            d = json.load(urllib.request.urlopen(req, timeout=90))
            if "errors" in d and not d.get("data"):
                if "VALIDATION" in json.dumps(d["errors"]):
                    raise ValueError(json.dumps(d["errors"])[:800])
                raise RuntimeError(json.dumps(d["errors"])[:500])
            break
        except (urllib.error.URLError, TimeoutError, RuntimeError, ConnectionError, json.JSONDecodeError) as e:
            last = e; time.sleep(delay); delay = min(delay * 2, 30)
    else:
        raise RuntimeError(f"query failed: {last}")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w") as f:
        json.dump(d, f)
    os.replace(tmp, p)
    return d
