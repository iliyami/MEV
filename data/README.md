# Per-run results

Scored results, one record per run, so that a reader can recompute a cell and its interval rather
than take it on trust. Every attack arm ships with the control arm it is scored against. How each
file was produced, and the value it should give, is in [`../REPRODUCE.md`](../REPRODUCE.md). The
raw run logs are not shipped (several GB); the scorers that turn logs into these files are in the
repository (`code/bullshark-flashboys/our_harness/`, `scripts/`), and the run-level statistics
over the Bullshark files are in `scripts/analysis/`, which read `bullshark/coal/` directly.

## Machines

All runs used four CloudLab machines, and an attack arm always ran on the same machine as its
control:

- a CloudLab node with two 14-core Intel Xeon E5-2683 v3 CPUs and 251 GB (the Bullshark
  campaigns in `bullshark/`, and the Narwhal-family, bribery, coordination and n = 100 / 125 runs);
- dedicated CloudLab `c6525-25g` nodes, 16-core AMD 7302P, 128 GB (the other cluster runs);
- a CloudLab AMD node, 64 cores, 125 GB (the first censorship cell, A1.4 = A2.8);
- the Sui node, a second CloudLab node with the same hardware as the first (the Sui and Mysticeti runs in `sui_frontrun/` and
  `sui_value/`; all validators of a run share one process).

## Directories

| Directory | Machine | Contents | Cells it backs |
|---|---|---|---|
| `bullshark/coal/` | Xeon node | coalition and bribery campaigns on Bullshark, n = 13, targeted committing-height: `runs.jsonl` (first campaign, 16 runs per arm), `runs2.jsonl` (second, 24 or 40 runs), `runs_pooled.jsonl` (both, 40 per arm, plus the `base4mv` control of T1.2); `m2_all_runs.jsonl` (same-round and all-pairs per run, both campaigns); `t2_pooled_runs.txt` (all three metrics per run for the lone-attacker and bribe arms); `coalscore_runs.jsonl` (same-round scored for the whole coalition, bribed validators' own blocks included) | A3.2 to A3.4, A5.1, A5.2, A6.1 to A6.3, T1.1 and T1.2 controls, T2.1 to T2.3, Figure 4a to 4c |
| `bullshark/coal/` | Xeon node | `fig4_runs.jsonl`: same-round and all-pairs pair counts, 5 runs per arm | A2.1 = A4.1 |
| `bullshark/coal/` | Xeon node | `dsweep_scores.jsonl` (committee-size sweep, n = 7 / 13 / 25, 10 runs per arm) and `lsweep_scores.jsonl` (n = 25 with 1, 2, 4, 6 attackers, and 10 more controls) | the fissure committee-size sweep and the n = 25 refusal law (Deployment) |
| `bullshark/coal/` | Xeon node | `cens5_scores.txt`: per-run censorship rate and withheld votes, k = 5 | A5.3, Figure 4d |
| `bullshark/bullshark_frontrun/` | Xeon node | `scores.jsonl` (155 runs, the Bullshark panel of Table IV; arms `X`, `X_x`, `X_y` pool into one row); `txc_scores.jsonl` (80 runs, the corruption panel) and `txc_pertx.jsonl` (the same runs, one entry per victim transaction: id, copied, won, same round) | A1.1 = P1.1, Table IV (Bullshark) |
| `bullshark/` | Xeon node | `sel_bull_scores.txt`: silent-except-leader and its dry-run control, scorer output per run | P3.2 |
| `sui_frontrun/` | Sui node | `grid_scores.json` (first panel of Table IV, 5 runs per arm); `compete_scores.jsonl` (two front-runners against one); `mlaw_scores.jsonl` (refusal law on Mysticeti, 6 arms x 5 runs); `sample_scores.json` (an earlier grid read at the attacker's own view, not used in Table IV) | Table IV (first panel), A3.5, A5.4, Figure 4b (Mysticeti) |
| `sui_value/` | Sui node | `valuemodel.csv`: silent-except-leader and control under three value models, one row per run (column `profit_weighted_asr`) | T2.4 = T3.1, T3.2, T3.3 |
| `sui_value/` | not a run | `sui_mainnet_trade_values.csv`: the 1,752 stablecoin amounts (USD) of real Sui mainnet transactions on shared pool objects that `scripts/value/` assigns to victim transactions; `inround_value_4000.txt`: our output of `scripts/value/inround_value.py 4000` | the value-with-real-trade-sizes result of the Bullshark front-running campaign |
| `cloudlab_withholding/`, `cloudlab_ds13_14_16/`, `cloudlab_ds8-18/`, `cloudlab_alpha/` | CloudLab (July 2026 campaign) | an earlier campaign on the two Sui trees: committee size and the withholding arms, stake, geo-distribution, value model, n = 49, relationship, incentive, victims, attacker fraction. `v2_*` files are the Sui v1.58 tree, `sui_*` the v1.74 tree | earlier versions of the D, A3, A5, A6 and T rows; the current Table II rows come from the runs listed in `../REPRODUCE.md` |
| `index_tax/` | CloudLab (July 2026 campaign) | no-attacker tiebreak measurement at n = 13, 25, 49 with and without the digest tiebreak; `per_index.csv` is one row per validator, `summary.csv` one row per committee size. Rows labelled `Bullshark` are the Sui v1.58 tree (`code/bullshark`), not the certified Bullshark of `code/bullshark-flashboys` | an earlier no-attacker measurement; the current P3 rows come from the runs in `../REPRODUCE.md` (g) |

## Reading the files

- Lines that do not start with `{` in the `.jsonl` files are driver log lines; skip them.
- Committing-height cells pool `succ` and `total` over the runs of an arm; runs with
  `total` = 0 (or `nopairs`) recorded no targeted pairs and are dropped.
- In `dsweep_scores.jsonl` the `arm` field is wrong; take the arm from the path component
  after `dsweep/` in `run` (`/mnt/data/dsweep/<arm>/r<rep>/...`). `lsweep_scores.jsonl` has the same layout.
- `grid_scores.json` and `sample_scores.json` contain `NaN` for undefined fields; Python's `json`
  module reads them.
- The `run` paths inside the files are paths on the machine that produced them.
