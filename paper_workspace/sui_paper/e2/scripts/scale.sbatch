#!/bin/bash
#SBATCH --job-name=sui-tie-scale
#SBATCH --partition=hbm-1tb-long-96core
#SBATCH --nodes=1
#SBATCH --cpus-per-task=96
#SBATCH --time=1-00:00:00
#SBATCH --output=logs/scale-%j.out
cd "${WORKDIR:?set WORKDIR to the run directory}"
TRIALS=${1:-60}; PAR=${2:-12}
while read mode net far fix fee n geo; do for seed in 1 2 3; do echo "$mode $net $far $fix $seed $TRIALS $fee $n $geo"; done; done < arms_scale.txt \
  | xargs -P $PAR -L 1 ./run_one_scale.sh
echo "all scale done $(date)"
grep -h TIE_SUMMARY "$WORKDIR"/results_scale/*.log | sort
