#!/bin/bash
set -e

# This script is the entrypoint for AlephBFT attack tests in Docker.
# It uses environment variables to configure the attack.

# Default values
ATTACK_MODE=${ATTACK_MODE:-"fissure"}
ATTACK_TYPE=${ATTACK_TYPE:-"frontrun"}
NETWORK_SIZE=${NETWORK_SIZE:-"13"}
ATTACKER_RATIO=${ATTACKER_RATIO:-"0.308"}
VICTIM_RATIO=${VICTIM_RATIO:-"0.231"}
TEST_DURATION_SECONDS=${TEST_DURATION_SECONDS:-"30"}
SPECULATIVE_P_MAX=${SPECULATIVE_P_MAX:-"50"}
SLUGGISH_PROCESSING_DELAY_MS=${SLUGGISH_PROCESSING_DELAY_MS:-"11"}

echo "--- AlephBFT Attack Test Configuration ---"
echo "Mode: $ATTACK_MODE"
echo "Type: $ATTACK_TYPE"
echo "Network Size: $NETWORK_SIZE"
echo "Attacker Ratio: $ATTACKER_RATIO"
echo "Victim Ratio: $VICTIM_RATIO"
echo "Duration: $TEST_DURATION_SECONDS s"
echo "------------------------------------------"

# Ensure results directory exists
mkdir -p /app/results

# Export variables for the Rust test to pick up
export ATTACK_MODE
export ATTACK_TYPE
export NETWORK_SIZE
export ATTACKER_RATIO
export VICTIM_RATIO
export TEST_DURATION_SECONDS
export SPECULATIVE_P_MAX
export SLUGGISH_PROCESSING_DELAY_MS

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
# Use a temporary file for the full output to avoid masking the pipe exit code
TMP_LOG="/tmp/test_output.log"
cargo test --release --package aleph-bft --lib $TEST_NAME -- --nocapture 2>&1 | tee $TMP_LOG

# Extract ASR from output
# Expected format in AlephBFT: "Attack Success Rate (ASR): XX.XX%"
ASR=$(grep "Attack Success Rate (ASR):" $TMP_LOG | tail -n 1 | sed 's/.*ASR): \([0-9.]*\)%/\1/')

if [ -z "$ASR" ]; then
    # Fallback for baseline or if using the new advanced runner
    ASR=$(grep "ASR-F (Frontrun):" $TMP_LOG | tail -n 1 | sed 's/.*Frontrun): \([0-9.]*\)%/\1/')
fi

if [ -z "$ASR" ] && [[ "$ATTACK_TYPE" == "backrun" ]]; then
    ASR=$(grep "ASR-B (Overall/LX):" $TMP_LOG | tail -n 1 | sed 's/.*LX): \([0-9.]*\)%/\1/')
fi

if [ -z "$ASR" ] && [[ "$ATTACK_TYPE" == "sandwich" ]]; then
    ASR=$(grep "Sandwich Efficiency (SeSR):" $TMP_LOG | tail -n 1 | sed 's/.*SeSR): \([0-9.]*\)%/\1/')
fi

if [ -z "$ASR" ]; then
    echo "Error: Could not extract ASR from test output."
    exit 1
fi

echo "Extracted ASR: $ASR"
echo "FINAL_ASR=$ASR" > /app/results/asr_result.txt

# Preserve important JSON stats for the sweeper to parse from container logs
grep "FINAL_BACKRUN_STATS:" $TMP_LOG || true
grep "FINAL_SANDWICH_STATS:" $TMP_LOG || true
grep "FINAL_ASR_RESULT:" $TMP_LOG || true

echo "Test completed. Results saved to /app/results/asr_result.txt"
