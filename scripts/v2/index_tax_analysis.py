"""Index-tax analysis — per-validator ordering advantage from committed orders.

Reads one or more `FINAL_COMMITTED_ORDER: [...]` lines (the baseline consensus
dump; each block = {"creator","position","round"}) and computes, per validator
index, purely positional (assumption-free) and economic (value-weighted) fairness
metrics. NO attacker involved — this measures whether the honest, default
protocol already allocates ordering advantage by validator ID.

Metrics per creator i (aggregated over all rounds across all input orders):
  - leader_share : fraction of i's blocks that are first-in-round (the anchor).
  - wr_same_round: same-round win-rate — over all same-round pairs (i,j), the
                   fraction where i is ordered before j. Fair = 0.5 for every i.
  - wr_nonleader : same as above but EXCLUDING the round's leader block, so it
                   isolates the author-index tiebreak from the leader-anchor bonus.
  - mev_uniform  : realized-MEV proxy — sum over same-round blocks positioned
                   AFTER i of the block's value (uniform=1 each). "Value sitting
                   behind you in your round," i.e. what i could frontrun.
  - mev_pareto   : same with a heavy-tailed (pareto) per-block value.

Summary: Spearman monotonicity of wr vs index, Gini of mev across validators,
and top/bottom ratios. Usage:
    cat run.log | python -m scripts.v2.index_tax_analysis --n 13 --label default
    python -m scripts.v2.index_tax_analysis --n 13 --files a.log b.log
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Iterable


def parse_orders(text: str) -> list[list[dict]]:
    orders = []
    for line in text.splitlines():
        if "FINAL_COMMITTED_ORDER:" in line:
            arr = line.split("FINAL_COMMITTED_ORDER:", 1)[1].strip()
            try:
                orders.append(json.loads(arr))
            except json.JSONDecodeError:
                pass
    return orders


def _pareto_value(rank: int, shape: float = 1.16) -> float:
    # Deterministic heavy-tailed value keyed by a stable per-block ordinal, so
    # the value model is independent of validator index (no circularity).
    # value = scale / (u)^(1/shape) with u a fixed fraction of the ordinal.
    u = ((rank * 2654435761) % 10007 + 1) / 10008.0
    return u ** (-1.0 / shape)


def analyze(orders: list[list[dict]], n: int) -> dict:
    leader_cnt = defaultdict(int)
    block_cnt = defaultdict(int)
    wr_win = defaultdict(int)
    wr_pairs = defaultdict(int)
    wrnl_win = defaultdict(int)
    wrnl_pairs = defaultdict(int)
    mev_u = defaultdict(float)
    mev_p = defaultdict(float)

    ordinal = 0
    for order in orders:
        by_round = defaultdict(list)
        for b in order:
            by_round[b["round"]].append(b)
        for _r, blocks in by_round.items():
            blocks.sort(key=lambda b: b["position"])
            m = len(blocks)
            # per-block deterministic values (index-independent)
            vals = []
            for _b in blocks:
                vals.append(_pareto_value(ordinal))
                ordinal += 1
            for idx, b in enumerate(blocks):
                c = int(b["creator"])
                block_cnt[c] += 1
                if idx == 0:
                    leader_cnt[c] += 1
                # same-round win-rate (all blocks in round)
                wr_win[c] += (m - 1 - idx)
                wr_pairs[c] += (m - 1)
                # realized-MEV proxy: value of blocks after i in this round
                mev_u[c] += (m - 1 - idx)  # uniform value = 1 each
                mev_p[c] += sum(vals[idx + 1:])
            # non-leader win-rate: drop idx 0, re-rank among the rest
            nl = blocks[1:]
            mnl = len(nl)
            for idx, b in enumerate(nl):
                c = int(b["creator"])
                wrnl_win[c] += (mnl - 1 - idx)
                wrnl_pairs[c] += (mnl - 1)

    rows = []
    for i in range(n):
        rows.append({
            "index": i,
            "blocks": block_cnt.get(i, 0),
            "leader_share": (leader_cnt.get(i, 0) / block_cnt[i]) if block_cnt.get(i) else 0.0,
            "wr_same_round": (wr_win[i] / wr_pairs[i]) if wr_pairs.get(i) else float("nan"),
            "wr_nonleader": (wrnl_win[i] / wrnl_pairs[i]) if wrnl_pairs.get(i) else float("nan"),
            "mev_uniform": mev_u.get(i, 0.0),
            "mev_pareto": mev_p.get(i, 0.0),
        })
    return {"rows": rows, "n_orders": len(orders),
            "total_blocks": sum(block_cnt.values())}


def _spearman(xs: list[float], ys: list[float]) -> float:
    # rank-correlation; xs is 0..n-1 (already ranks), rank ys
    def ranks(v):
        order = sorted(range(len(v)), key=lambda k: v[k])
        r = [0.0] * len(v)
        for pos, k in enumerate(order):
            r[k] = pos
        return r
    ry = ranks(ys)
    n = len(xs)
    d2 = sum((xs[i] - ry[i]) ** 2 for i in range(n))
    return 1 - 6 * d2 / (n * (n * n - 1))


def _gini(vals: list[float]) -> float:
    v = sorted(x for x in vals if x == x)  # drop nan
    if not v or sum(v) == 0:
        return 0.0
    cum = 0.0
    for i, x in enumerate(v, 1):
        cum += i * x
    nn = len(v)
    return (2 * cum) / (nn * sum(v)) - (nn + 1) / nn


def summarize(res: dict, n: int, label: str) -> str:
    rows = res["rows"]
    idx = [r["index"] for r in rows]
    wr = [r["wr_same_round"] for r in rows]
    wrnl = [r["wr_nonleader"] for r in rows]
    mev_u = [r["mev_uniform"] for r in rows]
    mev_p = [r["mev_pareto"] for r in rows]
    lead = [r["leader_share"] for r in rows]

    out = [f"\n=== INDEX TAX [{label}]  orders={res['n_orders']}  blocks={res['total_blocks']} ==="]
    out.append(f"{'idx':>3} {'blocks':>6} {'lead%':>6} {'wr_SR':>7} {'wr_nonldr':>9} {'mev_unif':>9} {'mev_pareto':>11}")
    for r in rows:
        out.append(f"{r['index']:>3} {r['blocks']:>6} {r['leader_share']*100:>5.1f} "
                   f"{r['wr_same_round']*100:>6.1f} {r['wr_nonleader']*100:>8.1f} "
                   f"{r['mev_uniform']:>9.0f} {r['mev_pareto']:>11.1f}")
    # stats
    sp_wr = _spearman(idx, wr)
    sp_wrnl = _spearman(idx, wrnl)
    mev_u_sorted = sorted(mev_u, reverse=True)
    ratio_u = (mev_u_sorted[0] / mev_u_sorted[-1]) if mev_u_sorted[-1] else float("inf")
    out.append(f"\n  leader_share spread: {min(lead)*100:.1f}%..{max(lead)*100:.1f}%  (fair≈{100/n:.1f}%)")
    out.append(f"  wr_same_round : {min(wr)*100:.1f}%..{max(wr)*100:.1f}%  Spearman(vs idx)={sp_wr:+.3f}  (fair: flat 50%, Spearman 0)")
    out.append(f"  wr_nonleader  : {min(wrnl)*100:.1f}%..{max(wrnl)*100:.1f}%  Spearman(vs idx)={sp_wrnl:+.3f}")
    out.append(f"  mev_uniform   : Gini={_gini(mev_u):.3f}  top/bottom={ratio_u:.2f}x  (fair: Gini 0, ratio 1)")
    out.append(f"  mev_pareto    : Gini={_gini(mev_p):.3f}")
    return "\n".join(out)


def main(argv: Iterable[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="index_tax_analysis")
    ap.add_argument("--n", type=int, default=13)
    ap.add_argument("--label", default="run")
    ap.add_argument("--files", nargs="*", default=None)
    ap.add_argument("--json-out", default=None)
    args = ap.parse_args(list(argv) if argv is not None else None)

    text = ""
    if args.files:
        for f in args.files:
            text += Path(f).read_text() + "\n"
    else:
        text = sys.stdin.read()
    orders = parse_orders(text)
    if not orders:
        print("no FINAL_COMMITTED_ORDER lines found", file=sys.stderr)
        return 2
    res = analyze(orders, args.n)
    print(summarize(res, args.n, args.label))
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(res, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
