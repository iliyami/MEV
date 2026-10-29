# Reproducing the headline findings

This file gives, for each headline finding of the paper, the code tree, the exact commands we ran,
the arms and their matched controls, the number of runs, the scorer, the value to expect, and the
machine it ran on. Cell IDs refer to Table II of the paper; "Table IV" is the transaction-level
front-running table. Code versions and our patch are in [`VERSIONS.md`](VERSIONS.md). The per-run
scores behind each finding are under [`data/`](data/README.md), so every expected value below can
be recomputed without rerunning anything.

All paths are relative to the repository root. The scripts we ran are shipped with their logic
unchanged; only their absolute paths are replaced by variables:

- `OUT`: an empty directory for run logs (required by every driver). A Bullshark run keeps about
  13 primary and 26 worker logs; put `OUT` on a disk with room for them.
- `PY`: the Python of the Bullshark harness venv (see below).
- `REPO`: the repository root. Drivers find it from their own location; set it only to override.

Where they are:

| Directory | Contents |
|---|---|
| `scripts/bullshark/` | Bullshark campaign drivers (`*.sh`) and per-run scorers (`coal_score_runs.py`, `coal2_score_runs.py`, `coalscore.py`, `txexport.py`) |
| `scripts/analysis/` | run-level statistics over the shipped Bullshark score files (`analyze.py`, `trend.py`, `law.py`, `law2.py`, `law25.py`, `dsweep_analyze.py`); they read `data/bullshark/coal/` (override with `COAL_DATA`) |
| `scripts/frontrun_sui/` | Sui front-running and refusal-law drivers and scorers, the Table IV generator `make_table.py` and `p1_stats.py` |
| `scripts/sui/` | Sui silent-except-leader and tiebreak driver (`sel290_run.sh`) and its scorer, and the 290-commit harness driver (`v2_290_run.sh`) |
| `scripts/value/` | front-running value with real trade sizes (`real_value.py`, `inround_value.py`) |

Lines in the drivers where our run waited for the previous campaign on the same machine are
replaced by a comment. Where a script we ran no longer exists, the section says so in a line
starting **Not in this repository**.

## Machines

All runs used four CloudLab machines. An attack arm always ran on the same machine as its control.

| Name used below | Hardware | Used for |
|---|---|---|
| Xeon node | CloudLab node, two 14-core Intel Xeon E5-2683 v3, 251 GB | every Bullshark campaign below except the first censorship cell |
| AMD node | CloudLab node, 64 cores, 125 GB | the first censorship testbed (A1.4 = A2.8, 84.4%) |
| c6525 nodes | CloudLab `c6525-25g`: 16-core AMD 7302P, 128 GB | the other cluster runs (the per-cell CSVs already in `data/cloudlab_*`) |
| Sui node | CloudLab node | every Sui v1.74 run; all validators of a run share one process |

## Common setup

### Bullshark (`code/bullshark-flashboys`)

```bash
# Toolchain: rustc 1.92.0. Cargo.lock is pinned.
VENV=<a directory outside the repository>
export OUT=<your output directory>
python3 -m venv $VENV
$VENV/bin/pip install -r code/bullshark-flashboys/our_harness/requirements.txt
export PY=$VENV/bin/python
cd code/bullshark-flashboys
cargo build --release --features benchmark
cd benchmark
```

Every run is one call of the artifact's local benchmark through our driver
`our_harness/run_and_score.py`, from `code/bullshark-flashboys/benchmark`:

```bash
$PY ../our_harness/run_and_score.py --attack <A> --fa <F> --nodes <N> --runs <R> --keep $OUT/<arm>
```

- `--attack 10` is the no-attack control: attacker and victim are designated and their pairs are
  logged, but the attacker takes no action. `--attack 1` is fissure.
- `--fa` is the number of attacking validators: the last `F` node indexes. The victim is the
  honest validator with the smallest public key. The delegate attacker that logs attack pairs is
  node `n - F`.
- `--keep` must be given; the default is a path on our cluster. The driver deletes and recreates
  `$OUT/<arm>/<baseline|fissure>_f<F>_n<N>/` and writes one `run<i>/` log directory per run, so
  repeated calls need distinct `--keep` directories.
- Fixed benchmark settings (`benchmark/fabfile.py`): 60 s per run, 30,000 transactions per
  second of 512 bytes, 2 workers per validator, header size 1,000 bytes, maximum header and batch
  delay 200 ms, garbage-collection depth 50, batch size 500,000 bytes.
- Seeds: none. Every run generates fresh validator keys, so the identity of the victim and the key
  order change from run to run; this is the run-to-run variation the run-level statistics
  resample.
- Start every campaign from a clean environment. Our drivers ran
  `unset FR_REACT FR_VICTIM_RATE FR_GRIND FR_SPRAY FR_VICTIM_SPRAY MULTI_VICTIM BRIBED COLLUDE INDEPENDENT RIVAL_GROUPS SILENT_EXCEPT_LEADER CENSOR`
  first and then set only the variables of the arm.
- A run took about 67 s on the Xeon node (five runs in about 5.5 minutes).

The scorer `our_harness/measure.py <run dir> --attack <baseline|fissure> --json` reports three
metrics for one run: targeted committing-height (`M3_targeted_committing_height`, the metric of
the Flash Boys paper), all-pairs (`M1_all_pairs`) and same-round (`M2_same_round`), each with its
`succ` and `total` pair counts. Committing-height cells, and the metric rows T2.1 and T2.2,
pool the pairs of all runs of an arm; the other same-round and all-pairs cells take the median
over runs.

### Sui v1.74 (`code/sui`)

```bash
# Toolchain from code/sui/rust-toolchain.toml (1.92). Debug test build.
cd code/sui
cargo test -p consensus-core --lib --no-run      # warm build
```

Each Sui run is one test of `consensus-core`, run as
`cargo test -p consensus-core --lib <test> -- --nocapture` from `code/sui` with `SEED=<rep>`
(reps 1 to 5, or 1 to 20 where stated). The run log carries the committed order
(`FINAL_COMMITTED_ORDER`, or `FINAL_TX_ORDER` for the front-running test) that the scorers read.
The drivers in `scripts/frontrun_sui/` find the repository themselves (override with `REPO=`) and
write their logs to `scripts/frontrun_sui/runs*/`, which git ignores.

---

## (a) Fissure on certified Bullshark, n = 13, four attackers

**Claim.** With four attackers (f = 4) aimed at one victim, fissure wins 69.6% [60.0, 80.8] of
79 targeted races, against 48.1% [42.0, 54.3] of 104 with no attack: +21.5 points, one-sided
permutation p = 0.002 (Deployment paragraph of the evaluation; full numbers in the extended
version). On same-round races in the same runs the gain is +10.3 points (p < 0.001). The default cell of
Table II, A2.1 = A4.1, is fissure on Bullshark scored on same-round: 50.59 to 64.37 (+13.78).

**Tree.** `code/bullshark-flashboys`, run from `benchmark/`. Machine: Xeon node.

### Committee-size sweep (the 69.6 vs 48.1 result)

Arms, interleaved within each repetition, ten repetitions:

| Arm | `--attack` | `--fa` | `--nodes` | Role |
|---|---|---|---|---|
| `b13` | 10 | 4 | 13 | control |
| `f13` | 1 | 4 | 13 | fissure |

The driver is `scripts/bullshark/dsweep.sh`. It also interleaves `b7`/`f7` (n = 7, f_a = 2),
`b25`/`f25` (n = 25, f_a = 8) and two WAN arms at n = 13 that add `tc netem delay 50ms` on the
loopback device, so it needs `sudo` for `tc`; the WAN arms recorded no attack pairs in any of
their 20 runs and are not reported.

```bash
OUT=<dir> PY=<venv python> bash scripts/bullshark/dsweep.sh        # writes $OUT/dsweep/<arm>/r<rep>/
```

Scoring, one JSON line per run (from the repository root):

```bash
cd code/bullshark-flashboys/our_harness
for d in $OUT/dsweep/*/r*/*/run0; do
  att=$(basename $(dirname $d) | cut -d_ -f1)            # baseline or fissure
  m=$($PY measure.py $d --attack $att --json 2>/dev/null | $PY -c "import json,sys;print(json.dumps(json.load(sys.stdin)))")
  echo "{\"run\":\"$d\",\"m\":${m:-null}}"
done > dsweep_scores.jsonl
```

Analysis: `python3 scripts/analysis/dsweep_analyze.py` (reads
`data/bullshark/coal/dsweep_scores.jsonl`; point `COAL_DATA` at your own directory to analyse
your runs). Per arm it pools `succ` and `total` over the runs that recorded any pairs, a
4,000-resample bootstrap over runs for the interval, and a one-sided permutation test over run
labels for the difference, on M3, M2 and M1. On the shipped file it prints the values below.

**Expected.** n = 13: fissure 69.6% [60.0, 80.8] on 79 pairs (8 of 10 runs recorded pairs);
control 48.1% [42.0, 54.3] on 104 pairs; +21.5, p = 0.002. Same-round +10.3, p < 0.001. Our
per-run scores are `data/bullshark/coal/dsweep_scores.jsonl` (80 runs; take the arm from the
run path, not from the file's `arm` field). The 80 runs took 91 minutes.

The n = 25 refusal law that the Deployment paragraph cites (2.5 points per refusal, 95% interval
[1.1, 3.9]; eight attackers +15.7 over a 20-run control) adds `scripts/bullshark/lsweep.sh`
(n = 25 with 1, 2, 4 and 6 attackers, and 10 more controls, interleaved, ten repetitions) and is
analysed by `python3 scripts/analysis/law25.py`, which reads `lsweep_scores.jsonl` and
`dsweep_scores.jsonl` and prints slope 2.52 [1.10, 3.92], run-level p = 0.00075, and +15.7
[+4.8, +27.6], one-sided p = 0.014. Score the lsweep runs with the loop above over
`$OUT/lsweep/*/r*/*/run0`.

### Fresh-copy check

We reran the n = 13 arms of this recipe from a fresh copy of the repository (`git archive` of the
commit that added `Cargo.lock`), with a new venv from `our_harness/requirements.txt` and a new
cargo build: `OUT=<dir> scripts/bullshark/freshrun.sh`, then `measure.py --json` on each run and
`python3 scripts/analysis/fresh_analyze.py`. Result: fissure 67.1% [61.0, 76.7] on 82 pairs against
47.1% [39.4, 54.5] on 70 pairs, +19.9, p = 0.002; same-round +13.5. Per-run scores:
`data/bullshark/coal/fresh_scores.jsonl`. Build plus 20 runs took 25 minutes on the Xeon node.

### Same-round default cell (A2.1 = A4.1)

Driver `scripts/bullshark/fig4_bull.sh`: five runs each of attacks 10 (control), 1 (fissure),
3 and 2 (speculative and sluggish, for the Bullshark bars of Figure 4), n = 13, f_a = 4, into
`$OUT/fig4/<baseline|fissure|...>_f4_n13/run<i>`. Score each run with
`measure.py <run> --attack <baseline|fissure> --json` and take `M2_same_round`; the cell is the
median over runs.

**Expected.** Per run, no attack 50.6, 52.2, 56.6, 50.6, 49.4 (median 50.59); fissure 76.3, 64.0,
64.4, 63.8, 68.3 (median 64.37); +13.78. Table II marks it significant: the 95% bootstrap
interval of the difference, resampling runs, is [+7.8, +25.7]. Per-run pair counts:
`data/bullshark/coal/fig4_runs.jsonl`.

**Not in this repository:** the few lines that collected the `measure.py` counts of these ten runs
into `fig4_runs.jsonl`.

---

## (b) Coordination on Bullshark: competing, colluding, multi-group (A3.2 to A3.4)

**Claim.** Six attackers (two more than f), targeted committing-height, n = 13. Each refusing a
different victim (competing) they win 52.2% against a 47.4% control (A3.2, p = 0.15); split into
two rival groups with one victim each (multi-group) 62.3% (A3.4); aimed together at one victim
(colluding) 69.2% (A3.3 = A6.3). Colluding beats competing by 17.0 points (run-level p < 0.001).

**Tree.** `code/bullshark-flashboys`. Machine: Xeon node.

| Arm | `--attack` | `--fa` | Extra variables | Paper value |
|---|---|---|---|---|
| `base6` | 10 | 6 | none | control of A3.2 to A3.4 |
| `f6ind` | 1 | 6 | `INDEPENDENT=1` (the j-th attacker targets the (j mod 7)-th honest validator: six victims) | competing, A3.2 |
| `f6rival` | 1 | 6 | `RIVAL_GROUPS=2` (two groups of three, one victim each) | multi-group, A3.4 |
| `f6` | 1 | 6 | none (every attacker targets the same victim) | colluding, A3.3 |

All arms use `--nodes 13`. Runs: 40 per arm, from two campaigns. `scripts/bullshark/coal.sh` runs
each arm of (b) and (c) as one call with `--runs 16`, one arm after the other (16 runs took about
18 minutes); `scripts/bullshark/coal2.sh` adds 24 runs per arm and the two new bribery arms at 40.

```bash
OUT=<dir> PY=<venv python> bash scripts/bullshark/coal.sh      # $OUT/coal/<arm>/
OUT=<dir> PY=<venv python> bash scripts/bullshark/coal2.sh     # $OUT/coal2/<arm>/
OUT=<dir> python3 scripts/bullshark/coal_score_runs.py  > runs.jsonl
OUT=<dir> python3 scripts/bullshark/coal2_score_runs.py > runs2.jsonl
python3 scripts/analysis/analyze.py data/bullshark/coal/runs_pooled.jsonl
python3 scripts/analysis/law.py; python3 scripts/analysis/law2.py
```

The per-run scorers keep, for every run, the targeted committing-height pairs won (`succ`) and
scored (`total`) as `measure.py` computes them. `runs_pooled.jsonl` is `runs.jsonl` and
`runs2.jsonl` together; `runs.jsonl` also carries the 16 runs of the three-victim control
`base4mv` (`scripts/bullshark/coal_mv.sh`), which `coal_score_runs.py`'s arm list does not
include. `analyze.py` pools each arm's pairs, takes a 10,000-resample bootstrap over runs for the
interval, and permutes run labels (20,000 shuffles) for the tests; on the shipped file it prints
the values below. `law.py` and `law2.py` fit the refusal law.

**Expected** (pooled, 95% run bootstrap, runs with pairs): base6 47.44 [43.32, 51.60] (37 runs);
f6ind 52.19 [47.49, 56.63] (40); f6rival 62.27 [58.35, 66.29] (39); f6 69.19 [65.00, 73.35] (38).
Differences: f6ind - base6 +4.75 (p = 0.151); f6rival - base6 +14.84 (p < 0.001; Table II prints
+14.83 from the rounded endpoints); f6 - base6 +21.75 (p < 0.001); f6 - f6ind +17.00 (p < 0.001).
Per-run scores: `data/bullshark/coal/runs_pooled.jsonl` (both campaigns; `runs.jsonl` and
`runs2.jsonl` are the two campaigns separately). The refusal law of Figure 4b (3.63 points per
refusal, intercept 49.24) fits the same file.

**Not in this repository:** the step that scored the `base4mv` runs into `runs.jsonl`, and the
scripts that wrote `m2_all_runs.jsonl` and `t2_pooled_runs.txt` (same-round and all-pairs counts
from `measure.py`) and that looped `scripts/bullshark/coalscore.py <run> <fa> <B>` over the runs
into `coalscore_runs.jsonl`.

---

## (c) Bribery on Bullshark (A5.1, A5.2, Figure 4c) and the refusal law on Mysticeti (A5.4)

**Claim, Bullshark.** One fissure attacker alone wins 51.4% of its targeted races against 48.6%
with no attack (A5.1, p = 0.52). One, two and three bribed validators lift it to 57.3, 58.8 and
63.8% (Figure 4c), about 3.9 points per bribe (run-level trend p < 0.001); three bribes are worth
12.4 points over the lone attacker (A5.2, p = 0.002), and reach what four Byzantine attackers
reach (65.5%, A6.2; p = 0.60).

**Tree.** `code/bullshark-flashboys`, same campaigns (`coal.sh`, `coal2.sh`), settings and scoring
as (b), n = 13. Machine: Xeon node. The trend test is `python3 scripts/analysis/trend.py`.

| Arm | `--attack` | `--fa` | Extra variables | Runs |
|---|---|---|---|---|
| `base1` | 10 | 1 | none | 16 + 24 |
| `solo` | 1 | 1 | none | 16 + 24 |
| `bribe1` | 1 | 1 | `BRIBED=1` | 40 (second campaign) |
| `bribe2` | 1 | 1 | `BRIBED=2` | 40 (second campaign) |
| `bribe` | 1 | 1 | `BRIBED=3` | 16 + 24 |
| `base4` | 10 | 4 | none | 16 + 24 |
| `f4` | 1 | 4 | none | 16 + 24 |

`BRIBED=B` makes the B honest validators that follow the victim in key order leave the victim's
certificate out of their own parents, a choice any honest validator may make.

**Expected** (pooled, 95% run bootstrap): base1 48.64 [43.08, 53.99]; solo 51.38 [45.88, 56.89];
bribe1 57.26 [53.50, 61.36]; bribe2 58.82 [53.83, 63.56]; bribe 63.76 [58.58, 68.31]; base4 50.47
[44.31, 56.00]; f4 65.53 [60.75, 70.09]. Tests: solo - base1 +2.74 (p = 0.522); bribe - solo
+12.38 (p = 0.002); bribe - f4 -1.78 (p = 0.595); f4 - base4 +15.06 (p < 0.001); trend over 0 to
3 bribes +3.85 points per bribe (p < 0.001, permutation of run labels on the weighted slope).
Per-run scores: `data/bullshark/coal/runs_pooled.jsonl`. The same runs rescored on all-pairs and
same-round (T2.1, T2.2): `data/bullshark/coal/t2_pooled_runs.txt` and `m2_all_runs.jsonl`.

**Claim, Mysticeti (A5.4).** On Sui v1.74, with the victim at validator 12 and the delegate
attacker at validator 0, one attacker plus three bribed validators lifts a tiebreak-neutral
committing-height rate from 50.83 to 57.57 (+6.74), the same as four Byzantine attackers (57.44).

**Tree.** `code/sui`, test `test_fissure_attack_asr_dynamic`, unmodified. Machine: Sui node.

```bash
bash scripts/frontrun_sui/run_mlaw.sh          # 6 arms x 5 reps (SEED 1-5), MIN_COMMITS=400
python3 scripts/frontrun_sui/score_mlaw.py scripts/frontrun_sui/runs_mlaw > scripts/frontrun_sui/runs_mlaw/scores.jsonl
```

Arms (all `NUM_NODES=13 VICTIM_RATIO=0.077 GC_DEPTH=10 COLLECTION_DURATION=60 MIN_COMMITS=400
RUST_LOG=error`): `base` (`NO_ATTACK=1`, one designated attacker), `k1` (one attacker), `b2`
(plus `FISSURE_BRIBED_NODES=1`), `b4` (plus `FISSURE_BRIBED_NODES=1,2,3`), `c4` (four attackers,
`ATTACKER_RATIO=0.308`), `c6` (six, `0.462`). The scorer takes every round in which validators 0
and 12 both have a committed block; the attacker wins if its block is in an earlier committed
sub-DAG, and a same-sub-DAG pair counts one half, so the identity tiebreak cannot move the rate.
Each arm's value is sum(`succ`) / sum(`pairs`) over its five runs.

**Expected** (pooled, 95% run bootstrap where recorded): base 50.83 [50.33, 51.23]; k1 49.67; b2
49.85; b4 57.57 [57.06, 58.33]; c4 57.44 [56.89, 57.99]; c6 70.69. Lifts over base: k1 -1.15, b2
-0.98, b4 +6.74, c4 +6.61, c6 +19.86 (exact 5 vs 5 p = 0.0079 for each of b4, c4, c6); c4 - b4
-0.13 [-1.05, +0.69], p = 0.80. Per-run scores: `data/sui_frontrun/mlaw_scores.jsonl`.

**Not in this repository:** the short script that bootstrapped these intervals. The pooled values
are sum(`succ`) / sum(`pairs`) per arm of `mlaw_scores.jsonl`.

---

## (d) Vote-withholding censorship on Bullshark (A1.4 = A2.8 at k = f, A5.3 at k = f + 1)

**Claim.** At n = 13 a certified block needs 9 votes. When k validators decline to vote on the
victim's headers, k = f = 4 kept 84.4% of the victim's blocks out of the order on one machine
and 0.8% on another (A1.4 = A2.8; whether the round succeeds depends on all nine remaining votes
arriving in time). k = f + 1 = 5 keeps every block out: 100% in 16 of 16 runs (A5.3; the fifth
withholder is a bribed validator, whose messages are identical to a Byzantine one's).

**Tree.** `code/bullshark-flashboys`. The hook is `CENSOR=k` in `primary/src/core.rs`: the first k
validators in key order other than the victim do not vote on the victim's headers and log
`CENSOR_VOTE_WITHHELD`. In both cells below the attack layout is fissure with four attackers, so
for k = 4 the withholders are the coalition.

| Cell | Machine | Arm | Control | Runs |
|---|---|---|---|---|
| A1.4 = A2.8 published value, k = 4 | AMD node | `CENSOR=4` | recorded only as its value, 0.35 | not recorded |
| k = 4 re-run (the "0.8%") | Xeon node | `CENSOR=4`, `--attack 1 --fa 4 --nodes 13` | the `f4` arm of (c), same settings without `CENSOR` | 16 |
| A5.3, k = 5 | Xeon node | `CENSOR=5`, `--attack 1 --fa 4 --nodes 13` | the k = 4 re-run | 16 |

```bash
OUT=<dir> PY=<venv python> bash scripts/bullshark/cens5.sh     # CENSOR=5, 16 runs, $OUT/coal/cens5/
OUT=<dir> PY=<venv python> bash scripts/bullshark/cens.sh      # CENSOR=4, 16 runs, $OUT/coal/cens4/
python3 scripts/score_censorship_bullshark.py --logdir $OUT/coal/cens5/fissure_f4_n13
```

The scorer prints one line per run and a `FINAL_CENSORSHIP_MEDIAN` line. Censorship rate =
1 - (victim blocks committed / median blocks committed by the other validators, excluding the
delegate attacker). When the victim
commits nothing, the scorer takes the victim from the hook's `CENSOR_VOTE_WITHHELD ... target`
line. The control of the k = 4 re-run is the `f4` arm of `coal.sh`.

**Expected.** A1.4 = A2.8: 0.35 to 84.40 (+84.05) on the AMD node. k = 4 on the Xeon node: median
0.78% [-0.39, 4.18] over 16 runs, against 0.19% for the control; the hook fired about 258 times
per withholder per run. A5.3: 100.0% in every one of 16 runs (the victim commits 0 blocks while
honest validators commit about 260; about 1,300 votes withheld per run), against 0.78 for k = 4:
+99.22. Per-run output of A5.3: `data/bullshark/coal/cens5_scores.txt`.

**Not in this repository:** the per-run scores of the k = 4 re-run (only its median and range
are recorded), and the driver, per-run scores and logs of the A1.4 = A2.8 campaign on the AMD
node (only its two endpoints, 0.35 and 84.40, are recorded).

---

## (e) Silent-except-leader on Mysticeti in Sui v1.74 (A2.4, T3.1)

**Claim.** One attacker (validator 0) that proposes only in its own leader rounds wins all of its
same-round races against the three highest-numbered validators, against 92.4% without the attack
(A2.4 = A3.1 = P2.1 = P4.1 = D1.1 = D3.1: 92.40 to 100.00). By staying silent it enters far fewer
races, so its share of victim value under a uniform value model falls from 92.4% to 8.0%
(T3.1 = T2.4: 92.38 to 7.96); pareto 94.04 to 5.99 (T3.2), lognormal 95.65 to 5.22 (T3.3).

**Tree.** `code/sui`, tests `test_withhold_baseline_asr_dynamic` (control: the hook is removed)
and `test_withhold_silent_attack_asr_dynamic` (attack) in
`consensus/core/src/withholding_attack_test.rs`. Every run stops at 290 commits, before Sui's
first leader-reputation update at commit 300, and follows the protocol's real leader schedule
(`SEL_REAL_SCHEDULE=1`). Machine: Sui node. A run takes about 20 seconds.

### Same-round (A2.4)

The driver is `scripts/sui/sel290_run.sh`. For each repetition it runs a control
(`test_withhold_baseline_asr_dynamic`) and an attack (`SILENT_EXCEPT_LEADER=1`,
`test_withhold_silent_attack_asr_dynamic`) arm under eight settings; this cell is the `rr` setting
(round-robin leader schedule, n = 13). The other settings are the stake, reputation, latency and
committee-size rows of Table II, and a final loop runs the tiebreak arms of (g). All arms share
`ATTACKER_RATIO=0.08 VICTIM_RATIO=0.231 GC_DEPTH=10 COLLECTION_DURATION=300 MIN_COMMITS=290
SEL_REAL_SCHEDULE=1 RUST_LOG=error` and `SEED=<rep>`.

```bash
OUT=<dir> bash scripts/sui/sel290_run.sh                        # $OUT/sel290/<setting>_<base|sel>_rep<k>.log
python3 scripts/sui/sel290_score.py "$OUT/sel290/rr_base_rep*.log" "$OUT/sel290/rr_sel_rep*.log"
# the same per-run values from the Bullshark harness scorer (attacker 0, victims 10-12):
python3 code/bullshark-flashboys/our_harness/measure.py $OUT/sel290/rr_base_rep1.log --format sui --attackers 0 --victims 10,11,12
```

`sel290_score.py` prints, per pattern, the median and range of the same-round rate, the all-pairs
median (checked against the log's own `FINAL_ALL_PAIRS_ASR`), the pair counts and the attacker's
committed blocks. `measure.py --format sui` gives the same per-run values on all 25 control and
tiebreak logs of this section and (g).

**Expected.** Same-round per run, control 92.41, 86.04, 92.38, 92.39, 79.68 (median 92.38, printed
92.40); attack 100.00, 100.00, 100.00, 100.00, 93.75 (median 100.00), on 68 to 80 same-round pairs
per run, with the attacker committing 23 to 27 blocks. All-pairs moves by less than a point (50.1
to 50.9). Table II marks the difference significant: 95% run bootstrap [+1.4, +20.3], rank test
p = 0.008.

### Value under three value models (T3.1 to T3.3)

The value rows run through the repository's harness (`scripts/v2/p_valuemodel.py`), which runs
the same two tests under a uniform, a pareto and a lognormal value per transaction and writes one
CSV row per run, with seeds 600 to 604:

```bash
# from the repository root
export V2_ATTACKERS=0 V2_ATTACKER_RATIO=0.08 V2_MIN_COMMITS=290 V2_COLLECTION_DURATION=300 SEL_REAL_SCHEDULE=1 CARGO_BUILD_JOBS=2 RUST_TEST_THREADS=1
nice -n 19 python3 -m scripts.v2.p_valuemodel --reps 5 --out-csv $OUT/valuemodel.csv --out-summary $OUT/valuemodel.json
```

The value is the column `profit_weighted_asr` (the attacker's share of victim value), cells
`baseline_<model>` against `silent_<model>`, median over the five runs.

**Expected.** uniform 92.38 to 7.96 (-84.42; run bootstrap [-84.5, -83.6], rank p = 0.008);
pareto 94.04 to 5.99; lognormal 95.65 to 5.22. Per-run rows: `data/sui_value/valuemodel.csv`.

`scripts/sui/v2_290_run.sh` is the 290-commit harness driver as we ran it with its default
four attackers (timestamp, value model, withholding and collusion rows); the value rows of the
paper are its value-model step rerun with one silent attacker.

**Not in this repository:** a driver file for that single-attacker value run; the command above
gives its settings as our run records state them (`V2_ATTACKERS=0`, `V2_ATTACKER_RATIO=0.08`,
290 commits, 5 reps, the other variables of `v2_290_run.sh`).

---

## (f) Transaction-level front-running (Table IV)

### Bullshark

**Claim.** The attacker's copy of each victim transaction is made only after its worker received
the victim's batch. With no attack its copy is committed first for 46.4% of victim transactions,
and 53.9% under fissure (A1.1 = P1.1: +7.5, permutation p = 0.024 for the median; Table II does
not mark it significant, since the run bootstrap interval of the difference, [-1.3, +14.0],
contains zero). Sending the copy to every validator gives 76.1%, and fissure adds 5.8 points
(81.9%, run-level p = 0.01). When the victim also sends to every validator, the attacker falls to
0.5% (no attack) and 0.4% (fissure). In a separate campaign (copy to all validators), a lone
fissure attacker wins 76.6% of the races it reaches in the victim's round against 70.2% with no
attack, and three bribes raise it to 80.4%.

**Tree.** `code/bullshark-flashboys`, hooks `FR_REACT` (worker copies victim-tagged transactions
it receives into its own next batch), `FR_GRIND` (digest grinding of the parent set), `FR_SPRAY`
(the attacker also sends its copy to every validator), `FR_VICTIM_SPRAY` (the victim does too);
`FR_VICTIM_RATE=10` makes a client stream victim transactions to the victim at 10 per second.
n = 13, f_a = 4. Machine: Xeon node.

Main panel, all with `FR_REACT=1 FR_VICTIM_RATE=10`, `--fa 4 --nodes 13`, into
`$OUT/fr_runs/<arm>/`. Each driver runs with `OUT=<dir> PY=<venv python> bash scripts/bullshark/<driver>`:

| Driver | Arms (runs each) |
|---|---|
| `fr_grid.sh` | `none`, `fissure`, `none_grind`, `fissure_grind` (5) |
| `fr_spray.sh` | `none_spray`, `fissure_spray`, `fissure_grind_spray` (5), with `FR_SPRAY=1` |
| `p1x_bull.sh` | `none_x`, `fissure_x`, `none_spray_x`, `fissure_spray_x` (15) |
| `p1y.sh` | `none_y`, `fissure_y` (20) |
| `vspray.sh` | `none_vspray`, `fissure_vspray` (10), with `FR_SPRAY=1 FR_VICTIM_SPRAY=1` |

Corruption panel: `scripts/bullshark/txc.sh`, `FR_REACT=1 FR_SPRAY=1 FR_GRIND=0
FR_VICTIM_RATE=10`, n = 13, 16 repetitions, the five arms interleaved within each repetition,
each run a separate call with `--runs 1 --keep $OUT/txc/<arm>/r<rep>`:

| Arm | `--attack` | `--fa` | Extra |
|---|---|---|---|
| `tbase4` | 10 | 4 | |
| `tf4` | 1 | 4 | |
| `tbase1` | 10 | 1 | |
| `tsolo` | 1 | 1 | |
| `tbribe3` | 1 | 1 | `BRIBED=3` |

Scoring, one JSON line per run (field `success_pct` = attacker copy committed at a lower height
than the victim transaction, over all committed victim transactions; `in_round_win_pct` = the same
among copies that land in the victim's round):

```bash
$PY code/bullshark-flashboys/our_harness/frontrun_score.py <run dir> [<run dir> ...]
# txc campaign, as we ran it:
for a in tbase4 tf4 tbase1 tsolo tbribe3; do
  for d in $OUT/txc/$a/r*/*/run0; do
    $PY code/bullshark-flashboys/our_harness/frontrun_score.py $d | sed "s/^{/{\"arm\": \"$a\", /"
  done
done > txc_scores.jsonl
```

Each Table IV row is the median of `success_pct` over the runs of an arm (an arm and its `_x`,
`_y` batches pooled), with the run range. `python3 scripts/frontrun_sui/make_table.py out.tex`
writes these rows from `data/bullshark/bullshark_frontrun/scores.jsonl`, together with the Sui
panels below, and `python3 scripts/frontrun_sui/p1_stats.py` gives the A1.1 and P1.2 tests (both
read the Sui logs from `scripts/frontrun_sui/runs*/`, so run the Sui drivers first). The
per-transaction file comes from `OUT=<dir> python3 scripts/bullshark/txexport.py >
txc_pertx.jsonl`.

**Expected** (median [range], runs): no attack 46.4 [23.0, 70.1] (40); fissure 53.9 [0.7, 79.0]
(40); no attack, digest grinding 60.2 [36.6, 68.2] (5); fissure, digest grinding 74.6 [59.6, 91.8]
(5); no attack, copy to all 76.1 [55.9, 90.7] (20); fissure, copy to all 81.9 [72.7, 90.5] (20);
fissure, grinding, copy to all 82.6 [75.4, 87.7] (5); both send to all, no attack 0.5 [0.0, 2.1]
(10) and fissure 0.4 [0.0, 1.4] (10). Corruption panel (16 runs each): tbase1 67.0 [56.6, 84.5],
tsolo 76.5 [62.4, 90.8], tbribe3 79.5 [45.4, 91.1], tbase4 72.2 [39.0, 86.2], tf4 73.4 [19.7,
90.4]; in-round means (permutation p, 20,000 shuffles) tbase1 70.20, tsolo 76.61 (+6.41, p =
0.006), tbribe3 80.37 (+10.17, p < 0.001; +3.76 over tsolo, p = 0.040), tbase4 72.11, tf4 77.79
(+5.69, p = 0.007). Per-run scores: `data/bullshark/bullshark_frontrun/scores.jsonl` (main panel,
155 runs), `txc_scores.jsonl` (80 runs) and `txc_pertx.jsonl` (per transaction: id, copied, won,
same round). Five runs took about 5.5 minutes.

**Not in this repository:** the script that ran the permutation tests of the corruption panel.
`scripts/value/inround_value.py` (below) runs the same run-label permutation of the in-round
means with its own seed and gives p = 0.006 (tsolo), < 0.001 (tbribe3), 0.008 (tf4) and 0.038
(tbribe3 over tsolo, where the paper cites 0.04).

**Value with real trade sizes.** Each victim transaction is given the stablecoin amount of a real
Sui mainnet transaction on a shared pool object, drawn independently from 1,752 such amounts
(median 22 USD, mean 6,796 USD). In every arm the share of value the attacker wins is within 0.2 points
of the share of races it wins; in-round value gains are +6.3 (tsolo), +10.0 (tbribe3) and +5.7
(tf4) points.

```bash
python3 scripts/value/inround_value.py 4000     # all races and in-round races, 4,000 resamples
python3 scripts/value/real_value.py 4000        # value share and USD per victim transaction, with and without a p99 cap
```

Both read `data/bullshark/bullshark_frontrun/txc_pertx.jsonl` and
`data/sui_value/sui_mainnet_trade_values.csv`. The amounts were extracted once from our read-only
census of Sui mainnet transactions (about 80 MB, not shipped) by `census_values()` in
`real_value.py`; the CSV keeps them in that order, so the scripts reproduce our output exactly.
Our output of the first command is `data/sui_value/inround_value_4000.txt`.

### Sui v1.74

**Claim.** On Sui, an attacker that must see the victim's transaction first rarely front-runs it
in consensus order (5.4% with block visibility), but in Sui's execution order, where each commit
is re-sorted by gas price, a copy sent to every validator at one gas unit more from 50 ms away
wins 91.3%. A victim that sends its own transaction to every validator cuts that to 20.3%.

**Tree.** `code/sui`, test `frontrun_attack_test` (hook `frontrun_prepend` in
`consensus/core/src/proposer.rs`; the test streams tagged victim transactions every 200 ms to the
three highest-numbered validators). Each run collects for 60 s. Every panel except the first sets
`FRONTRUN_VIEW=1`, which reads the committed order at honest validator 1; the first panel reads it
at the attacker. Machine: Sui node. Drivers and scorers are in
`scripts/frontrun_sui/`; each loops over its arms and over `SEED` 1 to 5 (1 to 20 where noted).

| Table IV panel | Driver(s) | Log directory | Order |
|---|---|---|---|
| Consensus order, no hook log, commits read at the attacker | `run_grid.sh` | `runs/` | consensus |
| One attacker, three victims | `run_sluggish.sh` (controls `blk_none_v1`, `mp_none_v1`), `run_v1.sh`, `run_sluggish_nb.sh` (sluggish rows) | `runs/`, `runs_slug_nb/` | consensus |
| Matched to Bullshark: four fissure attackers, one victim (20 runs) | `run_p1match.sh`, then `run_p1x.sh` and `run_p1mp.sh` | `runs_p1/` | consensus |
| Execution order (gas re-sort) | `run_gas.sh`, then `run_gasx.sh` (equal-gas arms to 20 runs) | `runs_gas/` | execution |
| Victim sends to one or to every validator | `run_vbcast.sh` | `runs_vbcast/` | execution |
| Competition, A3.5 | `run_compete.sh` | `runs_compete/` | consensus |

```bash
bash scripts/frontrun_sui/run_gas.sh
# consensus order: one JSON object per log, field success_pct
python3 scripts/frontrun_sui/score_frontrun.py scripts/frontrun_sui/runs_p1/blk_none_rep*.log
# execution order: same scorer with Sui's (commit, -gas, position) key
cd scripts/frontrun_sui
python3 -c "import glob,statistics as st; from score_frontrun import score, exec_key; v=[score(f, exec_key)['success_pct'] for f in sorted(glob.glob('runs_gas/bc_d50_outbid_rep*.log'))]; print(len(v), st.median(v), min(v), max(v))"
# competition: field cons.any
python3 score_compete.py runs_compete/*_rep*.log
```

The execution-order one-liner reproduces 91.3 [88.4, 92.4] on our `bc_d50_outbid` logs, and the
consensus-order scorer reproduces the four matched rows below.

**Expected** (median [range]): blind control 89.9 [82.6, 92.8]; blind with the digest tiebreak
51.8 [47.8, 55.4]; react on block visibility 5.4 [0.7, 5.8]; matched to Bullshark, 20 runs: block
4.7 [0.7, 39.1] to fissure 8.2 [0.4, 12.3] (P1.2), pending 30.3 [13.0, 43.1] to fissure 35.9
[16.3, 67.4]; execution order: copy to all, gas +1, at 0 / 50 / 200 ms 100.0 / 91.3 / 1.8; equal
gas 19.6 [14.9, 88.8] (20 runs) and with the digest tiebreak 24.6 [13.8, 81.2] (20 runs); victim
broadcast: copy to all 89.5 [86.2, 95.3] to 20.3 [14.1, 25.7], copy in own block 35.5 [22.8,
42.0] to 5.8 [4.7, 8.7] (exact 5 vs 5 p = 0.008); competition: one front-runner 29.3 [26.1,
31.9], two 34.4 [30.8, 39.1] (A3.5, exact one-sided p = 0.008). Per-run scores:
`data/sui_frontrun/grid_scores.json` (first panel), `compete_scores.jsonl` (A3.5); the other
panels are scored from the run logs with the commands above.

`scripts/frontrun_sui/make_table.py` applies the same two scorers to the first five panels of
Table IV and prints them; the victim-broadcast, competition and Bullshark corruption panels were
added to the table by hand from the scorer outputs listed above.

**Not in this repository:** the Sui run logs (about 7 GB).

---

## (g) Index tax: the tiebreak rows (P3.1 to P3.5)

**Claim.** With no attacker, Sui's author tiebreak hands validator 0 92.4% of its same-round races
against validators 10 to 12, where 50% is fair (P3.1). Bullshark sorts by round only and leaves it
at 48.9% (P3.2). Replacing the author key removes the advantage: digest 48.8% (P3.3), seeded
49.9% (P3.4), order-fair 52.1% (P3.5).

**Tree.** `code/sui` for P3.1 and P3.3 to P3.5. The alternative tiebreaks are env-gated in
`consensus/core/src/commit.rs` and, unlike the attack hooks, run on every node when set:
`FIX_TIEBREAK=1` (digest), `SEEDED_TIEBREAK=1`, `ORDER_FAIR_TIEBREAK=1`. P3.2 runs on
`code/bullshark-flashboys`. Machines: Sui node (Sui), Xeon node (Bullshark).

Sui: P3.1 is the control arm of (e) (`rr_base`). The other three are the same control test with
one variable added, five runs each; they are the last loop of `scripts/sui/sel290_run.sh`, which
writes `$OUT/sel290/p3_<digest|seeded|orderfair>_base_rep<k>.log`. Score them as in (e):

```bash
python3 scripts/sui/sel290_score.py "$OUT/sel290/p3_digest_base_rep*.log" "$OUT/sel290/p3_seeded_base_rep*.log" "$OUT/sel290/p3_orderfair_base_rep*.log"
```

**Expected** (median [range]): author 92.38 [79.7, 92.4]; digest 48.79 [45.2, 51.5]; seeded
49.94 [47.6, 50.8]; order-fair 52.14 [47.9, 57.0]. Differences from the author rule (Table II):
-43.60, -42.50, -40.30, each rank test p = 0.008. P3.1 is tested against the fixed 50% line, where
five runs cannot give p below 0.0625.

Bullshark (P3.2): the control arm of a silent-except-leader experiment,
`OUT=<dir> PY=<venv python> bash scripts/bullshark/sel_bull.sh`: `SILENT_EXCEPT_LEADER=1
SILENT_NODES=0` with `SILENT_DRYRUN=1` (control) or `SILENT_DRYRUN=0` (attack), `--attack 10
--fa 4 --nodes 13`, five runs each. The dry run logs the same markers as the attack but withholds
nothing. The driver scores every run with `measure.py <run> --silent-roles` into
`$OUT/sel_bull/scores.txt`; read `M2 same-round`. Expected: 48.85 [47.88, 51.44]; the attack arm
74.12 [63.88, 76.85]. Our per-run lines: `data/bullshark/sel_bull_scores.txt`.

What else the repository holds for the index tax: `data/index_tax/` is an earlier measurement
(July 2026) of the per-validator same-round win rate at n = 13, 25 and 49 on both Sui trees, made
with `scripts/v2/index_tax_analysis.py` and exported by `scripts/v2/index_tax_export.py`;
`scripts/v2/tiebreak_grind_sim.py` simulates digest grinding.

**Not in this repository:** the driver of the `data/index_tax/` runs, and the pipeline behind
the extended version's deployed-size index-tax table and figures (committees up to n = 125).
