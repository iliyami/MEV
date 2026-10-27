#!/bin/bash
REPO=${REPO:-$(cd "$(dirname "$0")/../.." && pwd)}
# Remaining primitives with commits read at honest validator 1, so every hook-log row shares one view.
cd $REPO/code/sui
R=$REPO/scripts/frontrun_sui/runs
COMMON="ATTACKER_RATIO=0.08 VICTIM_RATIO=0.231 COLLECTION_DURATION=60 FRONTRUN_VIEW=1 RUST_LOG=error,consensus_core::proposer=debug CARGO_BUILD_JOBS=2 RUST_TEST_THREADS=1"
ARMS=(
 "mp_none_fix_v1:FRONTRUN_VISIBILITY=mempool FIX_TIEBREAK=1"
 "blk_fissure_v1:ATTACK_MODE=fissure"
 "mp_fissure_v1:FRONTRUN_VISIBILITY=mempool ATTACK_MODE=fissure"
 "blk_speculative_v1:ATTACK_MODE=speculative SPECULATIVE_P_MAX=50"
 "mp_speculative_v1:FRONTRUN_VISIBILITY=mempool ATTACK_MODE=speculative SPECULATIVE_P_MAX=50"
 "blk_sel_v1:SILENT_EXCEPT_LEADER=1 NUM_ATTACKERS=1"
 "mp_sel_v1:FRONTRUN_VISIBILITY=mempool SILENT_EXCEPT_LEADER=1 NUM_ATTACKERS=1"
)
for rep in 1 2 3 4 5; do
  for a in "${ARMS[@]}"; do
    name=${a%%:*}; vars=${a#*:}; out=$R/${name}_rep${rep}.log
    [ -s "$out" ] && grep -q "test result: ok" "$out" && continue
    env $COMMON $vars SEED=$rep nice -n 19 cargo test -p consensus-core --lib frontrun_attack_test -- --nocapture > "$out" 2>&1
    echo "$(date +%H:%M:%S) $name rep$rep exit=$?" >> $R/sample.log
  done
done
echo "$(date +%H:%M:%S) V1 DONE" >> $R/sample.log
