#!/bin/bash
# E1 (reviewer W3): vote-withholding at k=f and k=f+1 against injected network jitter.
# Bullshark, n=13, fissure f_a=4 layout (as cens.sh); CENSOR=k validators withhold votes on the victim.
# Jitter: tc netem on the loopback interface (all validators run on this host), delay D ms +- D ms.
# This is a network condition on the host, not a code change. Usage:
#   e1_delay.sh <outdir> <runs> "<levels>" "<arms>"     arms: c0 (control), c4 (CENSOR=4), c5 (CENSOR=5)
OUT=$1; RUNS=$2; LEVELS=$3; ARMS=$4
export PATH=$HOME/.cargo/bin:$PATH CARGO_BUILD_JOBS=16
unset FR_REACT FR_VICTIM_RATE FR_GRIND FR_SPRAY FR_VICTIM_SPRAY MULTI_VICTIM BRIBED COLLUDE INDEPENDENT RIVAL_GROUPS SILENT_EXCEPT_LEADER CENSOR
cd /mnt/data/flashboys/benchmark
mkdir -p $OUT
cleanup() { sudo tc qdisc del dev lo root 2>/dev/null; }
trap cleanup EXIT
for D in $LEVELS; do
  cleanup
  if [ "$D" != "0" ]; then sudo tc qdisc add dev lo root netem delay ${D}ms ${D}ms; fi
  echo "$(date +%H:%M:%S) jitter $D: $(tc qdisc show dev lo | head -1)" >> $OUT/e1.log
  for A in $ARMS; do
    case $A in c0) E="X=1";; c4) E="CENSOR=4";; c5) E="CENSOR=5";; esac
    echo "$(date +%H:%M:%S) start d$D $A" >> $OUT/e1.log
    env $E nice -n 5 /mnt/data/venv/bin/python ../our_harness/run_and_score.py --attack 1 --fa 4 --nodes 13 --runs $RUNS --keep $OUT/d${D}_$A > $OUT/d${D}_$A.out 2>&1
  done
done
cleanup
echo "$(date +%H:%M:%S) E1 DONE" >> $OUT/e1.log
