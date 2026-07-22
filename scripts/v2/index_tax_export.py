"""Export index-tax results to tidy CSVs (+ an ASCII flagship plot).

Consumes the per-config committed-order logs produced by cloudlab_index_tax.sh
(results/index_tax/{proto}_n{N}_fix{0,1}.log) and emits:
  - results/index_tax/per_index.csv  : one row per (proto,n,fix,index)
  - results/index_tax/summary.csv    : one row per (proto,n,fix) with Spearman,
                                        Gini, top/bottom ratio, throughput.
and prints an ASCII win-rate-vs-index plot for the n=13 flagship. Pure stdlib
(no numpy/matplotlib) so it runs anywhere; the CSVs feed pgfplots on Overleaf.
"""

from __future__ import annotations

import csv
import glob
import re
from pathlib import Path

from scripts.v2.index_tax_analysis import analyze, parse_orders, _spearman, _gini

LOG_DIR = Path("results/index_tax")
_RE = re.compile(r"(?P<proto>sui|bull)_n(?P<n>\d+)(?P<full>full)?_fix(?P<fix>\d)\.log$")


def _load(path: Path):
    m = _RE.search(path.name)
    if not m:
        return None
    n = int(m.group("n"))
    orders = parse_orders(path.read_text())
    if not orders:
        return None
    res = analyze(orders, n)
    return {
        "proto": "Sui" if m.group("proto") == "sui" else "Bullshark",
        "n": n, "full": bool(m.group("full")),
        "fix": int(m.group("fix")), "res": res,
    }


def _summ_row(rec):
    rows = rec["res"]["rows"]
    idx = [r["index"] for r in rows]
    wr = [r["wr_same_round"] for r in rows]
    mev = [r["mev_uniform"] for r in rows]
    mev_sorted = sorted(mev, reverse=True)
    ratio = (mev_sorted[0] / mev_sorted[-1]) if mev_sorted[-1] else float("inf")
    return {
        "protocol": rec["proto"], "n": rec["n"],
        "scope": "full" if rec["full"] else "std",
        "fix": rec["fix"],
        "spearman_wr_idx": round(_spearman(idx, wr), 4),
        "gini_mev_uniform": round(_gini(mev), 4),
        "gini_mev_pareto": round(_gini([r["mev_pareto"] for r in rows]), 4),
        "top_bottom_ratio": round(ratio, 2),
        "wr_min_pct": round(min(wr) * 100, 1),
        "wr_max_pct": round(max(wr) * 100, 1),
        "total_blocks": rec["res"]["total_blocks"],
    }


def _ascii_plot(recs, n=13, width=42):
    """win-rate vs index, default vs fix, both protocols, n=13."""
    lines = [f"\n  Win-rate vs validator index (n={n}, HONEST run, no attacker)",
             "  each row = one validator ID; bar = same-round win-rate; | = 50% (fair)"]
    for proto in ("Sui", "Bullshark"):
        for fixv, tag in ((0, "DEFAULT"), (1, "FIX_TIEBREAK")):
            rec = next((r for r in recs if r["proto"] == proto and r["n"] == n
                        and not r["full"] and r["fix"] == fixv), None)
            if not rec:
                continue
            lines.append(f"\n  [{proto} {tag}]")
            for r in rec["res"]["rows"]:
                wr = r["wr_same_round"]
                fill = int(round(wr * width))
                mid = int(round(0.5 * width))
                bar = list("·" * width)
                for k in range(fill):
                    bar[k] = "█"
                if 0 <= mid < width:
                    bar[mid] = "|" if bar[mid] == "·" else "┃"
                lines.append(f"   id{r['index']:>2} {wr*100:>5.1f}% {''.join(bar)}")
    return "\n".join(lines)


def main() -> int:
    recs = [r for r in (_load(Path(p)) for p in sorted(glob.glob(str(LOG_DIR / "*.log")))) if r]
    if not recs:
        print("no logs found in", LOG_DIR)
        return 2
    # per-index tidy csv
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with open(LOG_DIR / "per_index.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["protocol", "n", "scope", "fix", "index", "blocks",
                    "leader_share", "wr_same_round", "wr_nonleader",
                    "mev_uniform", "mev_pareto"])
        for rec in recs:
            scope = "full" if rec["full"] else "std"
            for r in rec["res"]["rows"]:
                w.writerow([rec["proto"], rec["n"], scope, rec["fix"], r["index"],
                            r["blocks"], round(r["leader_share"], 4),
                            round(r["wr_same_round"], 4), round(r["wr_nonleader"], 4),
                            round(r["mev_uniform"], 2), round(r["mev_pareto"], 2)])
    # summary csv
    summ = [_summ_row(r) for r in recs]
    summ.sort(key=lambda s: (s["protocol"], s["n"], s["scope"], s["fix"]))
    with open(LOG_DIR / "summary.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(summ[0].keys()))
        w.writeheader()
        w.writerows(summ)
    # print summary table + flagship ascii
    print(f"\nwrote {LOG_DIR}/per_index.csv ({sum(len(r['res']['rows']) for r in recs)} rows) + summary.csv")
    print(f"\n{'proto':>9} {'n':>3} {'scope':>5} {'fix':>3} {'Spearman':>9} {'Gini_u':>7} {'ratio':>7} {'wr_range':>13} {'blocks':>7}")
    for s in summ:
        print(f"{s['protocol']:>9} {s['n']:>3} {s['scope']:>5} {s['fix']:>3} "
              f"{s['spearman_wr_idx']:>+9.3f} {s['gini_mev_uniform']:>7.3f} "
              f"{s['top_bottom_ratio']:>6.1f}x {s['wr_min_pct']:>5.1f}-{s['wr_max_pct']:<5.1f} {s['total_blocks']:>7}")
    print(_ascii_plot(recs, n=13))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
