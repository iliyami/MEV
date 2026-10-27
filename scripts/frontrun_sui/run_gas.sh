#!/bin/bash
REPO=${REPO:-$(cd "$(dirname "$0")/../.." && pwd)}
# A1 v2: Sui execution order (gas re-sort per commit). Waits for the Mahi-Mahi re-run to finish.
cd $REPO/code/sui
R=$REPO/scripts/frontrun_sui/runs_gas; mkdir -p $R
COMMON="ATTACKER_RATIO=0.08 VICTIM_RATIO=0.231 COLLECTION_DURATION=60 FRONTRUN_VIEW=1 RUST_LOG=error CARGO_BUILD_JOBS=2 RUST_TEST_THREADS=1"
ARMS=(
 "bc_d0_outbid:FRONTRUN_MODE=broadcast FRONTRUN_MEMPOOL_DELAY_MS=0 FRONTRUN_GAS=outbid"
 "bc_d50_outbid:FRONTRUN_MODE=broadcast FRONTRUN_MEMPOOL_DELAY_MS=50 FRONTRUN_GAS=outbid"
 "bc_d200_outbid:FRONTRUN_MODE=broadcast FRONTRUN_MEMPOOL_DELAY_MS=200 FRONTRUN_GAS=outbid"
 "bc_d50_match:FRONTRUN_MODE=broadcast FRONTRUN_MEMPOOL_DELAY_MS=50 FRONTRUN_GAS=match"
 "bc_d50_match_fix:FRONTRUN_MODE=broadcast FRONTRUN_MEMPOOL_DELAY_MS=50 FRONTRUN_GAS=match FIX_TIEBREAK=1"
 "hook_mp_d50_outbid:FRONTRUN_VISIBILITY=mempool FRONTRUN_MEMPOOL_DELAY_MS=50 FRONTRUN_GAS=outbid"
 "hook_blk_outbid:FRONTRUN_GAS=outbid"
)
for rep in 1 2 3 4 5; do
  for a in "${ARMS[@]}"; do
    name=${a%%:*}; vars=${a#*:}; out=$R/${name}_rep${rep}.log
    [ -s "$out" ] && grep -q "test result: ok" "$out" && continue
    env $COMMON $vars SEED=$rep nice -n 19 cargo test -p consensus-core --lib frontrun_attack_test -- --nocapture > "$out" 2>&1
    echo "$(date +%H:%M:%S) $name rep$rep exit=$?" >> $R/gas.log
  done
done
echo "$(date +%H:%M:%S) GAS DONE" >> $R/gas.log
