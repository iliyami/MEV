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
# Runtime Dependency Fix (for Python 3.11+ compatibility)
# -----------------------------------------------------
echo "🔧 Checking/Fixing runtime dependencies..."
# Install iproute2 for 'tc' if missing
if ! command -v tc &> /dev/null; then
    echo "  Installing iproute2..."
    apt-get update && apt-get install -y iproute2
fi

# Use --break-system-packages if needed (Debian/Ubuntu 23.04+)
pip3 install --upgrade "fabric>=3.0.0" "invoke>=2.0.0" --break-system-packages || \
pip3 install --upgrade "fabric>=3.0.0" "invoke>=2.0.0"

# -----------------------------------------------------
# Tmux Setup (ensure background processes can run)
# -----------------------------------------------------
echo "🪟 Initializing tmux..."
mkdir -p /tmp/tmux-0
chmod 700 /tmp/tmux-0
tmux start-server || echo "⚠️ tmux start-server skipped"

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
# Emit only the last marker so outer parsers do not accidentally consume a stale
# or intermediate ASR line.
FINAL_ASR_LINE=$(grep "FINAL_ASR_RESULT:" /app/results/test_output.log | tail -1 || true)
if [ -z "$FINAL_ASR_LINE" ]; then
    FINAL_ASR_LINE="FINAL_ASR_RESULT: UNKNOWN"
fi
echo "$FINAL_ASR_LINE"

# Output final line for parsing by test_runner.py
FINAL_ASR=$(echo "$FINAL_ASR_LINE" | sed -n 's/.*FINAL_ASR_RESULT:[[:space:]]*//p' | tr -d '\r' | sed 's/%$//')
if [ -n "$FINAL_ASR" ]; then
    echo "FINAL_ASR=$FINAL_ASR" > /app/results/asr_result.txt
    if [ "$FINAL_ASR" = "UNKNOWN" ] || [ "$FINAL_ASR" = "N/A" ]; then
        echo "Final ASR: $FINAL_ASR"
    else
        echo "Final ASR: $FINAL_ASR%"
    fi
else
    echo "FINAL_ASR=UNKNOWN" > /app/results/asr_result.txt
    echo "ERROR: Could not parse ASR from output"
fi
