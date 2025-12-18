#!/bin/bash
# Fissure Attack Test Script for Autobahn
# Runs 13 nodes locally with Fissure attack enabled

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

# Configuration
NODES=13
WORKERS=1
DURATION=120
ATTACKER_ID=0
VICTIM_ID=1
EXCLUSION_PROBABILITY=0.20

# Set attack environment variables
export ATTACK_MODE=fissure
export ATTACKER_ID=$ATTACKER_ID
export VICTIM_ID=$VICTIM_ID
export EXCLUSION_PROBABILITY=$EXCLUSION_PROBABILITY
export RUST_LOG=info

echo "============================================================"
echo "🎯 AUTOBAHN FISSURE ATTACK TEST"
echo "============================================================"
echo "Nodes: $NODES"
echo "Attacker: Node $ATTACKER_ID"
echo "Victim: Node $VICTIM_ID"
echo "Exclusion Probability: $EXCLUSION_PROBABILITY"
echo "Duration: ${DURATION}s"
echo "============================================================"
echo ""

# Clean up previous runs
echo "Cleaning up previous runs..."
rm -rf .db-* .*.json logs/ 2>/dev/null || true
mkdir -p logs

# Build the project
echo "Building Autobahn..."
cd "$PROJECT_ROOT"
cargo build --release --features benchmark 2>&1 | tail -5

# Create binaries alias
BINARY_PATH="target/release"
rm -f node benchmark_client 2>/dev/null || true
ln -sf "$BINARY_PATH/node" node
ln -sf "$BINARY_PATH/benchmark_client" benchmark_client

# Generate keys
echo "Generating keys..."
for i in $(seq 0 $((NODES-1))); do
    ./node generate_keys --filename ".key-$i.json" 2>/dev/null
done

# Generate committee file
echo "Generating committee configuration..."
python3 << EOF
import json
import subprocess
import os

# Read all keys
keys = []
for i in range($NODES):
    result = subprocess.run(['./node', 'generate_keys', '--filename', f'.key-{i}.json'], 
                          capture_output=True, text=True, cwd='$PROJECT_ROOT')
    # Parse key file
    with open(f'.key-{i}.json', 'r') as f:
        key_data = json.load(f)
        keys.append(key_data)

# Create committee structure
committee = {
    "authorities": {},
    "epoch": 0
}

base_port = 3000
for i, key in enumerate(keys):
    name = key.get("name", "")
    primary_to_primary = f"127.0.0.1:{base_port + i * 10}"
    primary_to_worker = f"127.0.0.1:{base_port + i * 10 + 1}"
    worker_to_worker = f"127.0.0.1:{base_port + i * 10 + 2}"
    
    committee["authorities"][name] = {
        "stake": 1,
        "primary": {
            "primary_to_primary": primary_to_primary,
            "primary_to_worker": primary_to_worker
        },
        "workers": {
            "0": {
                "worker_to_worker": worker_to_worker,
                "transactions": f"127.0.0.1:{base_port + i * 10 + 3}"
            }
        }
    }

with open('.committee.json', 'w') as f:
    json.dump(committee, f, indent=2)

print(f"Created committee with {len(keys)} nodes")
EOF

# Generate parameters file
echo "Generating parameters configuration..."
cat > .parameters.json << EOF
{
    "timeout_delay": 1000,
    "header_size": 1000,
    "max_header_delay": 100,
    "gc_depth": 50,
    "sync_retry_delay": 10000,
    "sync_retry_nodes": 3,
    "batch_size": 500000,
    "max_batch_delay": 100,
    "use_optimistic_tips": true,
    "use_parallel_proposals": true,
    "k": 4,
    "use_fast_path": true,
    "fast_path_timeout": 200,
    "use_ride_share": false,
    "car_timeout": 2000,
    "simulate_asynchrony": false,
    "use_fast_sync": true,
    "use_exponential_timeouts": false
}
EOF

# Kill any existing nodes
echo "Killing existing nodes..."
tmux kill-server 2>/dev/null || true
sleep 1

# Start primaries
echo "Starting primaries..."
for i in $(seq 0 $((NODES-1))); do
    # Set attack environment only for attacker node
    if [ $i -eq $ATTACKER_ID ]; then
        export ATTACK_MODE=fissure
        export ATTACKER_ID=$ATTACKER_ID
        export VICTIM_ID=$VICTIM_ID
        export EXCLUSION_PROBABILITY=$EXCLUSION_PROBABILITY
    else
        unset ATTACK_MODE
        unset ATTACKER_ID
        unset VICTIM_ID
        unset EXCLUSION_PROBABILITY
    fi
    
    tmux new-session -d -s "primary-$i" \
        "cd $PROJECT_ROOT && \
         ATTACK_MODE=$([ $i -eq $ATTACKER_ID ] && echo 'fissure' || echo '') \
         ATTACKER_ID=$([ $i -eq $ATTACKER_ID ] && echo $ATTACKER_ID || echo '') \
         VICTIM_ID=$([ $i -eq $ATTACKER_ID ] && echo $VICTIM_ID || echo '') \
         EXCLUSION_PROBABILITY=$([ $i -eq $ATTACKER_ID ] && echo $EXCLUSION_PROBABILITY || echo '') \
         RUST_LOG=info \
         ./node -vv run --keys .key-$i.json --committee .committee.json --store .db-$i --parameters .parameters.json primary 2>&1 | tee logs/primary-$i.log"
done

# Start workers
echo "Starting workers..."
for i in $(seq 0 $((NODES-1))); do
    for w in $(seq 0 $((WORKERS-1))); do
        tmux new-session -d -s "worker-$i-$w" \
            "cd $PROJECT_ROOT && \
             ./node -vv run --keys .key-$i.json --committee .committee.json --store .db-$i-$w --parameters .parameters.json worker --id $w 2>&1 | tee logs/worker-$i-$w.log"
    done
done

# Start clients (optional - for generating transactions)
echo "Starting clients..."
sleep 5  # Wait for nodes to start

# Get worker addresses from committee
WORKER_ADDRESSES=$(python3 << 'PYEOF'
import json
with open('.committee.json', 'r') as f:
    committee = json.load(f)
    addresses = []
    for name, auth in committee["authorities"].items():
        for worker_id, worker in auth["workers"].items():
            addresses.append(worker["transactions"])
    print(" ".join(addresses))
PYEOF
)

RATE_PER_CLIENT=1000
for i in $(seq 0 $((NODES-1))); do
    WORKER_ADDR=$(echo $WORKER_ADDRESSES | cut -d' ' -f$((i+1)))
    tmux new-session -d -s "client-$i" \
        "cd $PROJECT_ROOT && \
         ./benchmark_client $WORKER_ADDR --size 512 --rate $RATE_PER_CLIENT --nodes $WORKER_ADDRESSES 2>&1 | tee logs/client-$i.log"
done

# Wait for test duration
echo ""
echo "Running test for ${DURATION} seconds..."
echo "Monitor logs in: logs/"
sleep $DURATION

# Stop all nodes
echo "Stopping all nodes..."
tmux kill-server 2>/dev/null || true

# Calculate ASR
echo ""
echo "Calculating ASR..."
python3 "$SCRIPT_DIR/calculate-fissure-asr.py" logs/primary-*.log 2>&1

echo ""
echo "✅ Test complete!"
echo "Logs saved to: logs/"





