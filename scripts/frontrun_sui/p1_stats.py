#!/usr/bin/env python3
"""P1 contrast at the transaction level: does fissure lift front-running more on certified Bullshark
than on uncertified Mysticeti? Per-run success rates; lift = median(fissure) - median(no attack).
Tests: Mann-Whitney U within each protocol (exact by permutation), and a permutation test of the
difference in lifts (labels shuffled within each protocol, 100000 draws). Bootstrap 95% CI of the
difference (resampling runs within each arm, 20000 draws)."""
import glob, json, os, random, statistics as st, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from score_frontrun import score
# Bullshark per-run scores (shipped) and the Mysticeti logs written by run_p1match.sh / run_p1x.sh.
B = [json.loads(l) for l in open(os.path.join(HERE, "../../data/bullshark/bullshark_frontrun/scores.jsonl"))]
def bull(arms): return [r["success_pct"] for r in B if r["arm"] in arms]
def myst(p): return [score(f)["success_pct"] for f in sorted(glob.glob(os.path.join(HERE, f"runs_p1/{p}_rep*.log")))]
bn, bf = bull({"none", "none_x", "none_y"}), bull({"fissure", "fissure_x", "fissure_y"})
mn, mf = myst("blk_none"), myst("blk_fissure")
lift = lambda n, f: st.median(f) - st.median(n)
def perm_within(n, f, B=100000, seed=1):
    random.seed(seed); obs = lift(n, f); pool = n + f; c = 0
    for _ in range(B):
        random.shuffle(pool)
        if abs(lift(pool[:len(n)], pool[len(n):])) >= abs(obs) - 1e-12: c += 1
    return (c + 1) / (B + 1)
def perm_diff(B_=100000, seed=2):
    random.seed(seed); obs = lift(bn, bf) - lift(mn, mf); c = 0
    pb, pm = bn + bf, mn + mf
    for _ in range(B_):
        random.shuffle(pb); random.shuffle(pm)
        d = lift(pb[:len(bn)], pb[len(bn):]) - lift(pm[:len(mn)], pm[len(mn):])
        if abs(d) >= abs(obs) - 1e-12: c += 1
    return (c + 1) / (B_ + 1)
def boot(B_=20000, seed=3):
    random.seed(seed); ds = []
    for _ in range(B_):
        r = lambda x: [random.choice(x) for _ in x]
        ds.append(lift(r(bn), r(bf)) - lift(r(mn), r(mf)))
    ds.sort(); return ds[int(0.025 * B_)], ds[int(0.975 * B_)]
out = {"bullshark": {"none_n": len(bn), "fissure_n": len(bf), "none_med": st.median(bn), "fissure_med": st.median(bf),
                     "lift": lift(bn, bf), "p_within": perm_within(bn, bf)},
       "mysticeti": {"none_n": len(mn), "fissure_n": len(mf), "none_med": st.median(mn), "fissure_med": st.median(mf),
                     "lift": lift(mn, mf), "p_within": perm_within(mn, mf)},
       "diff_of_lifts": lift(bn, bf) - lift(mn, mf), "p_diff": perm_diff(), "ci95_diff": boot()}
print(json.dumps(out, indent=1))
