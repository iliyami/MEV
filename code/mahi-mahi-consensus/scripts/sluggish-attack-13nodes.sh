#!/bin/bash
# Copyright (c) Mysten Labs, Inc.
# SPDX-License-Identifier: Apache-2.0

# Sluggish Attack Test with 13 nodes
# Attacker: Node 0, Victim: Node 1

ATTACK_MODE=${1:-"sluggish"}
SLUGGISH_MULTIPLIER=${2:-"2.0"}
HYBRID_EXCLUSION=${3:-"0.05"}

echo "🐌 Starting Sluggish Attack Test with 13 nodes"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Attacker: Node 0"
echo "Victim: Node 1"
echo "Attack Mode: $ATTACK_MODE"
echo "Sluggish Multiplier: ${SLUGGISH_MULTIPLIER}x"
if [ "$ATTACK_MODE" = "hybrid_sluggish" ]; then
    echo "Hybrid Exclusion Rate: $(echo "$HYBRID_EXCLUSION * 100" | bc)%"
fi
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

output_dir=logs/sluggish-attack/
rm -rf ${output_dir}
mkdir -p ${output_dir}

# Kill any existing processes
pkill -f mysticeti
sleep 2

echo "📦 Building Mahi-Mahi..."
cargo build --release
if [ $? -ne 0 ]; then
    echo "❌ Build failed!"
    exit 1
fi
echo "✅ Build successful"

# Export logging configuration
export RUST_LOG=info,mysticeti_core::consensus=debug,mysticeti_core::core=info

# Export attack configuration
export ATTACK_MODE=$ATTACK_MODE
export ATTACKER_ID=0
export VICTIM_ID=1
export SLUGGISH_MULTIPLIER=$SLUGGISH_MULTIPLIER
export HYBRID_EXCLUSION=$HYBRID_EXCLUSION

echo ""
echo "🚀 Starting 13 nodes..."

# Start Node 0 (ATTACKER) with attack enabled
nohup ./target/release/mysticeti dry-run --committee-size 13 --authority 0 > ${output_dir}v0.log 2>&1 &
sleep 0.5

# Start remaining nodes (Node 1 is VICTIM, others are honest)
for i in {1..12}; do
    nohup ./target/release/mysticeti dry-run --committee-size 13 --authority $i > ${output_dir}v${i}.log 2>&1 &
    sleep 0.5
done

echo "✅ All 13 nodes started"
echo ""
echo "⏳ Running consensus for 120 seconds..."
echo "   (Attacker applying timing delays...)"

# Let the system run for 120 seconds
sleep 120

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





