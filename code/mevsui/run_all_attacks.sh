#!/bin/bash
# Automated Test Script for All Attacks on MEVSUI
# This script runs Fissure, Speculative, and Sluggish attacks and compares results with Bullshark

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=========================================="
echo "MEVSUI All Attacks Test Suite"
echo "=========================================="
echo ""

# Results storage
RESULTS_FILE="attack_results.txt"
rm -f "$RESULTS_FILE"

# Bullshark baselines
BULLSHARK_FISSURE_ASR=87.0
BULLSHARK_SPECULATIVE_ASR="TBD"
BULLSHARK_SLUGGISH_ASR=51.0

echo "Bullshark Baselines:"
echo "  Fissure: ${BULLSHARK_FISSURE_ASR}%"
echo "  Speculative: ${BULLSHARK_SPECULATIVE_ASR}"
echo "  Sluggish: ${BULLSHARK_SLUGGISH_ASR}%"
echo ""

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
    export ATTACKER_RATIO="0.308"  # 4/13
    export VICTIM_RATIO="0.231"    # 3/13
    
    # Set extra environment variables if provided
    if [ -n "$extra_env" ]; then
        eval "export $extra_env"
    fi
    
    echo "Attack Configuration:"
    echo "  ATTACK_MODE: $ATTACK_MODE"
    echo "  ATTACKER_RATIO: $ATTACKER_RATIO"
    echo "  VICTIM_RATIO: $VICTIM_RATIO"
    if [ -n "$SPECULATIVE_P_MAX" ]; then
        echo "  SPECULATIVE_P_MAX: $SPECULATIVE_P_MAX"
    fi
    if [ -n "$SLUGGISH_TIMEOUT_MULTIPLIER" ]; then
        echo "  SLUGGISH_TIMEOUT_MULTIPLIER: $SLUGGISH_TIMEOUT_MULTIPLIER"
    fi
    echo ""
    
    # Build if needed
    echo "Building MEVSUI consensus core..."
    cargo build --release --package consensus-core 2>&1 | grep -E "(Compiling|Finished|error)" || true
    
    # Run the test
    echo "Running ${attack_name} attack test..."
    echo "This may take 35+ seconds..."
    echo ""
    
    # Run test and capture output
    local test_output
    case "$attack_mode" in
        "fissure")
            test_output=$(cargo test --release --package consensus-core --lib fissure_attack_test::test_fissure_attack_asr_13_nodes -- --nocapture 2>&1)
            ;;
        "speculative")
            test_output=$(cargo test --release --package consensus-core --lib speculative_attack_test::test_speculative_attack_asr_13_nodes -- --nocapture 2>&1)
            ;;
        "sluggish")
            test_output=$(cargo test --release --package consensus-core --lib sluggish_attack_test::test_sluggish_attack_asr_13_nodes -- --nocapture 2>&1)
            ;;
    esac
    
    # Save output to file
    echo "$test_output" > "${attack_name}_attack_test_output.log"
    
    # Extract ASR from output
    local asr=$(echo "$test_output" | grep "Attack Success Rate:" | sed -E 's/.*Attack Success Rate: ([0-9.]+)%.*/\1/' | head -1)
    
    if [ -z "$asr" ]; then
        echo "❌ Could not extract ASR from test output"
        echo "Full output saved to: ${attack_name}_attack_test_output.log"
        echo ""
        echo "Last 50 lines of output:"
        echo "$test_output" | tail -50
        return 1
    fi
    
    echo "✅ ${attack_name} Attack ASR: ${asr}%"
    echo ""
    
    # Save result
    echo "${attack_name}:${asr}" >> "$RESULTS_FILE"
    
    return 0
}

# Run all attack tests
echo "Starting attack test suite..."
echo ""

# 1. Fissure Attack
run_attack_test "Fissure" "fissure" ""

# 2. Speculative Attack
run_attack_test "Speculative" "speculative" "SPECULATIVE_P_MAX=50"

# 3. Sluggish Attack
run_attack_test "Sluggish" "sluggish" "SLUGGISH_TIMEOUT_MULTIPLIER=2.0"

# Summary
echo "=========================================="
echo "RESULTS SUMMARY"
echo "=========================================="
echo ""

if [ -f "$RESULTS_FILE" ]; then
    echo "MEVSUI Results:"
    while IFS=':' read -r attack asr; do
        echo "  ${attack}: ${asr}%"
    done < "$RESULTS_FILE"
    echo ""
    
    echo "Comparison with Bullshark:"
    while IFS=':' read -r attack asr; do
        case "$attack" in
            "Fissure")
                baseline=$BULLSHARK_FISSURE_ASR
                diff=$(echo "$asr - $baseline" | bc -l 2>/dev/null || echo "N/A")
                echo "  ${attack}: MEVSUI ${asr}% vs Bullshark ${baseline}% (diff: ${diff}%)"
                ;;
            "Speculative")
                baseline=$BULLSHARK_SPECULATIVE_ASR
                echo "  ${attack}: MEVSUI ${asr}% vs Bullshark ${baseline}"
                ;;
            "Sluggish")
                baseline=$BULLSHARK_SLUGGISH_ASR
                diff=$(echo "$asr - $baseline" | bc -l 2>/dev/null || echo "N/A")
                echo "  ${attack}: MEVSUI ${asr}% vs Bullshark ${baseline}% (diff: ${diff}%)"
                ;;
        esac
    done < "$RESULTS_FILE"
else
    echo "❌ No results file found"
    exit 1
fi

echo ""
echo "=========================================="
echo "Test suite completed!"
echo "Full test outputs saved to: *_attack_test_output.log"
echo "Results summary saved to: $RESULTS_FILE"
echo "=========================================="

