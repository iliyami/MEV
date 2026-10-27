#!/bin/bash
REPO=${REPO:-$(cd "$(dirname "$0")/../.." && pwd)}
# Verbosity-matched block-visibility control for the sample grid (same RUST_LOG as run_sample.sh).
cd $REPO/code/sui
R=$REPO/scripts/frontrun_sui/runs
for rep in 1 2 3 4 5; do
  out=$R/blk_none_rep${rep}.log
  [ -s "$out" ] && grep -q "test result: ok" "$out" && continue
  env ATTACKER_RATIO=0.08 VICTIM_RATIO=0.231 COLLECTION_DURATION=60 RUST_LOG=error,consensus_core::proposer=debug CARGO_BUILD_JOBS=2 RUST_TEST_THREADS=1 SEED=$rep \
    nice -n 19 cargo test -p consensus-core --lib frontrun_attack_test -- --nocapture > "$out" 2>&1
  echo "$(date +%H:%M:%S) blk_none rep$rep exit=$?" >> $R/sample.log
done
