#!/usr/bin/env python3
"""Usage: OUT=<run output dir> python3 coal2_score_runs.py > runs.jsonl

Per-run targeted committing-height (M3) for the coalition re-run: one JSON line per run with the
pairs won and scored, plus committed blocks, so tests can treat the run (not the pair) as the unit."""
import glob, json, os, sys
REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "../.."))
OUT = os.environ["OUT"]   # the OUT directory the run drivers wrote to
sys.path.insert(0, os.path.join(REPO, "code/bullshark-flashboys/our_harness"))
import measure
R = os.path.join(OUT, "coal2")
for arm in ["bribe1", "bribe2", "base1", "base4", "base6", "solo", "bribe", "f4", "f6", "f6ind", "f6rival"]:
    for d in sorted(glob.glob(f"{R}/{arm}/*/run*")):
        heights, meta, pairs, _ = measure.load(d)
        name = "baseline" if arm.startswith("base") else "fissure"
        vp = pairs.get(name) or {}
        s3, t3 = measure.m3(heights, vp) if vp else (0, 0)
        print(json.dumps({"arm": arm, "run": os.path.basename(d), "succ": s3, "total": t3, "committed": len(heights)}))
