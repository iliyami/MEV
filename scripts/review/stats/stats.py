#!/usr/bin/env python3
"""Benjamini-Hochberg FDR pass over every tested Table II row (and the Table V reproduction check).
Default input (in the repo): per-run values stored in data/review/stats/results.json; all tests rerun.
With --raw DIR it instead reads the raw run logs and the paper tables under DIR (not in the repo).
Prints: 42 tested executions, 29 survive BH at q = 0.05, 28 also have a 95% CI that excludes 0.
"""
# Usage (from the repo root, about 2 to 4 minutes):
#   python3 -I scripts/review/stats/stats.py [--results PATH] [--out results.json]
#   python3 -I scripts/review/stats/stats.py --raw <paper2 dir> [--out results.json]
#     <paper2 dir> holds frontrun/, sel290/, aleph_rerun/, mysticeti_rerun/, MEV_Spectrum/tab_*.tex, ...
#     and needs score_cache.py run first.
# Inputs besides the raw logs (data/review/stats/):
#   cache/frontrun_scores.json   score_cache.py output (scripts/frontrun_sui/score_frontrun.py on every Sui log)
#   cache/aleph_nospec_base_rescored.jsonl   aleph_rescore.py on aleph_rerun/runs/nospec_base_rep1-5.log (seed 0)
#   cache/t1_multi3_m3.json      code/bullshark-flashboys/our_harness/measure.py load()+m3() on the multi3 runs
#   cens4_f4_scorer_output.txt   scripts/score_censorship_bullshark.py output for the CloudLab coal/{f4,cens4} runs
# Methods
#   Estimators: median (difference of run medians), pooled (difference of pooled ratios 100*sum(succ)/sum(total),
#   runs with total = 0 dropped), const (one measured arm against the fixed 50% line).
#   Interval: 95% percentile bootstrap of the row's estimator, runs resampled within each arm, 20000 resamples.
#   Tests (two-sided): exact rank-sum for small median rows, run-label permutation (100000 draws) for larger
#   ones and for pooled rows, exact signed-rank sign-flip for const rows.
#   Multiple testing: Benjamini-Hochberg at q = 0.05 over distinct executions (shared executions once).
#   New bold = 95% interval excludes 0 and BH-adjusted q <= 0.05.
import csv, glob, itertools, json, math, os, random, re, statistics as st, sys

import argparse
from pathlib import Path

sys.dont_write_bytecode = True
REPO = Path(__file__).resolve().parents[3]
ROOT = str(REPO)
HERE = f"{ROOT}/data/review/stats"            # cache/, scorer outputs, stored results.json
DATA = f"{ROOT}/data"
ap = argparse.ArgumentParser(description="BH-FDR pass over Table II")
ap.add_argument("--raw", help="paper2 workspace dir with the raw run logs and MEV_Spectrum/tab_*.tex (not in the repo)")
ap.add_argument("--results", default=f"{HERE}/results.json", help="stored per-run values (default mode)")
ap.add_argument("--out", help="write the full results JSON here")
ARGS = ap.parse_args()
P2 = ARGS.raw or "paper_workspace/paper2"     # only read in --raw mode
TAB_CELLS = f"{P2}/MEV_Spectrum/tab_cells.tex"
TAB_FR = f"{P2}/MEV_Spectrum/tab_frontrun.tex"
STORED = None if ARGS.raw else json.load(open(ARGS.results))
B_BOOT, B_PERM, EXACT_LIMIT = 20000, 100000, 1_000_000
Q_BH = 0.05

# ============================================================================ loaders
_fr_cache = None


def fr_scores():
    global _fr_cache
    if _fr_cache is None:
        _fr_cache = json.load(open(f"{HERE}/cache/frontrun_scores.json"))
    return _fr_cache


def sui_fr(subdir, prefix, order="cons"):
    """Per-run success_pct of paper2/frontrun/<subdir>/<prefix>_rep*.log (score_frontrun.py)."""
    fs = sorted(glob.glob(f"{P2}/frontrun/{subdir}/{prefix}_rep*.log"))
    c = fr_scores()
    out = []
    for f in fs:
        rec = c[os.path.relpath(f, f"{P2}/frontrun")]
        assert rec["size"] == os.path.getsize(f), f"stale cache for {f}"
        out.append(rec[order])
    return out


def jl(path):
    return [json.loads(l) for l in open(path) if l.startswith("{")]


def bull_fr(arms):
    return [r["success_pct"] for r in jl(f"{DATA}/bullshark/bullshark_frontrun/scores.jsonl") if r["arm"] in arms]


def txc(arm):
    return [r["success_pct"] for r in jl(f"{DATA}/bullshark/bullshark_frontrun/txc_scores.jsonl") if r["arm"] == arm]


def coal(arm):
    return [(r["succ"], r["total"]) for r in jl(f"{DATA}/bullshark/coal/runs_pooled.jsonl") if r["arm"] == arm and r["total"] > 0]


def t2(arm, m):
    return [tuple(r[m]) for r in jl(f"{DATA}/bullshark/coal/t2_pooled_runs.txt") if r["arm"] == arm and r[m][1] > 0]


def fig4(arm):
    return [100.0 * r["same_round_succ"] / r["same_round_total"] for r in jl(f"{DATA}/bullshark/coal/fig4_runs.jsonl") if r["arm"] == arm]


def mlaw(arm):
    return [(r["succ"], r["pairs"]) for r in jl(f"{DATA}/sui_frontrun/mlaw_scores.jsonl") if r["arm"] == arm]


def compete(arm):
    rows = sorted((r for r in jl(f"{DATA}/sui_frontrun/compete_scores.jsonl") if re.fullmatch(rf"{arm}_rep\d+\.log", r["run"])), key=lambda r: r["run"])
    return [r["cons"]["any"] for r in rows]


_sel = None


def sel290(arm):
    global _sel
    if _sel is None:
        sys.path.insert(0, f"{P2}/sel290")
        import score as _s  # paper2/sel290/score.py
        _sel = _s
    out = []
    for f in sorted(glob.glob(f"{P2}/sel290/{arm}_rep*.log")):
        o, logged = _sel.load(f)
        if not o:
            continue  # n49_sel_rep5 has no committed order (run stopped)
        ap, sr, t, na = _sel.rates(o)
        out.append(sr)
    return out


def e5(arm):
    """Strict-silence Sui runs (data/sui/e5/scores.jsonl), per-run same-round rate, in rep order."""
    rows = sorted((r for r in jl(f"{DATA}/sui/e5/scores.jsonl") if r["arm"] == arm),
                  key=lambda r: int(re.search(r"_rep(\d+)", r["run"]).group(1)))
    return [r["same_round"] for r in rows]


def sel_bull(kind):
    vals = []
    for line in open(f"{DATA}/bullshark/sel_bull_scores.txt"):
        if line.startswith(kind + " "):
            vals.append(float(re.search(r"M2 same-round : ([0-9.]+)%", line).group(1)))
    return vals


def v2csv(path, cell, field):
    rows = sorted((r for r in csv.DictReader(open(path)) if r["cell_name"] == cell), key=lambda r: int(r["rep"]))
    assert rows and all(r["exit_code"] == "0" for r in rows)
    return [float(r[field]) for r in rows]


def final_asr(pattern):
    vals = []
    for f in sorted(glob.glob(pattern)):
        m = re.findall(r"FINAL_ASR_RESULT: ([0-9.]+)", open(f, errors="replace").read())
        vals.append(float(m[-1]))
    return vals


def backrun_l1(pattern):
    vals = []
    for f in sorted(glob.glob(pattern)):
        m = re.findall(r'FINAL_BACKRUN_STATS: \{"l1_asr": ([0-9.]+)', open(f, errors="replace").read())
        vals.append(float(m[-1]))
    return vals


def aleph_base_rescored():
    rows = sorted((json.loads(l) for l in open(f"{HERE}/cache/aleph_nospec_base_rescored.jsonl")), key=lambda r: r["file"])
    assert len(rows) == 5 and all(len(r["scored"]) == 1 for r in rows)
    return [float(r["scored"][0]["cm_pct"]) for r in rows]


def mahi(prefix):
    rows = sorted((r for r in json.load(open(f"{P2}/mahimahi_rerun/scores.json")) if re.fullmatch(rf"runs/{prefix}_rep\d+", r["run"])), key=lambda r: r["run"])
    return [r["all_pairs"] for r in rows]


def t1_multi3():
    return [(r["succ"], r["total"]) for r in json.load(open(f"{HERE}/cache/t1_multi3_m3.json"))["runs"] if r["total"] > 0]


def cens(arm):
    """cens4 / f4 per-run censorship rates: the reps list of the scorer's FINAL_CENSORSHIP_MEDIAN line."""
    txt = open(f"{HERE}/cens4_f4_scorer_output.txt").read()
    m = re.search(rf"== {arm}\nFINAL_CENSORSHIP_MEDIAN: (\{{.*\}})", txt)
    return json.loads(m.group(1))["reps"]


def cens5():
    m = re.search(r"FINAL_CENSORSHIP_MEDIAN: (\{.*\})", open(f"{DATA}/bullshark/coal/cens5_scores.txt").read())
    d = json.loads(m.group(1))
    per_run = [json.loads(x)["censorship_rate_pct"] for x in re.findall(r"^run\d+: (\{.*\})$", open(f"{DATA}/bullshark/coal/cens5_scores.txt").read(), re.M)]
    assert sorted(per_run) == sorted(d["reps"])
    return per_run


def mlvw(label):
    for line in open(f"{P2}/PROVENANCE.md"):
        if line.startswith(f"| {label} |"):
            return [float(x) for x in line.split("|")[3].split()]
    raise KeyError(label)


def back_sand():
    rows = list(csv.reader(open(f"{ROOT}/back_sand_results.csv")))
    hdr = rows[0]; vals = []
    for r in rows[1:]:
        if r[0] == "timestamp":
            continue
        d = dict(zip(hdr, r))
        if (d["protocol"], d["attack_mode"], d["attack_type"], d["SANDWICH_METRIC_MODE"]) == ("bullshark", "fissure", "sandwich", "triplet"):
            assert d["exit_code"] == "0"; vals.append(float(d["asr"]))
    return vals


def autobahn_k16():
    return [float(r["asr"]) for r in csv.DictReader(open(f"{ROOT}/autobahn_results.csv"))
            if r["protocol"] == "autobahn" and r["experiment"] == "autobahn_k" and r["attack_mode"] == "fissure" and r["AUTOBAHN_K"] == "16"]


def autobahn_base():
    return [float(r["asr"]) for r in csv.DictReader(open(f"{ROOT}/baseline.csv")) if r["protocol"] == "autobahn" and r["status"] == "success"]


# ============================================================================ statistics
def pooled(runs):
    return 100.0 * sum(s for s, t in runs) / sum(t for s, t in runs)


def rate(runs):
    return [100.0 * s / t for s, t in runs]


def est_fn(est):
    if est == "median":
        return lambda a, b: st.median(b) - st.median(a)
    if est == "pooled":
        return lambda a, b: pooled(b) - pooled(a)
    raise ValueError(est)


def pctl(sorted_v, q):
    """Linear-interpolation percentile (numpy default / R type 7) of an already sorted list."""
    if not sorted_v:
        return None
    h = (len(sorted_v) - 1) * q; lo = math.floor(h); hi = math.ceil(h)
    a, b = sorted_v[lo], sorted_v[hi]
    if a == b:
        return a
    return a + (h - lo) * (b - a)


def sd(x):
    return st.stdev(x) if len(x) > 1 else float("nan")


def midranks(v):
    o = sorted(range(len(v)), key=lambda i: v[i]); r = [0.0] * len(v); i = 0
    while i < len(o):
        j = i
        while j + 1 < len(o) and v[o[j + 1]] == v[o[i]]:
            j += 1
        for k in range(i, j + 1):
            r[o[k]] = (i + j) / 2.0 + 1.0
        i = j + 1
    return r


def mw_exact(a, b):
    """Two-sided Wilcoxon-Mann-Whitney by complete enumeration: |rank sum of b - its null mean|."""
    pool = a + b; R = midranks(pool); na = len(a); N = len(pool); nb = N - na
    mean_b = nb * (N + 1) / 2.0; tot = sum(R); obs = abs(sum(R[na:]) - mean_b); c = 0; n = 0
    for idx in itertools.combinations(range(N), na):
        n += 1
        if abs(tot - sum(R[i] for i in idx) - mean_b) >= obs - 1e-9:
            c += 1
    return c / n, f"exact rank-sum ({n} relabelings)"


def mw_mc(a, b, seed):
    pool = a + b; R = midranks(pool); na = len(a); N = len(pool); mean_b = (N - na) * (N + 1) / 2.0
    obs = abs(sum(R[na:]) - mean_b); rng = random.Random(seed); RR = list(R); c = 0
    for _ in range(B_PERM):
        rng.shuffle(RR)
        if abs(sum(RR[na:]) - mean_b) >= obs - 1e-9:
            c += 1
    return (c + 1) / (B_PERM + 1), f"rank-sum Monte Carlo ({B_PERM} draws)"


def perm(a, b, f, seed):
    obs = abs(f(a, b)); pool = a + b; na = len(a); N = len(pool)
    if math.comb(N, na) <= EXACT_LIMIT:
        c = n = 0
        for idx in itertools.combinations(range(N), na):
            s = set(idx); n += 1
            if abs(f([pool[i] for i in idx], [pool[i] for i in range(N) if i not in s])) >= obs - 1e-9:
                c += 1
        return c / n, f"exact permutation ({n} relabelings)"
    rng = random.Random(seed); pool = list(pool); c = 0
    for _ in range(B_PERM):
        rng.shuffle(pool)
        if abs(f(pool[:na], pool[na:])) >= obs - 1e-9:
            c += 1
    return (c + 1) / (B_PERM + 1), f"permutation Monte Carlo ({B_PERM} draws)"


def signflip(d):
    nz = [v for v in d if v != 0]; R = midranks([abs(v) for v in nz]); n = len(nz)
    obs = abs(sum(r if v > 0 else -r for r, v in zip(R, nz))); c = 0
    for s in itertools.product((1, -1), repeat=n):
        if abs(sum(x * r for x, r in zip(s, R))) >= obs - 1e-9:
            c += 1
    return c / 2 ** n, f"exact signed-rank sign-flip ({2 ** n} flips)"


def boot(a, b, est, seed):
    """Bootstrap of the estimator and of the standardized effect (estimator / SD of resampled control)."""
    f = est_fn(est); rng = random.Random(seed); D = []; Z = []
    ca = rate(a) if est == "pooled" else None
    for _ in range(B_BOOT):
        ia = [rng.randrange(len(a)) for _ in a]; ib = [rng.randrange(len(b)) for _ in b]
        ra = [a[i] for i in ia]; rb = [b[i] for i in ib]
        d = f(ra, rb); D.append(d)
        ctrl = [ca[i] for i in ia] if est == "pooled" else ra
        s = sd(ctrl) if len(ctrl) > 1 else float("nan")
        Z.append(d / s if s > 0 else (math.copysign(math.inf, d) if d != 0 else float("nan")))
    D.sort(); zf = sorted(z for z in Z if z == z)
    return (pctl(D, 0.025), pctl(D, 0.975)), (pctl(zf, 0.025), pctl(zf, 0.975)), sum(1 for z in Z if math.isinf(z) or z != z)


def boot_const(x, c0, seed):
    rng = random.Random(seed); D = sorted(st.median([rng.choice(x) for _ in x]) - c0 for _ in range(B_BOOT))
    return pctl(D, 0.025), pctl(D, 0.975)


# ============================================================================ Table II definitions
FRB = f"{DATA}/bullshark/bullshark_frontrun/scores.jsonl"
COAL = f"{DATA}/bullshark/coal/runs_pooled.jsonl"
EXECS = {
    # exec id: (estimator, base loader, attack loader, source)
    "A1.1": ("median", lambda: bull_fr({"none", "none_x", "none_y"}), lambda: bull_fr({"fissure", "fissure_x", "fissure_y"}),
             f"{FRB}, arms none+none_x+none_y vs fissure+fissure_x+fissure_y, success_pct"),
    "A1.2": ("median", lambda: backrun_l1(f"{P2}/mysticeti_rerun/backrun_ctl/control_rep*.log"), lambda: backrun_l1(f"{P2}/mysticeti_rerun/runs/backrun_rep*.log"),
             f"{P2}/mysticeti_rerun/backrun_ctl/control_rep1-5.log vs {P2}/mysticeti_rerun/runs/backrun_rep1-5.log, FINAL_BACKRUN_STATS l1_asr"),
    "A1.3": ("const", None, back_sand,
             f"{ROOT}/back_sand_results.csv, protocol=bullshark (code/bullshark = Sui v1.58), fissure, sandwich, SANDWICH_METRIC_MODE=triplet, column asr; Base = assumed 50% line (no measured control)"),
    "A1.4": ("nodata", None, None, "CloudLab CENSOR=4 campaign: only the endpoints 0.35 and 84.40 are recorded (REPRODUCE.md (d)); no per-run file"),
    "A2.1": ("median", lambda: fig4("baseline_f4_n13"), lambda: fig4("fissure_f4_n13"),
             f"{DATA}/bullshark/coal/fig4_runs.jsonl, same_round_succ/same_round_total"),
    "A2.2": ("median", aleph_base_rescored, lambda: final_asr(f"{P2}/aleph_rerun/runs/spec_rep*.log"),
             f"base: {P2}/aleph_rerun/runs/nospec_base_rep1-5.log rescored (cache/aleph_nospec_base_rescored.jsonl, cm_pct); attack: {P2}/aleph_rerun/runs/spec_rep1-5.log FINAL_ASR_RESULT"),
    "A2.3": ("median", lambda: final_asr(f"{P2}/mysticeti_rerun/ctl/control_rep*.log"), lambda: final_asr(f"{P2}/mysticeti_rerun/runs/sluggish_rep*.log"),
             f"{P2}/mysticeti_rerun/ctl/control_rep1-5.log vs {P2}/mysticeti_rerun/runs/sluggish_rep1-5.log, FINAL_ASR_RESULT (all-pairs)"),
    "A2.4": ("median", lambda: sel290("rr_base"), lambda: sel290("rr_sel"),
             f"{P2}/sel290/rr_{{base,sel}}_rep1-5.log, same-round via sel290/score.py"),
    "A2.5": ("median", lambda: v2csv(f"{P2}/v2_290/withholding.csv", "withhold_baseline", "profit_weighted_asr"),
             lambda: v2csv(f"{P2}/v2_290/withholding.csv", "slw", "profit_weighted_asr"),
             f"{P2}/v2_290/withholding.csv, withhold_baseline vs slw, profit_weighted_asr"),
    "A2.6": ("median", lambda: v2csv(f"{P2}/v2_290/timestamp.csv", "timestamp_baseline", "asr"),
             lambda: v2csv(f"{P2}/v2_290/timestamp.csv", "timestamp", "asr"),
             f"{P2}/v2_290/timestamp.csv, timestamp_baseline vs timestamp, asr (all-pairs, 0.1 precision)"),
    "A2.7": ("median", lambda: mlvw("base (NO_ATTACK)"), lambda: mlvw("mlvw (pure, b=0)"),
             f"{P2}/PROVENANCE.md lines 865-866 (section 2.18): per-rep values transcribed at 0.1 precision; raw logs stayed on the CloudLab node"),
    "A3.2": ("pooled", lambda: coal("base6"), lambda: coal("f6ind"), f"{COAL}, base6 vs f6ind, succ/total"),
    "A3.3": ("pooled", lambda: coal("base6"), lambda: coal("f6"), f"{COAL}, base6 vs f6"),
    "A3.4": ("pooled", lambda: coal("base6"), lambda: coal("f6rival"), f"{COAL}, base6 vs f6rival"),
    "A3.5": ("median", lambda: compete("one"), lambda: compete("two"), f"{DATA}/sui_frontrun/compete_scores.jsonl, one vs two, cons.any"),
    "A4.2": ("median", lambda: final_asr(f"{P2}/aleph_safe/s123_spec_rep*.log"), lambda: final_asr(f"{P2}/aleph_safe/s123_spec_aware_rep*.log"),
             f"{P2}/aleph_safe/s123_spec_rep1-5.log vs s123_spec_aware_rep1-5.log, FINAL_ASR_RESULT"),
    "A4.3": ("median", lambda: sui_fr("runs_p1", "blk_none"), lambda: sui_fr("runs_p1", "mp_none"),
             f"{P2}/frontrun/runs_p1/blk_none_rep1-20.log vs mp_none_rep1-20.log, score_frontrun.score success_pct"),
    "A5.1": ("pooled", lambda: coal("base1"), lambda: coal("solo"), f"{COAL}, base1 vs solo"),
    "A5.2": ("pooled", lambda: coal("solo"), lambda: coal("bribe"), f"{COAL}, solo vs bribe"),
    "A5.3": ("median", lambda: cens("cens4"), cens5,
             f"base: cens4 reps in data/review/stats/cens4_f4_scorer_output.txt (scripts/score_censorship_bullshark.py on the CloudLab coal/cens4 runs); attack: {DATA}/bullshark/coal/cens5_scores.txt"),
    "A5.4": ("pooled", lambda: mlaw("base"), lambda: mlaw("b4"), f"{DATA}/sui_frontrun/mlaw_scores.jsonl, base vs b4, succ/pairs"),
    "A6.2": ("pooled", lambda: coal("base4"), lambda: coal("f4"), f"{COAL}, base4 vs f4"),
    "P1.2": ("median", lambda: sui_fr("runs_p1", "blk_none"), lambda: sui_fr("runs_p1", "blk_fissure"),
             f"{P2}/frontrun/runs_p1/blk_none_rep1-20.log vs blk_fissure_rep1-20.log, success_pct"),
    "P2.2": ("none", None, None, "no instance among the six protocols"),
    "P2.3": ("median", autobahn_base, autobahn_k16,
             f"base: {ROOT}/baseline.csv autobahn row (one run); attack: {ROOT}/autobahn_results.csv experiment=autobahn_k, fissure, AUTOBAHN_K=16 (5 runs)"),
    "P3.1": ("const", None, lambda: sel290("rr_base"), f"{P2}/sel290/rr_base_rep1-5.log same-round against the 50% line"),
    "P3.2": ("const", None, lambda: sel_bull("control"), f"{DATA}/bullshark/sel_bull_scores.txt, control lines, M2 same-round, against the 50% line"),
    "P3.3": ("median", lambda: sel290("rr_base"), lambda: sel290("p3_digest_base"), f"{P2}/sel290/rr_base vs p3_digest_base, same-round"),
    "P3.4": ("median", lambda: sel290("rr_base"), lambda: sel290("p3_seeded_base"), f"{P2}/sel290/rr_base vs p3_seeded_base, same-round"),
    "P3.5": ("median", lambda: sel290("rr_base"), lambda: sel290("p3_orderfair_base"), f"{P2}/sel290/rr_base vs p3_orderfair_base, same-round"),
    "P4.2": ("median", lambda: sel290("stake_base"), lambda: sel290("stake_sel"), f"{P2}/sel290/stake_{{base,sel}}_rep1-5.log, same-round"),
    "P4.3": ("median", lambda: sel290("rep_base"), lambda: sel290("rep_sel"), f"{P2}/sel290/rep_{{base,sel}}_rep1-5.log, same-round"),
    "P5.1": ("median", lambda: mahi("speculative"), lambda: mahi("speculative_w12"),
             f"{P2}/mahimahi_rerun/scores.json, runs/speculative_rep1-5 vs runs/speculative_w12_rep1-5, all_pairs"),
    "T1.2": ("pooled", lambda: coal("base4mv"), t1_multi3,
             f"base: {COAL} base4mv; attack: cache/t1_multi3_m3.json (measure.py m3 on fr_t1_logs.tgz t1_runs/multi3)"),
    "T2.1": ("pooled", lambda: t2("solo", "m1"), lambda: t2("bribe", "m1"), f"{DATA}/bullshark/coal/t2_pooled_runs.txt, solo vs bribe, m1"),
    "T2.2": ("pooled", lambda: t2("solo", "m2"), lambda: t2("bribe", "m2"), f"{DATA}/bullshark/coal/t2_pooled_runs.txt, solo vs bribe, m2"),
    "T2.4": ("median", lambda: v2csv(f"{DATA}/sui_value/valuemodel.csv", "baseline_uniform", "profit_weighted_asr"),
             lambda: v2csv(f"{DATA}/sui_value/valuemodel.csv", "silent_uniform", "profit_weighted_asr"), f"{DATA}/sui_value/valuemodel.csv, uniform"),
    "T3.2": ("median", lambda: v2csv(f"{DATA}/sui_value/valuemodel.csv", "baseline_pareto", "profit_weighted_asr"),
             lambda: v2csv(f"{DATA}/sui_value/valuemodel.csv", "silent_pareto", "profit_weighted_asr"), f"{DATA}/sui_value/valuemodel.csv, pareto"),
    "T3.3": ("median", lambda: v2csv(f"{DATA}/sui_value/valuemodel.csv", "baseline_lognormal", "profit_weighted_asr"),
             lambda: v2csv(f"{DATA}/sui_value/valuemodel.csv", "silent_lognormal", "profit_weighted_asr"), f"{DATA}/sui_value/valuemodel.csv, lognormal"),
    "D1.2": ("median", lambda: sel290("n25_base"), lambda: sel290("n25_sel"), f"{P2}/sel290/n25_{{base,sel}}, same-round"),
    "D1.3": ("median", lambda: e5("n49_base"), lambda: e5("n49_sel"), f"{DATA}/sui/e5/scores.jsonl, n49_base vs n49_sel, same_round (strict silence)"),
    "D2.1": ("median", lambda: sel290("d2_sbeq_base"), lambda: sel290("d2_sbeq_sel"), f"{P2}/sel290/d2_sbeq_{{base,sel}}, same-round"),
    "D2.2": ("median", lambda: sel290("d2_sbskew_base"), lambda: sel290("d2_sbskew_sel"),
             f"{P2}/sel290/d2_sbskew_{{base,sel}} (run_d2.sh), same-round; same configuration as P4.2's stake_* runs, separate execution"),
    "D3.2": ("median", lambda: sel290("wan_base"), lambda: sel290("wan_sel"), f"{P2}/sel290/wan_{{base,sel}}, same-round"),
    "D3.3": ("median", lambda: e5("asym_base"), lambda: e5("asym_sel"), f"{DATA}/sui/e5/scores.jsonl, asym_base vs asym_sel, same_round (strict silence)"),
}
SUPP = {
    # Not a printed Table II value: the k = 4 censorship re-run on CloudLab that A1.4/A2.8's cause column cites
    # ("0.8 in a second campaign"), against its control (the f4 arm, same harness, no CENSOR).
    "A1.4-rerun": ("median", lambda: cens("f4"), lambda: cens("cens4"),
                   "data/review/stats/cens4_f4_scorer_output.txt: '== f4' reps (control, 14 runs) vs '== cens4' reps (CENSOR=4, 16 runs), "
                   "scripts/score_censorship_bullshark.py on the CloudLab coal/{f4,cens4}/fissure_f4_n13 runs"),
}
ROW2EXEC = {"P1.1": "A1.1", "A2.8": "A1.4", "A4.1": "A2.1", "P2.4": "A2.2", "A3.1": "A2.4", "P2.1": "A2.4", "P4.1": "A2.4",
            "D1.1": "A2.4", "D3.1": "A2.4", "A6.3": "A3.3", "A6.1": "A5.1", "T2.3": "A5.2", "T1.1": "A6.2", "T3.1": "T2.4"}
NOT_IN_FAMILY = {"P3.1": "fixed 50% line; the caption tests it through P3.3-P3.5"}


def parse_table():
    if STORED is not None:
        return [{"row": r["row"], "value": r["value"], "protocol": r["protocol"], "metric": r["metric"],
                 "base_s": r["printed"]["base"], "attack_s": r["printed"]["attack"], "delta_s": r["printed"]["delta"],
                 "bold": r["bold_now"]} for r in STORED["rows"]]
    rows = []
    for line in open(TAB_CELLS):
        m = re.match(r"^([ATPD]\d\.\d)(\$\^\\ddagger\$)?\s*&", line)
        if not m:
            continue
        f = [x.strip() for x in line.rstrip().rstrip("\\").split("&")]
        num = lambda s: None if "--" in s else re.search(r"([+-]?\d+\.\d+|[+-]?\d+)", s).group(1)
        rows.append({"row": m.group(1), "value": f[1], "protocol": f[3], "metric": f[8].rstrip("\\ ").strip(),
                     "base_s": num(f[4]), "attack_s": num(f[5]), "delta_s": num(f[6]), "bold": "\\mathbf" in f[6]})
    return rows


def decimals(s):
    return len(s.split(".")[1]) if s and "." in s else 0


def check(printed, val):
    """'ok' if val rounds to the printed string, else the signed gap."""
    if printed is None or val is None:
        return None
    d = decimals(printed); p = float(printed)
    return "ok" if abs(round(val, d) - p) < 1e-9 or abs(val - p) <= 0.5 * 10 ** -d + 1e-9 else round(val - p, 4)


def run_exec(eid):
    est, lb, la, src = EXECS[eid] if eid in EXECS else SUPP[eid]
    rec = {"exec": eid, "estimator": est, "source": src.replace(ROOT + "/", "")}
    if STORED is not None and est not in ("nodata", "none"):
        s = STORED["executions"].get(eid) or STORED["supplementary"][eid]
        conv = (lambda xs: [tuple(x) for x in xs]) if est == "pooled" else (lambda xs: list(xs))
        lb = lambda: conv(s["base_runs"]); la = lambda: conv(s["attack_runs"])
    if est in ("nodata", "none"):
        rec["status"] = est; return rec
    seed = f"{eid}-20261028"
    if est == "const":
        x = la(); d = st.median(x) - 50.0
        lo, hi = boot_const(x, 50.0, seed + "b")
        p, how = signflip([v - 50.0 for v in x])
        s_att = sd(x)
        rec.update({"status": "ok", "n_base": 0, "n_attack": len(x), "base_runs": [], "attack_runs": list(x),
                    "base": 50.0, "attack": st.median(x), "delta": d, "ci": [lo, hi], "p": p, "test": how,
                    "sd_control": None, "z": None, "z_ci": None, "z_alt_measured_arm_sd": (d / s_att if s_att > 0 else None)})
        return rec
    a, b = lb(), la()
    f = est_fn(est)
    if est == "pooled":
        bpt, apt = pooled(a), pooled(b); ctrl = rate(a)
        rec["base_runs"] = [list(r) for r in a]; rec["attack_runs"] = [list(r) for r in b]
        rec["base_rates"] = [round(v, 4) for v in rate(a)]; rec["attack_rates"] = [round(v, 4) for v in rate(b)]
        p, how = perm(a, b, f, seed + "p")
        rec["p_secondary"] = None
    else:
        bpt, apt = st.median(a), st.median(b); ctrl = a
        rec["base_runs"] = list(a); rec["attack_runs"] = list(b)  # full precision, so the default mode reruns exactly
        if math.comb(len(a) + len(b), len(a)) <= EXACT_LIMIT:
            p, how = mw_exact(a, b)
            ps, hs = perm(a, b, f, seed + "p")
            rec["p_secondary"] = {"p": ps, "test": hs + ", statistic = median difference"}
        else:
            p, how = perm(a, b, f, seed + "p"); how += ", statistic = median difference"
            ps, hs = mw_mc(a, b, seed + "r")
            rec["p_secondary"] = {"p": ps, "test": hs}
    d = f(a, b)
    (lo, hi), (zlo, zhi), zbad = boot(a, b, est, seed + "b")
    s = sd(ctrl)
    rec.update({"status": "ok", "n_base": len(a), "n_attack": len(b), "base": bpt, "attack": apt, "delta": d, "ci": [lo, hi],
                "p": p, "test": how, "sd_control": s, "z": (d / s if s and s > 0 else None), "z_ci": [zlo, zhi], "z_boot_inf_or_nan": zbad})
    return rec


# ============================================================================ BH
def bh(pvals):
    """pvals: dict id -> p. Returns dict id -> (q, rank)."""
    items = sorted(pvals.items(), key=lambda kv: kv[1]); m = len(items); q = [0.0] * m; prev = 1.0
    for i in range(m - 1, -1, -1):
        prev = min(prev, items[i][1] * m / (i + 1)); q[i] = prev
    return {k: (q[i], i + 1) for i, (k, _) in enumerate(items)}, m


# ============================================================================ Table V
def tv_arms():
    """(panel, label, visibility, printed runs/median/range from tab_frontrun.tex row order, loader, source)."""
    P = "Sui consensus order, commits read at the attacker"
    arms = [
        (P, "blind", lambda: sui_fr("runs", "blind"), "frontrun/runs/blind"),
        (P, "blind_fix", lambda: sui_fr("runs", "blind_fix"), "frontrun/runs/blind_fix"),
        (P, "react0", lambda: sui_fr("runs", "react0"), "frontrun/runs/react0"),
        (P, "wait200", lambda: sui_fr("runs", "wait200"), "frontrun/runs/wait200"),
        (P, "wait200_fix", lambda: sui_fr("runs", "wait200_fix"), "frontrun/runs/wait200_fix"),
    ]
    B = "Bullshark front-run (tx)"
    for k in ["none", "fissure", "none_grind", "fissure_grind", "none_spray", "fissure_spray", "fissure_grind_spray", "none_vspray", "fissure_vspray"]:
        arms.append((B, k, (lambda k=k: bull_fr({k, k + "_x", k + "_y"})), f"data/bullshark/bullshark_frontrun/scores.jsonl arms {k}(+_x,_y)"))
    C = "Bullshark corruption campaign (txc)"
    for k in ["tbase1", "tsolo", "tbribe3", "tbase4", "tf4"]:
        arms.append((C, k, (lambda k=k: txc(k)), f"data/bullshark/bullshark_frontrun/txc_scores.jsonl arm {k}"))
    M = "Sui consensus order, matched to Bullshark"
    for k in ["blk_none", "blk_fissure", "mp_none", "mp_fissure"]:
        arms.append((M, k, (lambda k=k: sui_fr("runs_p1", k)), f"frontrun/runs_p1/{k}"))
    V = "Sui consensus order, one attacker, three victims"
    for k in ["blk_none_v1", "mp_none_v1", "mp_none_fix_v1", "blk_fissure_v1", "mp_fissure_v1", "blk_speculative_v1", "mp_speculative_v1"]:
        arms.append((V, k, (lambda k=k: sui_fr("runs", k)), f"frontrun/runs/{k}"))
    for k in ["blk_sluggish", "mp_sluggish"]:
        arms.append((V, k, (lambda k=k: sui_fr("runs_slug_nb", k)), f"frontrun/runs_slug_nb/{k}"))
    for k in ["blk_sel_v1", "mp_sel_v1"]:
        arms.append((V, k, (lambda k=k: sui_fr("runs", k)), f"frontrun/runs/{k}"))
    E = "Sui execution order"
    for k in ["bc_d0_outbid", "bc_d50_outbid", "bc_d200_outbid", "bc_d50_match", "bc_d50_match_fix", "hook_mp_d50_outbid", "hook_blk_outbid"]:
        arms.append((E, k, (lambda k=k: sui_fr("runs_gas", k, "exec")), f"frontrun/runs_gas/{k} (exec order)"))
    VB = "Sui execution order, victim broadcast campaign"
    for k in ["bc", "bc_vb", "mp", "mp_vb"]:
        arms.append((VB, k, (lambda k=k: sui_fr("runs_vbcast", k, "exec")), f"frontrun/runs_vbcast/{k} (exec order)"))
    CP = "Sui consensus order, competition (A3.5)"
    for k in ["one", "two"]:
        arms.append((CP, k, (lambda k=k: compete(k)), f"data/sui_frontrun/compete_scores.jsonl {k}, cons.any"))
    return arms


def parse_tab_fr():
    if STORED is not None:
        return [t["printed"] for t in STORED["tableV"]]
    rows = []
    for line in open(TAB_FR):
        m = re.match(r"^(.*?)&(.*?)&\s*(\d+)\s*&\s*\$([0-9.]+)\$\s*&\s*\\scriptsize\[([0-9.]+), ([0-9.]+)\]", line)
        if m:
            rows.append({"label": m.group(1).strip(), "vis": m.group(2).strip(), "runs": int(m.group(3)), "median": m.group(4), "lo": m.group(5), "hi": m.group(6), "line": line.rstrip("\n")})
    return rows


# ============================================================================ main
def f2(x, d=2):
    return "--" if x is None else (f"{x:+.{d}f}" if isinstance(x, float) else str(x))


def fp(p):
    if p is None:
        return "--"
    if p < 0.001:
        return f"{p:.1e}"
    return f"{p:.4f}"


def fci(ci, d=2):
    if not ci or ci[0] is None:
        return "--"
    g = lambda v: ("+inf" if v == math.inf else "-inf" if v == -math.inf else f"{v:+.{d}f}")
    return f"[{g(ci[0])}, {g(ci[1])}]"


def main():
    table = parse_table()
    assert len(table) == 59, len(table)
    ex = {}
    for eid in EXECS:
        ex[eid] = run_exec(eid)
        r = ex[eid]
        if r["status"] == "ok":
            print(f"{eid:5s} {r['estimator']:6s} n={r['n_base']}/{r['n_attack']} base={r['base']:.3f} att={r['attack']:.3f} d={r['delta']:+.3f} "
                  f"ci={fci(r['ci'])} p={fp(r['p'])} z={r['z']}", flush=True)
    supp = {e: run_exec(e) for e in SUPP}
    for e, r in supp.items():
        print(f"{e} n={r['n_base']}/{r['n_attack']} base={r['base']:.3f} att={r['attack']:.3f} d={r['delta']:+.3f} ci={fci(r['ci'])} p={fp(r['p'])}")
    # BH family: every tested execution except NOT_IN_FAMILY
    fam = {e: r["p"] for e, r in ex.items() if r["status"] == "ok" and e not in NOT_IN_FAMILY}
    qs, m = bh(fam)
    # sensitivity 1: P4.2 and D2.2 as one execution, as the caption lists them (keep P4.2's runs)
    fam_cap = {k: v for k, v in fam.items() if k != "D2.2"}
    qs_cap, m_cap = bh(fam_cap)
    # sensitivity 2: only the rows the caption tests today (drop the newly tested A1.2, A1.3, P2.3)
    fam_now = {k: v for k, v in fam.items() if k not in ("A1.2", "A1.3", "P2.3")}
    qs_now, m_now = bh(fam_now)
    # sensitivity 3: rank-sum p instead of the median-difference permutation for the large-n median rows
    fam_rank = {k: (ex[k]["p_secondary"]["p"] if ex[k]["estimator"] == "median" and "median difference" in ex[k]["test"] else v) for k, v in fam.items()}
    qs_rank, m_rank = bh(fam_rank)
    sens = {"caption_grouping": (qs_cap, m_cap), "current_rows_only": (qs_now, m_now), "ranksum_large_n": (qs_rank, m_rank)}

    rows_out = []
    for t in table:
        rid = t["row"]; eid = ROW2EXEC.get(rid, rid); r = ex.get(eid, {"status": "none"})
        o = {"row": rid, "exec": eid, "shared": eid != rid, "value": t["value"], "protocol": t["protocol"], "metric": t["metric"],
             "printed": {"base": t["base_s"], "attack": t["attack_s"], "delta": t["delta_s"]}, "bold_now": t["bold"], "status": r["status"]}
        if r["status"] == "ok":
            ci = r["ci"]; ci_ex0 = (ci[0] > 0 or ci[1] < 0)
            o.update({k: r[k] for k in ("estimator", "source", "n_base", "n_attack", "base", "attack", "delta", "ci", "p", "test", "p_secondary",
                                       "sd_control", "z", "z_ci", "base_runs", "attack_runs") if k in r})
            o["z_alt_measured_arm_sd"] = r.get("z_alt_measured_arm_sd")
            o["check"] = {"base": check(t["base_s"], r["base"]), "attack": check(t["attack_s"], r["attack"]), "delta": check(t["delta_s"], r["delta"])}
            o["ci_excludes_0"] = ci_ex0
            o["old_rule_recomputed"] = bool(ci_ex0 and r["p"] < 0.05)
            if eid in NOT_IN_FAMILY:
                o["bh_q"] = None; o["bold_new"] = False; o["note"] = NOT_IN_FAMILY[eid]
            else:
                o["bh_q"], o["bh_rank"] = qs[eid]; o["bh_survive"] = qs[eid][0] <= Q_BH
                o["bold_new"] = bool(ci_ex0 and o["bh_survive"])
                for name, (qq, _) in sens.items():
                    if eid in qq:
                        o[f"bh_q_{name}"] = qq[eid][0]
        else:
            o["source"] = EXECS.get(eid, (None, None, None, ""))[3]
            o["bold_new"] = False
        rows_out.append(o)

    # Table V
    tv = []
    printed = parse_tab_fr()
    arms = tv_arms() if STORED is None else [(t["panel"], t["arm"], (lambda t=t: t["runs"]), t["source"]) for t in STORED["tableV"]]
    assert len(printed) == len(arms), (len(printed), len(arms))
    for pr, (panel, key, ld, src) in zip(printed, arms):
        v = sorted(x for x in ld() if x is not None and x == x)
        q1, q3 = pctl(v, 0.25), pctl(v, 0.75)
        med = st.median(v)
        ok = (len(v) == pr["runs"] and f"{med:.1f}" == pr["median"] and f"{min(v):.1f}" == pr["lo"] and f"{max(v):.1f}" == pr["hi"])
        tv.append({"panel": panel, "arm": key, "label": pr["label"], "vis": pr["vis"], "source": src, "n": len(v), "median": med,
                   "min": min(v), "max": max(v), "q1": q1, "q3": q3, "printed": pr, "reproduces_printed": ok,
                   "new_line": pr["line"].replace(f"\\scriptsize[{pr['lo']}, {pr['hi']}]", f"\\scriptsize[{q1:.1f}, {q3:.1f}]"),
                   "runs": [round(x, 4) for x in v]})

    if ARGS.out:
        json.dump({"executions": ex, "supplementary": supp, "rows": rows_out, "bh_m": m, "bh_q": {k: v[0] for k, v in qs.items()},
                   "bh_sensitivity": {k: {"m": mm, "q": {e: v[0] for e, v in qq.items()}} for k, (qq, mm) in sens.items()}, "tableV": tv},
                  open(ARGS.out, "w"), indent=1, default=str)
    summary(rows_out, ex, fam, qs, m, tv)


def summary(rows, ex, fam, qs, m, tv):
    surv = [e for e in fam if qs[e][0] <= Q_BH]
    newb = [e for e in surv if ex[e]["ci"][0] > 0 or ex[e]["ci"][1] < 0]
    print()
    print(f"BH family: {m} distinct tested executions ({len(rows)} rows; shared executions once; P3.1 left out)")
    print(f"survive Benjamini-Hochberg at q = {Q_BH}: {len(surv)}; of these, 95% CI excludes 0 (new bold): {len(newb)}")
    print(f"survive BH but CI contains 0: {sorted(set(surv) - set(newb))}")
    print(f"rows: {sum(1 for r in rows if r.get('bh_q') is not None)} tested, {sum(1 for r in rows if r.get('bh_survive'))} survive BH, "
          f"{sum(1 for r in rows if r['bold_new'])} new bold; bold now {sum(r['bold_now'] for r in rows)} of {len(rows)}")
    ch = [f"{r['row']} ({'bold -> not bold' if r['bold_now'] else 'not bold -> bold'})" for r in rows if r["bold_now"] != r["bold_new"]]
    print("bold status changes: " + (", ".join(ch) if ch else "none"))
    print(f"Table V: {sum(t['reproduces_printed'] for t in tv)} of {len(tv)} arms reproduce the printed n, median, min and max")


if __name__ == "__main__":
    main()
