#!/usr/bin/env python3
"""Score the Mysticeti refusal-law runs (run_mlaw.sh). For every round in which both the delegate
attacker (validator 0) and the victim (validator 12) have a committed block, the attacker wins if its
block is linearized in an earlier committed sub-DAG, loses if later, and a same-sub-DAG pair counts
one half, so the identity tiebreak (which decides only same-sub-DAG order) cannot move the rate and
the neutral point is 50%. Also reports the plain same-round position rate for reference."""
import json, re, sys, glob
def score(path, a=0, v=12):
    order = None
    for line in open(path, errors="replace"):
        if "FINAL_COMMITTED_ORDER:" in line:
            order = json.loads(line.split("FINAL_COMMITTED_ORDER:", 1)[1].strip())
    if order is None: return None
    A = {}; V = {}
    for e in order:
        d = A if e["creator"] == a else V if e["creator"] == v else None
        if d is not None and e["round"] not in d: d[e["round"]] = e
    rounds = sorted(set(A) & set(V))
    w = sum(1.0 if A[r]["subdag"] < V[r]["subdag"] else 0.5 if A[r]["subdag"] == V[r]["subdag"] else 0.0 for r in rounds)
    pos = sum(1 for r in rounds if A[r]["position"] < V[r]["position"])
    cross = sum(1 for r in rounds if A[r]["subdag"] != V[r]["subdag"])
    return {"pairs": len(rounds), "succ": w, "height": 100 * w / len(rounds) if rounds else None,
            "position": 100 * pos / len(rounds) if rounds else None, "cross": cross,
            "victim_blocks": len(V), "attacker_blocks": len(A)}
if __name__ == "__main__":
    for p in sorted(glob.glob(sys.argv[1] + "/*_rep*.log")):
        r = score(p)
        if r: r["arm"] = p.rsplit("/", 1)[-1].rsplit("_rep", 1)[0]; r["run"] = p.rsplit("/", 1)[-1]; print(json.dumps(r))
