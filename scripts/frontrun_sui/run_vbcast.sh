#!/bin/bash
REPO=${REPO:-$(cd "$(dirname "$0")/../.." && pwd)}
# Victim broadcast on Sui: the victim also sends its transaction to every validator
# (FRONTRUN_VICTIM_BROADCAST=1, client behavior in the test workload only), against the two Sui
# attackers of Table III: a client copy sent to all at gas +1 (50 ms), and a validator copy in
# its own block at gas +1 with pending visibility (50 ms). Settings as run_gas.sh.
cd $REPO/code/sui
R=$REPO/scripts/frontrun_sui/runs_vbcast; mkdir -p $R
COMMON="ATTACKER_RATIO=0.08 VICTIM_RATIO=0.231 COLLECTION_DURATION=60 FRONTRUN_VIEW=1 RUST_LOG=error CARGO_BUILD_JOBS=2 RUST_TEST_THREADS=1 FRONTRUN_MEMPOOL_DELAY_MS=50 FRONTRUN_GAS=outbid"
ARMS=(
 "bc:FRONTRUN_MODE=broadcast"
 "bc_vb:FRONTRUN_MODE=broadcast FRONTRUN_VICTIM_BROADCAST=1"
 "mp:FRONTRUN_VISIBILITY=mempool"
 "mp_vb:FRONTRUN_VISIBILITY=mempool FRONTRUN_VICTIM_BROADCAST=1"
)
for rep in 1 2 3 4 5; do
  for a in "${ARMS[@]}"; do
    name=${a%%:*}; vars=${a#*:}; out=$R/${name}_rep${rep}.log
    [ -s "$out" ] && grep -q "test result: ok" "$out" && continue
    env $COMMON $vars SEED=$rep nice -n 19 cargo test -p consensus-core --lib frontrun_attack_test -- --nocapture > "$out" 2>&1
    echo "$(date +%H:%M:%S) $name rep$rep exit=$?" >> $R/vbcast.log
  done
done
echo "$(date +%H:%M:%S) VBCAST DONE" >> $R/vbcast.log
