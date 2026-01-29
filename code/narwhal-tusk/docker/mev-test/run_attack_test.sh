#!/bin/bash
# MEV Attack Test Runner for Narwhal-Tusk Docker
set -e

echo "========================================"
echo "Narwhal-Tusk MEV Attack Test Runner"
echo "========================================"
echo "Attack Mode: $ATTACK_MODE"
echo "Test: ${TEST_NAME:-fissure}"
echo ""

cd /app

# Run the automated attack script based on attack mode
case "${ATTACK_MODE}" in
    "fissure")
        ./automated_fissure_attack.sh 2>&1 | tee /app/results/test_output.log
        ;;
    "speculative")
        ./automated_speculative_attack.sh 2>&1 | tee /app/results/test_output.log
        ;;
    "sluggish")
        ./automated_sluggish_attack.sh 2>&1 | tee /app/results/test_output.log
        ;;
    *)
        echo "Unknown attack mode: $ATTACK_MODE"
        exit 1
        ;;
esac

echo ""
echo "========================================"
echo "Results Summary"
echo "========================================"
grep -E "(ASR|Attack Success Rate)" /app/results/test_output.log || echo "No ASR found in output"
