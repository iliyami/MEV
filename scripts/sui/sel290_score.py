#!/usr/bin/env python3
"""Same-round and all-pairs rates for silent-except-leader / tiebreak logs (attackers = first round(0.08 n),
victims = last round(0.231 n) validators, as in withholding_attack_test.rs). The all-pairs value is checked against the log's own FINAL_ALL_PAIRS_ASR.
Usage: python3 sel290_score.py "$OUT/sel290/rr_base_rep*.log" "$OUT/sel290/rr_sel_rep*.log" ..."""
import bisect, glob, json, re, statistics as st, sys, collections
def load(f):
    t = open(f, errors="ignore").read()
    m = re.search(r"FINAL_COMMITTED_ORDER: (\[.*?\])\s", t)
    ap = re.findall(r"FINAL_ALL_PAIRS_ASR: ([0-9.]+)", t)
    return (json.loads(m.group(1)) if m else None), (float(ap[-1]) if ap else None)
def rates(o):
    n = max(b["creator"] for b in o) + 1
    att = set(range(max(1, round(n * 0.08))))
    vic = set(range(n - round(n * 0.231), n))
    A = [b["position"] for b in o if b["creator"] in att]
    V = sorted(b["position"] for b in o if b["creator"] in vic)
    ap = 100.0 * sum(len(V) - bisect.bisect_right(V, a) for a in A) / (len(A) * len(V))
    by = collections.defaultdict(lambda: ([], []))
    for b in o:
        if b["creator"] in att: by[b["round"]][0].append(b["position"])
        elif b["creator"] in vic: by[b["round"]][1].append(b["position"])
    w = t = 0
    for a, v in by.values():
        for x in a:
            for y in v: t += 1; w += x < y
    return ap, (100.0 * w / t if t else None), t, len(A)
if __name__ == "__main__":
    for pat in sys.argv[1:]:
        res = []
        for f in sorted(glob.glob(pat)):
            o, logged = load(f)
            if not o: print("NO ORDER", f); continue
            ap, sr, pairs, na = rates(o)
            if logged is not None and abs(ap - logged) > 0.06: print("ALL-PAIRS MISMATCH", f, round(ap, 2), logged)
            res.append((sr, ap, pairs, na))
        if res:
            print(pat, "n=%d" % len(res), "same-round med %.1f [%.1f, %.1f]" % (st.median(r[0] for r in res), min(r[0] for r in res), max(r[0] for r in res)),
                  "all-pairs med %.1f" % st.median(r[1] for r in res), "pairs", [r[2] for r in res], "att blocks", [r[3] for r in res])
