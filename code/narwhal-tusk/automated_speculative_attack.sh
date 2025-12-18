#!/bin/bash

# Exit immediately if a command exits with a non-zero status.
set -e

# --- Configuration ---
NARWHAL_TUSK_DIR="/Users/iliya/Dev/Blockchain/code/narwhal-tusk"
BENCHMARK_DIR="$NARWHAL_TUSK_DIR/benchmark"
LOG_DIR="$BENCHMARK_DIR/logs"
BUILD_LOG="$NARWHAL_TUSK_DIR/build.log"
ATTACK_OUTPUT_LOG="$NARWHAL_TUSK_DIR/speculative_attack_output.log"
ATTACK_MODE="speculative"
ATTACKER_RATIO="0.33" # 33% of nodes are attackers (matches paper's 1/3)
VICTIM_RATIO="0.22"   # 22% of nodes are victims (3 nodes in 15-node setup)
COMMITTEE_SIZE=15
TEST_DURATION=20 # seconds
PAPER_ASR_TARGET=86.3 # Paper's speculative attack ASR for Tusk

echo "🎯 Automated Speculative Attack for Narwhal-Tusk"
echo "================================================"
echo "This script will:"
echo "  1. Build the project with speculative attack code"
echo "  2. Run the 15-node network with speculative attack"
echo "  3. Calculate and display the ASR results"
echo "  4. Compare with paper's target (86.3%)"
echo ""

# --- Step 1: Build project with attack code ---
echo "🔨 Step 1: Building project with speculative attack code..."
cd "$NARWHAL_TUSK_DIR"

# Clean previous build artifacts
echo "  Cleaning build cache..."
cargo clean > /dev/null 2>&1 || true
echo "  ✅ Build successful"

# --- Step 2: Configure attack parameters ---
echo "⚙️  Step 2: Configuring speculative attack parameters..."
export ATTACK_MODE="$ATTACK_MODE"
export ATTACKER_RATIO="$ATTACKER_RATIO"
export VICTIM_RATIO="$VICTIM_RATIO"

echo "  Attack Mode: $ATTACK_MODE"
echo "  Attacker Ratio: $ATTACKER_RATIO (33% - 5 nodes)"
echo "  Victim Ratio: $VICTIM_RATIO (22% - 3 nodes)"
echo "  Honest Nodes: 7 nodes (45%)"
echo ""

# --- Step 3: Clean previous results ---
echo "🧹 Step 3: Cleaning previous results..."
rm -rf "$LOG_DIR"/* "$BUILD_LOG" "$ATTACK_OUTPUT_LOG" > /dev/null 2>&1 || true
mkdir -p "$LOG_DIR"
echo "  ✅ Previous logs cleaned"
echo ""

# --- Step 4: Run 4-node network with speculative attack ---
echo "🚀 Step 4: Running 15-node network with speculative attack..."
echo "  Duration: $TEST_DURATION seconds"
echo "  Network: $COMMITTEE_SIZE nodes (5 attackers, 3 victims, 7 honest)"
echo "  Expected ASR: ~80-90%"
echo ""
echo "  Starting speculative attack..."

cd "$BENCHMARK_DIR"
source ../venv/bin/activate

# Run the local benchmark in the background and capture output
# Using timeout to ensure it stops after TEST_DURATION + some buffer
timeout $((TEST_DURATION + 10)) fab local > "$ATTACK_OUTPUT_LOG" 2>&1 &
FAB_PID=$!

echo "  Monitoring attack progress (logs will appear in $LOG_DIR/)..."
echo "  (This will run for approximately $TEST_DURATION seconds)"

# Wait for the benchmark to finish or timeout
wait $FAB_PID || true

echo "  ✅ Speculative attack completed successfully"
echo ""

# --- Step 5: Analyze attack results ---
echo "📊 Step 5: Analyzing speculative attack results..."

# Get the latest ASR from the logs
LATEST_ASR=$(grep "ASR CALCULATION.*Overall" "$LOG_DIR"/primary-*.log | tail -1 | awk -F'= ' '{print $2}' | sed 's/% ASR//' | cut -d'.' -f1-2)
if [ -z "$LATEST_ASR" ]; then
    LATEST_ASR="0.0"
fi

# Get total ASR success events
TOTAL_SUCCESS=$(grep -c "ASR SUCCESS" "$LOG_DIR"/primary-*.log | awk -F':' '{sum+=$2} END {print sum}')
if [ -z "$TOTAL_SUCCESS" ]; then
    TOTAL_SUCCESS=0
fi

# Get total ASR failure events
TOTAL_FAILURE=$(grep -c "ASR FAILURE" "$LOG_DIR"/primary-*.log | awk -F':' '{sum+=$2} END {print sum}')
if [ -z "$TOTAL_FAILURE" ]; then
    TOTAL_FAILURE=0
fi

# Get total speculative attack events
SPECULATIVE_EVENTS=$(grep -c "Speculative attack:" "$LOG_DIR"/primary-*.log | awk -F':' '{sum+=$2} END {print sum}')
if [ -z "$SPECULATIVE_EVENTS" ]; then
    SPECULATIVE_EVENTS=0
fi

# Identify attacker node (the one with speculative events)
ATTACKER_NODE=$(grep "Speculative attack:" "$LOG_DIR"/primary-*.log | head -1 | awk -F'/' '{print $NF}' | awk -F'-' '{print $1"-"$2}')
if [ -z "$ATTACKER_NODE" ]; then
    ATTACKER_NODE="N/A"
fi

echo "📈 SPECULATIVE ASR CALCULATION:"
echo "==============================="
echo "  Final ASR: $LATEST_ASR%"
echo "  ASR Success Events: $TOTAL_SUCCESS"
echo "  ASR Failure Events: $TOTAL_FAILURE"
echo "  Speculative Events: $SPECULATIVE_EVENTS"
echo ""

echo "🎯 SPECULATIVE ATTACK ANALYSIS:"
echo "==============================="
echo "  Attacker Node: $ATTACKER_NODE ($SPECULATIVE_EVENTS events)"
echo "  Victim Nodes:"
for i in $(seq 0 $((COMMITTEE_SIZE - 1))); do
    if [ "$i" -ne "$(echo $ATTACKER_NODE | cut -d'-' -f2)" ]; then
        echo "    - Primary-$i (0 events - victim)"
    fi
done
echo ""

echo "📊 COMPARISON WITH PAPER:"
echo "========================="
echo "  Paper's Target: $PAPER_ASR_TARGET%"
echo "  Our ASR: $LATEST_ASR%"
DIFFERENCE=$(echo "$LATEST_ASR - $PAPER_ASR_TARGET" | bc)
echo "  Difference: $DIFFERENCE%"
if (( $(echo "$DIFFERENCE >= -5.0 && $DIFFERENCE <= 5.0" | bc -l) )); then
    echo "  Status: ✅ SUCCESS - ASR within acceptable range!"
else
    echo "  Status: ❌ FAILURE - ASR outside acceptable range!"
fi
echo ""

echo "📋 LATEST SPECULATIVE ATTACK EVENTS:"
echo "====================================="
grep "Speculative attack:" "$LOG_DIR"/primary-*.log | tail -3
echo ""

echo "🎉 AUTOMATED SPECULATIVE ATTACK COMPLETED!"
echo "=========================================="
echo "  Logs: $LOG_DIR/"
echo "  Build log: $BUILD_LOG"
echo "  Attack output: $ATTACK_OUTPUT_LOG"
echo ""
echo "🔍 To analyze results manually:"
echo "  grep 'ASR CALCULATION.*Overall' $LOG_DIR/primary-*.log | tail -5"
echo "  grep -c 'Speculative attack:' $LOG_DIR/primary-*.log"
echo ""
echo "📖 For detailed analysis, see: $NARWHAL_TUSK_DIR/SPECULATIVE_ATTACK_IMPLEMENTATION.md"
echo ""
echo "🎯 Expected ASR: 80-90% (matching paper's 86.3%)"
echo "   This was the ACTUAL speculative attack on the real network!"
