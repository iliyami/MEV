#!/usr/bin/env python3
"""Generate tab_frontrun.tex (from tab_frontrun_template.tex): transaction-level
front-running, medians of five runs with the run range. Every number is recomputed from raw logs:
  Bullshark  data/bullshark/bullshark_frontrun/scores.jsonl (our_harness/frontrun_score.py on each run)
  Mysticeti  runs/*_rep*.log scored in consensus order (score_frontrun.score)
  Sui        runs_gas/*_rep*.log scored in Sui's execution order (score_frontrun.exec_key)
"""
import glob, json, os, statistics as st, sys
HERE = os.path.dirname(os.path.abspath(__file__))
CWD = os.getcwd()
os.chdir(HERE)          # the run directories (runs/, runs_p1/, runs_gas/, runs_slug_nb/) are relative to this folder
sys.path.insert(0, HERE)
from score_frontrun import score, exec_key
BULLSHARK = os.path.join(HERE, "../../data/bullshark/bullshark_frontrun/scores.jsonl")

def cell(vals):
    vals = [v for v in vals if v is not None and v == v]
    if len(vals) < 5:
        sys.exit(f"expected at least 5 runs, got {len(vals)}")
    q1, _, q3 = st.quantiles(vals, n=4, method="inclusive")  # interquartile range over runs
    return f"{len(vals)} & ${st.median(vals):.1f}$ & \\scriptsize[{q1:.1f}, {q3:.1f}]"

def bullshark(arm):
    rows = [json.loads(l) for l in open(BULLSHARK)]
    arms = {arm, arm + "_x", arm + "_y"}
    return cell([r["success_pct"] for r in rows if r["arm"] in arms])

def blindpanel(prefix):
    return cell([score(f)["success_pct"] for f in sorted(glob.glob(f"runs/{prefix}_rep*.log"))])

def mysticeti(prefix):
    # Sluggish arms come from runs_slug_nb/: the hook no longer blocks the runtime thread
    # that co-hosted honest validators share (the runs/ sluggish logs predate that fix).
    d = "runs_slug_nb" if prefix.endswith("_sluggish") else "runs"
    return cell([score(f)["success_pct"] for f in sorted(glob.glob(f"{d}/{prefix}_rep*.log"))])

def mysticeti_p1(prefix):
    return cell([score(f)["success_pct"] for f in sorted(glob.glob(f"runs_p1/{prefix}_rep*.log"))])

def sui(prefix):
    return cell([score(f, exec_key)["success_pct"] for f in sorted(glob.glob(f"runs_gas/{prefix}_rep*.log"))])

PANELS = [
    ("Mysticeti in Sui, consensus order, no hook log, commits read at the attacker", [
        ("Blind (control)", "nothing", blindpanel, "blind"),
        ("Blind, \\textsc{FixTiebreak}", "nothing", blindpanel, "blind_fix"),
        ("No attack", "block", blindpanel, "react0"),
        ("No attack, wait $\\le 200$\\,ms", "block", blindpanel, "wait200"),
        ("Wait $\\le 200$\\,ms, \\textsc{FixTiebreak}", "block", blindpanel, "wait200_fix"),
    ]),
    ("Bullshark (certified), committing height; the attacker sees the victim's batch", [
        ("No attack", "batch", bullshark, "none"),
        ("Fissure", "batch", bullshark, "fissure"),
        ("No attack, digest grinding", "batch", bullshark, "none_grind"),
        ("Fissure, digest grinding", "batch", bullshark, "fissure_grind"),
        ("No attack, copy sent to all validators", "batch", bullshark, "none_spray"),
        ("Fissure, copy sent to all validators", "batch", bullshark, "fissure_spray"),
        ("Fissure, digest grinding, copy sent to all", "batch", bullshark, "fissure_grind_spray"),
        ("No attack, both send to all", "batch", bullshark, "none_vspray"),
        ("Fissure, both send to all", "batch", bullshark, "fissure_vspray"),
    ]),
    ("Mysticeti in Sui (uncertified), consensus order, matched to Bullshark: four fissure attackers, one victim", [
        ("No attack", "block", mysticeti_p1, "blk_none"),
        ("Fissure", "block", mysticeti_p1, "blk_fissure"),
        ("No attack", "pending", mysticeti_p1, "mp_none"),
        ("Fissure", "pending", mysticeti_p1, "mp_fissure"),
    ]),
    ("Mysticeti in Sui (uncertified), consensus order, one attacker, three victims", [
        ("No attack", "block", mysticeti, "blk_none_v1"),
        ("No attack", "pending", mysticeti, "mp_none_v1"),
        ("No attack, \\textsc{FixTiebreak}", "pending", mysticeti, "mp_none_fix_v1"),
        ("Fissure", "block", mysticeti, "blk_fissure_v1"),
        ("Fissure", "pending", mysticeti, "mp_fissure_v1"),
        ("Speculative", "block", mysticeti, "blk_speculative_v1"),
        ("Speculative", "pending", mysticeti, "mp_speculative_v1"),
        ("Sluggish", "block", mysticeti, "blk_sluggish"),
        ("Sluggish", "pending", mysticeti, "mp_sluggish"),
        ("Silent-except-leader", "block", mysticeti, "blk_sel_v1"),
        ("Silent-except-leader", "pending", mysticeti, "mp_sel_v1"),
    ]),
    ("Sui execution order (gas price re-sort inside each commit)", [
        ("Copy sent to all validators, gas $+1$", "pending, 0\\,ms", sui, "bc_d0_outbid"),
        ("Copy sent to all validators, gas $+1$", "pending, 50\\,ms", sui, "bc_d50_outbid"),
        ("Copy sent to all validators, gas $+1$", "pending, 200\\,ms", sui, "bc_d200_outbid"),
        ("Copy sent to all validators, equal gas", "pending, 50\\,ms", sui, "bc_d50_match"),
        ("Equal gas, \\textsc{FixTiebreak}", "pending, 50\\,ms", sui, "bc_d50_match_fix"),
        ("Copy in own block only, gas $+1$", "pending, 50\\,ms", sui, "hook_mp_d50_outbid"),
        ("Copy in own block only, gas $+1$", "block", sui, "hook_blk_outbid"),
    ]),
]

def main(out):
    lines = []
    for title, rows in PANELS:
        lines.append(("\\midrule\n" if lines else "") + f"\\multicolumn{{5}}{{@{{}}l}}{{\\emph{{{title}}}}} \\\\")
        for label, vis, fn, key in rows:
            lines.append(f"{label} & {vis} & {fn(key)} \\\\")
    tpl = open("tab_frontrun_template.tex").read()
    assert "%%ROWS%%" in tpl
    open(out, "w").write(tpl.replace("%%ROWS%%", "\n".join(lines)))
    print("\n".join(lines))

if __name__ == "__main__":
    main(os.path.join(CWD, sys.argv[1]) if len(sys.argv) > 1 else os.path.join(HERE, "tab_frontrun.tex"))
