#!/usr/bin/env python3
"""Step 3: per-trade sandwich profit under a constant-product model of the victim's own pool, at slippage
tolerance tau = 0.5%, 1%, 3%. Inputs: data/review/amm/trades.jsonl, hops.jsonl (parse_hops.py) and the
cached events and pool objects in $AMM_CACHE (not shipped). Outputs: data/review/amm/trade_profit.jsonl
(shipped) and hop_model.jsonl. Usage: model.py
"""
import json, os, sys, math, collections
from pathlib import Path
REPO = Path(__file__).resolve().parents[3]
DATA = REPO / "data/review/amm"                              # shipped inputs and regenerated outputs
CACHE = Path(os.environ.get("AMM_CACHE", DATA / "cache"))   # downloaded chain data (not shipped)
Q = 2 ** 64
TAUS = (0.005, 0.01, 0.03)
STABLE = {"0xdba34672e30cb065b1f93e3ab55318768fd6fef66c15942c9f7cb846e2f900e7::usdc::USDC": 1e-6,
          "0x375f70cf2ae4c00bf37117d0c85a2c71545e6ee05c4a5c7d282cd66a4504b068::usdt::USDT": 1e-6}  # USD per raw unit (6 decimals, verified)

def nc(c):
    """normalise a coin type: 0x-prefixed, address without leading zeros."""
    if c is None: return None
    c = c.strip()
    addr, rest = c.split("::", 1)
    addr = addr[2:] if addr.startswith("0x") else addr
    return "0x" + addr.lstrip("0").rjust(64, "0") + "::" + rest
STABLE = {nc(k): v for k, v in STABLE.items()}

def type_args(t):
    if not t or "<" not in t: return []
    inner = t[t.index("<") + 1: t.rindex(">")]
    out, depth, cur = [], 0, ""
    for ch in inner:
        if ch == "<": depth += 1
        if ch == ">": depth -= 1
        if ch == "," and depth == 0: out.append(cur.strip()); cur = ""
        else: cur += ch
    if cur.strip(): out.append(cur.strip())
    return out

def obj(o, v):
    p = CACHE / "objects" / f"{o}@{v}.json"
    if not os.path.exists(p): return None
    d = json.load(open(p))
    return (d or {}).get("asMoveObject", {}).get("contents") if d else None

# ---------------- sandwich model ----------------
def swap(r, s, g, d):
    """gross input d into reserves (r in, s out); fee (1-g) leaves the curve. returns out, r', s'."""
    n = g * d
    o = s * n / (r + n)
    return o, r + n, s - o

def sandwich_profit(r, s, g, dv, a):
    oa, r1, s1 = swap(r, s, g, a)
    ov, r2, s2 = swap(r1, s1, g, dv)
    b, _, _ = swap(s2, r2, g, oa)      # sell oa of the out-token back
    return b - a, ov

def a_max(r, s, g, dv, tau):
    """largest gross front-run that keeps the victim's output >= (1-tau) x its no-attack output (closed form)."""
    u = g * dv / r
    x = (-u + math.sqrt(u * u + 4 * (1 + u) / (1 - tau))) / 2   # r1/r
    return max(0.0, (x - 1) * r / g)

def best_frontrun(r, s, g, dv, tau):
    am = a_max(r, s, g, dv, tau)
    if am <= 0: return 0.0, 0.0, am
    f = lambda a: sandwich_profit(r, s, g, dv, a)[0]
    grid = [am * i / 400 for i in range(1, 401)] + [am * 10 ** (-k / 4) for k in range(1, 40)]
    best_a = max(grid, key=f)
    lo, hi = max(0.0, best_a - am / 400), min(am, best_a + am / 400)
    phi = (math.sqrt(5) - 1) / 2
    for _ in range(80):
        m1, m2 = hi - phi * (hi - lo), lo + phi * (hi - lo)
        if f(m1) < f(m2): lo = m1
        else: hi = m2
    for c in ((lo + hi) / 2, best_a, am):
        if f(c) > f(best_a): best_a = c
    p = f(best_a)
    return (p, best_a, am) if p > 0 else (0.0, 0.0, am)

# ---------------- hop construction ----------------
def merge_clmm(hops):
    """merge consecutive same-pool same-direction CLMM events (verified to chain exactly)."""
    out = []
    for h in hops:
        if out and out[-1]["pool"] == h["pool"] and out[-1]["a2b"] == h["a2b"] and out[-1]["kind"] == "clmm" \
                and out[-1]["S1"] == h.get("S0_true"):
            m = out[-1]
            m["gross_in"] += h["gross_in"]; m["out"] += h["out"]; m["fee"] += h["fee"]; m["S1"] = h["S1"]; m["n_merged"] += 1
        else:
            h = dict(h); h["S0"] = h.pop("S0_true"); h["n_merged"] = 1; out.append(h)
    return out

def build_hops(trade, rec, evs):
    sh = {p[0]: p for p in trade["shared"]}
    clmm = []
    flowx_fee = {}
    for h in rec["hops"]:
        h = dict(h)
        p = sh.get(h["pool"])
        pre = obj(p[0], p[2]) if p else None
        js = (pre or {}).get("json") or {}
        if h["pool_type"] is None:  # FlowX CLMM pools are dynamic fields; type from the latest object
            o = obj(h["pool"], None)
            if o:
                h["pool_type"] = o["type"]["repr"]
                A, B = type_args(h["pool_type"])[:2]
                h["coin_in"], h["coin_out"] = (A, B) if h["a2b"] else (B, A)
        # fee rate (per 1e6 in the pool object, at the consumed version)
        f = None
        for k in ("fee_rate", "swap_fee_rate", "fee"):
            if k in js and str(js[k]).isdigit():
                f = int(js[k]) / 1e6; break
        h["f_src"] = "pool object"
        if f is None:
            f = h["fee"] / h["gross_in"] if h["gross_in"] else None; h["f_src"] = "event fee/amount_in"
        h["f"] = f
        # pre-trade sqrt price
        if h["style"] == "turbos":
            L = h["L_event"]; S1 = h["S1"]
            if h["a2b"]: S0 = S1 + h["out"] * Q / L
            else: S0 = 1 / (1 / S1 + h["out"] / (L * Q))
            h["S0_true"] = S0
        elif h["venue"].startswith("Magma"):
            post = obj(p[0], p[3]) if p else None
            h["S0_true"] = int(js["current_sqrt_price"]); h["S1"] = int(((post or {}).get("json") or {})["current_sqrt_price"])
        else:
            h["S0_true"] = h["S0"]
        # pre-trade active liquidity: pool object at the consumed version; event value when no object
        h["L_pre"] = int(js["liquidity"]) if "liquidity" in js else h.get("L_event")
        clmm.append(h)
    hops = merge_clmm(clmm)
    # first hop on each pool uses the consumed-version object; later separate hops on the same pool use event L
    seen = set()
    for h in hops:
        h["repeat_pool"] = h["pool"] in seen
        seen.add(h["pool"])
        S0, S1 = h["S0"], h["S1"]
        s0, s1 = S0 / Q, S1 / Q
        # calibrated liquidity reproducing the victim's own output over its price move
        try:
            h["L_cal"] = h["out"] / (s0 - s1) if h["a2b"] else h["out"] / (1 / s0 - 1 / s1)
            if h["L_cal"] <= 0: h["L_cal"] = None
        except ZeroDivisionError:
            h["L_cal"] = None
        if h["n_merged"] > 1: h["L_pre"] = h["L_cal"]
        if h["repeat_pool"]: h["L_pre"] = h.get("L_event") or h["L_cal"]   # consumed-version object no longer applies
        h["model"] = "clmm virtual reserves"
    # constant-product venues verified against pre-trade pool objects
    cp = []
    for o in rec["other"]:
        v, j = o["venue"], o.get("json") or {}
        try:
            if v == "Kriya spot_dex":
                p = sh.get(j["pool_id"]);  t = evs[o["ev_index"]]["contents"]["type"]["repr"]
                c = (obj(p[0], p[2]) if p else None)
                if not c or c["json"].get("is_stable"): continue
                A, B = [nc(x) for x in type_args(c["type"]["repr"])[:2]]; cin = nc(type_args(t)[0])
                X, Y = int(c["json"]["token_x"]), int(c["json"]["token_y"])
                g = 1 - int(c["json"]["lp_fee_percent"]) / 1e6
                x_in = cin == A
                cp.append(dict(venue=v, pool=p[0], r=X if x_in else Y, s=Y if x_in else X, g=g,
                               gross_in=int(j["amount_in"]), out=int(j["amount_out"]), coin_in=A if x_in else B, coin_out=B if x_in else A))
            elif v == "manage::Pool 0xdae28ab9":
                name = j["lp_name"][3:]
                for p in sh.values():
                    if not p[1].startswith("0xdae28ab9"): continue
                    A, B = [nc(x) for x in type_args(p[1])[:2]]
                    if name != (A[2:] + "-" + B[2:]) and name != (A[2:].lstrip("0") + "-" + B[2:]) and \
                       nc("0x" + name.split("-")[0]) + "|" + nc("0x" + name.split("-")[1]) != A + "|" + B:
                        continue
                    c = obj(p[0], p[2]); X, Y = int(c["json"]["bal_x"]), int(c["json"]["bal_y"])
                    g = 1 - int(c["json"]["fee_rate"]) / 1e4
                    if int(j["value_x_in"]) > 0:
                        cp.append(dict(venue=v, pool=p[0], r=X, s=Y, g=g, gross_in=int(j["value_x_in"]), out=int(j["value_y_out"]), coin_in=A, coin_out=B))
                    else:
                        cp.append(dict(venue=v, pool=p[0], r=Y, s=X, g=g, gross_in=int(j["value_y_in"]), out=int(j["value_x_out"]), coin_in=B, coin_out=A))
                    break
            elif v == "pool 0x361dd589":
                for p in sh.values():
                    if not p[1].startswith("0x361dd589"): continue
                    c = obj(p[0], p[2])
                    if not c or c["json"].get("index") != j["pool_index"] or c["json"].get("pool_type") != 100: continue
                    A, B = [nc(x) for x in type_args(c["type"]["repr"])[:2]]
                    X, Y = int(c["json"]["balance"]["x"]), int(c["json"]["balance"]["y"])
                    fe = c["json"]["fee"]; g = 1 - (int(fe["lp"]) + int(fe["admin"]) + int(fe["th"])) / 1e4
                    if j["x_to_y"]:
                        cp.append(dict(venue=v, pool=p[0], r=X, s=Y, g=g, gross_in=int(j["in_amount"]), out=int(j["out_amount"]), coin_in=A, coin_out=B))
                    else:
                        cp.append(dict(venue=v, pool=p[0], r=Y, s=X, g=g, gross_in=int(j["in_amount"]), out=int(j["out_amount"]), coin_in=B, coin_out=A))
                    break
        except (KeyError, TypeError, ValueError, IndexError):
            continue
    cnt = collections.Counter(h["pool"] for h in cp)
    cp = [h for h in cp if cnt[h["pool"]] == 1]   # pre-trade object is exact only for a single event per pool
    for h in cp: h["model"] = "constant product"
    return hops, cp

def reserves(h, which):
    """virtual reserves (r_in, s_out, g) for a hop."""
    if h["model"] == "constant product":
        return h["r"], h["s"], h["g"]
    L = h["L_pre"] if which == "pre" else h["L_cal"]
    if not L: return None
    s0 = h["S0"] / Q
    x, y = L / s0, L * s0                     # virtual reserves of coin A and coin B (raw units)
    r, s = (x, y) if h["a2b"] else (y, x)
    return r, s, 1 - h["f"]

# ---------------- USD pricing within the transaction ----------------
def usd_prices(edges):
    """edges: list of (coin_u, coin_v, rate raw v per raw u). BFS from the two stablecoins."""
    adj = collections.defaultdict(list)
    for u, v, rate in edges:
        if u and v and rate and rate > 0 and math.isfinite(rate):
            adj[u].append((v, rate)); adj[v].append((u, 1 / rate))
    price = {c: p for c, p in STABLE.items()}
    frontier = list(price)
    while frontier:
        nxt = []
        for u in frontier:
            for v, rate in adj[u]:
                if v not in price:
                    price[v] = price[u] / rate   # USD per raw v = USD per raw u / (raw v per raw u)
                    nxt.append(v)
        frontier = nxt
    return price

def deepbook_edges(trade, rec):
    sh = {p[0]: p for p in trade["shared"]}
    out = []
    for o in rec["other"]:
        if o["venue"].startswith("DeepBook") and o["event"] == "order_info::OrderFilled":
            j = o["json"]; p = sh.get(j.get("pool_id"))
            if not p: continue
            a = type_args(p[1])
            if len(a) < 2: continue
            bq, qq = int(j["base_quantity"]), int(j["quote_quantity"])
            if bq > 0 and qq > 0: out.append((nc(a[0]), nc(a[1]), qq / bq))
    return out

def ts_of(tr):
    from datetime import datetime
    return datetime.fromisoformat(tr["ts"].replace("Z", "+00:00")).timestamp()

def global_prices(trades):
    """coin -> sorted list of (timestamp, USD per raw unit) from in-transaction price paths of all trades."""
    obs = collections.defaultdict(list)
    for l in open(DATA / "hops.jsonl"):
        rec = json.loads(l); tr = trades[rec["digest"]]
        evs = json.load(open(CACHE / "events" / (rec["digest"] + ".json")))["events"]
        clmm, cp = build_hops(tr, rec, evs)
        edges = []
        for h in clmm + cp:
            rs = reserves(h, "pre") or reserves(h, "cal")
            if rs: edges.append((nc(h.get("coin_in")), nc(h.get("coin_out")), rs[1] / rs[0]))
        edges += deepbook_edges(tr, rec)
        for c, p in usd_prices(edges).items():
            if c not in STABLE: obs[c].append((ts_of(tr), p))
    return {c: sorted(v) for c, v in obs.items()}

def nearest_price(G, coin, t, k=5):
    v = G.get(coin)
    if not v: return None
    near = sorted(v, key=lambda x: abs(x[0] - t))[:k]
    ps = sorted(p for _, p in near)
    return ps[len(ps) // 2]

if __name__ == "__main__":
    trades = {json.loads(l)["digest"]: json.loads(l) for l in open(DATA / "trades.jsonl")}
    G = global_prices(trades)
    fo = open(DATA / "trade_profit.jsonl", "w")
    ho = open(DATA / "hop_model.jsonl", "w")
    for l in open(DATA / "hops.jsonl"):
        rec = json.loads(l); tr = trades[rec["digest"]]
        evs = json.load(open(CACHE / "events" / (rec["digest"] + ".json")))["events"]
        clmm, cp = build_hops(tr, rec, evs)
        allh = clmm + cp
        for h in allh:
            h["coin_in"], h["coin_out"] = nc(h.get("coin_in")), nc(h.get("coin_out"))
        edges = []
        for h in allh:
            rs = reserves(h, "pre") or reserves(h, "cal")
            if rs: edges.append((h["coin_in"], h["coin_out"], rs[1] / rs[0]))
        edges += deepbook_edges(tr, rec)
        price = usd_prices(edges)
        res = dict(i=rec["i"], digest=rec["digest"], usd=rec["usd"], n_hops_modeled=len(allh),
                   venues=sorted(set(h["venue"] for h in allh)),
                   other_venues=sorted(set(o["venue"] for o in rec["other"])))
        if allh: res["category"] = "swap, modeled"
        elif rec["other"]: res["category"] = "swap, venue not modeled"
        else:
            d = [e["contents"]["type"]["repr"].split("<")[0].split("::")[-1].lower() for e in evs]
            res["category"] = "swap, venue not modeled" if any(("swap" in x) for x in d) else "no swap (liquidity or other operation)"
        for which in ("pre", "cal"):
            best = {t: (0.0, None) for t in TAUS}
            for k, h in enumerate(allh):
                rs = reserves(h, which)
                if not rs: continue
                r, s, g = rs
                pu = price.get(h["coin_in"]); psrc = "in-transaction path"
                if not pu:
                    pu = nearest_price(G, h["coin_in"], ts_of(tr)); psrc = "nearest-in-time other trades" if pu else "unpriced"
                hop = dict(price_src=psrc, digest=rec["digest"], k=k, which=which, venue=h["venue"], model=h["model"],
                           gross_in=h["gross_in"], out=h["out"], f=1 - g, coin_in=h["coin_in"], coin_out=h["coin_out"],
                           usd_per_raw_in=pu, n_merged=h.get("n_merged", 1))
                ov = swap(r, s, g, h["gross_in"])[0]
                hop["model_out_over_actual"] = ov / h["out"] if h["out"] else None
                hop["in_usd"] = h["gross_in"] * pu if pu else None
                for t in TAUS:
                    p, a, am = best_frontrun(r, s, g, h["gross_in"], t)
                    hop[f"profit_raw_{t}"] = p; hop[f"frontrun_raw_{t}"] = a
                    hop[f"profit_usd_{t}"] = p * pu if pu else None
                    hop[f"frontrun_usd_{t}"] = a * pu if pu else None
                    if pu and p * pu > best[t][0]: best[t] = (p * pu, k)
                ho.write(json.dumps(hop) + "\n")
                if which == "pre" and not pu: res["unpriced_hop"] = True
                if which == "pre" and psrc.startswith("nearest"): res["fallback_priced_hop"] = True
            for t in TAUS:
                res[f"profit_{which}_{t}"] = best[t][0]; res[f"best_hop_{which}_{t}"] = best[t][1]
        res["hops"] = [dict(venue=h["venue"], pool=h["pool"], coin_in=h["coin_in"], coin_out=h["coin_out"],
                            gross_in=h["gross_in"], out=h["out"], model=h["model"]) for h in allh]
        fo.write(json.dumps(res) + "\n")
    fo.close(); ho.close()
