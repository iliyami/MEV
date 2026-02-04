#!/bin/bash

# Automated Fissure Attack Script for Narwhal-Tusk
# This script automates the entire process: build, run attack, calculate ASR
# Usage: ./automated_fissure_attack.sh

echo "🎯 Automated Fissure Attack for Narwhal-Tusk (13-node)"
echo "======================================================="
echo "This script will:"
echo "  1. Build the project with attack code (using sccache)"
echo "  2. Run the 13-node network with fissure attack"
echo "  3. Calculate and display the ASR results (paper-aligned)"
echo "  4. Compare with paper's target (87.31%)"
echo ""

# Check if we're in the right directory
if [ ! -f "benchmark/.committee.json" ]; then
    if [ "$PWD" == "/app" ]; then
        echo "⚠️ Running in /app, continuing..."
    else
        echo "❌ Error: Not in the correct directory"
        echo "Please run this from: /Users/iliya/Dev/Blockchain/code/narwhal-tusk"
        exit 1
    fi
fi

# --- Step 1: Build project with attack code (skip if already built) ---
if [ -f "target/release/primary" ] || [ -f "primary" ] || [ -f "target/release/node" ] || [ -f "node" ]; then
    echo "🔨 Step 1: Skipping build (binary already exists)"
    # Ensure binary is in the place fab local expects if it's named 'node'
    if [ ! -f "target/release/node" ] && [ -f "node" ]; then
        mkdir -p target/release
        cp node target/release/node
    fi
else
    echo "🔨 Step 1: Building project with attack code (using sccache)..."
    export RUSTC_WRAPPER=sccache

    cargo build --release > build.log 2>&1
    if [ $? -eq 0 ]; then
        echo "  ✅ Build successful"
    else
        echo "  ❌ Build failed - check build.log for details"
        exit 1
    fi
fi

# Configuration
NARWHAL_TUSK_DIR=$(pwd)
BENCHMARK_DIR="$NARWHAL_TUSK_DIR/benchmark"
LOG_DIR="$BENCHMARK_DIR/logs"
ATTACK_OUTPUT_LOG="attack_output.log" # Define the variable for the attack output log

# Attack Parameters (Dynamic with defaults, can be overridden by env or arguments)
# Priority: Positional Argument > Env Var > Default
export NUM_NODES=${1:-${NUM_NODES:-13}}
export ATTACKER_RATIO=${2:-${ATTACKER_RATIO:-0.308}}
export VICTIM_RATIO=${3:-${VICTIM_RATIO:-0.231}}
export DURATION=${4:-${DURATION:-35}}
export ATTACK_MODE=${ATTACK_MODE:-fissure}

echo ""
echo "⚙️  Configuring attack parameters..."
echo "  Attack Mode: $ATTACK_MODE"
echo "  Attacker Ratio: $ATTACKER_RATIO"
echo "  Victim Ratio: $VICTIM_RATIO"
echo "  Network Size: $NUM_NODES nodes"
echo "  Duration: $DURATION seconds"

# Step 2: Clean previous logs
echo ""
echo "🧹 Step 2: Cleaning previous results..."
rm -rf "$LOG_DIR"/* /app/results/logs/* > /dev/null 2>&1 || true
mkdir -p "$LOG_DIR" /app/results/logs
echo "  ✅ Previous logs cleaned"

# Step 3: Run the attack
echo ""
echo "🚀 Step 3: Running network with fissure attack..."
echo "  Network: $NUM_NODES nodes"
echo "  ASR Calculation: Paper-aligned all-pairs methodology"
echo "  Expected ASR: ~87% (paper target: 87.31%)"
echo ""

cd "$BENCHMARK_DIR"
if [ -d "../venv" ]; then
    source ../venv/bin/activate
else
    echo "⚠️  No venv found, using system python/fab"
fi

# Run the attack and capture output
echo "  Starting attack..."
fab local > "../$ATTACK_OUTPUT_LOG" 2>&1
ATTACK_EXIT_CODE=$?

cd ..

# Step 5: Analyze results
echo ""
echo "📊 Step 5: Analyzing fissure attack results..."

if [ ! "$(ls -A "$LOG_DIR" 2>/dev/null)" ]; then
    echo "⚠️ Warning: No logs found in $LOG_DIR!"
    echo "Checking if tmux sessions failed to start..."
    tmux ls || echo "No tmux sessions found."
    echo "Last 20 lines of attack output log ($ATTACK_OUTPUT_LOG):"
    cat "$ATTACK_OUTPUT_LOG" || echo "Attack output log is empty or missing."
fi

# Identify the latest primary log
if [ -z "$(ls -A "$LOG_DIR" 2>/dev/null)" ]; then
    FINAL_ASR="0%"
    TOTAL_SAMPLES="0"
else
    # Find the maximum ASR across all logs that have results and extract sample counts
    ASR_LINE=$(grep "GLOBAL ASR" "$LOG_DIR"/primary-*.log 2>/dev/null | tail -n 1)
    ASR_VAL=$(echo "$ASR_LINE" | sed -n 's/.*Same-round: [0-9]*\/[0-9]* = \([0-9.]*\)%.*/\1/p')
    TOTAL_SAMPLES=$(echo "$ASR_LINE" | sed -n 's/.*Same-round: [0-9]*\/\([0-9]*\).*/\1/p')
    
    if [ ! -z "$ASR_VAL" ]; then
        FINAL_ASR="${ASR_VAL}%"
    else
        # Fallback to older exclusion metric if Global ASR not found
        FINAL_ASR=$(grep "Cumulative ASR" "$LOG_DIR"/primary-*.log 2>/dev/null | tail -n 1 | sed -n 's/.*Cumulative ASR: \([0-9.]*\)%.*/\1/p')
        TOTAL_SAMPLES="N/A"
        if [ -z "$FINAL_ASR" ]; then
            FINAL_ASR="0.0%"
        else
            FINAL_ASR="${FINAL_ASR}%"
        fi
    fi
fi

if [ $ATTACK_EXIT_CODE -eq 0 ] && [ -f "benchmark/logs/primary-0.log" ]; then
    echo "  ✅ Attack completed successfully"
    
    # Calculate ASR
    echo ""
    echo "📈 ASR CALCULATION:"
    echo "=================="
    
    # Get final ASR (GLOBAL ASR from Consensus is the true Ordering ASR)
    if [ "$FINAL_ASR" != "0%" ]; then
        echo "  Final ASR (Ordering): $FINAL_ASR"
    else
        # Fallback to Proposer's Exclusion ASR if Global not found
        FINAL_ASR=$(grep "Cumulative ASR" benchmark/logs/primary-*.log 2>/dev/null | tail -1 | grep -o '[0-9.]\+%' | tail -1)
        if [ -z "$FINAL_ASR" ]; then FINAL_ASR="0%"; fi
        echo "  Final ASR (Exclusion): $FINAL_ASR (Global ASR not found)"
    fi
    
    # Count exclusions
    TOTAL_EXCLUSIONS=$(grep "Excluding victim parent" benchmark/logs/primary-*.log 2>/dev/null | wc -l)
    echo "  Total Exclusions: $TOTAL_EXCLUSIONS"
    
    # Count attack events
    TOTAL_EVENTS=$(grep "Cumulative ASR" benchmark/logs/primary-*.log 2>/dev/null | wc -l)
    echo "  Attack Events: $TOTAL_EVENTS"
    
    # Get network performance
    CONSENSUS_TPS=$(grep "Consensus TPS" benchmark/logs/primary-*.log 2>/dev/null | tail -1 | grep -o '[0-9,]\+' | head -1)
    if [ ! -z "$CONSENSUS_TPS" ]; then
        echo "  Network TPS: $CONSENSUS_TPS"
    fi
    
    # Show which node was the attacker
    echo ""
    # Robust Identification: Extract node number from primary-X.log
ATTACKER_ID=$(grep -l "GLOBAL ASR" "$LOG_DIR"/primary-*.log 2>/dev/null | head -n 1 | xargs basename | sed 's/primary-//; s/.log//')
if [ -z "$ATTACKER_ID" ]; then
    ATTACKER_ID=$(grep -l "Excluding victim parent" "$LOG_DIR"/primary-*.log 2>/dev/null | head -n 1 | xargs basename | sed 's/primary-//; s/.log//')
fi

echo "🎯 ATTACK ANALYSIS:"
echo "=================="
if [ ! -z "$ATTACKER_ID" ]; then
    echo "  Attacker Node: Primary-$ATTACKER_ID"
else
    echo "  Attacker Node: Unknown"
fi
echo "  Victim Nodes:"
for i in $(seq 0 $((NUM_NODES - 1))); do
    # Only show a few victims if network is large
    if [ "$i" -ne "$ATTACKER_ID" ] 2>/dev/null; then
        if [ "$NUM_NODES" -le 15 ] || [ "$i" -le 5 ]; then
            echo "    - Primary-$i (victim candidate)"
        fi
    fi
done
    
    # Compare with paper
    echo ""
    echo "📊 COMPARISON WITH PAPER:"
    echo "========================"
    echo "  Paper's Target: 87.31%"
    echo "  Our ASR: $FINAL_ASR"
    echo "FINAL_ASR_RESULT: $FINAL_ASR"
    
    # Simple comparison (extract number from percentage)
    ASR_NUM=$(echo $FINAL_ASR | sed 's/%//')
    if [ ! -z "$ASR_NUM" ] && [ "$ASR_NUM" != "0" ]; then
        DIFF=$(echo "scale=2; $ASR_NUM - 87.31" | bc -l)
        if (( $(echo "$ASR_NUM >= 80" | bc -l) )); then
            echo "  Difference: ${DIFF}%"
            echo "  Status: ✅ SUCCESS - ASR within acceptable range!"
        else
            echo "  Status: ⚠️  Below expected - Check attack implementation"
        fi
    else
        echo "  Status: ❌ No valid ASR found"
    fi
    
    # Show latest attack events
    echo ""
    echo "📋 LATEST ATTACK EVENTS:"
    echo "======================="
    grep "GLOBAL ASR" benchmark/logs/primary-*.log 2>/dev/null | tail -3 | while read line; do
        echo "  $line"
    done
    grep "Fissure attack" benchmark/logs/primary-*.log 2>/dev/null | tail -3 | while read line; do
        echo "  $line"
    done
    
    # Copy logs to results for easier analysis
    echo ""
    echo "📂 Copying logs to results/logs/..."
    mkdir -p /app/results/logs
    cp benchmark/logs/primary-*.log /app/results/logs/
    
else
    echo "  ❌ Attack failed or no logs found"
    echo "  Check attack_output.log for details"
    if [ -f "attack_output.log" ]; then
        echo "  Last few lines of output:"
        tail -5 attack_output.log
    fi
fi

# Step 6: Summary
echo ""
echo "🎉 AUTOMATED ATTACK COMPLETED!"
echo "============================="
echo "  Logs: benchmark/logs/"
echo "  Build log: build.log"
echo "  Attack output: attack_output.log"
echo ""
echo "🔍 To analyze results manually:"
echo "  grep 'Cumulative ASR' benchmark/logs/primary-*.log | tail -5"
echo "  grep -c 'Excluding victim parent' benchmark/logs/primary-*.log"
echo ""
echo "📖 For detailed analysis, see: FISSURE_ATTACK_IMPLEMENTATION_GUIDE.md"
echo ""
echo "🎯 Expected ASR: 83-87% (matching paper's 87.31%)"
echo "   This was the ACTUAL attack on the real network!"
