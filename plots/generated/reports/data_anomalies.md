# Data Anomalies and Consistency Checks

These are the main places where the collected data needs explicit caveats in the paper.

## Structural checks
- Rows after cleaning and filtering: `2545`
- Extra unnamed trailing CSV fields: `experiment_results.csv=46`, `autobahn_results.csv=0`
- High-ASR rows (`>=99.9%`): `67`
- Incomplete parameter cells: `27`

## Baseline comparability
- The harmonized baselines cluster between roughly 49.9% and 52.9%, which makes a 50% fair-order reference defensible in non-baseline sweep figures.
- MEVSUI is the one protocol whose non-scaling sweeps default to 16 nodes in the config, while the harmonized baseline is 13 nodes. Any direct baseline-normalized claim for MEVSUI therefore uses only its 13-node cells.

## Incomplete cells
- `bullshark` / `defense_memory` / `fissure` / `DAG_STATE_CACHED_ROUNDS=50` only has reps `[1]` out of expected `5`.
- `mahimahi` / `scaling` / `fissure` / `NUM_NODES=100` only has reps `[1]` out of expected `5`.
- `mahimahi` / `scaling` / `fissure` / `NUM_NODES=50` only has reps `[1, 2, 3, 4]` out of expected `5`.
- `narwhal` / `defense_batching` / `sluggish` / `BATCH_SIZE=1000000, MAX_BATCH_DELAY=500` only has reps `[2, 3, 5]` out of expected `4`.
- `narwhal` / `defense_batching` / `sluggish` / `BATCH_SIZE=250000, MAX_BATCH_DELAY=100` only has reps `[2]` out of expected `4`.
- `narwhal` / `defense_batching` / `speculative` / `BATCH_SIZE=1000000, MAX_BATCH_DELAY=500` only has reps `[1, 2, 4, 5]` out of expected `5`.
- `narwhal` / `defense_batching` / `speculative` / `BATCH_SIZE=250000, MAX_BATCH_DELAY=100` only has reps `[1, 3, 4, 5]` out of expected `5`.
- `narwhal` / `defense_gc` / `sluggish` / `GC_DEPTH=10` only has reps `[1, 2, 3]` out of expected `5`.
- `narwhal` / `defense_gc` / `sluggish` / `GC_DEPTH=5` only has reps `[3, 4, 5]` out of expected `5`.
- `narwhal` / `defense_header` / `sluggish` / `HEADER_SIZE=1000, MAX_HEADER_DELAY=200` only has reps `[1, 2, 5]` out of expected `4`.
- `narwhal` / `defense_header` / `sluggish` / `HEADER_SIZE=2000, MAX_HEADER_DELAY=500` only has reps `[2]` out of expected `4`.
- `narwhal` / `defense_memory` / `sluggish` / `DAG_STATE_CACHED_ROUNDS=2` only has reps `[1, 3, 4]` out of expected `4`.
- `narwhal` / `defense_memory` / `sluggish` / `DAG_STATE_CACHED_ROUNDS=20` only has reps `[1, 2, 5]` out of expected `4`.
- `narwhal` / `defense_memory` / `sluggish` / `DAG_STATE_CACHED_ROUNDS=5` only has reps `[4]` out of expected `4`.
- `narwhal` / `defense_memory` / `speculative` / `DAG_STATE_CACHED_ROUNDS=1` only has reps `[1, 2, 3, 4]` out of expected `5`.
- `narwhal` / `defense_memory` / `speculative` / `DAG_STATE_CACHED_ROUNDS=2` only has reps `[1, 4, 5]` out of expected `5`.
- `narwhal` / `defense_network` / `sluggish` / `SYNC_TIMEOUT_MS=500` only has reps `[2, 3, 4, 5]` out of expected `5`.
- `narwhal` / `defense_network` / `sluggish` / `SYNC_TIMEOUT_MS=5000` only has reps `[2, 3]` out of expected `5`.
- `narwhal` / `defense_network` / `speculative` / `SYNC_TIMEOUT_MS=5000` only has reps `[1, 2, 4, 5]` out of expected `5`.
- `narwhal` / `env_latency` / `sluggish` / `LATENCY_JITTER=150ms 30ms` only has reps `[1, 2]` out of expected `5`.
- `narwhal` / `env_latency` / `sluggish` / `LATENCY_JITTER=300ms 50ms` only has reps `[1, 2, 3, 5]` out of expected `5`.
- `narwhal` / `env_latency` / `speculative` / `LATENCY_JITTER=150ms 30ms` only has reps `[2, 3, 4, 5]` out of expected `5`.
- `narwhal` / `offense_sluggish` / `sluggish` / `SLUGGISH_TIMEOUT_MULTIPLIER=1.5` only has reps `[2, 4]` out of expected `4`.
- `narwhal` / `offense_speculative` / `speculative` / `SPECULATIVE_P_MAX=20` only has reps `[2, 3, 4, 5]` out of expected `5`.
- `narwhal` / `scaling` / `fissure` / `NUM_NODES=13` only has reps `[1, 2, 3, 5]` out of expected `5`.

## High-variance cells
- `autobahn` / `autobahn_fast_path` / `sluggish` / `AUTOBAHN_FAST_PATH_TIMEOUT=500` spans `3.60%` to `95.59%` with median `50.00%`.
- `autobahn` / `offense_sluggish` / `sluggish` / `SLUGGISH_TIMEOUT_MULTIPLIER=5.0` spans `4.11%` to `96.03%` with median `49.93%`.
- `autobahn` / `env_latency` / `sluggish` / `LATENCY_JITTER=300ms 50ms` spans `4.41%` to `95.73%` with median `49.92%`.
- `narwhal` / `offense_sluggish` / `sluggish` / `SLUGGISH_TIMEOUT_MULTIPLIER=5.0` spans `12.50%` to `100.00%` with median `55.55%`.
- `narwhal` / `defense_header` / `fissure` / `HEADER_SIZE=1000, MAX_HEADER_DELAY=200` spans `16.67%` to `100.00%` with median `61.36%`.
- `narwhal` / `defense_network` / `fissure` / `SYNC_TIMEOUT_MS=500` spans `16.67%` to `100.00%` with median `50.00%`.
- `narwhal` / `defense_batching` / `sluggish` / `BATCH_SIZE=500000, MAX_BATCH_DELAY=200` spans `25.00%` to `100.00%` with median `75.00%`.
- `narwhal` / `defense_gc` / `sluggish` / `GC_DEPTH=5` spans `25.00%` to `100.00%` with median `60.00%`.
- `narwhal` / `defense_header` / `sluggish` / `HEADER_SIZE=1000, MAX_HEADER_DELAY=200` spans `25.00%` to `100.00%` with median `100.00%`.
- `narwhal` / `defense_memory` / `fissure` / `DAG_STATE_CACHED_ROUNDS=20` spans `25.00%` to `100.00%` with median `66.67%`.
- `narwhal` / `defense_memory` / `speculative` / `DAG_STATE_CACHED_ROUNDS=1` spans `25.00%` to `100.00%` with median `67.10%`.
- `narwhal` / `defense_network` / `sluggish` / `SYNC_TIMEOUT_MS=2000` spans `25.00%` to `100.00%` with median `50.00%`.
- `narwhal` / `defense_network` / `speculative` / `SYNC_TIMEOUT_MS=5000` spans `25.00%` to `100.00%` with median `58.34%`.
- `narwhal` / `env_latency` / `sluggish` / `LATENCY_JITTER=300ms 50ms` spans `25.00%` to `100.00%` with median `70.59%`.
- `narwhal` / `offense_fissure` / `fissure` / `ATTACKER_RATIO=0.1` spans `25.00%` to `100.00%` with median `100.00%`.
- `narwhal` / `offense_speculative` / `speculative` / `SPECULATIVE_P_MAX=20` spans `25.00%` to `100.00%` with median `63.05%`.
- `narwhal` / `scaling_workers` / `sluggish` / `NUM_WORKERS=4` spans `25.00%` to `100.00%` with median `25.00%`.
- `alephbft` / `env_latency` / `sluggish` / `LATENCY_JITTER=50ms 10ms` spans `28.09%` to `98.54%` with median `58.75%`.
- `alephbft` / `aleph_sync_speed` / `sluggish` / `ALEPH_COORD_REQUEST_DELAY_MS=50` spans `11.79%` to `78.54%` with median `74.74%`.
- `narwhal` / `defense_batching` / `fissure` / `BATCH_SIZE=500000, MAX_BATCH_DELAY=200` spans `33.33%` to `100.00%` with median `83.33%`.
- `narwhal` / `defense_gc` / `fissure` / `GC_DEPTH=10` spans `33.33%` to `100.00%` with median `75.00%`.
- `narwhal` / `defense_gc` / `sluggish` / `GC_DEPTH=50` spans `33.33%` to `100.00%` with median `80.00%`.
- `narwhal` / `defense_memory` / `fissure` / `DAG_STATE_CACHED_ROUNDS=1` spans `33.33%` to `100.00%` with median `100.00%`.
- `narwhal` / `defense_memory` / `speculative` / `DAG_STATE_CACHED_ROUNDS=5` spans `33.33%` to `100.00%` with median `71.43%`.
- `narwhal` / `defense_network` / `fissure` / `SYNC_TIMEOUT_MS=2000` spans `33.33%` to `100.00%` with median `50.00%`.

## Notes worth carrying into captions
- Narwhal contributes many near-100% cells; the figures should present them, but the text should avoid implying that all Narwhal regimes are saturated across every scale.
- Autobahn stays near baseline in median for most sweeps, but several cells show very large run-to-run spread. That makes the boxplots and median-only trend lines important.
- The Aleph rows that appear under `mahimahi_wave`, `mahimahi_leaders`, and `mysticeti_strategy` look like exploratory misrouted runs and are excluded from the protocol-specific figures.
