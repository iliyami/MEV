#!/usr/bin/env python3
"""Unified MEV scorer for the real Bullshark (Flash Boys fork).

Computes THREE metrics from ONE committed order, so a single run can be scored
under every definition and the metric dimension (T4) becomes measurable rather
than anecdotal.

  M3  targeted-pair committing-height ASR   <-- the "No Fish Is Too Big for Flash
      Boys" metric. For each logged (attacker header A, victim header V) pair,
      success iff height[V] > height[A] (attacker committed earlier in the global
      linear order). Cross-round. PROVEN identical to their benchmark/logs.py.

  M1  all-pairs ASR. Over ALL committed blocks: every (attacker-authored block,
      target-victim-authored block) pair, success iff height[att] < height[vic].
      Cross-round, positional; fair ordering ~= 50%.

  M2  same-round ASR. M1 restricted to pairs in the same round. Isolates the
      intra-round tiebreak (the "index tax").

Roles are inferred from the logs themselves (no committee file needed):
  - attacker authors  = authors of the logged attacking headers
  - target victim     = author of the logged victim headers referenced by those pairs
Author/round/height per committed block come from the benchmark-only line
  "FairDag CommitMeta <id> author <a> round <r> height <h>"
and heights also from the original
  "FairDag Committed <id> in height <h>"   (kept for M3 fidelity with their parser).

Usage:  measure.py <logs_dir> [--attack fissure|sluggish|speculative|baseline] [--json]
"""
import argparse
import glob
import json
import os
import re
import sys

RE_SILENT = re.compile(r"FairDag SILENT skip round \d+ \(not leader\) by (\S+)")
RE_VICTIM_HDR = re.compile(r"FairDag Created a victim header (\S+) in round (\d+)")
RE_HEIGHT = re.compile(r"FairDag Committed (\S+) in height (\d+)")
RE_META = re.compile(r"FairDag CommitMeta (\S+) author (\S+) round (\d+) height (\d+)")
RE_PAIR = {
    "baseline":    re.compile(r"FairDag Monitor attacking header (\S+), victim header (\S+), in round (\d+)"),
    "fissure":     re.compile(r"FairDag Created a fissure attacking header (\S+), victim header (\S+), in round (\d+)"),
    "sluggish":    re.compile(r"FairDag Created a sluggish attacking header (\S+), victim header (\S+), in round (\d+)"),
    "speculative": re.compile(r"FairDag Created a speculative attacking header (\S+), victim header (\S+), in round (\d+)"),
}


def load_silent_roles(logs_dir, meta):
    """Roles for the silent-except-leader cell, where no attack pairs are logged.

    attackers = authors that emitted a `FairDag SILENT skip ... by <author>` marker
    victims   = every other author seen in the committed order
    Returns (attacker_authors, victim_authors, marker_count). A zero marker count
    means the hook never fired and the cell must NOT be scored.
    """
    att, markers = set(), 0
    files = sorted(glob.glob(os.path.join(logs_dir, "primary-*.log"))) or \
            sorted(glob.glob(os.path.join(logs_dir, "*.log")))
    for f in files:
        try:
            txt = open(f, "r", errors="replace").read()
        except OSError:
            continue
        for m in RE_SILENT.finditer(txt):
            att.add(m.group(1))
            markers += 1
    all_authors = {b["author"] for b in meta.values()}
    return att, (all_authors - att), markers


def load(logs_dir):
    heights, meta = {}, {}
    pairs = {k: {} for k in RE_PAIR}
    files = sorted(glob.glob(os.path.join(logs_dir, "primary-*.log"))) or \
            sorted(glob.glob(os.path.join(logs_dir, "*.log")))
    for f in files:
        try:
            txt = open(f, "r", errors="replace").read()
        except OSError:
            continue
        for m in RE_HEIGHT.finditer(txt):
            heights.setdefault(m.group(1), int(m.group(2)))
        for m in RE_META.finditer(txt):
            bid = m.group(1)
            if bid not in meta:
                meta[bid] = {"author": m.group(2), "round": int(m.group(3)), "height": int(m.group(4))}
            heights.setdefault(bid, int(m.group(4)))
        for atk, rx in RE_PAIR.items():
            for m in rx.finditer(txt):
                pairs[atk].setdefault(m.group(2), m.group(1))   # victim -> attacker, first-seen
    return heights, meta, pairs, files


def m3(heights, victim_to_attack):
    """Targeted-pair committing-height ASR (their metric)."""
    total = succ = 0
    for v, a in victim_to_attack.items():
        if v in heights and a in heights:
            total += 1
            if heights[v] > heights[a]:
                succ += 1
    return succ, total


def roles(meta, victim_to_attack):
    """Infer attacker authors and the target-victim author from the logged pairs."""
    att_authors, vic_authors = set(), set()
    for v, a in victim_to_attack.items():
        if a in meta:
            att_authors.add(meta[a]["author"])
        if v in meta:
            vic_authors.add(meta[v]["author"])
    return att_authors, vic_authors


def m1_m2(meta, att_authors, vic_authors):
    """All-pairs (cross-round) and same-round ASR over every committed block."""
    att = [b for b in meta.values() if b["author"] in att_authors]
    vic = [b for b in meta.values() if b["author"] in vic_authors]
    ap_s = ap_t = sr_s = sr_t = 0
    for a in att:
        for v in vic:
            ap_t += 1
            if a["height"] < v["height"]:
                ap_s += 1
            if a["round"] == v["round"]:
                sr_t += 1
                if a["height"] < v["height"]:
                    sr_s += 1
    return (ap_s, ap_t), (sr_s, sr_t)


def pct(s, t):
    return (100.0 * s / t) if t else None


# ---------------------------------------------------------------------------
# Sui / Mysticeti support. The uncertified fork emits the whole committed order
# as  FINAL_COMMITTED_ORDER: [{"creator":C,"position":P,"round":R}, ...].
# We convert it into the SAME (author, round, height) block records used above
# and score it with the SAME m1_m2() function, so cross-protocol M1/M2 numbers
# come from one implementation and are genuinely commensurable.
# ---------------------------------------------------------------------------
RE_SUI_ORDER = re.compile(r"FINAL_COMMITTED_ORDER:\s*(\[.*?\])", re.S)


def load_sui(path, attacker_ids, victim_ids):
    """Parse a Sui/Mysticeti run log/order file into block records + role sets."""
    txt = open(path, "r", errors="replace").read()
    m = RE_SUI_ORDER.search(txt)
    if not m:
        return {}, set(), set()
    order = json.loads(m.group(1))
    meta = {}
    for i, e in enumerate(order):
        # position in the committed sequence IS the committing height
        meta[f"b{i}"] = {
            "author": str(e["creator"]),
            "round": int(e["round"]),
            "height": int(e.get("position", i)),
        }
    return meta, {str(a) for a in attacker_ids}, {str(v) for v in victim_ids}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("logs_dir")
    ap.add_argument("--attack", choices=list(RE_PAIR), default=None)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--format", choices=["bullshark", "sui"], default="bullshark",
                    help="sui: parse FINAL_COMMITTED_ORDER from a single file (M1/M2 only)")
    ap.add_argument("--attackers", default="", help="sui: comma-separated attacker indices")
    ap.add_argument("--victims", default="", help="sui: comma-separated victim indices")
    ap.add_argument("--silent-roles", action="store_true",
                    help="bullshark: derive roles from SILENT skip markers (for the silent cell)")
    args = ap.parse_args(argv)

    if args.format == "sui":
        ids = lambda s: [int(x) for x in s.split(",") if x.strip() != ""]
        meta, att_a, vic_a = load_sui(args.logs_dir, ids(args.attackers), ids(args.victims))
        if not meta:
            print("[scorer] no FINAL_COMMITTED_ORDER found"); return 1
        (s1, t1), (s2, t2) = m1_m2(meta, att_a, vic_a)
        res = {"M1_all_pairs": {"pct": pct(s1, t1), "succ": s1, "total": t1},
               "M2_same_round": {"pct": pct(s2, t2), "succ": s2, "total": t2},
               "blocks": len(meta)}
        if args.json:
            print(json.dumps(res, indent=2))
        else:
            g = lambda d: (f"{d['pct']:.2f}% ({d['succ']}/{d['total']})" if d["pct"] is not None else "n/a")
            print(f"[scorer/sui] {len(meta)} committed blocks | attackers={sorted(att_a)} victims={sorted(vic_a)}")
            print(f"     M1 all-pairs  : {g(res['M1_all_pairs'])}")
            print(f"     M2 same-round : {g(res['M2_same_round'])}")
        return 0

    heights, meta, pairs, files = load(args.logs_dir)

    if args.silent_roles:
        att_a, vic_a, markers = load_silent_roles(args.logs_dir, meta)
        print(f"[scorer/silent] {len(files)} logs | {len(meta)} blocks with meta | "
              f"{markers} SILENT markers | {len(att_a)} silent author(s)")
        if markers == 0:
            print("  REFUSING TO SCORE: hook never fired (0 markers)")
            return 1
        (s1, t1), (s2, t2) = m1_m2(meta, att_a, vic_a)
        g = lambda s, t: (f"{100.0*s/t:.2f}% ({s}/{t})" if t else "n/a")
        print(f"     M1 all-pairs  : {g(s1, t1)}")
        print(f"     M2 same-round : {g(s2, t2)}")
        return 0

    out = {"log_files": len(files), "committed_blocks": len(heights), "with_meta": len(meta), "cells": {}}
    if not args.json:
        print(f"[scorer] {len(files)} logs | {len(heights)} committed blocks | {len(meta)} with author/round meta")
        if not meta:
            print("  WARNING: no CommitMeta lines -> M1/M2 unavailable (rebuild with the CommitMeta log line)")

    for atk in ([args.attack] if args.attack else list(RE_PAIR)):
        vp = pairs[atk]
        if not vp:
            continue
        s3, t3 = m3(heights, vp)
        att_a, vic_a = roles(meta, vp)
        (s1, t1), (s2, t2) = m1_m2(meta, att_a, vic_a) if meta else ((0, 0), (0, 0))
        cell = {
            "M3_targeted_committing_height": {"pct": pct(s3, t3), "succ": s3, "total": t3},
            "M1_all_pairs":                  {"pct": pct(s1, t1), "succ": s1, "total": t1},
            "M2_same_round":                 {"pct": pct(s2, t2), "succ": s2, "total": t2},
            "attacker_authors": len(att_a), "victim_authors": len(vic_a),
        }
        out["cells"][atk] = cell
        if not args.json:
            f = lambda d: (f"{d['pct']:.2f}% ({d['succ']}/{d['total']})" if d["pct"] is not None else "n/a")
            print(f"  {atk}:")
            print(f"     M3 targeted committing-height : {f(cell['M3_targeted_committing_height'])}")
            print(f"     M1 all-pairs                  : {f(cell['M1_all_pairs'])}")
            print(f"     M2 same-round                 : {f(cell['M2_same_round'])}")
            print(f"     roles: {len(att_a)} attacker author(s), {len(vic_a)} victim author(s)")
    if args.json:
        print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
