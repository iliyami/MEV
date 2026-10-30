#!/usr/bin/env python3
"""Cost of the victim-broadcast defense: per-arm tables and permutation tests (prints markdown).
Inputs: data/review/bcast/bull_rows.jsonl (bull_cost.py, 60 Bullshark runs) and sui_rows.jsonl
(sui_copies.py, 20 Sui runs); other paths can be given as: aggregate.py [bull_rows] [sui_rows].
Prints the paper numbers: 13 committed copies per victim tx, 0.44% of committed bytes, 29,615 vs
29,583 tx/s (p = 0.24), consensus latency 563 vs 562 ms, victim latency 799 -> 586 ms (p < 0.001).
"""
import itertools, json, os, random, statistics as st, sys
from pathlib import Path

DATA = Path(__file__).resolve().parents[3] / "data/review/bcast"
BULL = sys.argv[1] if len(sys.argv) > 1 else DATA / "bull_rows.jsonl"
SUI = sys.argv[2] if len(sys.argv) > 2 else DATA / "sui_rows.jsonl"

def perm_p(a, b, stat=st.median, n_mc=100000, seed=1):
    """Two-sided permutation p for difference of `stat` between groups a and b.
    Exact enumeration when C(n,k) <= 200000, else seeded Monte Carlo."""
    obs = abs(stat(a) - stat(b))
    pool = a + b
    k = len(a)
    from math import comb
    if comb(len(pool), k) <= 200000:
        hits = tot = 0
        for idx in itertools.combinations(range(len(pool)), k):
            s = set(idx)
            x = [pool[i] for i in idx]; y = [pool[i] for i in range(len(pool)) if i not in s]
            tot += 1
            hits += abs(stat(x) - stat(y)) >= obs - 1e-12
        return hits / tot, "exact"
    rng = random.Random(seed)
    hits = 0
    for _ in range(n_mc):
        rng.shuffle(pool)
        hits += abs(stat(pool[:k]) - stat(pool[k:])) >= obs - 1e-12
    return (hits + 1) / (n_mc + 1), f"MC {n_mc}"

def rng_(xs):
    return f"{st.median(xs):.1f} [{min(xs):.1f}, {max(xs):.1f}]"

# ---------------- Bullshark ----------------
B = [json.loads(l) for l in open(BULL)]
def arm_of(run):
    # run dirs are laid out as .../fr_runs/<arm>/<cell>/run<k>
    return run.split("fr_runs/")[1].split("/")[0]
groups = {
    "No attack, attacker to all, victim to one (none_spray+none_spray_x)": ["none_spray", "none_spray_x"],
    "No attack, both to all (none_vspray)": ["none_vspray"],
    "Fissure, attacker to all, victim to one (fissure_spray+fissure_spray_x)": ["fissure_spray", "fissure_spray_x"],
    "Fissure, both to all (fissure_vspray)": ["fissure_vspray"],
}
G = {g: [r for r in B if arm_of(r["run"]) in arms] for g, arms in groups.items()}
print("## Bullshark per-arm (per-run medians, [min, max] over runs)\n")
print("| arm | runs | victim committed copies per tx: pooled median / max / min | victim copies sealed in batches: median / max | victim copy bytes committed per run (MB) | victim copy bytes as % of committed bytes | committed bytes per run (MB) | consensus TPS | consensus latency mean (ms) | end-to-end latency mean (ms) | victim send-to-commit latency, per-run median (ms) |")
print("|---|---|---|---|---|---|---|---|---|---|---|")
summ = {}
for g, rows in G.items():
    pooled = []  # can't pool per-tx from summary; use per-run stats
    cc_med = [r["victim"]["committed_copies"]["median"] for r in rows]
    cc_max = [r["victim"]["committed_copies"]["max"] for r in rows]
    cc_min = [r["victim"]["committed_copies"]["min"] for r in rows]
    cc_mean = [r["victim"]["committed_copies"]["mean"] for r in rows]
    sc_med = [r["victim"]["sealed_copies"]["median"] for r in rows]
    sc_max = [r["victim"]["sealed_copies"]["max"] for r in rows]
    vbytes = [r["victim"]["committed_copy_total"] * r["tx_size"] / 1e6 for r in rows]
    share = [100.0 * r["victim"]["committed_copy_total"] * r["tx_size"] / r["committed_bytes"] for r in rows]
    cbytes = [r["committed_bytes"] / 1e6 for r in rows]
    tps = [r["consensus_tps"] for r in rows]
    clat = [r["consensus_latency_ms_mean"] for r in rows]
    e2e = [r["e2e_latency_ms_mean"] for r in rows]
    vlat = [r["victim_latency_ms"]["median"] for r in rows]
    # consensus TPS with the duplicate victim copies (committed copies beyond the first) removed
    utps = [(r["committed_bytes"] - (r["victim"]["committed_copy_total"] - r["victim"]["ids_committed"]) * r["tx_size"])
            / r["consensus_duration_s"] / r["tx_size"] for r in rows]
    summ[g] = dict(tps=tps, utps=utps, clat=clat, e2e=e2e, vlat=vlat, cbytes=cbytes, cc_mean=cc_mean)
    print(f"| {g} | {len(rows)} | {st.median(cc_med):g} / {max(cc_max)} / {min(cc_min)} (per-run mean copies {rng_(cc_mean)}) | {st.median(sc_med):g} / {max(sc_max)} | {rng_(vbytes)} | {st.median(share):.2f}% [{min(share):.2f}, {max(share):.2f}] | {rng_(cbytes)} | {rng_(tps)} | {rng_(clat)} | {rng_(e2e)} | {rng_(vlat)} |")
print()
print("Permutation tests (difference of per-run medians, victim-to-one vs both-to-all):\n")
pairs = [("No attack, attacker to all, victim to one (none_spray+none_spray_x)", "No attack, both to all (none_vspray)"),
         ("Fissure, attacker to all, victim to one (fissure_spray+fissure_spray_x)", "Fissure, both to all (fissure_vspray)")]
for a, b in pairs:
    for k in ("tps", "utps", "cbytes", "clat", "e2e", "vlat"):
        p, how = perm_p(summ[a][k], summ[b][k])
        print(f"- {a.split(',')[0]}: {k}: {st.median(summ[a][k]):.1f} -> {st.median(summ[b][k]):.1f}, p = {p:.4f} ({how})")
print()
tx = B[0]["tx_size"]
print(f"Bullshark tx size from client logs: {sorted(set(r['tx_size'] for r in B))} B")
print(f"Victim sends over all victim clients per run (both-to-all arms): " +
      str(sorted(r['victim_sent_all_clients'] for r in B if 'vspray' in arm_of(r['run']))))
print(f"Victim clients per run (both-to-all arms): {sorted(set(r['victim_clients'] for r in B if 'vspray' in arm_of(r['run'])))}")
for g, rows in G.items():
    print(f"{g}: TPS without duplicate victim copies {rng_(summ[g]['utps'])}; low-TPS runs (< 29000): {sum(1 for x in summ[g]['tps'] if x < 29000)}")
print(f"Attacker committed copies per tx, per-run median (all 60 runs): {sorted(set(r['attacker']['committed_copies']['median'] for r in B))}")

# ---------------- Sui ----------------
S = [json.loads(l) for l in open(SUI)]
def sarm(run):
    return os.path.basename(run).rsplit("_rep", 1)[0]
print("\n## Sui (consensus-core harness) per-arm\n")
print("| arm | runs | victim committed copies per tx: median / max / min | copies in the commit of the first copy: per-run median / mean [range] / max | distinct commits holding the copies: median / max | committed transactions per run (lower bound) | commits per run (60 s) | highest round |")
print("|---|---|---|---|---|---|---|---|")
sg = {}
for a in ("bc", "bc_vb", "mp", "mp_vb"):
    rows = [r for r in S if sarm(r["run"]) == a]
    V = [r["V"] for r in rows]
    fc_mean = [v["copies_in_first_commit"]["mean"] for v in V]
    sg[a] = dict(commits=[r["summary_commits"] for r in rows], rounds=[r["max_round"] for r in rows],
                 tx=[r["max_pos_plus1"] for r in rows])
    print(f"| {a} | {len(rows)} | {st.median([v['copies']['median'] for v in V]):g} / {max(v['copies']['max'] for v in V)} / {min(v['copies']['min'] for v in V)} | "
          f"{st.median([v['copies_in_first_commit']['median'] for v in V]):g} / {rng_(fc_mean)} / {max(v['copies_in_first_commit']['max'] for v in V)} | "
          f"{st.median([v['distinct_commits']['median'] for v in V]):g} / {max(v['distinct_commits']['max'] for v in V)} | "
          f"{st.median(sg[a]['tx']):g} [{min(sg[a]['tx'])}, {max(sg[a]['tx'])}] | {st.median(sg[a]['commits']):g} [{min(sg[a]['commits'])}, {max(sg[a]['commits'])}] | {st.median(sg[a]['rounds']):g} [{min(sg[a]['rounds'])}, {max(sg[a]['rounds'])}] |")
print()
for a, b in (("bc", "bc_vb"), ("mp", "mp_vb")):
    for k in ("commits", "rounds"):
        p, how = perm_p(sg[a][k], sg[b][k])
        print(f"- Sui {a} vs {b}: {k} {st.median(sg[a][k]):g} -> {st.median(sg[b][k]):g}, p = {p:.3f} ({how})")
