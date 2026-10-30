#!/usr/bin/env python3
"""Per-run targeted committing-height (M3) for E3 (competing attackers within f).
Usage: e3_score_runs.py <OUT>/e3   (the directory e3_compete.sh wrote)."""
import glob, json, os, sys
REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPO, "code/bullshark-flashboys/our_harness"))
import measure
R = sys.argv[1]
for arm in ["base4e", "f4ind"]:
    for d in sorted(glob.glob(f"{R}/{arm}/*/run*")):
        heights, meta, pairs, _ = measure.load(d)
        name = "baseline" if arm.startswith("base") else "fissure"
        vp = pairs.get(name) or {}
        s3, t3 = measure.m3(heights, vp) if vp else (0, 0)
        print(json.dumps({"arm": arm, "run": os.path.basename(d), "succ": s3, "total": t3, "committed": len(heights)}))
