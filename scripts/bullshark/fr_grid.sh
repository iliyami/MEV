#!/bin/bash
# Bullshark transaction-level front-running grid, n=13, 5 runs per arm.
# Paths: REPO is this repository (found from the script's location), OUT the directory for run
# logs (required), PY the Python of the harness venv (code/bullshark-flashboys/our_harness/requirements.txt).
REPO=${REPO:-$(cd "$(dirname "$0")/../.." && pwd)}
: "${OUT:?set OUT to an output directory}"
PY=${PY:-python3}
export PATH=$HOME/.cargo/bin:$PATH CARGO_BUILD_JOBS=16 FR_REACT=1 FR_VICTIM_RATE=10
cd $REPO/code/bullshark-flashboys/benchmark
mkdir -p $OUT/fr_runs
run() { # name attack extra-env
  echo "$(date +%H:%M:%S) start $1" >> $OUT/fr_runs/grid.log
  env $3 nice -n 5 $PY ../our_harness/run_and_score.py --attack $2 --fa 4 --nodes 13 --runs 5 --keep $OUT/fr_runs/$1 > $OUT/fr_runs/$1.out 2>&1
  echo "$(date +%H:%M:%S) done $1" >> $OUT/fr_runs/grid.log
}
run none 10 "FR_GRIND=0"
run fissure 1 "FR_GRIND=0"
run none_grind 10 "FR_GRIND=1"
run fissure_grind 1 "FR_GRIND=1"
echo "$(date +%H:%M:%S) GRID DONE" >> $OUT/fr_runs/grid.log
