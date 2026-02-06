#!/bin/bash
# Copyright (c) Mysten Labs, Inc.
# SPDX-License-Identifier: Apache-2.0

# Sluggish Attack Test with 13 nodes
# Attacker: Node 0, Victim: Node 1

ATTACK_MODE=${1:-"sluggish"}
SLUGGISH_MULTIPLIER=${2:-"2.0"}
HYBRID_EXCLUSION=${3:-"0.05"}

# Configuration (set defaults if not already set)
NUM_NODES=${NUM_NODES:-13}
DURATION=${DURATION:-120}
ATTACK_MODE=${ATTACK_MODE:-"sluggish"}
SLUGGISH_MULTIPLIER=${SLUGGISH_MULTIPLIER:-"2.0"}
HYBRID_EXCLUSION=${HYBRID_EXCLUSION:-"0.05"}

echo "🐌 Starting Sluggish Attack Test with $NUM_NODES nodes"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Attacker: Node 0"
echo "Victim: Node 1"
echo "Attack Mode: $ATTACK_MODE"
echo "Sluggish Multiplier: ${SLUGGISH_MULTIPLIER}x"
if [ "$ATTACK_MODE" = "hybrid_sluggish" ]; then
    echo "Hybrid Exclusion Rate: $(echo "$HYBRID_EXCLUSION * 100" | bc | sed 's/\.00//')%"
fi
echo "Duration: $DURATION seconds"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

output_dir=logs/sluggish-attack/
rm -rf ${output_dir}
mkdir -p ${output_dir}

# Kill any existing processes
pkill -f mysticeti || true
sleep 2

# Check if binary exists
if [ ! -f "./target/release/mysticeti" ]; then
    echo "📦 Building Mahi-Mahi..."
    cargo build --release
fi

# Export logging configuration
export RUST_LOG=info,mysticeti_core::consensus=debug,mysticeti_core::core=info

# Export attack configuration
export ATTACK_MODE=$ATTACK_MODE
export ATTACKER_ID=0
export VICTIM_ID=1
export SLUGGISH_MULTIPLIER=$SLUGGISH_MULTIPLIER
export HYBRID_EXCLUSION=$HYBRID_EXCLUSION

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
echo "   (Attacker applying timing delays...)"

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
python3 scripts/calculate-sluggish-asr.py ${output_dir}v*.log

echo ""
echo "📝 Logs saved to: ${output_dir}"
echo ""

# Cleanup
rm -rf dryrun-validator-*
rm -f client-times-*.txt

echo "✅ Test complete!"





