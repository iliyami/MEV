#!/bin/bash

# Automated Fissure Attack Script for Mysticeti
# This script automates the entire process: build, run attack, calculate ASR
# Usage: ./automated_fissure_attack.sh

echo "🎯 Automated Fissure Attack for Mysticeti"
echo "==========================================="
echo "This script will:"
echo "  1. Build the Mysticeti project with attack code"
echo "  2. Run the 13-node network with fissure attack"
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
export ATTACK_MODE=fissure
export ATTACKER_RATIO=0.308
export VICTIM_RATIO=0.231
export RUST_LOG=info

echo "  Attack Mode: $ATTACK_MODE"
echo "  Attacker Ratio: $ATTACKER_RATIO (~30.8% - 4 validators)"
echo "  Victim Ratio: $VICTIM_RATIO (~23.1% - 3 validators)"
echo "  Network Size: 13 nodes"

# Step 3: Run the test
echo ""
echo "🚀 Step 3: Running 13-node fissure attack test..."
echo "  Test: test_fissure_attack_asr_13_nodes"
echo "  Duration: ~30 seconds"
echo "  Expected ASR: 70-80%"
echo ""

# Run the test and capture output
echo "  Executing test..."
TEST_OUTPUT=$(mktemp)
cargo test --release --package mysticeti-core test_fissure_attack_asr_13_nodes -- --nocapture > "$TEST_OUTPUT" 2>&1
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

# Extract ASR from test output
ASR=$(grep "Attack Success Rate:" "$TEST_OUTPUT" | tail -1 | grep -oE '[0-9]+\.[0-9]+%' | head -1)
ASR_CALC=$(grep "ASR calculation:" "$TEST_OUTPUT" | tail -1)

if [ ! -z "$ASR" ]; then
    echo "  ✅ Attack Success Rate: $ASR"
    
    if [ ! -z "$ASR_CALC" ]; then
        echo "  📈 $ASR_CALC"
    fi
    
    # Extract additional metrics
    EXCLUSIONS=$(grep -c "Excluding victim block" "$TEST_OUTPUT" 2>/dev/null || echo "0")
    COMMITS=$(grep "Collected.*commits" "$TEST_OUTPUT" | tail -1)
    ATTACKER_BLOCKS=$(grep "Attacker blocks:" "$TEST_OUTPUT" | tail -1)
    VICTIM_BLOCKS=$(grep "Victim blocks:" "$TEST_OUTPUT" | tail -1)
    
    if [ ! -z "$COMMITS" ]; then
        echo "  $COMMITS"
    fi
    if [ ! -z "$ATTACKER_BLOCKS" ]; then
        echo "  $ATTACKER_BLOCKS"
    fi
    if [ ! -z "$VICTIM_BLOCKS" ]; then
        echo "  $VICTIM_BLOCKS"
    fi
    if [ "$EXCLUSIONS" -gt 0 ]; then
        echo "  Total Victim Exclusions: $EXCLUSIONS"
    fi
    
    echo ""
    echo "🎯 COMPARISON WITH PAPER:"
    echo "========================"
    echo "  Paper's Target: ~87% (for Tusk/Narwhal-Tusk)"
    echo "  Our ASR: $ASR (13 nodes)"
    
    # Extract numeric value for comparison
    ASR_NUM=$(echo "$ASR" | sed 's/%//')
    if (( $(echo "$ASR_NUM >= 60" | bc -l) )); then
        echo "  Status: ✅ SUCCESS - ASR above 60% target!"
        if (( $(echo "$ASR_NUM >= 75" | bc -l) )); then
            echo "  Rating: ⭐⭐⭐ EXCELLENT - ASR ≥ 75%!"
        fi
    else
        echo "  Status: ⚠️  Below 60% target - Review optimization"
    fi
    
else
    echo "  ⚠️  Could not extract ASR from test output"
    echo "  Showing test output:"
    cat "$TEST_OUTPUT"
fi

# Step 5: Summary
echo ""
echo "🎉 AUTOMATED MYSTICETI FISSURE ATTACK COMPLETED!"
echo "==============================================="
echo "  Test Output: Saved to temporary file (displayed above)"
echo "  Build log: build.log"
echo ""
echo "🔍 To run manually:"
echo "  export ATTACK_MODE=fissure"
echo "  export ATTACKER_RATIO=0.308"
echo "  export VICTIM_RATIO=0.231"
echo "  export RUST_LOG=info"
echo "  cargo test --release --package mysticeti-core test_fissure_attack_asr_13_nodes -- --nocapture"
echo ""
echo "🎯 Measured ASR: $ASR (from real consensus data on 13-node network)"
echo ""

# Clean up
rm -f "$TEST_OUTPUT"


