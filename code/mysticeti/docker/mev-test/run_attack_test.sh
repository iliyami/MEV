#!/bin/bash
# MEV Attack Test Runner for Mysticeti Docker
set -e

echo "========================================"
echo "Mysticeti MEV Attack Test Runner"
echo "========================================"
echo "Attack Mode: $ATTACK_MODE"
echo "Nodes: ${NUM_NODES:-13}"
echo "Duration: ${DURATION:-120}"
echo ""

# -----------------------------------------------------
# Network Simulation (Geo-Distribution / Jitter)
# -----------------------------------------------------
if [ ! -z "$LATENCY_JITTER" ]; then
    echo "🌍 Applying Network Simulation: ${LATENCY_JITTER} delay"
    tc qdisc add dev lo root netem delay $LATENCY_JITTER distribution normal || echo "⚠️ Failed to apply TC (check --cap-add=NET_ADMIN)"
    tc qdisc show dev lo
else 
    echo "🌍 Network Simulation: Disabled (Localhost Speed)"
fi

echo ""

cd /app

# Ensure we have a results directory
mkdir -p /app/results

# Run the automated attack script based on attack mode
case "${ATTACK_MODE}" in
    "fissure")
        ./scripts/legacy_automation/automated_fissure_attack.sh 2>&1 | tee /app/results/test_output.log || true
        ;;
    "speculative")
        ./scripts/legacy_automation/automated_speculative_attack.sh 2>&1 | tee /app/results/test_output.log || true
        ;;
    "sluggish")
        ./scripts/legacy_automation/automated_sluggish_attack.sh 2>&1 | tee /app/results/test_output.log || true
        ;;
    "certification_race")
        ./scripts/legacy_automation/automated_certification_race_attack.sh 2>&1 | tee /app/results/test_output.log || true
        ;;
    "none")
        ./scripts/legacy_automation/automated_baseline_test.sh 2>&1 | tee /app/results/test_output.log || true
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

# Extract ASR from output for test_runner.py
# The scripts output "FINAL_ASR_RESULT: XX.XX%"
FINAL_ASR=$(grep -a "FINAL_ASR_RESULT:" /app/results/test_output.log | tail -1 | sed -n 's/.*FINAL_ASR_RESULT: \([0-9.]*\)%.*/\1/p')

if [ ! -z "$FINAL_ASR" ]; then
    echo "FINAL_ASR=$FINAL_ASR" > /app/results/asr_result.txt
    echo "FINAL_ASR_RESULT: $FINAL_ASR%"
    # Forward backrun/sandwich stats for the experiment sweeper to capture
    grep -a "FINAL_BACKRUN_STATS:" /app/results/test_output.log || true
    grep -a "FINAL_SANDWICH_STATS:" /app/results/test_output.log || true
    exit 0
else
    echo "ERROR: Could not parse ASR from output"
    # Dump tail of log for debugging
    tail -n 20 /app/results/test_output.log
    exit 1
fi
