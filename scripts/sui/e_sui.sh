#!/bin/bash
# Sui phase of the reviewer-response experiments, Sui v1.74 consensus-core tests, CloudLab clnode132.
#  E2 (W5): silent-except-leader value rows and SLW realized MEV with the identity tiebreak removed
#           (FIX_TIEBREAK=1 on every node: a labelled fix arm), same settings as v2_290_solo / v2_290.
#  E5 (W5): strict silence (SEL_STRICT=1, attacker-only) at n=49 and asymmetric latency, with controls.
#  E7 (W1): refusal-model predictions: refusers {0,5} vs {0,1}; stake-weighted leaders, base vs {0,1}.
# Waits for the Bullshark E3 campaign so timing-sensitive runs never overlap. 5 reps per arm.
set -u
ROOT=/mnt/data/sui_src; SUI=$ROOT/sui; O=/mnt/data/esui; mkdir -p $O/e2 $O/e5 $O/e7
until grep -q "E3 DONE" /mnt/data/e3/e3.log 2>/dev/null; do sleep 60; done
export PATH=$HOME/.cargo/bin:$PATH CARGO_BUILD_JOBS=16 RUST_TEST_THREADS=1
echo "$(date +%H:%M:%S) build start" >> $O/esui.log
cd $SUI && nice -n 10 cargo test -p consensus-core --lib --no-run > $O/build.log 2>&1
BIN=$(ls -t $SUI/target/debug/deps/consensus_core-* | grep -v '\.d$' | head -1)
echo "$(date +%H:%M:%S) build done exit=$? bin=$BIN" >> $O/esui.log
[ -x "$BIN" ] || { echo "NO BINARY" >> $O/esui.log; exit 1; }

# E2: value models, one silent attacker (v2_290_solo settings) and SLW (v2_290 settings), FixTiebreak on all nodes.
cd $ROOT
export SUI_TEST_BIN=$BIN V2_MIN_COMMITS=290 V2_COLLECTION_DURATION=300 SEL_REAL_SCHEDULE=1 FIX_TIEBREAK=1
V2_ATTACKERS=0 V2_ATTACKER_RATIO=0.08 nice -n 10 python3 -m scripts.v2.p_valuemodel --reps 5 --out-csv $O/e2/valuemodel_fix.csv --out-summary $O/e2/valuemodel_fix.json > $O/e2/valuemodel_fix.out 2>&1
echo "$(date +%H:%M:%S) e2 valuemodel done" >> $O/esui.log
nice -n 10 python3 -m scripts.v2.p_sui_withholding --reps 5 --out-csv $O/e2/withholding_fix.csv --out-summary $O/e2/withholding_fix.json > $O/e2/withholding_fix.out 2>&1
echo "$(date +%H:%M:%S) e2 withholding done" >> $O/esui.log
unset SUI_TEST_BIN V2_MIN_COMMITS V2_COLLECTION_DURATION FIX_TIEBREAK

# E5: strict silence, sel290 settings.
COMMON="ATTACKER_RATIO=0.08 VICTIM_RATIO=0.231 GC_DEPTH=10 COLLECTION_DURATION=300 MIN_COMMITS=290 SEL_REAL_SCHEDULE=1 RUST_LOG=error"
for rep in 1 2 3 4 5; do
 for st in "n49:NUM_NODES=49" "asym:NUM_NODES=13 LATENCY_MS=100 ASYMMETRIC_LATENCY=1"; do
  tag=${st%%:*}; svar=${st#*:}
  for arm in base sel; do
   if [ $arm = base ]; then t=test_withhold_baseline_asr_dynamic; av="X=1"; else t=test_withhold_silent_attack_asr_dynamic; av="SILENT_EXCEPT_LEADER=1 SEL_STRICT=1"; fi
   env $COMMON $svar $av SEED=$rep nice -n 10 $BIN $t --nocapture > $O/e5/${tag}_${arm}_rep$rep.log 2>&1
   echo "$(date +%H:%M:%S) e5 $tag $arm rep$rep exit=$?" >> $O/esui.log
  done
 done
done

# E7: refusal model, run_mlaw.sh settings.
COMMON="NUM_NODES=13 VICTIM_RATIO=0.077 GC_DEPTH=10 COLLECTION_DURATION=60 MIN_COMMITS=400 RUST_LOG=error"
ARMS=("base:NO_ATTACK=1 ATTACKER_RATIO=0.077" "b2:ATTACKER_RATIO=0.077 FISSURE_BRIBED_NODES=1" "b2at5:ATTACKER_RATIO=0.077 FISSURE_BRIBED_NODES=5"
      "sbase:NO_ATTACK=1 ATTACKER_RATIO=0.077 STAKE_BASED_LEADER=1" "sb2:ATTACKER_RATIO=0.077 FISSURE_BRIBED_NODES=1 STAKE_BASED_LEADER=1")
for rep in 1 2 3 4 5; do
 for a in "${ARMS[@]}"; do
  name=${a%%:*}; vars=${a#*:}
  env $COMMON $vars SEED=$rep nice -n 10 $BIN test_fissure_attack_asr_dynamic --nocapture > $O/e7/${name}_rep$rep.log 2>&1
  echo "$(date +%H:%M:%S) e7 $name rep$rep exit=$?" >> $O/esui.log
 done
done
echo "$(date +%H:%M:%S) ESUI DONE" >> $O/esui.log
