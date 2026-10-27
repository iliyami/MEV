#!/bin/bash
# Refusal law at a second committee size: fissure on Bullshark at n=25 (f=8), one victim,
# fa = 1, 2, 4, 6 attackers (fa=8 and 10 no-attack reps already in $OUT/dsweep/{f25,b25}),
# plus 10 more no-attack reps. Same settings as dsweep.sh LAN arms; arms interleaved per rep.
# Paths: REPO is this repository (found from the script's location), OUT the directory for run
# logs (required), PY the Python of the harness venv (code/bullshark-flashboys/our_harness/requirements.txt).
REPO=${REPO:-$(cd "$(dirname "$0")/../.." && pwd)}
: "${OUT:?set OUT to an output directory}"
PY=${PY:-python3}
export PATH=$HOME/.cargo/bin:$PATH CARGO_BUILD_JOBS=16
unset FR_REACT FR_VICTIM_RATE FR_GRIND FR_SPRAY FR_VICTIM_SPRAY MULTI_VICTIM BRIBED COLLUDE INDEPENDENT RIVAL_GROUPS SILENT_EXCEPT_LEADER CENSOR
cd $REPO/code/bullshark-flashboys/benchmark
R=$OUT/lsweep; mkdir -p $R
sudo tc qdisc del dev lo root 2>/dev/null
for rep in $(seq 1 10); do
  for spec in "f25a1 1 1 25" "f25a2 1 2 25" "f25a4 1 4 25" "f25a6 1 6 25" "b25x 10 8 25"; do
    set -- $spec
    echo "$(date +%H:%M:%S) $1 rep$rep" >> $R/lsweep.log
    nice -n 5 $PY ../our_harness/run_and_score.py --attack $2 --fa $3 --nodes $4 --runs 1 --keep $R/$1/r$rep > $R/$1_r$rep.out 2>&1
  done
done
echo "$(date +%H:%M:%S) LSWEEP DONE" >> $R/lsweep.log
