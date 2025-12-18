#!/bin/bash

# Automated Fissure Attack Script for Bullshark
# Usage: ./automated_fissure_attack.sh

echo "🌋 Automated Fissure Attack for Bullshark"
echo "=========================================="
echo "This script will:"
echo "  1. Run the dedicated 13-node Fissure test"
echo "  2. Measure ASR (Victim Exclusion -> Attacker Priority)"

# Configuration
BS_DIR="/Users/iliya/Dev/Blockchain/code/bullshark"
ATTACK_OUTPUT_LOG="$BS_DIR/fissure_attack_output.log"

export ATTACK_MODE="fissure"
export ATTACKER_RATIO="0.308"
export VICTIM_RATIO="0.231"
export RUST_LOG="info"

echo "⚙️  Parameters:"
echo "  Attack Mode: $ATTACK_MODE"
echo "  Attacker Ratio: $ATTACKER_RATIO"
echo ""

cd "$BS_DIR"

echo "🚀 Running Test: test_fissure_attack_asr_13_nodes..."
rm -f "$ATTACK_OUTPUT_LOG"

cargo test --release --package consensus-core test_fissure_attack_asr_13_nodes -- --nocapture 2>&1 | tee "$ATTACK_OUTPUT_LOG"

# Extract Result
echo ""
echo "📊 Analysis:"
LATEST_ASR=$(grep "ASR calculation" "$ATTACK_OUTPUT_LOG" | tail -1)

if [ ! -z "$LATEST_ASR" ]; then
    echo "  $LATEST_ASR"
    ASR_VAL=$(echo "$LATEST_ASR" | sed -n 's/.*= \([0-9.]*\)%.*/\1/p')
    echo "  Final ASR: $ASR_VAL%"
    echo "  Target: ~94%"
else
    echo "  ❌ ASR not found in output."
fi

echo ""
echo "🎉 Done."
