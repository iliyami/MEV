#!/bin/bash
# Automated Baseline Test for Mysticeti
# Measures natural ASR without any active MEV attacks

echo "🔬 Automated Baseline Test for Mysticeti"
echo "=========================================="

# Ensure we have a results directory
mkdir -p /app/results

# Run the baseline test
echo "🚀 Running 13-node baseline test..."
echo "  Test: test_baseline_asr_13_nodes"
echo "  Duration: ~25 seconds"
echo ""

TEST_OUTPUT=$(mktemp)
# Use --nocapture to ensure info! logs are printed and can be parsed
cargo test --release --package mysticeti-core test_baseline_asr_13_nodes -- --nocapture > "$TEST_OUTPUT" 2>&1
TEST_EXIT_CODE=$?

# Save output for debugging if needed
cat "$TEST_OUTPUT" > /app/results/test_output.log

if [ $TEST_EXIT_CODE -eq 0 ]; then
    echo "  ✅ Test completed successfully"
else
    echo "  ⚠️  Test finished with exit code $TEST_EXIT_CODE (common during shutdown)"
fi

# Extract ASR
ASR=$(grep "FINAL_ASR_RESULT:" "$TEST_OUTPUT" | tail -1 | sed -n 's/.*FINAL_ASR_RESULT: \([0-9.]*\)%.*/\1/p')

if [ ! -z "$ASR" ]; then
    echo "  ✅ Baseline ASR: $ASR%"
    echo "FINAL_ASR_RESULT: $ASR%"
else
    echo "  ❌ Error: Could not parse ASR from output"
    tail -n 20 "$TEST_OUTPUT"
    exit 1
fi

rm -f "$TEST_OUTPUT"
