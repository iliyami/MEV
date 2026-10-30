#!/usr/bin/env python3
"""Score every Sui front-running log that Table II (A4.3, P1.2) and Table V use, once, with the project's
scorer (scripts/frontrun_sui/score_frontrun.py), for stats.py --raw. Input: the frontrun run dir with
runs/, runs_p1/, runs_slug_nb/, runs_gas/, runs_vbcast/ (written by scripts/frontrun_sui/run_*.sh, not in
the repo). Output: data/review/stats/cache/frontrun_scores.json. Usage: score_cache.py <frontrun_dir>
"""
import glob, json, os, sys
from multiprocessing import Pool
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "scripts/frontrun_sui"))
from score_frontrun import score, exec_key  # noqa: E402

FR = sys.argv[1] if len(sys.argv) > 1 else "paper_workspace/paper2/frontrun"
OUT = str(REPO / "data/review/stats/cache/frontrun_scores.json")
# keys are paths relative to FR, e.g. "runs_p1/blk_none_rep1.log"
PATTERNS = [f"{FR}/runs/*_rep*.log", f"{FR}/runs_p1/*_rep*.log", f"{FR}/runs_slug_nb/*_rep*.log",
            f"{FR}/runs_gas/*_rep*.log", f"{FR}/runs_vbcast/*_rep*.log"]


def one(path):
    st = os.stat(path)
    rec = {"size": st.st_size, "mtime": st.st_mtime}
    try:
        rec["cons"] = score(path)["success_pct"]
        rec["exec"] = score(path, exec_key)["success_pct"]
    except SystemExit as e:  # scorer raises SystemExit when a log has no FINAL_TX_ORDER
        rec["error"] = str(e)
    return os.path.relpath(path, FR), rec


def main():
    files = sorted(set(f for p in PATTERNS for f in glob.glob(p)))
    cache = json.load(open(OUT)) if os.path.exists(OUT) else {}
    todo = [f for f in files if os.path.relpath(f, FR) not in cache or cache[os.path.relpath(f, FR)]["size"] != os.stat(f).st_size]
    print(f"{len(files)} logs, {len(todo)} to score", flush=True)
    with Pool(4) as pool:
        for i, (p, rec) in enumerate(pool.imap_unordered(one, todo), 1):
            cache[p] = rec
            if i % 20 == 0:
                json.dump(cache, open(OUT, "w"), indent=0)
                print(i, flush=True)
    json.dump(cache, open(OUT, "w"), indent=0)
    print("done", len(cache))


if __name__ == "__main__":
    main()
