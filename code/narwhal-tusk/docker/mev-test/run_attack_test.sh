#!/bin/bash
# MEV Attack Test Runner for Narwhal-Tusk Docker
set -e

echo "========================================"
echo "Narwhal-Tusk MEV Attack Test Runner"
echo "========================================"
echo "Attack Mode: $ATTACK_MODE"
echo "Nodes: ${NUM_NODES:-15}"
echo "Attacker Ratio: ${ATTACKER_RATIO:-0.33}"
echo "Victim Ratio: ${VICTIM_RATIO:-0.22}"
echo "Duration: ${DURATION:-35}"
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
# Final grep to ensure the sweeper can find the result even if it's buried in logs
grep "FINAL_ASR_RESULT:" /app/results/test_output.log || echo "FINAL_ASR_RESULT: 0.0% (No result found)"

# Output final line for parsing by test_runner.py
FINAL_ASR=$(grep "FINAL_ASR_RESULT:" /app/results/test_output.log | tail -1 | sed -n 's/.*FINAL_ASR_RESULT: \([0-9.]*\)%.*/\1/p')
if [ ! -z "$FINAL_ASR" ]; then
    echo "FINAL_ASR=$FINAL_ASR" > /app/results/asr_result.txt
    echo "Final ASR: $FINAL_ASR%"
else
    # Fallback to general ASR if FINAL_ASR_RESULT is missing
    ALT_ASR=$(grep -E "(ASR|Attack Success Rate)" /app/results/test_output.log | tail -1 | grep -o '[0-9.]\+%' | sed 's/%//')
    if [ ! -z "$ALT_ASR" ]; then
        echo "FINAL_ASR=$ALT_ASR" > /app/results/asr_result.txt
        echo "Final ASR (fallback): $ALT_ASR%"
    else
        echo "FINAL_ASR=UNKNOWN" > /app/results/asr_result.txt
        echo "ERROR: Could not parse ASR from output"
    fi
fi
