#!/bin/bash
# P1 extension: 15 more runs per arm (to 20 with the first 5), same settings as the A1 grid.
# (Our run waited here for the previous campaign on the same machine to finish.)
# Paths: REPO is this repository (found from the script's location), OUT the directory for run
# logs (required), PY the Python of the harness venv (code/bullshark-flashboys/our_harness/requirements.txt).
REPO=${REPO:-$(cd "$(dirname "$0")/../.." && pwd)}
: "${OUT:?set OUT to an output directory}"
PY=${PY:-python3}
export PATH=$HOME/.cargo/bin:$PATH CARGO_BUILD_JOBS=16 FR_REACT=1 FR_VICTIM_RATE=10
cd $REPO/code/bullshark-flashboys/benchmark
mkdir -p $OUT/fr_runs
run() {
  echo "$(date +%H:%M:%S) start $1" >> $OUT/fr_runs/grid.log
  env $3 nice -n 5 $PY ../our_harness/run_and_score.py --attack $2 --fa 4 --nodes 13 --runs 15 --keep $OUT/fr_runs/$1 > $OUT/fr_runs/$1.out 2>&1
  echo "$(date +%H:%M:%S) done $1" >> $OUT/fr_runs/grid.log
}
run none_x 10 "FR_GRIND=0 FR_SPRAY=0"
run fissure_x 1 "FR_GRIND=0 FR_SPRAY=0"
run none_spray_x 10 "FR_GRIND=0 FR_SPRAY=1"
run fissure_spray_x 1 "FR_GRIND=0 FR_SPRAY=1"
echo "$(date +%H:%M:%S) P1X DONE" >> $OUT/fr_runs/grid.log
