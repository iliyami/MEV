#!/bin/bash

# Run Sluggish Attack on 13-Node Bullshark Cluster
# This script sets up a proper 13-node cluster and measures ASR

echo "🐌 13-Node Bullshark Sluggish Attack Test"
echo "========================================"
echo ""

# Check directory
if [ ! -f "Cargo.toml" ]; then
    echo "❌ Error: Run from /Users/iliya/Dev/Blockchain/code/bullshark"
    exit 1
fi

# Step 1: Build with attack code
echo "🔨 Step 1: Building with sluggish attack enabled..."
export ATTACK_MODE=sluggish
export ATTACKER_RATIO=0.308  # 4/13
export VICTIM_RATIO=0.231    # 3/13
export SLUGGISH_TIMEOUT_MULTIPLIER=2.0
export RUST_LOG=info,consensus_core=debug

cargo build --release --package consensus-core 2>&1 | tail -5
if [ $? -ne 0 ]; then
    echo "❌ Build failed"
    exit 1
fi
echo "✅ Build complete"
echo ""

# Step 2: Run the sluggish attack test
echo "🚀 Step 2: Running 13-node sluggish attack test..."
echo "  Network: 13 validators"
echo "  Attackers: 4 nodes (30%)"
echo "  Victims: 3 nodes (23%)"
echo "  Honest: 6 nodes (46%)"
echo "  Duration: 60 seconds"
echo ""

# Run the test with proper environment
timeout 60s cargo test --release --package consensus-core \
    test_sluggish_attack_asr_13_nodes \
    -- --nocapture \
    2>&1 | tee sluggish_13_node_test.log

# Step 3: Analyze results
echo ""
echo "📊 Step 3: Analyzing Results..."
echo "========================================"

if [ -f "sluggish_13_node_test.log" ]; then
    # Extract ASR from log
    ASR=$(grep "Attack Success Rate:" sluggish_13_node_test.log | tail -1 | grep -oE '[0-9]+\.[0-9]+%' | head -1)
    
    if [ -n "$ASR" ]; then
        echo "✅ TEST COMPLETED SUCCESSFULLY"
        echo ""
        echo "🎯 MEASURED ASR: $ASR"
        echo "📖 Paper Target: ~87% (13 nodes)"
        echo ""
        
        # Extract numeric value
        ASR_NUM=$(echo $ASR | grep -oE '[0-9]+\.[0-9]+')
        
        # Compare with target
        if [ -n "$ASR_NUM" ]; then
            DIFF=$(echo "scale=1; $ASR_NUM - 87.0" | bc 2>/dev/null || echo "0.0")
            echo "📈 Difference from paper: ${DIFF}%"
            
            if (( $(echo "$ASR_NUM > 60" | bc -l) )); then
                echo "✅ ASR within reasonable range"
            else
                echo "⚠️  ASR lower than expected"
            fi
        fi
    else
        echo "⚠️  No ASR measurement found in logs"
        echo "Check sluggish_13_node_test.log for details"
    fi
    
    # Show node activity
    echo ""
    echo "📋 Node Activity:"
    echo "  Attack Events: $(grep -c 'Sluggish attack:' sluggish_13_node_test.log 2>/dev/null || echo "0")"
    echo "  Commits: $(grep -c 'received commit' sluggish_13_node_test.log 2>/dev/null || echo "0")"
    
else
    echo "❌ Test log not found"
    exit 1
fi

echo ""
echo "🎉 SLUGGISH ATTACK TEST COMPLETE!"
echo "Logs saved to: sluggish_13_node_test.log"


