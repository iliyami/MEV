#!/bin/bash
# Automated Fissure Attack Test for MEVSUI
# This script builds and runs the fissure attack test, then extracts ASR results

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=========================================="
echo "MEVSUI Fissure Attack Test"
echo "=========================================="
echo ""

# Set attack parameters
export ATTACK_MODE="fissure"
export ATTACKER_RATIO="0.308"  # 4/13
export VICTIM_RATIO="0.231"    # 3/13

echo "Attack Configuration:"
echo "  ATTACK_MODE: $ATTACK_MODE"
echo "  ATTACKER_RATIO: $ATTACKER_RATIO"
echo "  VICTIM_RATIO: $VICTIM_RATIO"
echo ""

# Build the project
echo "Building MEVSUI consensus core..."
cargo build --release --package consensus-core 2>&1 | grep -E "(Compiling|Finished|error|warning)" || true

if [ $? -ne 0 ]; then
    echo "❌ Build failed!"
    exit 1
fi

echo "✅ Build successful"
echo ""

# Run the test
echo "Running Fissure Attack Test..."
echo "This may take 35+ seconds..."
echo ""

# Run test and capture output
TEST_OUTPUT=$(cargo test --release --package consensus-core --lib fissure_attack_test::test_fissure_attack_asr_13_nodes -- --nocapture 2>&1)

# Save full output to file
echo "$TEST_OUTPUT" > fissure_attack_test_output.log

# Extract ASR from output
ASR=$(echo "$TEST_OUTPUT" | grep -oP "Attack Success Rate: \K[0-9.]+" | head -1)

if [ -z "$ASR" ]; then
    echo "❌ Could not extract ASR from test output"
    echo "Full output saved to: fissure_attack_test_output.log"
    echo ""
    echo "Last 50 lines of output:"
    echo "$TEST_OUTPUT" | tail -50
    exit 1
fi

echo "=========================================="
echo "RESULTS"
echo "=========================================="
echo "Attack Success Rate (ASR): ${ASR}%"
echo ""
echo "Comparison:"
echo "  Bullshark Baseline: ~87.0%"
echo "  MEVSUI Result: ${ASR}%"
echo ""

# Determine if MEV mitigations were effective
ASR_FLOAT=$(echo "$ASR" | bc -l 2>/dev/null || echo "$ASR" | awk '{print $1}')

if (( $(echo "$ASR_FLOAT < 60.0" | bc -l 2>/dev/null || echo "0") )); then
    echo "✅ MEV mitigations appear effective (ASR < 60%)"
elif (( $(echo "$ASR_FLOAT > 80.0" | bc -l 2>/dev/null || echo "0") )); then
    echo "⚠️  MEV mitigations may not be effective (ASR > 80%, similar to Bullshark)"
else
    echo "⚠️  MEV mitigations partially effective (ASR between 60-80%)"
fi

echo ""
echo "Full test output saved to: fissure_attack_test_output.log"
echo "=========================================="

