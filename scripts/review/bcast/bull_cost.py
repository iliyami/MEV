#!/usr/bin/env python3
"""Per-run cost of victim broadcast on Narwhal-Bullshark, from raw benchmark logs (read-only).
Inputs: run directories (worker-*.log, primary-*.log, client-*.log, fr-victim*.log) written by
scripts/bullshark/fr_spray.sh, p1x_bull.sh (*_x arms) and vspray.sh; not in the repo, pass paths.
Layout expected by aggregate.py: <OUT>/fr_runs/<arm>/<cell>/run<k>.
Usage: python3 bull_cost.py <run_dir> ... > data/review/bcast/bull_rows.jsonl
Consensus TPS and latency follow benchmark/benchmark/logs.py (LogParser); adds victim copy counts
and victim send-to-commit latency. Prints one JSON row per run; feeds aggregate.py.
"""
import glob, json, os, re, statistics, sys
from datetime import datetime, timezone

TS = re.compile(r"^\[(\S+Z) ")
def ts(line):
    m = TS.match(line)
    if not m:
        return None
    return datetime.strptime(m.group(1), "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc).timestamp()

FR = re.compile(r"Batch (\S+) contains fr tx (\d) (\d+)")
SIZE = re.compile(r"Batch (\S+) contains (\d+) B")
SAMPLE_W = re.compile(r"Batch (\S+) contains sample tx (\d+)")
CREATED = re.compile(r"Created B\d+\([^ ]+\) -> ([^ ]+=)")
COMMIT = re.compile(r"Committed B(\d+)\((\S+)\) -> ([^ ]+=)")
SENTV = re.compile(r"Sending victim tx (\d+)")
SAMPLE_C = re.compile(r"Sending sample transaction (\d+)")

def st(xs):
    xs = sorted(xs)
    if not xs:
        return None
    return {"n": len(xs), "median": statistics.median(xs), "mean": statistics.mean(xs), "min": xs[0], "max": xs[-1]}

def run(d):
    where = {}          # (tag,id) -> set(batch digest)
    size = {}           # digest -> bytes
    wsample = {}        # worker file base -> {sample id: digest}
    for f in sorted(glob.glob(os.path.join(d, "worker-*.log"))):
        base = os.path.basename(f)[len("worker-"):]
        ws = {}
        with open(f, errors="replace") as fh:
            for line in fh:
                if "Batch " not in line:
                    continue
                if " fr tx " in line:
                    m = FR.search(line)
                    if m:
                        where.setdefault((int(m.group(2)), int(m.group(3))), set()).add(m.group(1))
                    continue
                if "sample tx" in line:
                    m = SAMPLE_W.search(line)
                    if m:
                        ws[int(m.group(2))] = m.group(1)
                    continue
                m = SIZE.search(line)
                if m:
                    size[m.group(1)] = int(m.group(2))
        wsample[base] = ws
    proposals, commits = {}, {}
    for f in sorted(glob.glob(os.path.join(d, "primary-*.log"))):
        with open(f, errors="replace") as fh:
            for line in fh:
                if "Created B" in line:
                    m = CREATED.search(line)
                    if m:
                        t = ts(line); k = m.group(1)
                        if k not in proposals or proposals[k] > t:
                            proposals[k] = t
                elif "Committed B" in line:
                    m = COMMIT.search(line)
                    if m:
                        t = ts(line); k = m.group(3)
                        if k not in commits or commits[k] > t:
                            commits[k] = t
    # victim send times (main victim client only) and number of victim submissions over all victim clients
    vsend = {}
    with open(os.path.join(d, "fr-victim.log"), errors="replace") as fh:
        for line in fh:
            m = SENTV.search(line)
            if m:
                vsend[int(m.group(1))] = ts(line)
    copy_logs = sorted(glob.glob(os.path.join(d, "fr-victim-copy-*.log")))
    copy_sends = 0
    for f in copy_logs:
        with open(f, errors="replace") as fh:
            copy_sends += sum(1 for line in fh if "Sending victim tx" in line)
    # client sample sends for end-to-end latency (LogParser pairs client-X-Y with worker-X-Y via sorted zip)
    e2e = []
    clients = sorted(glob.glob(os.path.join(d, "client-*.log")))
    workers = sorted(glob.glob(os.path.join(d, "worker-*.log")))
    tx_size = None
    for cf, wf in zip(clients, workers):
        sent = {}
        with open(cf, errors="replace") as fh:
            for line in fh:
                if tx_size is None and "Transactions size:" in line:
                    tx_size = int(re.search(r"Transactions size: (\d+)", line).group(1))
                if "sample transaction" in line:
                    m = SAMPLE_C.search(line)
                    if m:
                        sent[int(m.group(1))] = ts(line)
        rec = wsample[os.path.basename(wf)[len("worker-"):]]
        for i, dg in rec.items():
            if dg in commits and i in sent:
                e2e.append(commits[dg] - sent[i])
    # consensus throughput / latency as LogParser
    csizes = {k: v for k, v in size.items() if k in commits}
    start, end = min(proposals.values()), max(commits.values())
    dur = end - start
    cbytes = sum(csizes.values())
    clat = [commits[k] - proposals[k] for k in commits if k in proposals]
    out = {"run": d, "tx_size": tx_size, "consensus_duration_s": dur,
           "committed_batches": len(csizes), "committed_bytes": cbytes,
           "consensus_bps": cbytes / dur, "consensus_tps": cbytes / dur / tx_size,
           "consensus_latency_ms_mean": 1000 * statistics.mean(clat),
           "consensus_latency_ms_median": 1000 * statistics.median(clat),
           "e2e_latency_ms_mean": 1000 * statistics.mean(e2e) if e2e else None,
           "e2e_latency_ms_median": 1000 * statistics.median(e2e) if e2e else None,
           "victim_clients": 1 + len(copy_logs), "victim_sent_main": len(vsend),
           "victim_sent_all_clients": len(vsend) + copy_sends}
    for tag, name in ((2, "victim"), (3, "attacker")):
        ids = sorted(i for t, i in where if t == tag)
        sealed = [len(where[(tag, i)]) for i in ids]
        comm = [sum(1 for x in where[(tag, i)] if x in commits) for i in ids]
        out[name] = {"ids_in_batches": len(ids), "ids_committed": sum(1 for c in comm if c > 0),
                     "sealed_copies": st(sealed), "committed_copies": st([c for c in comm if c > 0]),
                     "committed_copy_total": sum(comm), "sealed_copy_total": sum(sealed)}
    # victim commit latency: send time (main client) -> earliest commit of any batch carrying the id
    vl = []
    for i, t0 in vsend.items():
        cs = [commits[x] for x in where.get((2, i), ()) if x in commits]
        if cs:
            vl.append(min(cs) - t0)
    out["victim_latency_ms"] = st([1000 * x for x in vl])
    return out

for d in sys.argv[1:]:
    try:
        print(json.dumps(run(d)), flush=True)
    except Exception as e:
        print(json.dumps({"run": d, "error": repr(e)}), flush=True)
