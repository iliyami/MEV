#!/bin/bash
# Figure 4 real-Bullshark column: n=13, f_a=4, 5 runs per attack, all-pairs (M1) scored per run.
# Paths: REPO is this repository (found from the script's location), OUT the directory for run
# logs (required), PY the Python of the harness venv (code/bullshark-flashboys/our_harness/requirements.txt).
REPO=${REPO:-$(cd "$(dirname "$0")/../.." && pwd)}
: "${OUT:?set OUT to an output directory}"
PY=${PY:-python3}
export PATH=$HOME/.cargo/bin:$PATH CARGO_BUILD_JOBS=16
unset FR_REACT FR_VICTIM_RATE FR_GRIND FR_SPRAY MULTI_VICTIM BRIBED COLLUDE
cd $REPO/code/bullshark-flashboys/benchmark
mkdir -p $OUT/fig4
for a in 10 1 3 2; do
  echo "$(date +%H:%M:%S) start $a" >> $OUT/fig4/fig4.log
  nice -n 5 $PY ../our_harness/run_and_score.py --attack $a --fa 4 --nodes 13 --runs 5 --keep $OUT/fig4 > $OUT/fig4/attack$a.out 2>&1
done
echo "$(date +%H:%M:%S) FIG4 DONE" >> $OUT/fig4/fig4.log
