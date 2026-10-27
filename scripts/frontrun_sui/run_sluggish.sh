#!/bin/bash
REPO=${REPO:-$(cd "$(dirname "$0")/../.." && pwd)}
# Sluggish arms re-run reading commits from honest validator 1 (the attacker's own view lags under sluggish).
cd $REPO/code/sui
R=$REPO/scripts/frontrun_sui/runs
COMMON="ATTACKER_RATIO=0.08 VICTIM_RATIO=0.231 COLLECTION_DURATION=60 FRONTRUN_VIEW=1 RUST_LOG=error,consensus_core::proposer=debug CARGO_BUILD_JOBS=2 RUST_TEST_THREADS=1"
for rep in 1 2 3 4 5; do
 for a in "blk_sluggish:ATTACK_MODE=sluggish SLUGGISH_TIMEOUT_MULTIPLIER=2.0" "mp_sluggish:FRONTRUN_VISIBILITY=mempool ATTACK_MODE=sluggish SLUGGISH_TIMEOUT_MULTIPLIER=2.0" "blk_none_v1:X=1" "mp_none_v1:FRONTRUN_VISIBILITY=mempool"; do
  name=${a%%:*}; vars=${a#*:}; out=$R/${name}_rep${rep}.log
  [ -s "$out" ] && grep -q "test result: ok" "$out" && continue
  env $COMMON $vars SEED=$rep nice -n 19 cargo test -p consensus-core --lib frontrun_attack_test -- --nocapture > "$out" 2>&1
  echo "$(date +%H:%M:%S) $name rep$rep exit=$?" >> $R/sample.log
 done
done
echo "$(date +%H:%M:%S) SLUGGISH DONE" >> $R/sample.log
