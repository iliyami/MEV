#!/bin/bash
REPO=${REPO:-$(cd "$(dirname "$0")/../.." && pwd)}
# Equal-gas arms to 20 reps (FixTiebreak contrast), after the D2/D3 re-run.
cd $REPO/code/sui
R=$REPO/scripts/frontrun_sui/runs_gas
COMMON="ATTACKER_RATIO=0.08 VICTIM_RATIO=0.231 COLLECTION_DURATION=60 FRONTRUN_VIEW=1 RUST_LOG=error CARGO_BUILD_JOBS=2 RUST_TEST_THREADS=1"
for rep in $(seq 1 20); do
  for a in "bc_d50_match:FRONTRUN_MODE=broadcast FRONTRUN_MEMPOOL_DELAY_MS=50 FRONTRUN_GAS=match" "bc_d50_match_fix:FRONTRUN_MODE=broadcast FRONTRUN_MEMPOOL_DELAY_MS=50 FRONTRUN_GAS=match FIX_TIEBREAK=1"; do
    name=${a%%:*}; vars=${a#*:}; out=$R/${name}_rep${rep}.log
    [ -s "$out" ] && grep -q "test result: ok" "$out" && continue
    env $COMMON $vars SEED=$rep nice -n 19 cargo test -p consensus-core --lib frontrun_attack_test -- --nocapture > "$out" 2>&1
    echo "$(date +%H:%M:%S) $name rep$rep exit=$?" >> $R/gas.log
  done
done
echo "$(date +%H:%M:%S) GASX DONE" >> $R/gas.log
