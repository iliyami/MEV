#!/usr/bin/env python3
"""Tables and paper numbers for the sandwich-profit analysis (prints markdown to stdout).
Inputs (shipped): data/review/amm/trade_profit.jsonl and combine_B4000.json (or a path given as the first
argument). Prints: 1,229 swaps (median $7.36, mean $76.72), mean profit per swap, median $0, the lone
fissure gain (+$0.006 per victim tx, [-0.007, 0.019]) and the profit-share vs race-share gap.
"""
import json, os, collections, statistics as st, sys
from pathlib import Path
DATA = Path(__file__).resolve().parents[3] / "data/review/amm"
T = [json.loads(l) for l in open(DATA / "trade_profit.jsonl")]
C = json.load(open(sys.argv[1] if len(sys.argv) > 1 else DATA / "combine_B4000.json"))
L = []
def p(s=""): L.append(s)
# --- annotated per-trade record, only when hops.jsonl was regenerated (parse_hops.py)
if (DATA / "hops.jsonl").exists():
  TR = {json.loads(l)["digest"]: json.loads(l) for l in open(DATA / "trades.jsonl")}
  HP = {json.loads(l)["digest"]: json.loads(l) for l in open(DATA / "hops.jsonl")}
  with open(DATA / "trades_annotated.jsonl", "w") as o:
    for t in T:
        tr = TR[t["digest"]]; hp = HP[t["digest"]]
        o.write(json.dumps(dict(digest=t["digest"], usd_size=t["usd"], category=t["category"],
            pools=[dict(id=x[0], type=x[1]) for x in tr["pools"]],
            venues_modeled=t["venues"], venues_other=t["other_venues"],
            swap_events=[dict(venue=h["venue"], pool=h["pool"], a2b=h["a2b"], gross_in=h["gross_in"], out=h["out"], fee=h["fee"]) for h in hp["hops"]]
                        + [dict(venue=x["venue"], event=x["event"], pool=x.get("pool")) for x in hp["other"]],
            profit_usd={tau: t[f"profit_pre_{tau}"] for tau in ("0.005", "0.01", "0.03")},
            profit_usd_calibratedL={tau: t[f"profit_cal_{tau}"] for tau in ("0.005", "0.01", "0.03")})) + "\n")
# --- coverage
cat = collections.Counter(t["category"] for t in T)
tot = sum(t["usd"] for t in T)
p("| Category | Transactions | Median size ($) | Mean size ($) | Share of total $ |"); p("|---|---:|---:|---:|---:|")
for c in ("swap, modeled", "swap, venue not modeled", "no swap (liquidity or other operation)"):
    v = [t["usd"] for t in T if t["category"] == c]
    p(f"| {c} | {len(v)} | {st.median(v):.2f} | {st.mean(v):,.2f} | {100*sum(v)/tot:.1f}% |")
v = [t["usd"] for t in T]
p(f"| all | {len(v)} | {st.median(v):.2f} | {st.mean(v):,.2f} | 100% |")
p()
# --- distribution
p("| tau | Population | n | Median ($) | Mean ($) | Mean capped at p99 ($) | p99 ($) | Max ($) | Zero profit |"); p("|---|---|---:|---:|---:|---:|---:|---:|---:|")
for tau in ("0.005", "0.01", "0.03"):
    for nm, sel in (("all 1,752", lambda t: True), ("modeled swaps", lambda t: t["category"] == "swap, modeled")):
        P = sorted(t[f"profit_pre_{tau}"] for t in T if sel(t)); cap = P[int(.99 * (len(P) - 1))]
        p(f"| {float(tau)*100:g}% | {nm} | {len(P)} | {st.median(P):.4f} | {st.mean(P):.4f} | {st.mean(min(x, cap) for x in P):.4f} | {cap:.3f} | {P[-1]:.2f} | {100*sum(1 for x in P if x <= 0)/len(P):.1f}% |")
p()
# --- combination tables
NAMES = {"tbase1": "no attack (1 attacker)", "tsolo": "fissure, 1 attacker", "tbribe3": "fissure, 1 attacker + 3 bribes",
         "tbase4": "no attack (4 attackers)", "tf4": "fissure, 4 attackers"}
def ci(x, f="{:.4f}"): return "(" + f.format(x[0]) + ", " + f.format(x[1]) + ")"
for sel in ("in_round", "all"):
    p(f"**Selection: {sel}**"); p()
    p("| Values | Arm | Races won (%) | Value share (%) | $ per victim tx (95% CI) |"); p("|---|---|---:|---:|---:|")
    for name, v in C.items():
        for a in ("tbase1", "tsolo", "tbribe3", "tbase4", "tf4"):
            r = v[sel]["arms"][a]
            fmt = "{:,.0f}" if name.startswith("trade size") else "{:.4f}"
            p(f"| {name} | {NAMES[a]} | {r['races']:.1f} | {r['share_mean']:.1f} | {fmt.format(r['usd_mean'])} {ci(r['usd_ci'], fmt)} |")
    p()
    p("| Values | Comparison | Race gain (pts) | Value-share gain (pts, 95% CI) | $ gain per victim tx (95% CI) |"); p("|---|---|---:|---:|---:|")
    for name, v in C.items():
        for k, r in v[sel]["diffs"].items():
            fmt = "{:+,.0f}" if name.startswith("trade size") else "{:+.4f}"
            p(f"| {name} | {k} | {r['races']:+.1f} | {r['share_mean']:+.1f} {ci(r['share_ci'], '{:.1f}')} | {fmt.format(r['usd_mean'])} {ci(r['usd_ci'], fmt.replace('+',''))} |")
    p()
# --- the numbers the paper quotes
p("## Paper numbers (tau = 1%)"); p()
sw = [t for t in T if t["category"].startswith("swap")]
md = [t for t in T if t["category"] == "swap, modeled"]
for nm, X in (("swaps (modeled or not; 0 where no model)", sw), ("modeled swaps", md), ("all 1,752 transactions", T)):
    P = [t["profit_pre_0.01"] for t in X]; U = [t["usd"] for t in X]
    p(f"- {nm}: n = {len(X):,}, trade size median ${st.median(U):.2f} mean ${st.mean(U):.2f}; "
      f"profit mean ${st.mean(P):.4f}, median ${st.median(P):.4f}")
g = C["profit tau=0.01, all 1752 (0 where no model)"]["in_round"]["diffs"]["tsolo-tbase1"]
p(f"- lone fissure gain over its no-attack control (in-round): ${g['usd_mean']:+.4f} per victim tx "
  f"[{g['usd_ci'][0]:.4f}, {g['usd_ci'][1]:.4f}]")
gap = max((abs(r["share_mean"] - r["races"]), nm, sel, a) for nm, v in C.items() if not nm.startswith("trade")
          for sel in ("in_round", "all") for a, r in v[sel]["arms"].items())
r = C[gap[1]][gap[2]]["arms"][gap[3]]
p(f"- profit share vs race share, largest gap over all profit variants, arms and selections: {gap[0]:.3f} pts "
  f"({gap[1]}, {gap[2]}, {gap[3]}: races {r['races']:.1f}%, profit share {r['share_mean']:.1f}%)")
print("\n".join(L))
