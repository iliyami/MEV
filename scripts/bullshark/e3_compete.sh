#!/bin/bash
# E3 (reviewer W2): competition within f. Four fissure attackers, each refusing a DIFFERENT victim
# (INDEPENDENT=1), against a no-attack control with the same four designated attackers; 40 runs per arm,
# same settings as coal.sh/coal2.sh. Colluding at four is A6.2 (coal+coal2 f4 vs base4).
export PATH=$HOME/.cargo/bin:$PATH CARGO_BUILD_JOBS=16
unset FR_REACT FR_VICTIM_RATE FR_GRIND FR_SPRAY FR_VICTIM_SPRAY MULTI_VICTIM BRIBED COLLUDE INDEPENDENT RIVAL_GROUPS SILENT_EXCEPT_LEADER CENSOR
sudo tc qdisc del dev lo root 2>/dev/null
cd /mnt/data/flashboys/benchmark
PY=/mnt/data/venv/bin/python
R=/mnt/data/e3; mkdir -p $R
for spec in "base4e 10 4 X=1 40" "f4ind 1 4 INDEPENDENT=1 40"; do
  set -- $spec
  echo "$(date +%H:%M:%S) start $1" >> $R/e3.log
  env $4 nice -n 5 $PY ../our_harness/run_and_score.py --attack $2 --fa $3 --nodes 13 --runs $5 --keep $R/$1 > $R/$1.out 2>&1
done
echo "$(date +%H:%M:%S) E3 DONE" >> $R/e3.log
