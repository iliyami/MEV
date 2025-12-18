#!/bin/bash

set -e

echo "🧪 Testing Speculative Attack (Bullshark)"
echo "========================================"

cd /Users/iliya/Dev/Blockchain/code/bullshark

export ATTACK_MODE="speculative"
export ATTACKER_RATIO="0.33"
export VICTIM_RATIO="0.22"
export SPECULATIVE_P_MAX="20"

echo "🔨 cargo check --release"
cargo check --release >/dev/null 2>&1 && echo "✅ Build OK" || { echo "❌ Build failed"; exit 1; }

echo "🚀 Short dry-run placeholder (no orchestrator available in-tree)"
sleep 3

echo "📄 Grepping runtime logs if any exist"
LOG_DIR="/Users/iliya/Dev/Blockchain/code/bullshark/benchmark/logs"
[ -d "$LOG_DIR" ] && grep -R "Speculative attack:" "$LOG_DIR" | tail -5 || echo "(no logs found)"

echo "🎯 Test completed"




