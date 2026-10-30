#!/usr/bin/env python3
"""Offline re-scorer for AlephBFT run logs: rebuilds the unit DAG from TRACE "New unit received" lines,
reruns the AlephBFT ordering, and applies the project's ASR scoring. Input: one raw AlephBFT log (not in the
repo, e.g. aleph_rerun/runs/nospec_base_rep1.log) and a seed. Usage: aleph_rescore.py <log> <seed>
Output feeds data/review/stats/cache/aleph_nospec_base_rescored.jsonl (Table II row A2.2 control).
"""
import re, sys, json, struct
from collections import deque

N = 13
THRESH = (N * 2) // 3 + 1  # consensus_threshold
LOOKAHEAD = 3

RE_RECV = re.compile(
    r"New unit received UncheckedSigned \{ signable: FullUnit \{ pre_unit: PreUnit \{ coord: UnitCoord \{ round: (\d+), creator: NodeIndex\((\d+)\) \}, control_hash: ControlHash \{ parents: NodeMap\(\[([^\]]*)\]\), combined_hash: \[[^\]]*\] \} \}, data: [^,]*, session_id: \d+, hash: RwLock \{ data: Some\(\[([^\]]*)\]\) \}")

# ---------------- SipHash-1-3 (Rust DefaultHasher, keys 0,0) ----------------
M64 = (1 << 64) - 1
def _rotl(x, b): return ((x << b) | (x >> (64 - b))) & M64
def siphash13(data, k0=0, k1=0):
    v0 = k0 ^ 0x736f6d6570736575; v1 = k1 ^ 0x646f72616e646f6d
    v2 = k0 ^ 0x6c7967656e657261; v3 = k1 ^ 0x7465646279746573
    def rnd(v0, v1, v2, v3):
        v0 = (v0 + v1) & M64; v1 = _rotl(v1, 13); v1 ^= v0; v0 = _rotl(v0, 32)
        v2 = (v2 + v3) & M64; v3 = _rotl(v3, 16); v3 ^= v2
        v0 = (v0 + v3) & M64; v3 = _rotl(v3, 21); v3 ^= v0
        v2 = (v2 + v1) & M64; v1 = _rotl(v1, 17); v1 ^= v2; v2 = _rotl(v2, 32)
        return v0, v1, v2, v3
    L = len(data); end = L - (L % 8)
    for i in range(0, end, 8):
        m = struct.unpack_from('<Q', data, i)[0]
        v3 ^= m; v0, v1, v2, v3 = rnd(v0, v1, v2, v3); v0 ^= m
    b = (L & 0xff) << 56
    tail = data[end:]
    for i, c in enumerate(tail): b |= c << (8 * i)
    v3 ^= b; v0, v1, v2, v3 = rnd(v0, v1, v2, v3); v0 ^= b
    v2 ^= 0xff
    for _ in range(3): v0, v1, v2, v3 = rnd(v0, v1, v2, v3)
    return v0 ^ v1 ^ v2 ^ v3

def seeded_rank_key(seed, hb):
    # seed.hash(h) -> write_u64; bytes.hash(h) -> write_usize(len) + write(bytes)
    return siphash13(struct.pack('<Q', seed) + struct.pack('<Q', len(hb)) + bytes(hb))

# ---------------- parse ----------------
def parse(path):
    units = {}       # hash(tuple) -> (round, creator, parent_rounds list)
    by_coord = {}    # (round, creator) -> set(hash)
    with open(path, 'r', errors='replace') as f:
        for line in f:
            if 'New unit received' not in line: continue
            m = RE_RECV.search(line)
            if not m:
                raise SystemExit(f"unparsed unit line in {path}: {line[:200]}")
            r, c = int(m.group(1)), int(m.group(2))
            h = tuple(int(x) for x in m.group(4).split(','))
            if h in units: continue
            pr = []
            for tok in m.group(3).split(','):
                tok = tok.strip()
                if tok == 'None': pr.append(None)
                else: pr.append(int(tok[5:-1]))
            assert len(pr) == N
            units[h] = (r, c, pr)
            by_coord.setdefault((r, c), set()).add(h)
    return units, by_coord

def logged(path):
    out = {}
    with open(path, 'r', errors='replace') as f:
        for line in f:
            if 'FINAL_' not in line and 'closest-match' not in line and 'Attacker blocks' not in line \
               and 'Pairwise baseline' not in line and 'Units by creator' not in line and 'Total finalized units' not in line:
                continue
            if m := re.search(r'closest-match\): (\d+)/(\d+) trials = ([\d.]+)%', line):
                out['cm'] = (int(m.group(1)), int(m.group(2)), m.group(3))
            elif m := re.search(r'Attacker blocks: (\d+), Victim blocks: (\d+)', line):
                out['blocks'] = (int(m.group(1)), int(m.group(2)))
            elif m := re.search(r'FINAL_ASR_RESULT: ([\d.]+)%', line):
                out['final'] = m.group(1)
            elif m := re.search(r'FINAL_ALL_PAIRS_ASR: ([\d.]+)%', line):
                out['allpairs'] = m.group(1)
            elif m := re.search(r'FINAL_SAME_ROUND_ASR: ([\d.]+)% \(n_pairs=(\d+)\)', line):
                out['sameround'] = (m.group(1), int(m.group(2)))
            elif m := re.search(r'Pairwise baseline ASR \(node (\d+) vs node (\d+)\): (\d+)/(\d+) = ([\d.]+)%', line):
                out['pair'] = (int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4)), m.group(5))
            elif m := re.search(r'Units by creator: \{([^}]*)\}', line):
                out['by_creator'] = {int(k): int(v) for k, v in re.findall(r'(\d+): (\d+)', m.group(1))}
            elif m := re.search(r'Total finalized units collected: (\d+)', line):
                out['total'] = int(m.group(1))
    return out

# ---------------- AlephBFT ordering ----------------
def common_vote(rr):
    if rr == 3: return False
    if rr <= 4: return True
    return rr % 2 == 1

def build(units, by_coord):
    forks = {k: v for k, v in by_coord.items() if len(v) > 1}
    if forks:
        raise SystemExit(f"forked coords present ({len(forks)}), parent resolution ambiguous")
    coord_hash = {k: next(iter(v)) for k, v in by_coord.items()}
    parents = {}   # hash -> list of (parent_hash, parent_round) in index order
    for h, (r, c, pr) in units.items():
        lst = []
        for idx, prr in enumerate(pr):
            if prr is None: lst.append(None); continue
            ph = coord_hash.get((prr, idx))
            if ph is None:
                lst.append('MISSING'); continue
            lst.append((ph, prr))
        parents[h] = lst
    return coord_hash, parents

def order(units, parents, seed):
    """Returns list of batches (each a list of hashes) per AlephBFT extender."""
    # Only units whose full ancestry is present can be in a DAG.
    ok = {}
    for h in sorted(units, key=lambda x: units[x][0]):
        good = all(p is None or (p != 'MISSING' and ok.get(p[0], False)) for p in parents[h])
        ok[h] = good
    dag = [h for h in units if ok[h]]
    by_round = {}
    for h in dag: by_round.setdefault(units[h][0], []).append(h)
    highest = max(by_round)
    remaining = set(dag)

    def direct_parents(h):
        r = units[h][0]
        if r == 0: return []
        return [p[0] for p in parents[h] if p is not None and p[1] == r - 1]

    def decide(cand):
        cr, cc, _ = units[cand]
        votes = {}
        for rr_abs in range(cr + 1, highest + 1):
            rel = rr_abs - cr
            for v in by_round.get(rr_abs, []):
                if rel == 1:
                    p = parents[v][cc]
                    votes[v] = (p is not None and p[0] == cand)
                else:
                    dps = direct_parents(v)
                    vf = sum(1 for p in dps if votes[p]); va = len(dps) - vf
                    assert vf + va >= THRESH
                    cv = common_vote(rel)
                    if rel >= 3:
                        if cv and vf >= THRESH: return 'elected', rr_abs
                        if (not cv) and va >= THRESH: return 'eliminated', rr_abs
                    votes[v] = False if vf == 0 else (True if va == 0 else cv)
        return 'undecided', None

    batches = []
    rnd = 0
    while highest >= rnd + LOOKAHEAD and rnd in by_round:
        cands = sorted(by_round[rnd])
        if seed != 0:
            cands.sort(key=lambda h: (seeded_rank_key(seed, h), h))
        head = None
        for cand in cands:
            res, _ = decide(cand)
            if res == 'elected': head = cand; break
            if res == 'undecided': break
        if head is None: break
        # remove_batch: BFS from head over parents (index order) still remaining, then reverse
        batch = []; q = deque([head]); remaining.discard(head)
        while q:
            u = q.popleft()
            for p in parents[u]:
                if p is None: continue
                if p[0] in remaining:
                    remaining.discard(p[0]); q.append(p[0])
            batch.append(u)
        batch.reverse()
        batches.append(batch)
        rnd += 1
    return batches

# ---------------- scorers ----------------
ATT = range(0, 4)      # AttackLayout frontrun: 0..num_attackers (round(13*0.308)=4)
VIC = range(10, 13)    # num_nodes-num_victims..num_nodes (round(13*0.231)=3)

def closest_match(seq, units):
    att, vic = [], []
    for height, h in enumerate(seq):
        r, c, _ = units[h]
        if c in ATT: att.append((height, r))
        elif c in VIC: vic.append((height, r))
    succ = tot = 0
    for vh, vr in vic:
        cands = [(ah, ar) for ah, ar in att if ar >= vr]
        if not cands: continue
        ah, _ = min(cands, key=lambda x: (x[1] - vr, x[0]))  # stable sort by diff -> earliest height
        tot += 1
        if ah < vh: succ += 1
    return succ, tot, len(att), len(vic)

def all_pairs(seq, units):
    att, vic = [], []
    for height, h in enumerate(seq):
        r, c, _ = units[h]
        if c in ATT: att.append((r, height))
        elif c in VIC: vic.append((r, height))
    aps = apt = srs = srt = 0
    for ar, ah in att:
        for vr, vh in vic:
            apt += 1; aps += ah < vh
            if ar == vr:
                srt += 1; srs += ah < vh
    return aps, apt, srs, srt

def pair_baseline(seq, units, a, v):
    ap = [i for i, h in enumerate(seq) if units[h][1] == a]
    vp = [i for i, h in enumerate(seq) if units[h][1] == v]
    s = sum(1 for x in ap for y in vp if x < y)
    return s, len(ap) * len(vp)

def fmt(s, t): return f"{s / t * 100:.2f}" if t else "n/a"

def main():
    path, seed = sys.argv[1], int(sys.argv[2])
    units, by_coord = parse(path)
    lg = logged(path)
    coord_hash, parents = build(units, by_coord)
    batches = order(units, parents, seed)
    # candidate prefixes: cumulative per-creator counts after k batches
    seq = []; cnt = [0] * N
    matches = []
    prefixes = [(0, [], list(cnt))]
    for k, b in enumerate(batches, 1):
        seq.extend(b)
        for h in b: cnt[units[h][1]] += 1
        prefixes.append((k, len(seq), list(cnt)))
    res = {'file': path, 'seed': seed, 'n_units': len(units), 'n_batches': len(batches), 'logged': lg}
    def counts_match(c):
        if 'blocks' in lg:
            return (sum(c[i] for i in ATT), sum(c[i] for i in VIC)) == lg['blocks']
        if 'by_creator' in lg:
            return {i: c[i] for i in range(N) if c[i]} == lg['by_creator']
        return False
    cand_k = [k for k, L, c in prefixes if counts_match(c)]
    res['matching_prefixes'] = cand_k
    full = []
    for b in batches: full.extend(b)
    outs = []
    for k in cand_k:
        s = [h for b in batches[:k] for h in b]
        cm = closest_match(s, units)
        ap = all_pairs(s, units)
        pb = pair_baseline(s, units, 0, 1)
        outs.append({'k': k, 'len': len(s), 'cm_succ': cm[0], 'cm_trials': cm[1], 'cm_pct': fmt(cm[0], cm[1]),
                     'att_blocks': cm[2], 'vic_blocks': cm[3],
                     'allpairs_pct': fmt(ap[0], ap[1]), 'sameround_pct': fmt(ap[2], ap[3]), 'sameround_n': ap[3],
                     'pair01': (pb[0], pb[1], fmt(pb[0], pb[1]))})
    res['scored'] = outs
    print(json.dumps(res))

if __name__ == '__main__':
    main()
