#!/bin/bash
# Baseline Test (No Attack) with 13 nodes

echo "📊 Starting BASELINE Test with 13 nodes (No Attack)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

output_dir=logs/baseline/
rm -rf ${output_dir}
mkdir -p ${output_dir}

pkill -f mysticeti
sleep 2

echo "📦 Building Mahi-Mahi..."
cargo build --release > /dev/null 2>&1

export RUST_LOG=info,mysticeti_core::consensus=debug,mysticeti_core::core=warn

echo "🚀 Starting 13 nodes (NO ATTACK)..."

for i in {0..12}; do
    nohup ./target/release/mysticeti dry-run --committee-size 13 --authority $i > ${output_dir}v${i}.log 2>&1 &
    sleep 0.5
done

echo "✅ All 13 nodes started"
echo "⏳ Running consensus for 120 seconds..."

sleep 120

echo "🛑 Stopping nodes..."
pkill -f mysticeti
sleep 2

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📊 Analyzing Baseline Results..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

python3 scripts/calculate-fissure-asr.py ${output_dir}v*.log

echo "📝 Logs saved to: ${output_dir}"
rm -rf dryrun-validator-*
rm -f client-times-*.txt

echo "✅ Baseline test complete!"

