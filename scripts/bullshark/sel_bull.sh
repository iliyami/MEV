#!/bin/bash
# Bullshark silent-except-leader, one attacker (position 0), 5 runs per arm; control = SILENT_DRYRUN.
# (Our run waited here for the previous campaign on the same machine to finish.)
# Paths: REPO is this repository (found from the script's location), OUT the directory for run
# logs (required), PY the Python of the harness venv (code/bullshark-flashboys/our_harness/requirements.txt).
REPO=${REPO:-$(cd "$(dirname "$0")/../.." && pwd)}
: "${OUT:?set OUT to an output directory}"
PY=${PY:-python3}
export PATH=$HOME/.cargo/bin:$PATH CARGO_BUILD_JOBS=16
unset FR_REACT FR_VICTIM_RATE FR_GRIND FR_SPRAY FR_VICTIM_SPRAY MULTI_VICTIM BRIBED COLLUDE
cd $REPO/code/bullshark-flashboys/benchmark
mkdir -p $OUT/sel_bull
for arm in control silent; do
  echo "$(date +%H:%M:%S) start $arm" >> $OUT/sel_bull/sel.log
  if [ $arm = control ]; then X="SILENT_DRYRUN=1"; else X="SILENT_DRYRUN=0"; fi
  env SILENT_EXCEPT_LEADER=1 SILENT_NODES=0 $X nice -n 5 $PY ../our_harness/run_and_score.py --attack 10 --fa 4 --nodes 13 --runs 5 --keep $OUT/sel_bull/$arm > $OUT/sel_bull/$arm.out 2>&1
  for d in $OUT/sel_bull/$arm/baseline_f4_n13/run*; do
    echo "$arm $(basename $d) $($PY ../our_harness/measure.py $d --silent-roles 2>&1 | tr "\n" " " | cut -c1-400)" >> $OUT/sel_bull/scores.txt
  done
done
echo "$(date +%H:%M:%S) SELBULL DONE" >> $OUT/sel_bull/sel.log
