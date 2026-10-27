#!/bin/bash
# A1.4 / A2.8: four validators withhold votes on the victim (CENSOR=4), fissure f_a=4 layout, 16 runs; control = $OUT/coal/f4.
# Paths: REPO is this repository (found from the script's location), OUT the directory for run
# logs (required), PY the Python of the harness venv (code/bullshark-flashboys/our_harness/requirements.txt).
REPO=${REPO:-$(cd "$(dirname "$0")/../.." && pwd)}
: "${OUT:?set OUT to an output directory}"
PY=${PY:-python3}
export PATH=$HOME/.cargo/bin:$PATH CARGO_BUILD_JOBS=16
unset FR_REACT FR_VICTIM_RATE FR_GRIND FR_SPRAY FR_VICTIM_SPRAY MULTI_VICTIM BRIBED COLLUDE INDEPENDENT RIVAL_GROUPS SILENT_EXCEPT_LEADER
cd $REPO/code/bullshark-flashboys/benchmark
R=$OUT/coal; mkdir -p $R; echo "$(date +%H:%M:%S) start cens4" >> $R/coal.log
CENSOR=4 nice -n 5 $PY ../our_harness/run_and_score.py --attack 1 --fa 4 --nodes 13 --runs 16 --keep $R/cens4 > $R/cens4.out 2>&1
echo "$(date +%H:%M:%S) CENS DONE" >> $R/coal.log
