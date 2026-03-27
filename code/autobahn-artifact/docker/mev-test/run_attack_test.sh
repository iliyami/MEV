#!/bin/bash
set -e

# Autobahn Multi-Node Attack Orchestrator
# Ported from run_fissure_attack.py for standardized Docker execution

# Default values
ATTACK_MODE=${ATTACK_MODE:-"fissure"}
NUM_NODES=${NUM_NODES:-"13"}
DURATION=${DURATION:-"60"}
ATTACKER_ID=${ATTACKER_ID:-"0"}
VICTIM_ID=${VICTIM_ID:-"1"}
EXCLUSION_PROBABILITY=${EXCLUSION_PROBABILITY:-"1.0"}
VICTIM_DELAY_MS=${VICTIM_DELAY_MS:-"50"}
SLUGGISH_TIMEOUT_MULTIPLIER=${SLUGGISH_TIMEOUT_MULTIPLIER:-"5.0"}
AUTOBAHN_K=${AUTOBAHN_K:-"4"}

echo "--- Autobahn Attack Test Configuration ---"
echo "Mode: $ATTACK_MODE"
echo "Nodes: $NUM_NODES"
echo "Attacker: $ATTACKER_ID"
echo "Victim: $VICTIM_ID"
echo "Duration: $DURATION s"
echo "K: $AUTOBAHN_K"
echo "------------------------------------------"

# Ensure results directory exists
mkdir -p /app/results

# Cleanup previous runs
rm -rf .db-* .*.json results/*.log asr_result.txt
mkdir -p logs

# Path to binaries (built in Dockerfile)
NODE_BIN="./target/release/node"
CLIENT_BIN="./target/release/benchmark_client"

# Generate keys
echo "Generating keys..."
for i in $(seq 0 $(($NUM_NODES - 1))); do
    $NODE_BIN generate_keys --filename .node-$i.json
done

# Generate committee and parameters using python helper (since we already have the benchmark crate)
echo "Setting up committee and parameters..."
python3 << EOF
import sys
sys.path.insert(0, '/app/benchmark')
from benchmark.config import Key, LocalCommittee, NodeParameters
from benchmark.utils import PathMaker

nodes = $NUM_NODES
keys = [Key.from_file(PathMaker.key_file(i)) for i in range(nodes)]
names = [x.name for x in keys]
committee = LocalCommittee(names, 3000, 1) # 1 worker per node
committee.print(PathMaker.committee_file())

node_params = NodeParameters({
    'timeout_delay': 1000,
    'header_size': 1000,
    'max_header_delay': 100,
    'gc_depth': 50,
    'sync_retry_delay': 10000,
    'sync_retry_nodes': 3,
    'batch_size': 500000,
    'max_batch_delay': 100,
    'use_optimistic_tips': True,
    'use_parallel_proposals': True,
    'k': $AUTOBAHN_K,
    'use_fast_path': True,
    'fast_path_timeout': 200,
    'use_ride_share': False,
    'car_timeout': 2000,
    'simulate_asynchrony': False,
    'asynchrony_start': 20000,
    'asynchrony_duration': 10000,
    'use_fast_sync': True,
    'use_exponential_timeouts': False,
})
node_params.print(PathMaker.parameters_file())
EOF

# Trap to kill background processes on exit
cleanup() {
    echo "Shutting down nodes..."
    pkill -f "$NODE_BIN" || true
    pkill -f "$CLIENT_BIN" || true
}
trap cleanup EXIT

# Start Primaries
echo "Starting primaries..."
for i in $(seq 0 $(($NUM_NODES - 1))); do
    LOG_FILE="logs/primary-$i.log"
    
    # Base command
    CMD="$NODE_BIN -vv run --keys .node-$i.json --committee .committee.json --store .db-primary-$i --parameters .parameters.json primary"
    
    # Add attack environment variables if node is attacker
    if [ "$ATTACK_MODE" != "baseline" ] && [ "$i" -eq "$ATTACKER_ID" ]; then
        echo "🔧 Starting attacker node $i"
        ATTACK_MODE=$ATTACK_MODE \
        ATTACKER_ID=$ATTACKER_ID \
        VICTIM_ID=$VICTIM_ID \
        EXCLUSION_PROBABILITY=$EXCLUSION_PROBABILITY \
        VICTIM_DELAY_MS=$VICTIM_DELAY_MS \
        SLUGGISH_TIMEOUT_MULTIPLIER=$SLUGGISH_TIMEOUT_MULTIPLIER \
        AUTOBAHN_K=$AUTOBAHN_K \
        $CMD 2> $LOG_FILE &
    else
        AUTOBAHN_K=$AUTOBAHN_K \
        $CMD 2> $LOG_FILE &
    fi
done

# Start Workers
echo "Starting workers..."
for i in $(seq 0 $(($NUM_NODES - 1))); do
    LOG_FILE="logs/worker-$i-0.log"
    $NODE_BIN -vv run --keys .node-$i.json --committee .committee.json --store .db-worker-$i-0 --parameters .parameters.json worker --id 0 2> $LOG_FILE &
done

sleep 5

# Start Clients
echo "Starting clients..."
# Get all worker addresses
WORKER_ADDRS=$(python3 -c "import json; data = json.load(open('.committee.json')); addrs = [w['transactions'] for a in data['authorities'].values() for w in a['workers'].values()]; print(' '.join(addrs))")

for i in $(seq 0 $(($NUM_NODES - 1))); do
    # Each client talks to its local worker
    ADDR=$(python3 -c "import json; data = json.load(open('.committee.json')); name = list(data['authorities'].keys())[$i]; print(data['authorities'][name]['workers']['0']['transactions'])")
    
    $CLIENT_BIN $ADDR --size 512 --rate 1000 --nodes $WORKER_ADDRS > logs/client-$i.log 2>&1 &
done

echo "Running experiment for $DURATION seconds..."
sleep $DURATION

echo "Stopping nodes..."
cleanup

# Calculate ASR
echo "Calculating ASR..."
# The script expects primary logs
PRIMARY_LOGS=$(ls logs/primary-*.log)
python3 scripts/calculate-fissure-asr.py $PRIMARY_LOGS > /app/results/asr_output.log 2>&1

# Extract ASR
ASR=$(grep "FINAL ATTACK SUCCESS RATE (ASR):" /app/results/asr_output.log | tail -n 1 | sed 's/.*ASR): \([0-9.]*\)%/\1/')

if [ -z "$ASR" ]; then
    echo "Error: Could not extract ASR from logs."
    cat /app/results/asr_output.log
    exit 1
fi

echo "Extracted ASR: $ASR"
echo "FINAL_ASR=$ASR" > /app/results/asr_result.txt

echo "Test completed. Results saved to /app/results/asr_result.txt"
