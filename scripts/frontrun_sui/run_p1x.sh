#!/bin/bash
REPO=${REPO:-$(cd "$(dirname "$0")/../.." && pwd)}
# P1 contrast matched to Bullshark: 4 fissure attackers (alpha=4/13), 1 victim, front-runner at index 0.
cd $REPO/code/sui
R=$REPO/scripts/frontrun_sui/runs_p1; mkdir -p $R
COMMON="VICTIM_RATIO=0.08 FRONTRUN_VICTIMS=1 FRONTRUN_ATTACKERS=1 COLLECTION_DURATION=60 FRONTRUN_VIEW=1 RUST_LOG=error,consensus_core::proposer=debug CARGO_BUILD_JOBS=2 RUST_TEST_THREADS=1"
ARMS=(
 "blk_none:ATTACKER_RATIO=0.308"
 "blk_fissure:ATTACKER_RATIO=0.308 ATTACK_MODE=fissure"
)
for rep in $(seq 1 20); do
  for a in "${ARMS[@]}"; do
    name=${a%%:*}; vars=${a#*:}; out=$R/${name}_rep${rep}.log
    [ -s "$out" ] && grep -q "test result: ok" "$out" && continue
    env $COMMON $vars SEED=$rep nice -n 19 cargo test -p consensus-core --lib frontrun_attack_test -- --nocapture > "$out" 2>&1
    echo "$(date +%H:%M:%S) $name rep$rep exit=$?" >> $R/p1.log
  done
done
echo "$(date +%H:%M:%S) P1X DONE" >> $R/p1.log
