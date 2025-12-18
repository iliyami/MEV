#!/bin/bash

# Automated Sluggish Attack Script for Bullshark
# Usage: ./automated_sluggish_attack.sh

echo "🐌 Automated Sluggish Attack for Bullshark"
echo "=========================================="
echo "This script will:"
echo "  1. Configure the environment for Sluggish Attack"
echo "  2. Run the dedicated 13-node test (test_sluggish_attack_asr_13_nodes)"
echo "  3. Measure the ASR (ordering bias: Attacker < Victim)"
echo ""

# Configuration
BS_DIR="/Users/iliya/Dev/Blockchain/code/bullshark"
ATTACK_OUTPUT_LOG="$BS_DIR/sluggish_attack_output.log"

# Attack Parameters
export ATTACK_MODE="sluggish"
export ATTACKER_RATIO="0.308" # 4/13
export VICTIM_RATIO="0.231"   # 3/13
# Optimization: Lower multiplier to avoid being orphaned
export SLUGGISH_TIMEOUT_MULTIPLIER="1.5"
export RUST_LOG="info"

echo "⚙️  Parameters:"
echo "  Attack Mode: $ATTACK_MODE"
echo "  Attacker Ratio: $ATTACKER_RATIO"
echo "  Victim Ratio: $VICTIM_RATIO"
echo "  Multiplier: $SLUGGISH_TIMEOUT_MULTIPLIER"
echo ""

cd "$BS_DIR"

echo "🚀 Running Test: test_sluggish_attack_asr_13_nodes..."
rm -f "$ATTACK_OUTPUT_LOG"

# Run test
# Note: Ensure test_sluggish_attack_asr_13_nodes is enabled in lib.rs
cargo test --release --package consensus-core test_sluggish_attack_asr_13_nodes -- --nocapture 2>&1 | tee "$ATTACK_OUTPUT_LOG"

# Extract Result
echo ""
echo "📊 Analysis:"
LATEST_ASR=$(grep "ASR calculation" "$ATTACK_OUTPUT_LOG" | tail -1)

if [ ! -z "$LATEST_ASR" ]; then
    echo "  $LATEST_ASR"
    ASR_VAL=$(echo "$LATEST_ASR" | sed -n 's/.*= \([0-9.]*\)%.*/\1/p')
    echo "  Final ASR: $ASR_VAL%"
    
    # Check target 87%
    DIFF=$(echo "$ASR_VAL - 87.0" | bc)
    echo "  Target: 87.0%"
    echo "  Diff: $DIFF%"
else
    echo "  ❌ ASR not found in output."
fi

echo ""
echo "🎉 Done."
