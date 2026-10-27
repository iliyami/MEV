#!/bin/bash
# Silent-except-leader re-measured with long runs (290 commits, before the first reputation update at 300), real leader schedule, 1 attacker, 5 reps.
# Paths: REPO is this repository (found from the script's location); OUT the directory for run logs (required).
REPO=${REPO:-$(cd "$(dirname "$0")/../.." && pwd)}
: "${OUT:?set OUT to an output directory}"
cd $REPO/code/sui
OUT=$OUT/sel290; mkdir -p $OUT
SKEW="5,1,1,1,1,1,1,1,1,1,1,1,1"
COMMON="ATTACKER_RATIO=0.08 VICTIM_RATIO=0.231 GC_DEPTH=10 COLLECTION_DURATION=300 MIN_COMMITS=290 SEL_REAL_SCHEDULE=1 RUST_LOG=error CARGO_BUILD_JOBS=2 RUST_TEST_THREADS=1"
SETS=(
 "rr:NUM_NODES=13"
 "stake:NUM_NODES=13 STAKE_BASED_LEADER=1 STAKE_PROFILE=$SKEW"
 "skew:NUM_NODES=13 STAKE_PROFILE=$SKEW"
 "rep:NUM_NODES=13 SCHEDULE_INTERVAL=50"
 "wan:NUM_NODES=13 LATENCY_MS=100"
 "asym:NUM_NODES=13 LATENCY_MS=100 ASYMMETRIC_LATENCY=1"
 "n25:NUM_NODES=25"
 "n49:NUM_NODES=49"
)
for rep in 1 2 3 4 5; do
 for st in "${SETS[@]}"; do
  tag=${st%%:*}; svar=${st#*:}
  for arm in base sel; do
    if [ $arm = base ]; then test=test_withhold_baseline_asr_dynamic; avar="X=1"; else test=test_withhold_silent_attack_asr_dynamic; avar="SILENT_EXCEPT_LEADER=1"; fi
    out=$OUT/${tag}_${arm}_rep$rep.log
    [ -s "$out" ] && grep -q "test result: ok" "$out" && continue
    env $COMMON $svar $avar SEED=$rep nice -n 19 cargo test -p consensus-core --lib $test -- --nocapture > "$out" 2>&1
    echo "$(date +%H:%M:%S) $tag $arm rep$rep exit=$? $(grep -o 'FINAL_ALL_PAIRS_ASR: [0-9.]*' $out | tail -1)" >> $OUT/run.log
  done
 done
done
# P3: no-attack arms under each tiebreak rule, same layout (attacker 0, victims 10-12), scored on same-round.
for rep in 1 2 3 4 5; do
 for st in "digest:FIX_TIEBREAK=1" "seeded:SEEDED_TIEBREAK=1" "orderfair:ORDER_FAIR_TIEBREAK=1"; do
  tag=${st%%:*}; svar=${st#*:}
  out=$OUT/p3_${tag}_base_rep$rep.log
  [ -s "$out" ] && grep -q "test result: ok" "$out" && continue
  env $COMMON NUM_NODES=13 $svar SEED=$rep nice -n 19 cargo test -p consensus-core --lib test_withhold_baseline_asr_dynamic -- --nocapture > "$out" 2>&1
  echo "$(date +%H:%M:%S) p3 $tag rep$rep exit=$? $(grep -o 'FINAL_ALL_PAIRS_ASR: [0-9.]*' $out | tail -1)" >> $OUT/run.log
 done
done
echo "$(date +%H:%M:%S) SEL290 DONE" >> $OUT/run.log
