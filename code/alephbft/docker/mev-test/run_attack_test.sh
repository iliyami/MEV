#!/bin/bash
set -e

# This script is the entrypoint for AlephBFT attack tests in Docker.
# It uses environment variables to configure the attack.

# Default values
ATTACK_MODE=${ATTACK_MODE:-"fissure"}
ATTACKER_RATIO=${ATTACKER_RATIO:-"0.308"}
VICTIM_RATIO=${VICTIM_RATIO:-"0.231"}
NETWORK_SIZE=${NETWORK_SIZE:-"13"}
TEST_DURATION_SECONDS=${TEST_DURATION_SECONDS:-"30"}
SPECULATIVE_P_MAX=${SPECULATIVE_P_MAX:-"50"}
SLUGGISH_PROCESSING_DELAY_MS=${SLUGGISH_PROCESSING_DELAY_MS:-"11"}

echo "--- AlephBFT Attack Test Configuration ---"
echo "Mode: $ATTACK_MODE"
echo "Network Size: $NETWORK_SIZE"
echo "Attacker Ratio: $ATTACKER_RATIO"
echo "Victim Ratio: $VICTIM_RATIO"
echo "Duration: $TEST_DURATION_SECONDS s"
echo "------------------------------------------"

# Ensure results directory exists
mkdir -p /app/results

# Map attack mode to cargo test command
# Note: In AlephBFT, we use the 13-node test as the standard benchmark
case "$ATTACK_MODE" in
    "fissure")
        TEST_NAME="attack_tests::fissure_attack_test::test_fissure_attack_asr_13_nodes"
        ;;
    "speculative")
        TEST_NAME="attack_tests::speculative_attack_test::test_speculative_attack_asr_13_nodes"
        ;;
    "sluggish")
        TEST_NAME="attack_tests::sluggish_attack_test::test_sluggish_attack_asr_13_nodes"
        ;;
    *)
        echo "Error: Unknown attack mode $ATTACK_MODE"
        exit 1
        ;;
esac

echo "Running test: $TEST_NAME"

# Run the test and capture output
# We use --nocapture to see the ASR output in logs
# We use || true because tests might panic during shutdown but still produce results
cargo test --release --package aleph-bft --lib $TEST_NAME -- --nocapture > /app/results/test_output.log 2>&1 || true

# Extract ASR from output
# Expected format in AlephBFT: "Attack Success Rate (ASR): XX.XX%"
ASR=$(grep "Attack Success Rate (ASR):" /app/results/test_output.log | tail -n 1 | sed 's/.*ASR): \([0-9.]*\)%/\1/')

if [ -z "$ASR" ]; then
    echo "Error: Could not extract ASR from test output."
    cat /app/results/test_output.log
    exit 1
fi

echo "Extracted ASR: $ASR"
echo "FINAL_ASR=$ASR" > /app/results/asr_result.txt

echo "Test completed. Results saved to /app/results/asr_result.txt"
