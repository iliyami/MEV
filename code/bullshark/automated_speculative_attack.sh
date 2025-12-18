#!/bin/bash

# Automated Speculative Attack Script for Bullshark
# usage: ./automated_speculative_attack.sh

echo "🎯 Automated Speculative Attack for Bullshark"
echo "==========================================="
echo "This script will:"
echo "  1. Configure the environment for Speculative Attack"
echo "  2. Run the dedicated 13-node test (test_speculative_attack_asr_13_nodes)"
echo "  3. Measure the ASR (ordering bias in same-round blocks)"
echo ""

# Configuration
BS_DIR="/Users/iliya/Dev/Blockchain/code/bullshark"
LOG_DIR="$BS_DIR/benchmark/logs"
ATTACK_OUTPUT_LOG="$BS_DIR/speculative_attack_output.log"

# Attack Parameters (Matching Paper/Summary Test Config)
export ATTACK_MODE="speculative"
export ATTACKER_RATIO="0.308" # 4/13
export VICTIM_RATIO="0.231"   # 3/13
export SPECULATIVE_P_MAX="50"
export RUST_LOG="info"

echo "⚙️  Parameters:"
echo "  Attack Mode: $ATTACK_MODE"
echo "  Attacker Ratio: $ATTACKER_RATIO"
echo "  Victim Ratio: $VICTIM_RATIO"
echo "  P_MAX: $SPECULATIVE_P_MAX"
echo ""

# Check directory
if [ ! -d "$BS_DIR" ]; then
    echo "❌ Error: Directory $BS_DIR not found."
    exit 1
fi

cd "$BS_DIR"

echo "🚀 Running Test: test_speculative_attack_asr_13_nodes..."
echo "   (This compiles and runs the consensus test harness)"

# clear previous log
rm -f "$ATTACK_OUTPUT_LOG"

# Run test
cargo test --release --package consensus-core test_speculative_attack_asr_13_nodes -- --nocapture 2>&1 | tee "$ATTACK_OUTPUT_LOG"

# Extract Result
echo ""
echo "📊 Analysis:"
LATEST_ASR=$(grep "ASR calculation (Same-Round):" "$ATTACK_OUTPUT_LOG" | tail -1)

if [ ! -z "$LATEST_ASR" ]; then
    echo "  $LATEST_ASR"
    ASR_VAL=$(echo "$LATEST_ASR" | sed -n 's/.*= \([0-9.]*\)%.*/\1/p')
    echo "  Final ASR: $ASR_VAL%"
    
    # Check target 86.3%
    DIFF=$(echo "$ASR_VAL - 86.3" | bc)
    echo "  Target: 86.3%"
    echo "  Diff: $DIFF%"
else
    echo "  ❌ ASR not found in output."
fi

echo ""
echo "🎉 Done."
