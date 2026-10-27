#!/bin/bash
# Deployment family on a value-positive primitive: fissure on Bullshark, one victim, attackers at
# alpha ~ 0.31 (n=7 fa=2, n=13 fa=4, n=25 fa=8), plus WAN (uniform 50 ms one-way netem on lo) at n=13.
# Identical settings to coal2.sh otherwise; matched no-attack control per arm; arms interleaved per rep.
# Paths: REPO is this repository (found from the script's location), OUT the directory for run
# logs (required), PY the Python of the harness venv (code/bullshark-flashboys/our_harness/requirements.txt).
REPO=${REPO:-$(cd "$(dirname "$0")/../.." && pwd)}
: "${OUT:?set OUT to an output directory}"
PY=${PY:-python3}
export PATH=$HOME/.cargo/bin:$PATH CARGO_BUILD_JOBS=16
unset FR_REACT FR_VICTIM_RATE FR_GRIND FR_SPRAY FR_VICTIM_SPRAY MULTI_VICTIM BRIBED COLLUDE INDEPENDENT RIVAL_GROUPS SILENT_EXCEPT_LEADER CENSOR
cd $REPO/code/bullshark-flashboys/benchmark
R=$OUT/dsweep; mkdir -p $R
netem_off() { sudo tc qdisc del dev lo root 2>/dev/null; }
trap netem_off EXIT
netem_off
for rep in $(seq 1 10); do
  for spec in "b13 10 4 13 lan" "f13 1 4 13 lan" "b7 10 2 7 lan" "f7 1 2 7 lan" "b25 10 8 25 lan" "f25 1 8 25 lan" "bwan 10 4 13 wan" "fwan 1 4 13 wan"; do
    set -- $spec
    if [ "$5" = wan ]; then sudo tc qdisc add dev lo root netem delay 50ms limit 1000000; else netem_off; fi
    echo "$(date +%H:%M:%S) $1 rep$rep" >> $R/dsweep.log
    nice -n 5 $PY ../our_harness/run_and_score.py --attack $2 --fa $3 --nodes $4 --runs 1 --keep $R/$1/r$rep > $R/$1_r$rep.out 2>&1
    netem_off
  done
done
echo "$(date +%H:%M:%S) DSWEEP DONE" >> $R/dsweep.log
