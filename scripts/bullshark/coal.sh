#!/bin/bash
# Coalition / bribery / fraction cells re-run with per-run logs kept (same settings as our earlier coalition runs), 16 runs per arm.
# Paths: REPO is this repository (found from the script's location), OUT the directory for run
# logs (required), PY the Python of the harness venv (code/bullshark-flashboys/our_harness/requirements.txt).
REPO=${REPO:-$(cd "$(dirname "$0")/../.." && pwd)}
: "${OUT:?set OUT to an output directory}"
PY=${PY:-python3}
export PATH=$HOME/.cargo/bin:$PATH CARGO_BUILD_JOBS=16
unset FR_REACT FR_VICTIM_RATE FR_GRIND FR_SPRAY FR_VICTIM_SPRAY MULTI_VICTIM BRIBED COLLUDE INDEPENDENT RIVAL_GROUPS SILENT_EXCEPT_LEADER
cd $REPO/code/bullshark-flashboys/benchmark
R=$OUT/coal; mkdir -p $R
for spec in "base1 10 1 X=1" "base4 10 4 X=1" "base6 10 6 X=1" "solo 1 1 X=1" "bribe 1 1 BRIBED=3" "f4 1 4 X=1" "f6 1 6 X=1" "f6ind 1 6 INDEPENDENT=1" "f6rival 1 6 RIVAL_GROUPS=2"; do
  set -- $spec
  echo "$(date +%H:%M:%S) start $1" >> $R/coal.log
  env $4 nice -n 5 $PY ../our_harness/run_and_score.py --attack $2 --fa $3 --nodes 13 --runs 16 --keep $R/$1 > $R/$1.out 2>&1
done
echo "$(date +%H:%M:%S) COAL DONE" >> $R/coal.log
