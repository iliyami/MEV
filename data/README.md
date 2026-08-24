# Per-cell results

The measurements behind Table 2. Each row of a CSV is one repetition, with the arm it belongs to
(`dag_strategy`), the committee size (`num_nodes`), the attacker fraction (`attacker_fraction`)
and the score (`asr`, plus `realized_mev` and `profit_weighted_asr` where a value model applies).
A cell in the paper is the median over five such rows, and every attack arm ships alongside the
control arm it is scored against, so a reader can recompute a lift rather than take it on trust.

All runs were executed on dedicated CloudLab nodes (`c6525-25g`: 16-core AMD 7302P, 128 GB ECC,
25 Gb Ethernet). `v2_*` files are the Sui v1.58 tree, `sui_*` the v1.74 tree.

| directory | dimensions it covers |
|---|---|
| `cloudlab_withholding/` | committee size (D1) and the withholding arms: baseline, silent-except-leader, SLW |
| `cloudlab_ds13_14_16/` | stake (D2), geo-distribution (D3), value model (T3), and the n=49 fill |
| `cloudlab_ds8-18/` | relationship (A3), incentive (A5), victims (T1) and the cross-cutting sweeps |
| `cloudlab_alpha/` | attacker fraction (A6) |
| `index_tax/` | the no-attacker tiebreak measurement (P3.1) behind Figures 8 and 9; `per_index.csv` is one row per validator, `summary.csv` one row per committee size |

The raw committed-order logs these were scored from are ~512 MB and are archived separately
rather than shipped here; the scorers that turn logs into these CSVs are under
[`../scripts/`](../scripts).
