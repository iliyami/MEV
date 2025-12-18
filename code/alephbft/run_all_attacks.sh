#!/bin/bash
# Automated Test Script for All Attacks on AlephBFT
# This script runs Fissure, Speculative, and Sluggish attacks and measures ASRs
#
# Usage: ./run_all_attacks.sh [config_file] [attack_name]
#   config_file: Optional YAML configuration file (default: experimental_config.yaml)
#   attack_name: Optional attack to run (fissure, speculative, sluggish, or "all" for all attacks)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Parse arguments
CONFIG_FILE="${1:-experimental_config.yaml}"
ATTACK_TO_RUN="${2:-all}"

echo "=========================================="
echo "AlephBFT All Attacks Test Suite"
echo "=========================================="
echo ""

# Load configuration from YAML if file exists
if [ -f "$CONFIG_FILE" ]; then
    echo "Loading configuration from: $CONFIG_FILE"
    source scripts/load_config.sh "$CONFIG_FILE"
    echo ""
else
    echo "Warning: Configuration file not found: $CONFIG_FILE"
    echo "Using default configuration values"
    echo ""
    
    # Default configuration (backward compatibility)
    export NETWORK_SIZE="${NETWORK_SIZE:-13}"
    export ATTACKER_RATIO="${ATTACKER_RATIO:-0.308}"
    export VICTIM_RATIO="${VICTIM_RATIO:-0.231}"
    export TEST_DURATION_SECONDS="${TEST_DURATION_SECONDS:-35}"
    export SPECULATIVE_P_MAX="${SPECULATIVE_P_MAX:-50}"
    export SLUGGISH_PROCESSING_DELAY_MS="${SLUGGISH_PROCESSING_DELAY_MS:-11}"
fi

# Results storage
RESULTS_DIR="${TEST_OUTPUT_DIR:-attack_results}"
mkdir -p "$RESULTS_DIR"
rm -f "$RESULTS_DIR"/*.log "$RESULTS_DIR"/*.txt 2>/dev/null || true

# Function to run an attack test and extract ASR
run_attack_test() {
    local attack_name=$1
    local attack_mode=$2
    local extra_env=$3
    
    echo "=========================================="
    echo "Running ${attack_name} Attack Test"
    echo "=========================================="
    echo ""
    
    # Set attack parameters
    export ATTACK_MODE="$attack_mode"
    
    # Set extra environment variables if provided
    if [ -n "$extra_env" ]; then
        eval "export $extra_env"
    fi
    
    echo "Attack Configuration:"
    echo "  ATTACK_MODE: $ATTACK_MODE"
    echo "  NETWORK_SIZE: ${NETWORK_SIZE:-13}"
    echo "  ATTACKER_RATIO: ${ATTACKER_RATIO:-0.308}"
    echo "  VICTIM_RATIO: ${VICTIM_RATIO:-0.231}"
    echo "  TEST_DURATION_SECONDS: ${TEST_DURATION_SECONDS:-35}"
    if [ -n "$SPECULATIVE_P_MAX" ]; then
        echo "  SPECULATIVE_P_MAX: $SPECULATIVE_P_MAX"
    fi
    if [ -n "$SLUGGISH_PROCESSING_DELAY_MS" ]; then
        echo "  SLUGGISH_PROCESSING_DELAY_MS: $SLUGGISH_PROCESSING_DELAY_MS"
    fi
    echo ""
    
    # Build if needed
    echo "Building AlephBFT..."
    cargo build --release --package aleph-bft 2>&1 | grep -E "(Compiling|Finished|error)" || true
    echo ""
    
    # Run the test
    echo "Running ${attack_name} attack test..."
    echo "This may take ${TEST_DURATION_SECONDS:-35}+ seconds..."
    echo ""
    
    # Run test and capture output
    local test_output
    local output_file="$RESULTS_DIR/${attack_name}_attack_test_output.log"
    
    case "$attack_mode" in
        "fissure")
            test_output=$(cargo test --release --package aleph-bft --lib attack_tests::fissure_attack_test::test_fissure_attack_asr_13_nodes -- --nocapture 2>&1 || true)
            ;;
        "speculative")
            test_output=$(cargo test --release --package aleph-bft --lib attack_tests::speculative_attack_test::test_speculative_attack_asr_13_nodes -- --nocapture 2>&1 || true)
            ;;
        "sluggish")
            test_output=$(cargo test --release --package aleph-bft --lib attack_tests::sluggish_attack_test::test_sluggish_attack_asr_13_nodes -- --nocapture 2>&1 || true)
            ;;
    esac
    
    # Save output to file
    echo "$test_output" > "$output_file"
    
    # Extract ASR from output (look for "ASR: XX.XX%")
    local asr=$(echo "$test_output" | grep -oE "Attack Success Rate \(ASR\): [0-9]+\.[0-9]+%" | tail -1 | grep -oE "[0-9]+\.[0-9]+" || echo "")
    
    if [ -z "$asr" ]; then
        echo "❌ Could not extract ASR from test output"
        echo "Full output saved to: $output_file"
        echo ""
        echo "Last 50 lines of output:"
        echo "$test_output" | tail -50
        echo "N/A" > "$RESULTS_DIR/${attack_name}_asr.txt"
        return 1
    fi
    
    echo "✅ ${attack_name} Attack ASR: ${asr}%"
    echo "$asr" > "$RESULTS_DIR/${attack_name}_asr.txt"
    echo ""
    
    return 0
}

# Run attacks based on argument
echo "Starting attack tests..."
echo ""

if [ "$ATTACK_TO_RUN" = "all" ] || [ "$ATTACK_TO_RUN" = "fissure" ]; then
    run_attack_test "fissure" "fissure" ""
fi

if [ "$ATTACK_TO_RUN" = "all" ] || [ "$ATTACK_TO_RUN" = "speculative" ]; then
    run_attack_test "speculative" "speculative" "SPECULATIVE_P_MAX=${SPECULATIVE_P_MAX:-50}"
fi

if [ "$ATTACK_TO_RUN" = "all" ] || [ "$ATTACK_TO_RUN" = "sluggish" ]; then
    run_attack_test "sluggish" "sluggish" "SLUGGISH_PROCESSING_DELAY_MS=${SLUGGISH_PROCESSING_DELAY_MS:-11}"
fi

# Summary
echo "=========================================="
echo "Attack Success Rate Summary"
echo "=========================================="
echo ""

FISSURE_ASR="N/A"
SPECULATIVE_ASR="N/A"
SLUGGISH_ASR="N/A"

if [ -f "$RESULTS_DIR/fissure_asr.txt" ]; then
    FISSURE_ASR=$(cat "$RESULTS_DIR/fissure_asr.txt")
fi

if [ -f "$RESULTS_DIR/speculative_asr.txt" ]; then
    SPECULATIVE_ASR=$(cat "$RESULTS_DIR/speculative_asr.txt")
fi

if [ -f "$RESULTS_DIR/sluggish_asr.txt" ]; then
    SLUGGISH_ASR=$(cat "$RESULTS_DIR/sluggish_asr.txt")
fi

echo "Fissure Attack ASR:    ${FISSURE_ASR}%"
echo "Speculative Attack ASR: ${SPECULATIVE_ASR}%"
echo "Sluggish Attack ASR:    ${SLUGGISH_ASR}%"
echo ""

# Calculate average if all ASRs are available
if [ "$FISSURE_ASR" != "N/A" ] && [ "$SPECULATIVE_ASR" != "N/A" ] && [ "$SLUGGISH_ASR" != "N/A" ]; then
    AVERAGE_ASR=$(echo "scale=2; ($FISSURE_ASR + $SPECULATIVE_ASR + $SLUGGISH_ASR) / 3" | bc)
    echo "Average ASR:           ${AVERAGE_ASR}%"
    echo ""
fi

echo "✅ All tests completed!"
echo "📁 Results saved in: $RESULTS_DIR/"
echo ""

