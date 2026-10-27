#!/usr/bin/env python3
"""Score the competition cell (run_compete.sh): two front-runners, validators 0 and 1, each put their
own copy of a victim's transaction in their own block. A copy is attributed by its block author.
Per run and per order (consensus position, and Sui's execution order = gas re-sort per commit):
  any      victims front-run by at least one attacker (% of committed victims)
  by_a     victims front-run by attacker a's own copy
  contested victims where both attackers' copies committed; first_a = share of those where a's copy
           comes first (the competition's winner)."""
import json, sys, statistics as st
sys.path.insert(0, __file__.rsplit("/", 1)[0])
from score_frontrun import parse, exec_key

def score(path):
    order, _, _, summary = parse(path)
    out = {"run": path.rsplit("/", 1)[-1]}
    for view, k in [("cons", lambda e: e["pos"]), ("exec", exec_key)]:
        vic, fr = {}, {}
        for e in order:
            if e["tag"] == "V":
                if e["id"] not in vic or k(e) < k(vic[e["id"]]): vic[e["id"]] = e
            else:
                d = fr.setdefault(e["id"], {})
                a = e["author"]
                if a not in d or k(e) < k(d[a]): d[a] = e
        n = len(vic); anyw = 0; by = {}; cont = 0; first = {}
        for i, v in vic.items():
            cps = fr.get(i, {})
            wins = [a for a, c in cps.items() if k(c) < k(v)]
            if wins: anyw += 1
            for a in wins: by[a] = by.get(a, 0) + 1
            if len(cps) >= 2:
                cont += 1; w = min(cps, key=lambda a: k(cps[a])); first[w] = first.get(w, 0) + 1
        out[view] = {"victims": n, "any": 100 * anyw / n if n else None,
                     "by": {a: 100 * c / n for a, c in sorted(by.items())},
                     "contested": cont, "first": {a: 100 * c / cont for a, c in sorted(first.items())} if cont else {}}
    return out

if __name__ == "__main__":
    for p in sys.argv[1:]:
        print(json.dumps(score(p)))
