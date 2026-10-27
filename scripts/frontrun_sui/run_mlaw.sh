#!/bin/bash
REPO=${REPO:-$(cd "$(dirname "$0")/../.." && pwd)}
# The refusal law on a second protocol: Mysticeti in Sui v1.74 (uncertified), fissure, one victim
# (validator 12), delegate attacker validator 0. Refusals per victim are bought three ways:
# Byzantine colluders (ATTACKER_RATIO) or bribed honest nodes (FISSURE_BRIBED_NODES, which only
# leave the victim's block out of their parents). Unmodified fissure_attack_test; same log level for all arms.
cd $REPO/code/sui
R=$REPO/scripts/frontrun_sui/runs_mlaw; mkdir -p $R
COMMON="NUM_NODES=13 VICTIM_RATIO=0.077 GC_DEPTH=10 COLLECTION_DURATION=60 MIN_COMMITS=400 RUST_LOG=error CARGO_BUILD_JOBS=2 RUST_TEST_THREADS=1"
ARMS=(
 "base:NO_ATTACK=1 ATTACKER_RATIO=0.077"
 "k1:ATTACKER_RATIO=0.077"
 "b2:ATTACKER_RATIO=0.077 FISSURE_BRIBED_NODES=1"
 "b4:ATTACKER_RATIO=0.077 FISSURE_BRIBED_NODES=1,2,3"
 "c4:ATTACKER_RATIO=0.308"
 "c6:ATTACKER_RATIO=0.462"
)
for rep in 1 2 3 4 5; do
  for a in "${ARMS[@]}"; do
    name=${a%%:*}; vars=${a#*:}; out=$R/${name}_rep${rep}.log
    [ -s "$out" ] && grep -q "test result: ok" "$out" && continue
    env $COMMON $vars SEED=$rep nice -n 19 cargo test -p consensus-core --lib test_fissure_attack_asr_dynamic -- --nocapture > "$out" 2>&1
    echo "$(date +%H:%M:%S) $name rep$rep exit=$?" >> $R/mlaw.log
  done
done
echo "$(date +%H:%M:%S) MLAW DONE" >> $R/mlaw.log
