#!/bin/bash
# Reproduction check: the n=13 arms of dsweep.sh (b13 no attack, f13 fissure; f_a=4, LAN, 10 reps
# interleaved), run from a fresh copy of this repository with a fresh venv and a fresh cargo build.
# Paths: REPO is this repository (found from the script's location), OUT the directory for run
# logs (required).
set -u
REPO=${REPO:-$(cd "$(dirname "$0")/../.." && pwd)}
: "${OUT:?set OUT to an output directory}"
export PATH=$HOME/.cargo/bin:$PATH CARGO_BUILD_JOBS=16
unset FR_REACT FR_VICTIM_RATE FR_GRIND FR_SPRAY FR_VICTIM_SPRAY MULTI_VICTIM BRIBED COLLUDE INDEPENDENT RIVAL_GROUPS SILENT_EXCEPT_LEADER CENSOR
T=$REPO/code/bullshark-flashboys
R=$OUT/freshrun; mkdir -p $R
echo "$(date +%H:%M:%S) START" >> $R/fresh.log
python3 -m venv $OUT/venv >> $R/setup.out 2>&1
$OUT/venv/bin/pip install -q -r $T/our_harness/requirements.txt >> $R/setup.out 2>&1 || { echo "$(date +%H:%M:%S) PIP FAILED" >> $R/fresh.log; exit 1; }
cd $T && nice -n 5 cargo build --quiet --release --features benchmark >> $R/setup.out 2>&1 || { echo "$(date +%H:%M:%S) BUILD FAILED" >> $R/fresh.log; exit 1; }
echo "$(date +%H:%M:%S) BUILT" >> $R/fresh.log
cd $T/benchmark
PY=$OUT/venv/bin/python
for rep in $(seq 1 10); do
  for spec in "b13 10" "f13 1"; do
    set -- $spec
    echo "$(date +%H:%M:%S) $1 rep$rep" >> $R/fresh.log
    nice -n 5 $PY ../our_harness/run_and_score.py --attack $2 --fa 4 --nodes 13 --runs 1 --keep $R/$1/r$rep > $R/$1_r$rep.out 2>&1
  done
done
echo "$(date +%H:%M:%S) FRESH DONE" >> $R/fresh.log
