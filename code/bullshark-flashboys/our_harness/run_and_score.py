#!/usr/bin/env python3
"""Run N single-run benchmark configs, preserving each run's logs, then score
every run under M1/M2/M3 and aggregate.

The stock benchmark overwrites `logs/` on every run, so the stock flow cannot
produce M1/M2/M3 from the *same* committed orders (their cumulative results file
aggregates M3 only). This driver snapshots `logs/` after each run so all three
metrics are computed over an identical set of orders -- which is what the metric
dimension (T4) requires to be an honest comparison.

Usage (from the benchmark/ dir, with the venv python):
    python ../our_harness/run_and_score.py --attack 1 --fa 4 --nodes 13 --runs 12 [--env K=V ...]
attack: 10=baseline 1=fissure 2=sluggish 3=speculative
"""
import argparse
import os
import shutil
import sys

sys.path.insert(0, os.getcwd())          # benchmark/ so `fabfile` imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import measure                            # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--attack", type=int, required=True)
    ap.add_argument("--fa", type=int, default=4)
    ap.add_argument("--crash", type=int, default=0)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--nodes", type=int, default=13)
    ap.add_argument("--runs", type=int, default=12)
    ap.add_argument("--keep", default="/mnt/data/flashboys/run_logs")
    args = ap.parse_args()

    name = {10: "baseline", 1: "fissure", 2: "sluggish", 3: "speculative"}[args.attack]
    keep = os.path.join(args.keep, f"{name}_f{args.fa}_n{args.nodes}")
    shutil.rmtree(keep, ignore_errors=True)
    os.makedirs(keep, exist_ok=True)

    from fabfile import run_with_configurations   # noqa: E402

    for i in range(args.runs):
        cfg = [(args.attack, args.fa, args.crash, args.workers, args.nodes, 1)]
        try:
            run_with_configurations(cfg)
        except Exception as e:                     # a failed run must not kill the sweep
            print(f"[run {i}] FAILED: {e}", file=sys.stderr)
            continue
        dst = os.path.join(keep, f"run{i}")
        shutil.rmtree(dst, ignore_errors=True)
        try:
            shutil.copytree("logs", dst)
        except OSError as e:
            print(f"[run {i}] could not snapshot logs: {e}", file=sys.stderr)

    # Aggregate every preserved run under all three metrics.
    agg = {k: {"s": 0, "t": 0} for k in ("M1_all_pairs", "M2_same_round", "M3_targeted_committing_height")}
    scored = 0
    for d in sorted(os.listdir(keep)):
        rd = os.path.join(keep, d)
        if not os.path.isdir(rd):
            continue
        heights, meta, pairs, _ = measure.load(rd)
        vp = pairs[name]
        if not vp:
            continue
        s3, t3 = measure.m3(heights, vp)
        att_a, vic_a = measure.roles(meta, vp)
        (s1, t1), (s2, t2) = measure.m1_m2(meta, att_a, vic_a) if meta else ((0, 0), (0, 0))
        for k, (s, t) in (("M1_all_pairs", (s1, t1)),
                          ("M2_same_round", (s2, t2)),
                          ("M3_targeted_committing_height", (s3, t3))):
            agg[k]["s"] += s
            agg[k]["t"] += t
        scored += 1

    print(f"\n=== {name} f_a={args.fa} n={args.nodes} | {scored} runs scored (logs kept in {keep}) ===")
    for k, v in agg.items():
        p = (100.0 * v["s"] / v["t"]) if v["t"] else None
        print(f"  {k:32s}: " + (f"{p:.2f}% ({v['s']}/{v['t']})" if p is not None else "n/a"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
