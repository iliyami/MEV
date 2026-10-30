#!/usr/bin/env python3
"""Honest and attacker omission rates of the victim's previous-round block in signed parent lists, and
rounds of observation that flag a refuser at a 1% false-alarm rate. Input: two parse_sui_ancestors.py
outputs (raw-log derived, not in the repo). Usage: omission_stats.py <none.jsonl> <fissure.jsonl>
<victims> <attackers> <label> > data/review/bribe/<label>_stats.json. Paper: honest rate 1.0%, two rounds.
"""
import json, math, sys, random

# opportunity = a block by proposer i at round R, and target j != i has a block at round R-1.
# omission = that round-R block's signed parent list does not contain (j, R-1).
# Streams are kept per (run, proposer i, target j) in round order.
from collections import defaultdict

ALPHA = 0.01


def load(path):
    with open(path) as fh:
        for line in fh:
            yield json.loads(line)


def streams(run):
    have = set()
    for a, r, ts, anc in run["blocks"]:
        have.add((a, r))
    per = defaultdict(list)          # (i, j) -> list of (R, omitted, j_absent_entirely)
    dup = 0
    seen = set()
    for a, r, ts, anc in sorted(run["blocks"], key=lambda b: (b[0], b[1])):
        if (a, r) in seen:
            dup += 1
            continue
        seen.add((a, r))
        ancset = set((x[0], x[1]) for x in anc)
        authors = set(x[0] for x in anc)
        for j in range(13):
            if j == a or (j, r - 1) not in have:
                continue
            om = (j, r - 1) not in ancset
            per[(a, j)].append((r, om, om and j not in authors))
    return per, dup


def round_rate(run):
    """Rounds per second per proposer (median over proposers) from the blocks' own timestamps."""
    by = defaultdict(list)
    for a, r, ts, anc in run["blocks"]:
        by[a].append((r, ts))
    rates = []
    for a, v in by.items():
        v.sort()
        if len(v) > 10 and v[-1][1] > v[0][1]:
            rates.append((v[-1][0] - v[0][0]) / ((v[-1][1] - v[0][1]) / 1000.0))
    rates.sort()
    return rates[len(rates) // 2] if rates else None


def wilson(k, n, z=1.96):
    if n == 0:
        return (float("nan"),) * 2
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - h) / d, (c + h) / d)


def binom_sf(c, n, p):
    """P(X >= c), X ~ Bin(n, p)."""
    if c <= 0:
        return 1.0
    if c > n:
        return 0.0
    s = 0.0
    for k in range(c, n + 1):
        s += math.comb(n, k) * p ** k * (1 - p) ** (n - k)
    return s


def all_omit_rounds(p0, alpha=ALPHA):
    """Smallest N with P(N omissions out of N | honest p0) = p0^N <= alpha."""
    if p0 <= 0:
        return 1
    return math.ceil(math.log(alpha) / math.log(p0))


def binom_rounds(p0, q, alpha=ALPHA, power=0.99, nmax=400):
    """Smallest N with a threshold c such that P(Bin(N,p0) >= c) <= alpha and P(Bin(N,q) >= c) >= power."""
    for n in range(1, nmax + 1):
        for c in range(0, n + 1):
            if binom_sf(c, n, p0) <= alpha:
                if binom_sf(c, n, q) >= power:
                    return n, c
                break
    return None, None


def windows(seq, N):
    """Counts of omissions in every sliding window of N consecutive opportunities."""
    out = []
    s = sum(seq[:N])
    if len(seq) < N:
        return out
    out.append(s)
    for k in range(N, len(seq)):
        s += seq[k] - seq[k - N]
        out.append(s)
    return out


def empirical(honest_streams, attacker_streams, Ns, alpha=ALPHA):
    rows = []
    for N in Ns:
        hw = []
        for s in honest_streams:
            hw.extend(windows(s, N))
        aw = []
        for s in attacker_streams:
            aw.extend(windows(s, N))
        if not hw:
            continue
        from collections import Counter
        hc, ac = Counter(hw), Counter(aw)
        H, A = len(hw), len(aw)
        def tail(cnt, tot, cc):
            return sum(v for k, v in cnt.items() if k >= cc) / tot
        fa_all = hc.get(N, 0) / H
        # smallest threshold c with empirical false-alarm <= alpha
        c = None
        for cc in range(0, N + 1):
            if tail(hc, H, cc) <= alpha:
                c = cc
                break
        pw = tail(ac, A, c) if (A and c is not None) else None
        fa_c = tail(hc, H, c) if c is not None else None
        rows.append({"N": N, "honest_windows": len(hw), "fa_all_omitted": fa_all, "threshold_c": c,
                     "fa_at_c": fa_c, "attacker_windows": len(aw), "power_at_c": pw})
    return rows


def summarize(none_path, fiss_path, victims, attackers, label):
    res = {"label": label, "victims": victims, "fissure_attackers": attackers}
    # ---------- no-attack runs ----------
    tot = defaultdict(lambda: [0, 0, 0])   # key -> [opps, omissions, absent-entirely omissions]
    pair = defaultdict(lambda: [0, 0])
    run_vict = []                           # per-run honest omission rate of the victim(s)
    honest_vict_streams, honest_all_streams = [], []
    rates, dups, nruns = [], 0, 0
    for run in load(none_path):
        nruns += 1
        per, dup = streams(run)
        dups += dup
        rr = round_rate(run)
        if rr:
            rates.append(rr)
        rv = [0, 0]
        for (i, j), s in per.items():
            prop = "p0" if i == 0 else "p1_12"
            tgt = "victim" if j in victims else "other"
            for key in (("all_proposers", "all_targets"), ("all_proposers", tgt), (prop, "all_targets"), (prop, tgt)):
                t = tot[key]
                t[0] += len(s)
                t[1] += sum(1 for x in s if x[1])
                t[2] += sum(1 for x in s if x[2])
            pair[(i, j)][0] += len(s)
            pair[(i, j)][1] += sum(1 for x in s if x[1])
            if i != 0:   # validator 0 is the front-runner (reacts and may wait); keep honest = 1..12
                seq = [1 if x[1] else 0 for x in s]
                honest_all_streams.append(seq)
                if j in victims:
                    honest_vict_streams.append(seq)
                    rv[0] += len(s)
                    rv[1] += sum(seq)
        if rv[0]:
            run_vict.append(rv[1] / rv[0])
    res["none_runs"] = nruns
    res["duplicate_block_lines"] = dups
    res["rounds_per_s_median_over_runs"] = sorted(rates)[len(rates) // 2] if rates else None
    res["rounds_per_s_range"] = [min(rates), max(rates)] if rates else None
    res["none_rates"] = {f"{k[0]}|{k[1]}": {"opps": v[0], "omit": v[1], "rate": v[1] / v[0] if v[0] else None,
                                             "wilson95": wilson(v[1], v[0]),
                                             "absent_entirely_share": (v[2] / v[1]) if v[1] else None}
                         for k, v in sorted(tot.items())}
    run_vict.sort()
    res["victim_rate_per_run"] = {"min": run_vict[0], "median": run_vict[len(run_vict) // 2], "max": run_vict[-1],
                                  "n": len(run_vict)}
    hp = [(v[1] / v[0], i, j, v[0]) for (i, j), v in pair.items() if i != 0 and v[0] > 0]
    hp.sort()
    res["honest_pair_rate_max"] = {"rate": hp[-1][0], "proposer": hp[-1][1], "target": hp[-1][2], "opps": hp[-1][3]}
    res["honest_pair_rate_median"] = hp[len(hp) // 2][0]
    vp = [x for x in hp if x[2] in victims]
    res["honest_pair_rate_max_victim"] = {"rate": vp[-1][0], "proposer": vp[-1][1], "target": vp[-1][2], "opps": vp[-1][3]}

    # ---------- fissure runs: attacker and honest omissions of the victim ----------
    att = [0, 0]; hon = [0, 0]
    att_streams = []
    run_att = []
    for run in load(fiss_path):
        per, _ = streams(run)
        ra = [0, 0]
        for (i, j), s in per.items():
            if j not in victims:
                continue
            seq = [1 if x[1] else 0 for x in s]
            if i in attackers:
                att[0] += len(seq); att[1] += sum(seq); att_streams.append(seq)
                ra[0] += len(seq); ra[1] += sum(seq)
            elif j != i:
                hon[0] += len(seq); hon[1] += sum(seq)
        if ra[0]:
            run_att.append(ra[1] / ra[0])
    run_att.sort()
    res["fissure_attacker_victim_rate"] = {"opps": att[0], "omit": att[1], "rate": att[1] / att[0] if att[0] else None,
                                           "wilson95": wilson(att[1], att[0]),
                                           "per_run_min": run_att[0] if run_att else None,
                                           "per_run_max": run_att[-1] if run_att else None}
    res["fissure_honest_victim_rate"] = {"opps": hon[0], "omit": hon[1], "rate": hon[1] / hon[0] if hon[0] else None}

    # ---------- detection ----------
    p0 = res["none_rates"]["p1_12|victim"]["rate"]
    p0_hi = res["none_rates"]["p1_12|victim"]["wilson95"][1]
    p0_pair = res["honest_pair_rate_max_victim"]["rate"]
    q = res["fissure_attacker_victim_rate"]["rate"]
    det = {}
    for name, p in (("pooled", p0), ("pooled_upper95", p0_hi), ("worst_honest_pair", p0_pair),
                    ("worst_run", res["victim_rate_per_run"]["max"])):
        n_all = all_omit_rounds(p)
        det[name] = {"p0": p, "rounds_all_omit": n_all, "fa_at_that_N": p ** n_all}
        if q:
            n, c = binom_rounds(p, q, power=0.99)
            n95, c95 = binom_rounds(p, q, power=0.95)
            det[name]["binom_vs_measured_attacker_99power"] = {"N": n, "c": c}
            det[name]["binom_vs_measured_attacker_95power"] = {"N": n95, "c": c95}
    res["binomial_detection"] = det
    Ns = list(range(1, 11)) + [12, 15, 20, 25, 30, 40, 50]
    res["empirical_sliding_window"] = empirical(honest_vict_streams, att_streams, Ns)
    res["empirical_sliding_window_all_targets_fa_all_omitted"] = [
        {"N": r["N"], "fa_all_omitted": r["fa_all_omitted"], "threshold_c": r["threshold_c"]}
        for r in empirical(honest_all_streams, [], list(range(1, 11)))]
    return res


if __name__ == "__main__":
    none_path, fiss_path, victims, attackers, label = sys.argv[1:6]
    victims = set(int(x) for x in victims.split(","))
    attackers = set(int(x) for x in attackers.split(","))
    print(json.dumps(summarize(none_path, fiss_path, victims, attackers, label), indent=1, default=list))
