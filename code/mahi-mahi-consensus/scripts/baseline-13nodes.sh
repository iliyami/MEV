# Configuration
NUM_NODES=${NUM_NODES:-13}
DURATION=${DURATION:-120}

echo "📊 Starting BASELINE Test with $NUM_NODES nodes (No Attack)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Duration: $DURATION seconds"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

output_dir=logs/baseline/
rm -rf ${output_dir}
mkdir -p ${output_dir}

pkill -f mysticeti || true
sleep 2

# Check if binary exists
if [ ! -f "./target/release/mysticeti" ]; then
    echo "📦 Building Mahi-Mahi..."
    cargo build --release > /dev/null 2>&1
fi

export RUST_LOG=info,mysticeti_core::consensus=debug,mysticeti_core::core=warn

echo "🚀 Starting $NUM_NODES nodes (NO ATTACK)..."

for i in $(seq 0 $((NUM_NODES-1))); do
    nohup ./target/release/mysticeti dry-run --committee-size $NUM_NODES --authority $i > ${output_dir}v${i}.log 2>&1 &
    sleep 0.1
done

echo "✅ All $NUM_NODES nodes started"
echo "⏳ Running consensus for $DURATION seconds..."

sleep $DURATION

echo "🛑 Stopping nodes..."
pkill -f mysticeti || true
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

