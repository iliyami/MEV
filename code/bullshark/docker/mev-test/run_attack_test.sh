#!/bin/bash
# MEV Attack Test Runner for Docker
# Runs the specified attack test and outputs ASR results

set -e
export RUST_LOG=consensus_core=debug,info

echo "========================================"
echo "MEV Attack Test Runner"
echo "========================================"
echo "Attack Mode: $ATTACK_MODE"
echo "Attack Type: $ATTACK_TYPE"
echo "Nodes: ${NUM_NODES:-13}"
echo "Attacker Ratio: $ATTACKER_RATIO"
echo "Victim Ratio: $VICTIM_RATIO"
echo "Test Name: ${TEST_NAME:-test_fissure_attack_asr_dynamic}"

echo "Attack Mode: $ATTACK_MODE" > /app/results/debug_vars.log
echo "Attack Type: $ATTACK_TYPE" >> /app/results/debug_vars.log
echo "Nodes: ${NUM_NODES:-13}" >> /app/results/debug_vars.log
echo "Attacker Ratio: $ATTACKER_RATIO" >> /app/results/debug_vars.log
echo "Victim Ratio: $VICTIM_RATIO" >> /app/results/debug_vars.log
echo "Test Name: ${TEST_NAME:-test_fissure_attack_asr_dynamic}" >> /app/results/debug_vars.log
chmod 666 /app/results/debug_vars.log

# -----------------------------------------------------
# Network Simulation (Geo-Distribution / Jitter) - Defense 2/3
# -----------------------------------------------------
if [ ! -z "$LATENCY_JITTER" ]; then
    echo "🌍 Applying Network Simulation: ${LATENCY_JITTER} delay"
    # We apply delay to loopback since all nodes run locally in this container
    # 'tc qdisc add dev lo root netem delay 100ms 20ms distribution normal'
    # Format expected: "100ms 20ms" (mean jitter) or just "50ms"
    tc qdisc add dev lo root netem delay $LATENCY_JITTER distribution normal || echo "⚠️ Failed to apply TC (check --cap-add=NET_ADMIN)"
    tc qdisc show dev lo
else 
    echo "🌍 Network Simulation: Disabled (Localhost Speed)"
fi

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
    echo "ERROR: Could not parse ASR from output"
    exit 1
fi
