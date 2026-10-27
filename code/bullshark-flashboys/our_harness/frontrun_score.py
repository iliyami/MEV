#!/usr/bin/env python3
"""Transaction-level front-running on Bullshark (review #64A, point A1).

For one run's logs/ directory:
  * worker logs give, per batch digest, the tagged transactions it carries
    ("Batch <D> contains fr tx <tag> <id>", tag 2 = victim, 3 = attacker copy);
  * the longest primary log gives the committed order of certificates and their
    batches ("Committed B<round>(<author>) -> <D>"), i.e. the committing height.
A victim transaction is front-run when the attacker's copy of it is committed at a
lower height. Every copy exists only because the attacker's worker received the
victim's batch first ("FR_SEEN victim tx <id>"), so each success is causal.

Usage: frontrun_score.py <run_dir> [<run_dir> ...]   (prints one JSON row per run)
"""
import glob, json, os, re, sys

BATCH = re.compile(r"Batch (\S+) contains fr tx (\d) (\d+)")
COMMIT = re.compile(r"Committed B(\d+)\((\S+)\) -> (\S+)")
SEEN = re.compile(r"FR_SEEN victim tx (\d+)")
SENT = re.compile(r"Sending victim tx (\d+)")

def score(d):
    where = {}                                   # (tag, id) -> set of digests
    seen = set()
    for f in glob.glob(os.path.join(d, "worker-*.log")):
        for line in open(f, errors="replace"):
            m = BATCH.search(line)
            if m:
                where.setdefault((int(m.group(2)), int(m.group(3))), set()).add(m.group(1))
            m = SEEN.search(line)
            if m:
                seen.add(int(m.group(1)))
    sent = 0
    vf = os.path.join(d, "fr-victim.log")
    if os.path.exists(vf):
        sent = sum(1 for l in open(vf, errors="replace") if SENT.search(l))
    best = []
    for f in glob.glob(os.path.join(d, "primary-*.log")):
        rows, last, h = [], None, -1
        for line in open(f, errors="replace"):
            m = COMMIT.search(line)
            if m:
                cert = (m.group(1), m.group(2))
                if cert != last:
                    h += 1
                    last = cert
                rows.append((m.group(3), h, int(m.group(1))))
        if len(rows) > len(best):
            best = rows
    pos = {}
    for digest, h, rnd in best:
        pos.setdefault(digest, (h, rnd))
    def first(tag, i):
        c = [pos[x] for x in where.get((tag, i), ()) if x in pos]
        return min(c) if c else None
    vids = sorted({i for t, i in where if t == 2})
    committed = [i for i in vids if first(2, i) is not None]
    reacted = [i for i in committed if first(3, i) is not None]
    won = set(i for i in reacted if first(3, i)[0] < first(2, i)[0])
    same_round = [i for i in reacted if first(3, i)[1] == first(2, i)[1]]
    sr_won = [i for i in same_round if i in won]
    later = [i for i in reacted if first(3, i)[1] > first(2, i)[1]]
    later_won = [i for i in later if i in won]
    pct = lambda a, b: round(100.0 * a / b, 2) if b else None
    return {"run": d, "sent": sent, "victim_committed": len(committed), "seen": len(seen),
            "reacted_committed": len(reacted), "won": len(won),
            "success_pct": pct(len(won), len(committed)),
            "cond_success_pct": pct(len(won), len(reacted)),
            "same_round_pct": pct(len(same_round), len(reacted)),
            "in_round_win_pct": pct(len(sr_won), len(same_round)),
            "later_round_pct": pct(len(later), len(reacted)),
            "later_round_win_pct": pct(len(later_won), len(later)),
            "certs": (best[-1][1] + 1) if best else 0}

if __name__ == "__main__":
    for d in sys.argv[1:]:
        print(json.dumps(score(d)))
