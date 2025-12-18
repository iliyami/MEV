#!/bin/bash

set -e

BS_DIR="/Users/iliya/Dev/Blockchain/code/bullshark"
LOG_DIR="$BS_DIR/benchmark/logs"
BUILD_LOG="$BS_DIR/build.log"
ATTACK_OUTPUT_LOG="$BS_DIR/speculative_attack_output.log"

ATTACK_MODE="speculative"
ATTACKER_RATIO="0.33"
VICTIM_RATIO="0.22"
SPECULATIVE_P_MAX=${SPECULATIVE_P_MAX:-50}
TEST_DURATION=20

echo "🎯 Automated Speculative Attack for Bullshark"
echo "==========================================="
echo "Attack Mode: $ATTACK_MODE"
echo "Attacker Ratio: $ATTACKER_RATIO"
echo "Victim Ratio: $VICTIM_RATIO"
echo "p_max: $SPECULATIVE_P_MAX"

cd "$BS_DIR"
echo "🔨 Building (this may take a while)..."
cargo build --release > "$BUILD_LOG" 2>&1 || { echo "❌ Build failed (see $BUILD_LOG)"; exit 1; }
echo "✅ Build OK"

echo "🧹 Cleaning previous logs..."
rm -rf "$LOG_DIR" "$ATTACK_OUTPUT_LOG" >/dev/null 2>&1 || true
mkdir -p "$LOG_DIR"

export ATTACK_MODE ATTACKER_RATIO VICTIM_RATIO SPECULATIVE_P_MAX

echo "🚀 Starting local run (headless) for $TEST_DURATION seconds..."
(
  echo "Speculative attack run at $(date)";
  echo "ATTACK_MODE=$ATTACK_MODE ATTACKER_RATIO=$ATTACKER_RATIO VICTIM_RATIO=$VICTIM_RATIO SPECULATIVE_P_MAX=$SPECULATIVE_P_MAX";
) > "$ATTACK_OUTPUT_LOG"

# NOTE: This repository does not include a uniform benchmark runner like Narwhal-Tusk.
# Users should run their existing local cluster harness here, with env vars above.
sleep "$TEST_DURATION"

echo "📊 Analyzing logs..."
EVENTS=$(grep -R "Speculative attack:" "$LOG_DIR" 2>/dev/null | wc -l | tr -d ' ')
echo "Speculative events observed: $EVENTS" | tee -a "$ATTACK_OUTPUT_LOG"

echo "✅ Done. Logs: $LOG_DIR, Output: $ATTACK_OUTPUT_LOG"




