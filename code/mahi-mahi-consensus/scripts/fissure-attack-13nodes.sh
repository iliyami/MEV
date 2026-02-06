#!/bin/bash
# Copyright (c) Mysten Labs, Inc.
# SPDX-License-Identifier: Apache-2.0

# Configuration (set defaults if not already set)
NUM_NODES=${NUM_NODES:-13}
DURATION=${DURATION:-120}
ATTACKER_ID=${ATTACKER_ID:-0}
VICTIM_ID=${VICTIM_ID:-1}
EXCLUSION_PROBABILITY=${EXCLUSION_PROBABILITY:-0.20}

echo "🎯 Starting Fissure Attack Test with $NUM_NODES nodes"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Attacker: Node $ATTACKER_ID"
echo "Victim: Node $VICTIM_ID"
echo "Exclusion Probability: $(echo "$EXCLUSION_PROBABILITY * 100" | bc | sed 's/\.00//')%"
echo "Duration: $DURATION seconds"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

output_dir=logs/fissure-attack/
rm -rf ${output_dir}
mkdir -p ${output_dir}

# Kill any existing processes aggressively
pkill -9 -f mysticeti || true
sleep 3

# Check if binary exists, build if not (for local runs)
if [ ! -f "./target/release/mysticeti" ]; then
    echo "📦 Building Mahi-Mahi..."
    cargo build --release
fi

# Export logging configuration
export RUST_LOG=info,mysticeti_core::consensus=debug,mysticeti_core::core=info

# Export attack configuration
export ATTACK_MODE=fissure
export ATTACKER_ID=$ATTACKER_ID
export VICTIM_ID=$VICTIM_ID
export EXCLUSION_PROBABILITY=$EXCLUSION_PROBABILITY

echo ""
echo "🚀 Starting $NUM_NODES nodes..."

# Start nodes
for i in $(seq 0 $((NUM_NODES-1))); do
    nohup ./target/release/mysticeti dry-run --committee-size $NUM_NODES --authority $i > ${output_dir}v${i}.log 2>&1 &
    sleep 0.1
done

echo "✅ All $NUM_NODES nodes started"
echo ""
echo "⏳ Running consensus for $DURATION seconds..."
echo "   (Collecting blocks and measuring ASR...)"

# Let the system run
sleep $DURATION

echo ""
echo "🛑 Stopping nodes..."
pkill -f mysticeti
sleep 2

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📊 Analyzing Results..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Run ASR analysis
python3 scripts/calculate-fissure-asr.py ${output_dir}v*.log

echo ""
echo "📝 Logs saved to: ${output_dir}"
echo ""

# Cleanup
rm -rf dryrun-validator-*
rm -f client-times-*.txt

echo "✅ Test complete!"

