#!/usr/bin/env python3
"""Extract every created block and its signed parent (ancestor) list from Sui v1.74 harness logs.
Input: logs run with RUST_LOG=...,consensus_core::proposer=debug, i.e. scripts/frontrun_sui/run_p1match.sh
and run_p1x.sh (runs_p1, 40 no-attack runs) or run_grid.sh/run_v1.sh (runs); not in the repo.
Usage: parse_sui_ancestors.py OUT.jsonl LOG [LOG ...]   (OUT is 35-70 MB; feeds the other scripts here)
Source line: proposer.rs "Created block B<R>([<author>],<digest>)([B<r>([<a>],<d>), ...];<ts>ms;...) for round <R>".
"""
import json, re, sys, os

CREATED = re.compile(r"Created block B(\d+)\(\[(\d+)\],[^)]*\)\(\[(.*?)\];(\d+)ms;")
ANC = re.compile(r"B(\d+)\(\[(\d+)\],")
FISS = re.compile(r"Fissure: excluded (\d+) victim ancestor\(s\) at round (\d+)")


def parse(path):
    blocks, fiss, summary = [], [], None
    with open(path, errors="replace") as fh:
        for line in fh:
            if "Created block" in line:
                m = CREATED.search(line)
                if not m:
                    continue
                r, a, anc, ts = int(m.group(1)), int(m.group(2)), m.group(3), int(m.group(4))
                ancs = [[int(x[1]), int(x[0])] for x in ANC.findall(anc)]
                blocks.append([a, r, ts, ancs])
            elif "Fissure: excluded" in line:
                m = FISS.search(line)
                if m:
                    fiss.append([int(m.group(2)), int(m.group(1))])
            elif "FRONTRUN_SUMMARY:" in line:
                summary = line.split("FRONTRUN_SUMMARY:", 1)[1].strip()
    base = os.path.basename(path)
    arm, rep = base.rsplit("_rep", 1)
    return {"file": path, "arm": arm, "rep": int(rep.split(".")[0]), "summary": summary,
            "blocks": blocks, "fissure_excl": fiss}


if __name__ == "__main__":
    out = sys.argv[1]
    with open(out, "w") as o:
        for p in sys.argv[2:]:
            d = parse(p)
            o.write(json.dumps(d) + "\n")
            print(p, len(d["blocks"]), "blocks", len(d["fissure_excl"]), "fissure lines", file=sys.stderr)
