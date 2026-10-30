#!/usr/bin/env python3
"""Per-node sealed vs committed batches for Bullshark run directories (read-only).
Input: raw run directories (not in the repo); usage: python3 bull_pernode.py <run_dir> ...
Used to explain the low-throughput fissure runs (nodes 9-12 commit few of their sealed batches).
"""
import glob, os, re, sys, collections
SIZE = re.compile(r"Batch (\S+) contains (\d+) B")
COMMIT = re.compile(r"Committed B\d+\(\S+\) -> ([^ ]+=)")
for d in sys.argv[1:]:
    owner = {}
    for f in glob.glob(os.path.join(d, "worker-*.log")):
        node = os.path.basename(f).split("-")[1]
        for line in open(f, errors="replace"):
            if " B" in line and "contains" in line and "fr tx" not in line and "sample" not in line:
                m = SIZE.search(line)
                if m:
                    owner[m.group(1)] = node
    com = set()
    for f in glob.glob(os.path.join(d, "primary-*.log")):
        for line in open(f, errors="replace"):
            if "Committed B" in line:
                m = COMMIT.search(line)
                if m:
                    com.add(m.group(1))
    sealed = collections.Counter(owner.values())
    comm = collections.Counter(owner[x] for x in com if x in owner)
    print(d.split("fr_runs/")[-1], " ".join(f"{n}:{comm[n]}/{sealed[n]}" for n in sorted(sealed, key=int)))
