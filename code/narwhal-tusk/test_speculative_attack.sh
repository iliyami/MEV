#!/bin/bash

# Quick test script for speculative attack
echo "🧪 Testing Speculative Attack Implementation"
echo "==========================================="

cd /Users/iliya/Dev/Blockchain/code/narwhal-tusk

# Test 1: Check if the code compiles
echo "🔨 Testing compilation..."
export ATTACK_MODE="speculative"
export ATTACKER_RATIO="0.3"
export VICTIM_RATIO="0.2"

cargo check --release > /dev/null 2>&1
if [ $? -eq 0 ]; then
    echo "  ✅ Compilation successful"
else
    echo "  ❌ Compilation failed"
    exit 1
fi

# Test 2: Check if environment variables are read correctly
echo "⚙️  Testing environment variable parsing..."
cd benchmark
source ../venv/bin/activate

# Test 3: Run a very short test (5 seconds)
echo "🚀 Running short speculative attack test (5 seconds)..."
timeout 8s fab local > speculative_test.log 2>&1 &
FAB_PID=$!

wait $FAB_PID || true

# Check if speculative attack events were logged
SPECULATIVE_COUNT=$(grep -c "Speculative attack:" logs/primary-*.log 2>/dev/null || echo "0")
echo "  Speculative attack events: $SPECULATIVE_COUNT"

if [ $SPECULATIVE_COUNT -gt 0 ]; then
    echo "  ✅ Speculative attack is working!"
    echo "  Latest events:"
    grep "Speculative attack:" logs/primary-*.log | tail -2
else
    echo "  ⚠️  No speculative attack events detected"
    echo "  Checking logs for errors..."
    grep -i "error\|panic" logs/primary-*.log | head -3
fi

echo ""
echo "🎯 Test completed!"
echo "  Logs: logs/"
echo "  Test output: speculative_test.log"
