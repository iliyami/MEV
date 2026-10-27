#!/usr/bin/env python3
"""Per-run metric distributions for a preserved run-log directory.

Pooled ratios weight runs by pair count and can hide run-to-run variance, so for
any headline cell we report the per-run median and IQR alongside the pooled value.

Usage: per_run_stats.py <run_logs/cell_dir> [--attack fissure|baseline|...]
"""
import argparse
import os
import statistics as st
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import measure  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cell_dir")
    ap.add_argument("--attack", default=None)
    args = ap.parse_args()

    rows = []
    pooled = {k: [0, 0] for k in ("M1", "M2", "M3")}
    for d in sorted(os.listdir(args.cell_dir)):
        rd = os.path.join(args.cell_dir, d)
        if not os.path.isdir(rd):
            continue
        heights, meta, pairs, _ = measure.load(rd)
        atk = args.attack
        if atk is None:
            atk = next((k for k, v in pairs.items() if v), None)
        if not atk or not pairs.get(atk):
            continue
        vp = pairs[atk]
        s3, t3 = measure.m3(heights, vp)
        att_a, vic_a = measure.roles(meta, vp)
        (s1, t1), (s2, t2) = measure.m1_m2(meta, att_a, vic_a) if meta else ((0, 0), (0, 0))
        for k, (s, t) in (("M1", (s1, t1)), ("M2", (s2, t2)), ("M3", (s3, t3))):
            pooled[k][0] += s
            pooled[k][1] += t
        rows.append({
            "run": d,
            "M1": (100.0 * s1 / t1) if t1 else None,
            "M2": (100.0 * s2 / t2) if t2 else None,
            "M3": (100.0 * s3 / t3) if t3 else None,
            "m3n": t3,
        })

    print(f"=== {os.path.basename(args.cell_dir)} | {len(rows)} runs with pairs ===")
    for k in ("M1", "M2", "M3"):
        vals = [r[k] for r in rows if r[k] is not None]
        s, t = pooled[k]
        pooled_pct = (100.0 * s / t) if t else float("nan")
        if not vals:
            print(f"  {k}: no data")
            continue
        med = st.median(vals)
        lo, hi = min(vals), max(vals)
        iqr = ""
        if len(vals) >= 4:
            q = st.quantiles(vals, n=4)
            iqr = f" IQR[{q[0]:.1f},{q[2]:.1f}]"
        print(f"  {k}: median={med:6.2f}%  pooled={pooled_pct:6.2f}%  range[{lo:.1f},{hi:.1f}]{iqr}  n_runs={len(vals)}  pairs={t}")
    tot_m3 = sum(r["m3n"] for r in rows)
    print(f"  (M3 targeted pairs total = {tot_m3})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
