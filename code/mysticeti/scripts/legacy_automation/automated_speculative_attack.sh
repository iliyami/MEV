#!/bin/bash

# Automated Speculative Attack Script for Mysticeti
# This script automates the entire process: build, run attack, calculate ASR
# Usage: ./automated_speculative_attack.sh

echo "🎯 Automated Speculative Attack for Mysticeti"
echo "=============================================="
echo "This script will:"
echo "  1. Build the Mysticeti project with attack code"
echo "  2. Run the 13-node network with speculative attack"
echo "  3. Calculate and display the ASR results"
echo ""

# Check if we're in the right directory
if [ ! -f "Cargo.toml" ]; then
    echo "❌ Error: Not in the correct directory"
    echo "Please run this from: /Users/iliya/Dev/Blockchain/code/mysticeti"
    exit 1
fi

# Step 1: Clean and build
echo "🔨 Step 1: Building Mysticeti project with attack code..."
cargo clean > /dev/null 2>&1
echo "  Cleaning build cache..."

cargo build --release > build.log 2>&1
if [ $? -eq 0 ]; then
    echo "  ✅ Build successful"
else
    echo "  ❌ Build failed - check build.log for details"
    exit 1
fi

# Step 2: Set attack environment
echo ""
echo "⚙️  Step 2: Configuring attack parameters..."
export ATTACK_MODE=${ATTACK_MODE:-speculative}
export ATTACKER_RATIO=${ATTACKER_RATIO:-0.308}
export VICTIM_RATIO=${VICTIM_RATIO:-0.231}
export WAVE_LENGTH=${WAVE_LENGTH:-3}
export NUMBER_OF_LEADERS=${NUMBER_OF_LEADERS:-1}
export LEADER_TIMEOUT_MS=${LEADER_TIMEOUT_MS:-2000}
export RUST_LOG=${RUST_LOG:-info}

echo "  Attack Mode: $ATTACK_MODE"
echo "  Attacker Ratio: $ATTACKER_RATIO (~30.8% - 4 validators)"
echo "  Victim Ratio: $VICTIM_RATIO (~23.1% - 3 validators)"
echo "  Network Size: 13 nodes"

# Step 3: Run the test
echo ""
echo "🚀 Step 3: Running 13-node speculative attack test..."
echo "  Test: test_speculative_attack_asr_13_nodes"
echo "  Duration: ~30 seconds"
echo "  Expected ASR: 85-95%"
echo ""

# Run the test and capture output
echo "  Executing test..."
TEST_OUTPUT=$(mktemp)
cargo test --release --package mysticeti-core test_speculative_attack_asr_13_nodes -- --nocapture > "$TEST_OUTPUT" 2>&1
TEST_EXIT_CODE=$?

if [ $TEST_EXIT_CODE -eq 0 ]; then
    echo "  ✅ Test completed successfully"
else
    echo "  ❌ Test failed - check output for details"
    cat "$TEST_OUTPUT"
    rm -f "$TEST_OUTPUT"
    exit 1
fi

# Step 4: Extract and display ASR results
echo ""
echo "📊 Step 4: Extracting ASR results..."
echo "====================================="

# Extract ASR from test output (stripping ANSI codes)
ASR=$(sed 's/\x1b\[[0-9;]*m//g' "$TEST_OUTPUT" | grep "Attack Success Rate" | tail -1 | grep -oE '[0-9]+\.[0-9]+%' | head -1)
ASR_CALC=$(sed 's/\x1b\[[0-9;]*m//g' "$TEST_OUTPUT" | grep "ASR calculation:" | tail -1)

if [ ! -z "$ASR" ]; then
    echo "  ✅ Attack Success Rate: $ASR"
    
    if [ ! -z "$ASR_CALC" ]; then
        echo "  📈 $ASR_CALC"
    fi
    
    # Extract additional metrics
    COMMITS=$(grep "Collected.*commits" "$TEST_OUTPUT" | tail -1)
    
    if [ ! -z "$COMMITS" ]; then
        echo "  $COMMITS"
    fi
    
    echo ""
    echo "🎯 COMPARISON WITH PAPER:"
    echo "========================"
    echo "  Paper's Target: ~92% (for Bullshark)"
    echo "  Our ASR: $ASR (13 nodes)"
    
    # Extract numeric value for comparison
    ASR_NUM=$(echo "$ASR" | sed 's/%//')
    if (( $(echo "$ASR_NUM >= 75" | bc -l) )); then
        echo "  Status: ✅ SUCCESS - ASR above 75% target!"
        if (( $(echo "$ASR_NUM >= 85" | bc -l) )); then
            echo "  Rating: ⭐⭐⭐ EXCELLENT - ASR ≥ 85%!"
        fi
    else
        echo "  Status: ⚠️  Below 75% target - Review optimization"
    fi
    
else
    echo "  ⚠️  Could not extract ASR from test output"
    echo "  Showing test output:"
    cat "$TEST_OUTPUT"
fi

# Step 5: Summary
echo ""
echo "🎉 AUTOMATED MYSTICETI SPECULATIVE ATTACK COMPLETED!"
echo "===================================================="
echo "  Test Output: Saved to temporary file (displayed above)"
echo "  Build log: build.log"
echo ""
echo "🔍 To run manually:"
echo "  export ATTACK_MODE=speculative"
echo "  export ATTACKER_RATIO=0.308"
echo "  export VICTIM_RATIO=0.231"
echo "  export RUST_LOG=info"
echo "  cargo test --release --package mysticeti-core test_speculative_attack_asr_13_nodes -- --nocapture"
echo ""
# Standardized output for sweeper
echo "FINAL_ASR_RESULT: $ASR"

# Clean up
rm -f "$TEST_OUTPUT"


