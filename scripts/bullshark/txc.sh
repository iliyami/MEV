#!/bin/bash
# Transaction-level corruption contrast on Bullshark: copy sent to all (FR_SPRAY=1), attacker reacts to
# batch gossip (FR_REACT=1). One fissure attacker + 3 bribed (BRIBED=3) vs 4 Byzantine, with matched
# no-attack controls (attack 10 = monitor only) and the lone attacker. Arms interleaved per repetition.
# Paths: REPO is this repository (found from the script's location), OUT the directory for run
# logs (required), PY the Python of the harness venv (code/bullshark-flashboys/our_harness/requirements.txt).
REPO=${REPO:-$(cd "$(dirname "$0")/../.." && pwd)}
: "${OUT:?set OUT to an output directory}"
PY=${PY:-python3}
export PATH=$HOME/.cargo/bin:$PATH CARGO_BUILD_JOBS=16 FR_REACT=1 FR_VICTIM_RATE=10 FR_GRIND=0 FR_SPRAY=1
cd $REPO/code/bullshark-flashboys/benchmark
mkdir -p $OUT/txc
for rep in $(seq 1 16); do
  for spec in "tbase4 10 4 X=1" "tf4 1 4 X=1" "tbase1 10 1 X=1" "tsolo 1 1 X=1" "tbribe3 1 1 BRIBED=3"; do
    set -- $spec
    echo "$(date +%H:%M:%S) $1 rep$rep" >> $OUT/txc/txc.log
    env $4 nice -n 5 $PY ../our_harness/run_and_score.py --attack $2 --fa $3 --nodes 13 --runs 1 --keep $OUT/txc/$1/r$rep > $OUT/txc/$1_r$rep.out 2>&1
  done
done
echo "$(date +%H:%M:%S) TXC DONE" >> $OUT/txc/txc.log
