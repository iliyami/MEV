#!/bin/bash

# Quick Test for Bullshark Sluggish Attack
# This script tests if the attack code compiles and runs

echo "🐌 Quick Test: Bullshark Sluggish Attack"
echo "========================================"

# Set attack environment
export ATTACK_MODE=sluggish
export ATTACKER_RATIO=0.3
export VICTIM_RATIO=0.2
export SLUGGISH_TIMEOUT_MULTIPLIER=2.0

echo "Attack Configuration:"
echo "  ATTACK_MODE: $ATTACK_MODE"
echo "  ATTACKER_RATIO: $ATTACKER_RATIO"
echo "  VICTIM_RATIO: $VICTIM_RATIO"
echo "  SLUGGISH_TIMEOUT_MULTIPLIER: $SLUGGISH_TIMEOUT_MULTIPLIER"
echo ""

# Test 1: Check if attack code compiles
echo "🔨 Test 1: Compiling attack code..."
cargo check --release > compile_test.log 2>&1
if [ $? -eq 0 ]; then
    echo "  ✅ Attack code compiles successfully"
else
    echo "  ❌ Compilation failed - check compile_test.log"
    exit 1
fi

# Test 2: Quick build test
echo ""
echo "🏗️  Test 2: Building release binary..."
cargo build --release --quiet
if [ $? -eq 0 ]; then
    echo "  ✅ Release build successful"
else
    echo "  ❌ Release build failed"
    exit 1
fi

echo ""
echo "🎉 ALL TESTS PASSED!"
echo "==================="
echo "✅ Attack code compiles"
echo "✅ Release build successful"
echo ""
echo "🚀 Ready to run full attack: ./automated_sluggish_attack.sh"
echo ""
echo "📊 Expected Results:"
echo "  - Attack Events: Delayed block proposal attempts"
echo "  - Timing Advantage: ${SLUGGISH_TIMEOUT_MULTIPLIER}x slower responses"
echo "  - Round Priority: Lower round numbers for higher ordering priority"


