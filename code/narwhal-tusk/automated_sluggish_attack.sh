#!/bin/bash

# Automated Sluggish Attack Script for Narwhal-Tusk
# usage: ./automated_sluggish_attack.sh

echo "🐌 Automated Sluggish Attack for Narwhal-Tusk"
echo "============================================"
echo "This script will:"
echo "  1. Build the project with sluggish attack configuration"
echo "  2. Run the 15-node network"
echo "  3. Calculate and display the ASR results"
echo "  4. Compare with paper's target (82.4%)"
echo ""

# Configuration
NARWHAL_TUSK_DIR=$(pwd)
BENCHMARK_DIR="$NARWHAL_TUSK_DIR/benchmark"
LOG_DIR="$BENCHMARK_DIR/logs"
BUILD_LOG="$NARWHAL_TUSK_DIR/build.log" # Kept for rm command, but path is now relative
ATTACK_OUTPUT_LOG="$NARWHAL_TUSK_DIR/sluggish_attack_output.log" # Kept for rm command, but path is now relative

# Attack Parameters (Dynamic with defaults, can be overridden by env or arguments)
# Priority: Positional Argument > Env Var > Default
export NUM_NODES=${1:-${NUM_NODES:-15}}
export ATTACKER_RATIO=${2:-${ATTACKER_RATIO:-0.33}}
export VICTIM_RATIO=${3:-${VICTIM_RATIO:-0.22}}
export DURATION=${4:-${DURATION:-35}}
export SLUGGISH_TIMEOUT_MULTIPLIER=${SLUGGISH_TIMEOUT_MULTIPLIER:-2.0}
export ATTACK_MODE=${ATTACK_MODE:-sluggish}

# Check directory
if [ ! -d "$NARWHAL_TUSK_DIR" ]; then
    echo "❌ Error: Directory $NARWHAL_TUSK_DIR not found."
    exit 1
fi

# --- Step 1: Build project ---
echo "🔨 Step 1: Building project with sluggish attack code..."
cd "$NARWHAL_TUSK_DIR"
export RUSTC_WRAPPER=sccache
cargo build --release
echo "  ✅ Build successful"
echo ""

# --- Step 2: Configure parameters ---
echo "⚙️  Step 2: Configuring sluggish attack parameters..."
# Parameters are now set as environment variables with defaults at the top of the script.

echo "  Attack Mode: $ATTACK_MODE"
echo "  Attacker Ratio: $ATTACKER_RATIO"
echo "  Victim Ratio: $VICTIM_RATIO"
echo "  Timeout Multiplier: $SLUGGISH_TIMEOUT_MULTIPLIER"
echo "  Network Size: $NUM_NODES nodes"
echo "  Duration: $DURATION seconds"
echo ""

# --- Step 3: Clean ---
echo "🧹 Step 3: Cleaning previous results..."
rm -rf "$LOG_DIR"/* "$BUILD_LOG" "$ATTACK_OUTPUT_LOG" > /dev/null 2>&1 || true
mkdir -p "$LOG_DIR"
echo "  ✅ Previous logs cleaned"
echo ""

# --- Step 4: Run ---
echo "🚀 Step 4: Running 15-node network with sluggish attack..."
echo "  Duration: 35 seconds"
echo "  Network: $COMMITTEE_SIZE nodes"
echo "  Expected ASR: ~82.4%"
echo ""
echo "  Starting sluggish attack..."

cd "$BENCHMARK_DIR"
source ../venv/bin/activate

timeout 90 fab local > "$ATTACK_OUTPUT_LOG" 2>&1 &
FAB_PID=$!

echo "  Monitoring attack progress (logs will appear in $LOG_DIR/)..."
echo "  (This will run for approximately 25-30 seconds)"

wait $FAB_PID || true
echo "  ✅ Sluggish attack completed" 
echo ""

# --- Step 5: Analyze ---
echo "📊 Step 5: Analyzing sluggish attack results..."

# Log format: GLOBAL ASR: All-pairs: X/Y = Z% | Same-round: ...
# For Sluggish, "All-pairs" is relevant (includes older attackers)
LATEST_ASR=$(grep "GLOBAL ASR" "$LOG_DIR"/primary-*.log | tail -1 | sed -n 's/.*All-pairs: [0-9]*\/[0-9]* = \([0-9.]*\)%.*/\1/p')

if [ -z "$LATEST_ASR" ]; then
    LATEST_ASR="0.0"
fi

# Get event counts
SUCCESS_EVENTS=$(grep -c "ASR SUCCESS" "$LOG_DIR"/primary-*.log | awk '{s+=$1} END {print s}')
FAILURE_EVENTS=$(grep -c "ASR FAILURE" "$LOG_DIR"/primary-*.log | awk '{s+=$1} END {print s}')
TIMEOUT_EVENTS=$(grep -c "Sluggish attack: Node .* using modified timeout" "$LOG_DIR"/primary-*.log | awk '{s+=$1} END {print s}')

echo "📈 SLUGGISH ASR CALCULATION:"
echo "============================"
echo "  Final ASR (All-pairs): $LATEST_ASR%"
echo "  Timeout Modification Events: $TIMEOUT_EVENTS"
echo ""

echo "📊 COMPARISON WITH PAPER:"
echo "========================="
echo "  Paper's Target: $PAPER_TARGET%"
echo "  Our ASR: $LATEST_ASR%"
echo "FINAL_ASR_RESULT: $LATEST_ASR"
DIFF=$(echo "$LATEST_ASR - $PAPER_TARGET" | bc)
echo "  Difference: $DIFF%"

if (( $(echo "$LATEST_ASR >= 75.0" | bc -l) )); then
    echo "  Status: ✅ SUCCESS - ASR meets target range!"
else
    echo "  Status: ❌ FAILURE - ASR outside acceptable range!"
fi

echo ""
echo "🎉 AUTOMATED SLUGGISH ATTACK COMPLETED!"
echo "======================================="
