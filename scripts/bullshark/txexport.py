#!/usr/bin/env python3
"""Per-transaction outcomes of the Bullshark front-running (txc) runs, using frontrun_score.py's
own parsing: one row per run with, for every committed victim tx, (id, reacted, won, same_round).
Usage: OUT=<run output dir> python3 txexport.py > txc_pertx.jsonl"""
import glob, json, os, sys
REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "../.."))
OUT = os.environ["OUT"]   # the OUT directory the run drivers wrote to
sys.path.insert(0, os.path.join(REPO, "code/bullshark-flashboys/our_harness"))
import frontrun_score as fs
BATCH, COMMIT = fs.BATCH, fs.COMMIT

def per_tx(d):
    where = {}
    for f in glob.glob(os.path.join(d, "worker-*.log")):
        for line in open(f, errors="replace"):
            m = BATCH.search(line)
            if m:
                where.setdefault((int(m.group(2)), int(m.group(3))), set()).add(m.group(1))
    best = []
    for f in glob.glob(os.path.join(d, "primary-*.log")):
        rows, last, h = [], None, -1
        for line in open(f, errors="replace"):
            m = COMMIT.search(line)
            if m:
                cert = (m.group(1), m.group(2))
                if cert != last:
                    h += 1; last = cert
                rows.append((m.group(3), h, int(m.group(1))))
        if len(rows) > len(best):
            best = rows
    pos = {}
    for dg, h, rnd in best:
        pos.setdefault(dg, (h, rnd))
    def first(tag, i):
        c = [pos[x] for x in where.get((tag, i), ()) if x in pos]
        return min(c) if c else None
    out = []
    for i in sorted({i for t, i in where if t == 2}):
        v = first(2, i)
        if v is None:
            continue
        a = first(3, i)
        out.append([i, a is not None, bool(a and a[0] < v[0]), bool(a and a[1] == v[1])])
    return out

TXC = os.path.join(OUT, "txc")
for d in sorted(glob.glob(os.path.join(TXC, "*/r*/*/run0"))):
    parts = ["", "", "", ""] + os.path.relpath(d, TXC).split("/")   # parts[4] = arm, parts[5] = rep, as on our cluster
    s = fs.score(d)
    print(json.dumps({"arm": parts[4], "rep": parts[5], "won": s["won"], "in_round_win_pct": s["in_round_win_pct"], "txs": per_tx(d)}))
