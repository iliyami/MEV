#!/bin/bash
# E1 (reviewer W3), host-load knob: vote-withholding at k=f / k=f+1 with the whole local benchmark
# confined to C CPU cores (taskset; every validator, worker and client inherits the mask).
# A host condition, not a code change. Same layout as cens.sh (fissure f_a=4, n=13).
#   e1_cpu.sh <outdir> <runs> "<core counts>" "<arms>"     arms: c0 (control), c4 (CENSOR=4), c5 (CENSOR=5)
OUT=$1; RUNS=$2; CORES=$3; ARMS=$4
export PATH=$HOME/.cargo/bin:$PATH CARGO_BUILD_JOBS=16
unset FR_REACT FR_VICTIM_RATE FR_GRIND FR_SPRAY FR_VICTIM_SPRAY MULTI_VICTIM BRIBED COLLUDE INDEPENDENT RIVAL_GROUPS SILENT_EXCEPT_LEADER CENSOR
cd /mnt/data/flashboys/benchmark
mkdir -p $OUT
sudo tc qdisc del dev lo root 2>/dev/null
tmux kill-server 2>/dev/null
for C in $CORES; do
  MASK="0-$((C-1))"
  for A in $ARMS; do
    case $A in c0) E="X=1";; c4) E="CENSOR=4";; c5) E="CENSOR=5";; esac
    echo "$(date +%H:%M:%S) start cpu$C $A (mask $MASK)" >> $OUT/e1.log
    tmux kill-server 2>/dev/null
    env $E nice -n 5 taskset -c $MASK /mnt/data/venv/bin/python ../our_harness/run_and_score.py --attack 1 --fa 4 --nodes 13 --runs $RUNS --keep $OUT/cpu${C}_$A > $OUT/cpu${C}_$A.out 2>&1
  done
done
tmux kill-server 2>/dev/null
echo "$(date +%H:%M:%S) E1 DONE" >> $OUT/e1.log
