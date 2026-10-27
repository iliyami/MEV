#!/bin/bash
# Victim-also-sprays control: both attacker and victim submit to every validator. 10 runs per arm.
# (Our run waited here for the previous campaign on the same machine to finish.)
# Paths: REPO is this repository (found from the script's location), OUT the directory for run
# logs (required), PY the Python of the harness venv (code/bullshark-flashboys/our_harness/requirements.txt).
REPO=${REPO:-$(cd "$(dirname "$0")/../.." && pwd)}
: "${OUT:?set OUT to an output directory}"
PY=${PY:-python3}
export PATH=$HOME/.cargo/bin:$PATH CARGO_BUILD_JOBS=16 FR_REACT=1 FR_VICTIM_RATE=10 FR_SPRAY=1 FR_VICTIM_SPRAY=1 FR_GRIND=0
cd $REPO/code/bullshark-flashboys/benchmark
mkdir -p $OUT/fr_runs
for spec in "none_vspray 10" "fissure_vspray 1"; do
  set -- $spec
  echo "$(date +%H:%M:%S) start $1" >> $OUT/fr_runs/grid.log
  nice -n 5 $PY ../our_harness/run_and_score.py --attack $2 --fa 4 --nodes 13 --runs 10 --keep $OUT/fr_runs/$1 > $OUT/fr_runs/$1.out 2>&1
done
echo "$(date +%H:%M:%S) VSPRAY DONE" >> $OUT/fr_runs/grid.log
