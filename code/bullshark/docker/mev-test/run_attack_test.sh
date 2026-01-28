#!/bin/bash
# MEV Attack Test Runner for Docker
# Runs the specified attack test and outputs ASR results

set -e

echo "========================================"
echo "MEV Attack Test Runner"
echo "========================================"
echo "Attack Mode: $ATTACK_MODE"
echo "Nodes: ${NUM_NODES:-13}"
echo "Test Name: ${TEST_NAME:-test_fissure_attack_asr_dynamic}"
echo ""

# Run the test
cd /app
cargo test --release --package consensus-core ${TEST_NAME:-test_fissure_attack_asr_dynamic} -- --nocapture 2>&1 | tee /app/results/test_output.log

# Extract ASR from output
echo ""
echo "========================================"
echo "Results Summary"
echo "========================================"
# Capture the full results block starting with the 🎯 emoji
grep -A 10 "🎯 .* ATTACK RESULTS:" /app/results/test_output.log || grep -E "(ASR|Attack Success Rate)" /app/results/test_output.log || echo "No ASR found in output"

# Output final line for parsing
FINAL_ASR=$(grep "FINAL_ASR_RESULT:" /app/results/test_output.log | tail -1 | sed -n 's/.*FINAL_ASR_RESULT: \([0-9.]*\)%.*/\1/p')
if [ ! -z "$FINAL_ASR" ]; then
    echo "FINAL_ASR=$FINAL_ASR" > /app/results/asr_result.txt
    echo "Final ASR: $FINAL_ASR%"
else
    echo "FINAL_ASR=UNKNOWN" > /app/results/asr_result.txt
    echo "Could not parse ASR from output"
fi
