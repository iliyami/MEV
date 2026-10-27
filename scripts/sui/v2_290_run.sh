#!/bin/bash
# Remaining Sui rows re-run long (400 commits): timestamp (A2.6), value models (T2.4/T3), SLW (A2.5), LVW (A2.7).
# Paths: REPO is this repository (found from the script's location); OUT the directory for run logs (required).
REPO=${REPO:-$(cd "$(dirname "$0")/../.." && pwd)}
: "${OUT:?set OUT to an output directory}"
cd $REPO
export V2_MIN_COMMITS=290 V2_COLLECTION_DURATION=300 SEL_REAL_SCHEDULE=1 CARGO_BUILD_JOBS=2 RUST_TEST_THREADS=1
O=$OUT/v2_290; mkdir -p $O
nice -n 19 python3 -m scripts.v2.p_sui_timestamp --reps 5 --out-csv $O/timestamp.csv --out-summary $O/timestamp.json > $O/timestamp.out 2>&1
nice -n 19 python3 -m scripts.v2.p_valuemodel --reps 5 --out-csv $O/valuemodel.csv --out-summary $O/valuemodel.json > $O/valuemodel.out 2>&1
nice -n 19 python3 -m scripts.v2.p_sui_withholding --reps 5 --out-csv $O/withholding.csv --out-summary $O/withholding.json > $O/withholding.out 2>&1
nice -n 19 python3 -m scripts.v2.p3_sui_collusion --reps 5 --out-csv $O/collusion.csv --out-summary $O/collusion.json > $O/collusion.out 2>&1
echo "$(date +%H:%M:%S) V2290 DONE" >> $O/run.log
