#!/usr/bin/env python3
"""Compress two parse_sui_ancestors.py outputs (35-70 MB each, not in the repo) into per-stream victim
omission flags, small enough to ship (data/review/bribe/<label>_victim_flags.json.gz).
Usage: make_victim_flags.py <none.jsonl> <fissure.jsonl> <victims> <attackers> <label> <out.json.gz>
Flag per opportunity: 0 included, 1 omitted with some non-victim, 2 omitted with only victims (selective).
"""
import gzip, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from omission_stats import load


def flags(path, keep, victims):
    """One record per (run, proposer, victim): the round-ordered flag string (same opportunities as
    omission_stats.streams and selective.seqs)."""
    out = []
    for run in load(path):
        have = set((a, r) for a, r, _, _ in run["blocks"])
        seen, st = set(), {}
        for a, r, ts, anc in sorted(run["blocks"], key=lambda b: (b[0], b[1])):
            if (a, r) in seen:      # duplicate block lines (none in our runs)
                continue
            seen.add((a, r))
            if not keep(a):
                continue
            ancset = set((x[0], x[1]) for x in anc)
            omitted = [j for j in range(13) if j != a and (j, r - 1) in have and (j, r - 1) not in ancset]
            for v in victims:
                if v == a or (v, r - 1) not in have:
                    continue
                c = "0" if v not in omitted else ("2" if all(o in victims for o in omitted) else "1")
                st.setdefault((a, v), []).append(c)
        for (a, v), s in sorted(st.items()):
            out.append({"arm": run["arm"], "rep": run["rep"], "proposer": a, "victim": v, "flags": "".join(s)})
    return out


if __name__ == "__main__":
    none_p, fiss_p, vic, att, label, out = sys.argv[1:7]
    victims = set(map(int, vic.split(","))); attackers = set(map(int, att.split(",")))
    d = {"label": label, "victims": sorted(victims), "attackers": sorted(attackers),
         "honest": flags(none_p, lambda a: a != 0, victims),          # no-attack runs, proposers 1..12
         "attacker": flags(fiss_p, lambda a: a in attackers, victims)}  # fissure runs, attacker proposers
    with gzip.open(out, "wt") as f:
        json.dump(d, f, separators=(",", ":"))
    print(label, "honest streams", len(d["honest"]), "attacker streams", len(d["attacker"]))
