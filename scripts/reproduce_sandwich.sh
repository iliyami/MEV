#!/bin/bash
# Reproduce 19-Node Sandwich Attack (SeSR ~48%)
# This wrapper ensures all environment variables are set correctly to bypass Docker/Sandbox issues.

export NUM_NODES=19
export ATTACKER_RATIO=0.37
export VICTIM_RATIO=0.22
export ATTACK_TYPE=sandwich
export ATTACK_MODE=speculative

# Use the robust local runner script
echo "Starting 19-Node Sandwich Attack Experiment..."
echo "Configuration:"
echo "  Nodes: $NUM_NODES"
echo "  Attackers: 7 (Ratio $ATTACKER_RATIO)"
echo "  Victims: 4 (Ratio $VICTIM_RATIO)"
echo "  Type: $ATTACK_TYPE"
echo ""

bash scripts/run_backrun_local.sh
