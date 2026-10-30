#!/usr/bin/env python3
"""Committed copies of each tagged transaction in Sui v1.74 consensus-core front-running logs.
Input: logs from scripts/frontrun_sui/run_vbcast.sh (scripts/frontrun_sui/runs_vbcast/*_rep*.log,
not in the repo). Usage: python3 sui_copies.py <log> ... > data/review/bcast/sui_rows.jsonl
Prints one JSON row per log (13 copies per victim tx in the bc_vb and mp_vb arms); feeds aggregate.py.
"""
import json, re, statistics, sys, collections

def parse(path):
    order, summary, submits = None, "", 0
    with open(path, errors="replace") as f:
        for line in f:
            if "FINAL_TX_ORDER:" in line:
                order = json.loads(line.split("FINAL_TX_ORDER:", 1)[1].strip())
            elif "FRONTRUN_SUMMARY:" in line:
                summary = line.split("FRONTRUN_SUMMARY:", 1)[1].strip()
            elif "FRONTRUN_SUBMIT:" in line:
                submits += 1
    return order, summary, submits

def stats(xs):
    xs = sorted(xs)
    return {"n": len(xs), "median": statistics.median(xs) if xs else None,
            "mean": round(statistics.mean(xs), 3) if xs else None,
            "min": xs[0] if xs else None, "max": xs[-1] if xs else None}

def row(path):
    order, summary, submits = parse(path)
    m = dict(re.findall(r"(\w+)=(\S+)", summary))
    out = {"run": path.rsplit("/", 1)[-1], "summary_commits": int(m.get("commits", -1)),
           "summary_submitted": int(m.get("submitted", -1)), "submit_lines": submits}
    for tag in ("V", "F"):
        by = collections.defaultdict(list)
        for e in order:
            if e["tag"] == tag:
                by[e["id"]].append(e)
        copies = [len(v) for v in by.values()]
        # copies of the same id inside the commit (subdag) that holds its first copy
        first_commit = []
        distinct_commits = []
        distinct_authors = []
        for v in by.values():
            f = min(v, key=lambda e: e["pos"])
            first_commit.append(sum(1 for e in v if e["subdag"] == f["subdag"]))
            distinct_commits.append(len({e["subdag"] for e in v}))
            distinct_authors.append(len({e["author"] for e in v}))
        out[tag] = {"distinct_ids": len(by), "entries": sum(copies),
                    "copies": stats(copies),
                    "copies_in_first_commit": stats(first_commit),
                    "distinct_commits": stats(distinct_commits),
                    "distinct_authors": stats(distinct_authors),
                    "copies_hist": dict(sorted(collections.Counter(copies).items()))}
    out["max_pos_plus1"] = max(e["pos"] for e in order) + 1 if order else 0
    out["max_round"] = max(e["round"] for e in order) if order else 0
    out["max_subdag"] = max(e["subdag"] for e in order) if order else 0
    out["tagged_entries"] = len(order)
    return out

if __name__ == "__main__":
    for p in sys.argv[1:]:
        print(json.dumps(row(p)))
