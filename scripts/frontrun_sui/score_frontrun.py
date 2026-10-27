#!/usr/bin/env python3
"""Score a front-running run at the transaction level (review #64A, point A1).

Reads one or more test logs from `frontrun_attack_test` and reports, per run:
  victims       victim transactions committed
  reacted       victim transactions whose attacker copy was committed
  success       attacker copy committed before the victim transaction,
                as a share of all committed victim transactions
  cond_success  the same, as a share of reacted ones
  same_round    reactions placed in the victim's own round
and the reaction lag in rounds (from FRONTRUN_REACT lines, react arms only).

A front-run counts only when the attacker's transaction carries the victim's
id, so in the react arms every success is one the attacker caused after it saw
the victim's transaction in a block it had accepted.
"""
import json, re, statistics, sys

def parse(path):
    order, reacts, submits, summary = None, [], 0, ""
    with open(path, errors="replace") as f:
        for line in f:
            if "FINAL_TX_ORDER:" in line:
                order = json.loads(line.split("FINAL_TX_ORDER:", 1)[1].strip())
            elif "FRONTRUN_REACT:" in line:
                reacts.append(json.loads(line.split("FRONTRUN_REACT:", 1)[1].strip()))
            elif "FRONTRUN_SUBMIT:" in line:
                submits += 1
            elif "FRONTRUN_SUMMARY:" in line:
                summary = line.split("FRONTRUN_SUMMARY:", 1)[1].strip()
    if order is None:
        raise SystemExit(f"{path}: no FINAL_TX_ORDER line (run failed?)")
    return order, reacts, submits, summary

def exec_key(e):
    """Sui's execution order: commit by commit; inside a commit, PostConsensusTxReorder
    sorts by gas price descending with a stable sort, so equal gas keeps consensus order
    (sui-core post_consensus_tx_reorder.rs, on since protocol version 15)."""
    return (e["subdag"], -e.get("gas", 0), e["pos"])

def score(path, key=None):
    """key=None scores consensus order (pos); key=exec_key scores Sui's execution order."""
    order, reacts, submits, summary = parse(path)
    k = key or (lambda e: e["pos"])
    vic, fr = {}, {}
    for e in order:
        d = vic if e["tag"] == "V" else fr
        if e["id"] not in d or k(e) < k(d[e["id"]]):
            d[e["id"]] = e
    n_v = len(vic)
    reacted = [i for i in vic if i in fr]
    succ = [i for i in reacted if k(fr[i]) < k(vic[i])]
    same_commit = [i for i in reacted if fr[i]["subdag"] == vic[i]["subdag"]]
    same_round = [i for i in reacted if fr[i]["round"] == vic[i]["round"]]
    same_round_succ = [i for i in same_round if i in succ]
    lags = [r["own_round"] - r["vround"] for r in reacts if r.get("src", "block") == "block"]
    from_pool = sum(1 for r in reacts if r.get("src") == "mempool")
    pct = lambda a, b: 100.0 * a / b if b else float("nan")
    return {
        "run": path, "summary": summary, "submitted": submits,
        "victims": n_v, "reacted": len(reacted),
        "success_pct": pct(len(succ), n_v),
        "cond_success_pct": pct(len(succ), len(reacted)),
        "same_round_pct": pct(len(same_round), len(reacted)),
        "same_commit_pct": pct(len(same_commit), n_v),
        "same_round_success_pct": pct(len(same_round_succ), len(same_round)),
        "lag_rounds_median": statistics.median(lags) if lags else None,
        "lag0_pct": pct(sum(1 for x in lags if x == 0), len(lags)),
        "seen_pending_pct": pct(from_pool, len(reacts)),
        "waited_ms_median": statistics.median([r["waited_ms"] for r in reacts]) if reacts else None,
    }

if __name__ == "__main__":
    rows = [score(p) for p in sys.argv[1:]]
    print(json.dumps(rows, indent=1))
