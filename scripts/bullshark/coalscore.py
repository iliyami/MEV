#!/usr/bin/env python3
"""Coalition-wide same-round scoring for the Bullshark coalition campaign (coal, coal2).

measure.py scores only the delegate attacker (the author of the logged fissure pairs). This script
scores every validator's committed blocks against the target victim's in the same round, so the
bribed validators' own blocks (and, under f4, the other Byzantine attackers') are scored too.

Roles, all from the run's own logs:
  node i -> author key : the author in primary-i.log's proposer lines "Created B<r>(<author>)"
  attackers            : nodes n-fa..n-1 (benchmark/config.py appends the attack types after the
                         n-fa honest nodes; the delegate is node n-fa)
  victim               : author of the victim headers in the logged attack pairs (as measure.py)
  bribed positions     : honest authors sorted by key bytes, skipping the first (core.rs: victim =
                         honest[0], bribed = honest[1..=B]); checked: honest[0] must equal the victim
Usage: coalscore.py <run0 dir> <fa> <B>   -> one JSON line
"""
import base64, glob, json, os, re, sys
RE_META = re.compile(r"FairDag CommitMeta (\S+) author (\S+) round (\d+) height (\d+)")
RE_OWN = re.compile(r"primary::proposer\] Created B\d+\((\S+?)\)")
RE_PAIR = re.compile(r"FairDag (?:Created a fissure attacking|Monitor attacking) header (\S+), victim header (\S+), in round \d+")
d, fa, B = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
meta, own, pairs = {}, {}, []
for f in glob.glob(os.path.join(d, "primary-*.log")):
    i = int(re.search(r"primary-(\d+)\.log", f).group(1))
    txt = open(f, errors="replace").read()
    for m in RE_META.finditer(txt):
        meta.setdefault(m.group(1), (m.group(2), int(m.group(3)), int(m.group(4))))
    own[i] = set(m.group(1) for m in RE_OWN.finditer(txt))   # authors this node proposed as
    pairs += [(m.group(1), m.group(2)) for m in RE_PAIR.finditer(txt)]
node_author = {}
for i, au in own.items():
    if len(au) == 1: node_author[i] = next(iter(au))
vic = {meta[v][0] for a, v in pairs if v in meta}
dele = {meta[a][0] for a, v in pairs if a in meta}
out = {"run": d, "nodes_mapped": len(node_author), "ok": False}
if len(vic) != 1 or len(node_author) != len(own):
    print(json.dumps(out)); sys.exit()
vic = vic.pop()
n = len(node_author)
attackers = {node_author[i] for i in range(n - fa, n)}
honest = sorted((a for a in node_author.values() if a not in attackers), key=lambda s: base64.b64decode(s + "=" * (-len(s) % 4)))
bribed = set(honest[1:1 + B])
out.update(victim_is_min_honest=(honest[0] == vic), delegate_in_attackers=dele <= attackers, delegate=sorted(dele))
vr = {}
for bid, (au, r, h) in meta.items():
    if au == vic: vr.setdefault(r, []).append(h)
def score(group):
    s = t = 0
    for bid, (au, r, h) in meta.items():
        if au in group and r in vr:
            for vh in vr[r]:
                t += 1; s += h < vh
    return [s, t]
others_att = attackers - dele
out.update(ok=True, delegate_sr=score(dele), other_attackers_sr=score(others_att), bribed_pos_sr=score(bribed),
           rest_honest_sr=score(set(honest[1 + B:])))
print(json.dumps(out))
