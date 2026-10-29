#!/bin/bash
# Mainnet-scale variant of run_one.sh. Adds committee size (TIE_N) and the geographic latency
# matrix (TIE_GEO). usage: run_one_scale.sh MODE NET FAR FIX SEED TRIALS FEE N GEO
source "${WORKDIR:?set WORKDIR to the run directory}/env.sh"
BIN=$(ls -t $W/sui/target/simulator/deps/ordering_tie_tests-* | grep -v "\.d$" | head -1)
OUT=$W/results_scale/$1-$2-far$3-fix$4-fee${7:-1}-n${8:-13}-geo${9:-0}-seed$5.log
mkdir -p $W/results_scale
export TIE_MODE=$1 TIE_NET=$2 TIE_FAR_MS=$3 SUI_SEEDED_TIEBREAK=$4 MSIM_TEST_SEED=$5 TIE_TRIALS=$6 TIE_FEE_MULT=${7:-1}
export TIE_N=${8:-13} TIE_GEO=${9:-0} TIE_REGIONS=${TIE_REGIONS:-5}
export RUST_TEST_THREADS=1 MSIM_WATCHDOG_TIMEOUT_MS=1200000 RUST_LOG=error
cd $W/sui/crates/sui-e2e-tests
start=$(date +%s)
nice -n 10 timeout 40000 $BIN test::test_equal_fee_race --exact --nocapture > $OUT 2>&1
echo "EXIT rc=$? secs=$(( $(date +%s) - start ))" >> $OUT
grep TIE_SUMMARY $OUT
