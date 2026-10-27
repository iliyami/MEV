#!/bin/bash
REPO=${REPO:-$(cd "$(dirname "$0")/../.." && pwd)}
# Competition cell: two independent front-runners (the two lowest-indexed validators) react to the
# same victim transactions, each placing its own copy in its own block, against one front-runner.
# Same settings as hook_mp_d50_outbid in run_gas.sh. Attribution by the copy's block author.
cd $REPO/code/sui
R=$REPO/scripts/frontrun_sui/runs_compete; mkdir -p $R
COMMON="ATTACKER_RATIO=0.08 VICTIM_RATIO=0.231 COLLECTION_DURATION=60 FRONTRUN_VIEW=1 RUST_LOG=error CARGO_BUILD_JOBS=2 RUST_TEST_THREADS=1 FRONTRUN_VISIBILITY=mempool FRONTRUN_MEMPOOL_DELAY_MS=50 FRONTRUN_GAS=outbid"
ARMS=(
 "one:FRONTRUN_ATTACKERS=1"
 "two:FRONTRUN_ATTACKERS=2"
 "two_fix:FRONTRUN_ATTACKERS=2 FIX_TIEBREAK=1"
)
for rep in 1 2 3 4 5; do
  for a in "${ARMS[@]}"; do
    name=${a%%:*}; vars=${a#*:}; out=$R/${name}_rep${rep}.log
    [ -s "$out" ] && grep -q "test result: ok" "$out" && continue
    env $COMMON $vars SEED=$rep nice -n 19 cargo test -p consensus-core --lib frontrun_attack_test -- --nocapture > "$out" 2>&1
    echo "$(date +%H:%M:%S) $name rep$rep exit=$?" >> $R/compete.log
  done
done
echo "$(date +%H:%M:%S) COMPETE DONE" >> $R/compete.log
