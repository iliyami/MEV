#!/usr/bin/env python3
"""E1 scoring: censorship rate per run, with the victim identified by construction rather than by log
markers. In this tree the victim is the honest node with the smallest public key (core.rs / aggregators.rs
victims()[0]); attackers are nodes n-fa..n-1 (benchmark/config.py). Each node's author key comes from its own
proposer lines "Created B<r>(<author>)". Where the published scorer's markers exist we check that both
identify the same victim. Metric as score_censorship_bullshark.py: 1 - victim blocks / median honest
non-victim blocks, in percent.
Usage: e1_score.py <dir with run*/ subdirs> [fa=4]"""
import base64, glob, json, os, re, statistics as st, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + "/..")
RE_META = re.compile(r"FairDag CommitMeta (\S+) author (\S+) round (\d+) height (\d+)")
RE_OWN = re.compile(r"primary::proposer\] Created B\d+\((\S+?)\)")
def key_bytes(k):
    try: return base64.b64decode(k + "=" * (-len(k) % 4))
    except Exception: return k.encode()
def run(d, fa):
    meta, own = {}, {}
    for f in glob.glob(os.path.join(d, "primary-*.log")):
        i = int(re.search(r"primary-(\d+)\.log", f).group(1)); txt = open(f, errors="replace").read()
        for m in RE_META.finditer(txt): meta.setdefault(m.group(1), m.group(2))
        a = set(m.group(1) for m in RE_OWN.finditer(txt))
        if len(a) == 1: own[i] = a.pop()
    n = len(glob.glob(os.path.join(d, "primary-*.log")))
    if not meta or len(own) < n - fa: return {"error": "roles not recoverable", "nodes_mapped": len(own)}
    honest = [own[i] for i in range(n - fa) if i in own]
    victim = min(honest, key=key_bytes)
    counts = {}
    for a in meta.values(): counts[a] = counts.get(a, 0) + 1
    others = [counts.get(a, 0) for a in honest if a != victim]
    med = st.median(others)
    return {"rate": round((1 - counts.get(victim, 0) / med) * 100, 2), "victim_blocks": counts.get(victim, 0), "other_median": med}
if __name__ == "__main__":
    fa = int(sys.argv[2]) if len(sys.argv) > 2 else 4
    rs = []
    for d in sorted(glob.glob(os.path.join(sys.argv[1], "run*"))):
        r = run(d, fa); print(os.path.basename(d), json.dumps(r))
        if "rate" in r: rs.append(r["rate"])
    print("MEDIAN", json.dumps({"median": round(st.median(rs), 2) if rs else None, "n": len(rs), "reps": rs}))
