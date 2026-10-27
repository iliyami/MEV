#!/bin/bash
REPO=${REPO:-$(cd "$(dirname "$0")/../.." && pwd)}
# A1 front-running grid: 6 arms x 5 reps, n=13, 60 s, one run at a time, resource-capped.
cd $REPO/code/sui
R=$REPO/scripts/frontrun_sui/runs
ARMS=("blind:FRONTRUN_MODE=blind" "react0:FRONTRUN_WAIT_MS=0" "wait100:FRONTRUN_WAIT_MS=100" "wait200:FRONTRUN_WAIT_MS=200" \
      "blind_fix:FRONTRUN_MODE=blind FIX_TIEBREAK=1" "wait200_fix:FRONTRUN_WAIT_MS=200 FIX_TIEBREAK=1")
for rep in 1 2 3 4 5; do
  for a in "${ARMS[@]}"; do
    name=${a%%:*}; vars=${a#*:}
    out=$R/${name}_rep${rep}.log
    [ -s "$out" ] && grep -q "test result: ok" "$out" && continue
    env $vars SEED=$rep COLLECTION_DURATION=60 RUST_LOG=error CARGO_BUILD_JOBS=2 RUST_TEST_THREADS=1 \
      nice -n 19 cargo test -p consensus-core --lib frontrun_attack_test -- --nocapture > "$out" 2>&1
    echo "$(date +%H:%M:%S) $name rep$rep exit=$?" >> $R/grid.log
  done
done
echo "$(date +%H:%M:%S) DONE" >> $R/grid.log
