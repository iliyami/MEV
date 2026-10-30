#!/usr/bin/env python3
"""Step 2b: extract pool-level swap events from the cached transaction events (parsed defensively).
Inputs: data/review/amm/trades.jsonl and $AMM_CACHE/events (from fetch_events.py, not shipped).
Output: data/review/amm/hops.jsonl. Usage: parse_hops.py
"""
import json, os, sys
from pathlib import Path
REPO = Path(__file__).resolve().parents[3]
DATA = REPO / "data/review/amm"                              # shipped inputs and regenerated outputs
CACHE = Path(os.environ.get("AMM_CACHE", DATA / "cache"))   # downloaded chain data (not shipped)
Q = 2 ** 64
# venue labels keyed by the package prefix of the pool-level event type
CETUS_STYLE = {"0x1eabed72": "Cetus CLMM", "0x4a35d3df": "Magma CLMM", "0xe74104c6": "Full Sail CLMM",
               "0xc895342d": "CLMM 0xc895342d (Cetus-style event)"}
XY_STYLE = {"0x70285592": "Momentum CLMM", "0xb5f529c1": "CLMM 0xb5f529c1 (Momentum-style event)",
            "0x25929e7f": "FlowX CLMM"}
OB = {"0x2c8d603b": "DeepBook v3 (order book)", "0xbf7915f9": "order book 0xbf7915f9 (quote layers)"}
ORACLE = {"0x0c6b6b0e": "oracle-priced pool 0x0c6b6b0e", "0xa0e3b011": "oracle-priced pool 0xa0e3b011",
          "0x09525dec": "oracle-priced pool 0x09525dec"}
BINS = {"0x5664f9d3": "bin-based pool 0x5664f9d3 (DLMM)", "0x5a5c1d10": "bin-based pool 0x5a5c1d10 (liquidity book)"}
OTHER = {"0x56f72145": "saturation-curve pool 0x56f72145", "0x97fea955": "composite pool 0x97fea955",
         "0xaedb8c9a": "composite pool 0xaedb8c9a", "0xc4049b2d": "Aftermath-style multi-asset pool",
         "0xba153169": "FlowX AMM v2 pair", "0xdae28ab9": "manage::Pool 0xdae28ab9",
         "0x361dd589": "pool 0x361dd589", "0xa0eba10b": "Kriya spot_dex"}

def I(x):
    return int(x)

def type_args(t):
    """Top-level generic args of a Move type string."""
    if "<" not in t:
        return []
    inner = t[t.index("<") + 1: t.rindex(">")]
    out, depth, cur = [], 0, ""
    for ch in inner:
        if ch == "<": depth += 1
        if ch == ">": depth -= 1
        if ch == "," and depth == 0:
            out.append(cur.strip()); cur = ""
        else:
            cur += ch
    if cur.strip(): out.append(cur.strip())
    return out

def norm_coin(c):
    c = c if c.startswith("0x") else "0x" + c
    return c

def parse(row, evs):
    pools = {p[0]: p for p in row["shared"]}
    hops, other = [], []
    for k, e in enumerate(evs):
        t = e["contents"]["type"]["repr"]; j = e["contents"]["json"] or {}
        base = t.split("<")[0]; pk = base.split("::")[0][:10]; nm = "::".join(base.split("::")[1:])
        h = None
        try:
            if pk in CETUS_STYLE and nm == "pool::SwapEvent":
                pid = j["pool"]; a2b = bool(j["atob"])
                h = dict(kind="clmm", style="cetus", venue=CETUS_STYLE[pk], pool=pid, a2b=a2b,
                         gross_in=I(j["amount_in"]), out=I(j["amount_out"]), fee=I(j["fee_amount"]),
                         S0=I(j["before_sqrt_price"]), S1=I(j["after_sqrt_price"]), L_event=None)
            elif pk == "0x3492c874" and nm in ("events::AssetSwap", "events::FlashSwap"):
                pid = j["pool_id"]; a2b = bool(j["a2b"])
                h = dict(kind="clmm", style="bluefin", venue="Bluefin CLMM" + (" (flash swap)" if "Flash" in nm else ""),
                         pool=pid, a2b=a2b, gross_in=I(j["amount_in"]), out=I(j["amount_out"]), fee=I(j["fee"]),
                         S0=I(j["before_sqrt_price"]), S1=I(j["after_sqrt_price"]), L_event=I(j["before_liquidity"]),
                         L_after=I(j["after_liquidity"]), exceeded=j.get("exceeded"))
            elif pk == "0x91bfbc38" and nm == "pool::SwapEvent":
                pid = j["pool"]; a2b = bool(j["a_to_b"])
                ai, bi = I(j["amount_a"]), I(j["amount_b"])
                h = dict(kind="clmm", style="turbos", venue="Turbos CLMM", pool=pid, a2b=a2b,
                         gross_in=ai if a2b else bi, out=bi if a2b else ai, fee=I(j["fee_amount"]),
                         S0=None, S1=I(j["sqrt_price"]), L_event=I(j["liquidity"]),
                         tick_pre=j["tick_pre_index"]["bits"], tick_cur=j["tick_current_index"]["bits"],
                         exact_in=j.get("is_exact_in"))
            elif pk in XY_STYLE and nm in ("trade::SwapEvent", "pool::Swap"):
                pid = j["pool_id"]; a2b = bool(j["x_for_y"])
                ax, ay = I(j["amount_x"]), I(j["amount_y"])
                h = dict(kind="clmm", style="xy", venue=XY_STYLE[pk], pool=pid, a2b=a2b,
                         gross_in=ax if a2b else ay, out=ay if a2b else ax, fee=I(j["fee_amount"]),
                         S0=I(j["sqrt_price_before"]), S1=I(j["sqrt_price_after"]), L_event=I(j["liquidity"]))
            elif pk in OB or pk in ORACLE or pk in BINS or pk in OTHER:
                if any(w in nm.split("::")[-1].lower() for w in ("swap", "filled", "buybase", "sellbase", "consumeexecuted")) \
                        and "Confirm" not in nm and "Repay" not in nm and "Result" not in nm:
                    lab = OB.get(pk) or ORACLE.get(pk) or BINS.get(pk) or OTHER.get(pk)
                    pid = j.get("pool_id") or j.get("pool") or j.get("pair")
                    other.append(dict(venue=lab, event=nm, pool=pid, ev_index=k, json=j))
        except (KeyError, TypeError, ValueError) as ex:
            other.append(dict(venue="parse-error", event=nm, err=str(ex), ev_index=k))
            continue
        if h:
            p = pools.get(h["pool"])
            h["pool_type"] = p[1] if p else None
            args = type_args(p[1]) if p else []
            if len(args) >= 2:
                A, B = norm_coin(args[0]), norm_coin(args[1])
                h["coin_in"], h["coin_out"] = (A, B) if h["a2b"] else (B, A)
            else:
                h["coin_in"] = h["coin_out"] = None
            h["ev_index"] = k
            hops.append(h)
    return hops, other

if __name__ == "__main__":
    rows = [json.loads(l) for l in open(DATA / "trades.jsonl")]
    with open(DATA / "hops.jsonl", "w") as o:
        for r in rows:
            d = json.load(open(CACHE / "events" / (r["digest"] + ".json")))
            hops, other = parse(r, d["events"])
            o.write(json.dumps(dict(i=r["i"], digest=r["digest"], usd=r["usd"], hops=hops, other=other,
                                    n_events=len(d["events"]))) + "\n")
