#!/bin/bash

# Speculative Attack Test Script for Mahi-Mahi (13 Nodes)
# Based on paper: https://eprint.iacr.org/2024/1496.pdf Section 4.2

set -e

# Configuration (set defaults if not already set)
export ATTACK_MODE=${ATTACK_MODE:-speculative}
export ATTACKER_ID=${ATTACKER_ID:-0}
export VICTIM_ID=${VICTIM_ID:-1}
export SPECULATIVE_STRATEGY=${SPECULATIVE_STRATEGY:-sophisticated}
export SPECULATIVE_P_MAX=${SPECULATIVE_P_MAX:-50}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
LOG_DIR="$REPO_DIR/logs/speculative-attack"

echo "🔮 Starting Mahi-Mahi Speculative Attack Test (13 Nodes)"
echo "=============================================="
echo "Attack Mode: $ATTACK_MODE"
echo "Attacker ID: $ATTACKER_ID"
echo "Victim ID: $VICTIM_ID"
echo "Strategy: $SPECULATIVE_STRATEGY"
echo "p_max: $SPECULATIVE_P_MAX"
echo ""

# Clean up previous logs
rm -rf "$LOG_DIR"
mkdir -p "$LOG_DIR"

# Navigate to repo
cd "$REPO_DIR"

# Check if binary exists
if [ ! -f "./target/release/mysticeti" ]; then
    echo "❌ Binary not found. Please run 'cargo build --release' first."
    exit 1
fi

# Kill any existing processes
pkill -f mysticeti || true
sleep 2

# Set logging
export RUST_LOG=info,mysticeti_core::consensus=debug,mysticeti_core::core=info

echo "🚀 Starting 13 validator nodes..."

# Start 13 nodes
for i in {0..12}; do
    nohup ./target/release/mysticeti dry-run --committee-size 13 --authority $i \
        > "$LOG_DIR/v${i}.log" 2>&1 &
    sleep 0.5
done

# Wait for consensus to establish
echo ""
echo "⏳ Running attack for 120 seconds..."
sleep 120

# Stop all nodes
echo ""
echo "🛑 Stopping all nodes..."
pkill -f mysticeti || true
sleep 2

# Clean up
rm -rf dryrun-validator-*
rm -f client-times-*.txt

echo ""
echo "✅ Attack test completed. Logs saved to: $LOG_DIR"
echo ""
echo "📊 To calculate ASR, run:"
echo "  python3 scripts/calculate-speculative-asr.py $LOG_DIR/v*.log"

