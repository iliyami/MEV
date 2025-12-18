#!/bin/bash

# Quick Test for Bullshark Fissure Attack
# This script tests if the attack code compiles and runs

echo "🧪 Quick Test: Bullshark Fissure Attack"
echo "======================================"

# Set attack environment
export ATTACK_MODE=fissure
export ATTACKER_RATIO=0.3
export VICTIM_RATIO=0.2

echo "Attack Configuration:"
echo "  ATTACK_MODE: $ATTACK_MODE"
echo "  ATTACKER_RATIO: $ATTACKER_RATIO"
echo "  VICTIM_RATIO: $VICTIM_RATIO"
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

# Test 2: Check if Sui binary exists
echo ""
echo "🔍 Test 2: Checking Sui binary..."
if [ -f "target/release/sui" ]; then
    echo "  ✅ Sui binary found"
else
    echo "  ❌ Sui binary not found - need to build first"
    exit 1
fi

# Test 3: Test Sui genesis with attack environment
echo ""
echo "🚀 Test 3: Testing Sui genesis with attack environment..."
./target/release/sui genesis --force > genesis_test.log 2>&1
if [ $? -eq 0 ]; then
    echo "  ✅ Sui genesis successful with attack environment"
else
    echo "  ❌ Sui genesis failed - check genesis_test.log"
    exit 1
fi

# Test 4: Quick Sui start test
echo ""
echo "⚡ Test 4: Quick Sui start test..."
timeout 10s ./target/release/sui start > sui_test.log 2>&1 &
SUI_PID=$!

sleep 5

# Check if Sui is running
if kill -0 $SUI_PID 2>/dev/null; then
    echo "  ✅ Sui started successfully with attack environment"
    kill $SUI_PID 2>/dev/null
else
    echo "  ❌ Sui failed to start - check sui_test.log"
    exit 1
fi

echo ""
echo "🎉 ALL TESTS PASSED!"
echo "==================="
echo "✅ Attack code compiles"
echo "✅ Sui binary available"
echo "✅ Genesis works with attack environment"
echo "✅ Sui starts with attack environment"
echo ""
echo "🚀 Ready to run full attack: ./automated_fissure_attack.sh"
echo ""
echo "📊 Expected Results:"
echo "  - ASR: ~87% (matching paper's target)"
echo "  - Network: 4 validators with fissure attack"
echo "  - Performance: Maintained during attack"

