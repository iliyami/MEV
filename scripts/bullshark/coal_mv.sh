#!/bin/bash
# No-attack control for the three-victim cell (T1.2): designated-but-unarmed, f_a=4, MULTI_VICTIM=3, 16 runs.
# Paths: REPO is this repository (found from the script's location), OUT the directory for run
# logs (required), PY the Python of the harness venv (code/bullshark-flashboys/our_harness/requirements.txt).
REPO=${REPO:-$(cd "$(dirname "$0")/../.." && pwd)}
: "${OUT:?set OUT to an output directory}"
PY=${PY:-python3}
export PATH=$HOME/.cargo/bin:$PATH CARGO_BUILD_JOBS=16
unset FR_REACT FR_VICTIM_RATE FR_GRIND FR_SPRAY FR_VICTIM_SPRAY BRIBED COLLUDE INDEPENDENT RIVAL_GROUPS SILENT_EXCEPT_LEADER
cd $REPO/code/bullshark-flashboys/benchmark
R=$OUT/coal; mkdir -p $R; echo "$(date +%H:%M:%S) start base4mv" >> $R/coal.log
MULTI_VICTIM=3 nice -n 5 $PY ../our_harness/run_and_score.py --attack 10 --fa 4 --nodes 13 --runs 16 --keep $R/base4mv > $R/base4mv.out 2>&1
echo "$(date +%H:%M:%S) MV DONE" >> $R/coal.log
