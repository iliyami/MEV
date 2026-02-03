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
    echo "❌ Error: Not in the correct directory"
    echo "Please run this from: /Users/iliya/Dev/Blockchain/code/narwhal-tusk"
    exit 1
fi

# Step 1: Build (using sccache, no clean needed)
echo "🔨 Step 1: Building project with attack code (using sccache)..."
export RUSTC_WRAPPER=sccache

cargo build --release > build.log 2>&1
if [ $? -eq 0 ]; then
    echo "  ✅ Build successful"
else
    echo "  ❌ Build failed - check build.log for details"
    exit 1
fi

# Configuration
NARWHAL_TUSK_DIR=$(pwd)
BENCHMARK_DIR="$NARWHAL_TUSK_DIR/benchmark"
LOG_DIR="$BENCHMARK_DIR/logs"

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
rm -rf "$LOG_DIR"/*
echo "  ✅ Previous logs cleaned"

# Step 3: Run the attack
echo ""
echo "🚀 Step 3: Running network with fissure attack..."
echo "  Network: $NUM_NODES nodes"
echo "  ASR Calculation: Paper-aligned all-pairs methodology"
echo "  Expected ASR: ~87% (paper target: 87.31%)"
echo ""

cd "$BENCHMARK_DIR"
source ../venv/bin/activate

# Run the attack and capture output
echo "  Starting attack..."
fab local > ../attack_output.log 2>&1
ATTACK_EXIT_CODE=$?

cd ..

# Step 5: Analyze results
echo ""
echo "📊 Step 5: Analyzing attack results..."

if [ $ATTACK_EXIT_CODE -eq 0 ] && [ -f "benchmark/logs/primary-0.log" ]; then
    echo "  ✅ Attack completed successfully"
    
    # Calculate ASR
    echo ""
    echo "📈 ASR CALCULATION:"
    echo "=================="
    
    # Get final ASR
    FINAL_ASR=$(grep "Cumulative ASR" benchmark/logs/primary-*.log 2>/dev/null | tail -1 | grep -o '[0-9]\+\.[0-9]\+%' | tail -1)
    if [ ! -z "$FINAL_ASR" ]; then
        echo "  Final ASR: $FINAL_ASR"
    else
        echo "  ❌ No ASR found in logs"
        FINAL_ASR="0%"
    fi
    
    # Count exclusions
    TOTAL_EXCLUSIONS=$(grep -c "Excluding victim parent" benchmark/logs/primary-*.log 2>/dev/null | awk '{sum += $1} END {print sum}')
    echo "  Total Exclusions: $TOTAL_EXCLUSIONS"
    
    # Count attack events
    TOTAL_EVENTS=$(grep -c "Cumulative ASR" benchmark/logs/primary-*.log 2>/dev/null | awk '{sum += $1} END {print sum}')
    echo "  Attack Events: $TOTAL_EVENTS"
    
    # Get network performance
    CONSENSUS_TPS=$(grep "Consensus TPS" benchmark/logs/primary-*.log 2>/dev/null | tail -1 | grep -o '[0-9,]\+' | head -1)
    if [ ! -z "$CONSENSUS_TPS" ]; then
        echo "  Network TPS: $CONSENSUS_TPS"
    fi
    
    # Show which node was the attacker
    echo ""
    echo "🎯 ATTACK ANALYSIS:"
    echo "=================="
    for i in {0..3}; do
        EXCLUSIONS=$(grep -c "Excluding victim parent" benchmark/logs/primary-$i.log 2>/dev/null)
        if [ $EXCLUSIONS -gt 0 ]; then
            echo "  Attacker Node: Primary-$i ($EXCLUSIONS exclusions)"
        fi
    done
    
    # Show victim nodes (nodes with 0 exclusions)
    echo "  Victim Nodes:"
    for i in {0..3}; do
        EXCLUSIONS=$(grep -c "Excluding victim parent" benchmark/logs/primary-$i.log 2>/dev/null)
        if [ $EXCLUSIONS -eq 0 ]; then
            echo "    - Primary-$i (0 exclusions - victim)"
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
    grep "Cumulative ASR" benchmark/logs/primary-*.log | tail -3 | while read line; do
        echo "  $line"
    done
    
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
