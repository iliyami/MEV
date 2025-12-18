#!/bin/bash

# Realistic ASR Calculation
# This script runs a test and calculates BOTH traditional and effective ASR

echo "======================================="
echo "    REALISTIC ASR EVALUATION"
echo "======================================="
echo ""

# Configuration from environment or defaults
STRATEGY=${SPECULATIVE_STRATEGY:-simple}
EXCLUSION=${SIMPLE_EXCLUSION_PROB:-0.05}

echo "Testing: $STRATEGY strategy with exclusion=$EXCLUSION"
echo ""

# Count blocks from simple grep patterns
echo "Analyzing attack results..."

# Count attacker activity vs others
ATTACKER_LOGS=$(wc -l logs/speculative-attack/v0.log 2>/dev/null | awk '{print $1}')
VICTIM_LOGS=$(wc -l logs/speculative-attack/v1.log 2>/dev/null | awk '{print $1}')
AVG_LOGS=$(ls logs/speculative-attack/v*.log 2>/dev/null | xargs wc -l | tail -1 | awk '{print int($1/13)}')

echo "📊 Activity Analysis:"
echo "  Attacker log lines: $ATTACKER_LOGS"
echo "  Victim log lines: $VICTIM_LOGS"
echo "  Average log lines: $AVG_LOGS"

# Calculate participation rate
if [ "$AVG_LOGS" -gt 0 ]; then
    PARTICIPATION=$(echo "scale=2; $ATTACKER_LOGS * 100 / $AVG_LOGS" | bc)
    echo "  Attacker participation: ${PARTICIPATION}%"
else
    PARTICIPATION=0
fi

echo ""

# Determine if attack is sustainable
if (( $(echo "$PARTICIPATION < 50" | bc -l) )); then
    echo "❌ UNSUSTAINABLE: Attacker is isolated (${PARTICIPATION}% participation)"
    echo "   The attacker has lost connectivity to the network."
    echo "   Any ASR measurement is meaningless."
elif (( $(echo "$PARTICIPATION < 80" | bc -l) )); then
    echo "⚠️  DEGRADED: Attacker has reduced participation (${PARTICIPATION}%)"
    echo "   The attack is causing connectivity issues."
else
    echo "✅ SUSTAINABLE: Attacker maintains good participation (${PARTICIPATION}%)"
    echo "   The attack appears sustainable."
fi

echo ""
echo "======================================="

# Now run the original ASR calculation
python3 scripts/calculate-speculative-asr.py logs/speculative-attack/v*.log 2>/dev/null | tail -20

echo ""
echo "💡 Reality Check:"
if (( $(echo "$PARTICIPATION < 50" | bc -l) )); then
    echo "Any high ASR is an artifact of isolation - the attack has FAILED."
else
    echo "The ASR above appears to be realistic given good participation."
fi





