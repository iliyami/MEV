#!/bin/bash

# Automated Sluggish Attack Script for Narwhal-Tusk
# This script automates the entire process: build, run attack, analyze results
# Usage: ./automated_sluggish_attack.sh

echo "🐌 Automated Sluggish Attack for Narwhal-Tusk"
echo "============================================"
echo "This script will:"
echo "  1. Build the Narwhal-Tusk project with attack code"
echo "  2. Run the 4-node network with sluggish attack"
echo "  3. Calculate and display the ASR results"
echo "  4. Compare with paper's expected performance"
echo ""

# Check if we're in the right directory
if [ ! -f "Cargo.toml" ]; then
    echo "❌ Error: Not in the correct directory"
    echo "Please run this from: /Users/iliya/Dev/Blockchain/code/narwhal-tusk"
    exit 1
fi

# Step 1: Clean and build
echo "🔨 Step 1: Building Narwhal-Tusk project with attack code..."
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
echo "⚙️  Step 2: Configuring sluggish attack parameters..."
export ATTACK_MODE=sluggish
export ATTACKER_RATIO=0.3
export VICTIM_RATIO=0.2
export SLUGGISH_TIMEOUT_MULTIPLIER=2.0

echo "  Attack Mode: $ATTACK_MODE"
echo "  Attacker Ratio: $ATTACKER_RATIO (30% - 1 node)"
echo "  Victim Ratio: $VICTIM_RATIO (20% - 1 node)"
echo "  Sluggish Timeout Multiplier: $SLUGGISH_TIMEOUT_MULTIPLIER (2x slower rounds for priority)"
echo "  Honest Nodes: 50% (2 nodes)"

# Step 3: Clean previous results
echo ""
echo "🧹 Step 3: Cleaning previous results..."
rm -rf benchmark/logs/
mkdir -p benchmark/logs
echo "  ✅ Previous data cleaned"

# Step 4: Initialize Sui network
echo ""
echo "🚀 Step 4: Initializing 4-node Narwhal-Tusk network with sluggish attack..."
echo "  Duration: 30 seconds"
echo "  Network: 4 nodes (1 attacker, 1 victim, 2 honest)"
echo "  Expected Impact: Delayed attacker propagation"

# Start the network using fab local (must run from benchmark directory)
echo "  Starting Narwhal-Tusk network with attack..."
cd benchmark
source ../venv/bin/activate
# Increased timeout to allow sufficient blocks for ASR calculation (needs at least 10 blocks)
# Longer duration for more stable ASR measurement
timeout 90s fab local > ../sluggish_attack.log 2>&1
ATTACK_EXIT_CODE=$?
cd ..

# Step 5: Analyze final results
echo ""
echo "📈 Step 5: Analyzing sluggish attack results..."
echo "=========================================="

if [ $ATTACK_EXIT_CODE -eq 0 ] && [ -f "benchmark/logs/primary-0.log" ]; then
    echo "  ✅ Attack completed successfully"
    
    # Extract ASR from all consensus logs - aggregate across all commits
    # Calculate cumulative ASR from all individual ASR calculations
    ASR_LINES=$(grep "ASR CALCULATION: Overall" benchmark/logs/primary-*.log 2>/dev/null)
    
    if [ ! -z "$ASR_LINES" ]; then
        # Extract all ASR percentages and calculate weighted average
        TOTAL_SUCCESS=0
        TOTAL_ATTACKS=0
        
        while IFS= read -r line; do
            # Extract "X/Y successful attacks = Z% ASR" pattern
            if echo "$line" | grep -qE "[0-9]+/[0-9]+ successful attacks"; then
                # Extract numbers before and after the slash
                RATIO=$(echo "$line" | grep -oE '[0-9]+/[0-9]+' | head -1)
                if [ ! -z "$RATIO" ]; then
                    SUCCESS=$(echo "$RATIO" | cut -d'/' -f1)
                    TOTAL=$(echo "$RATIO" | cut -d'/' -f2)
                    if [ ! -z "$SUCCESS" ] && [ ! -z "$TOTAL" ] && [ "$TOTAL" -gt 0 ] 2>/dev/null; then
                        TOTAL_SUCCESS=$((TOTAL_SUCCESS + SUCCESS))
                        TOTAL_ATTACKS=$((TOTAL_ATTACKS + TOTAL))
                    fi
                fi
            fi
        done <<< "$ASR_LINES"
        
        if [ $TOTAL_ATTACKS -gt 0 ]; then
            FINAL_ASR_NUM=$(echo "scale=1; ($TOTAL_SUCCESS * 100) / $TOTAL_ATTACKS" | bc -l 2>/dev/null || echo "0")
            FINAL_ASR="${FINAL_ASR_NUM}%"
        else
            FINAL_ASR="0%"
        fi
    else
        FINAL_ASR="0%"
    fi
    
    # Count attack events (timeout modifications)
    TIMEOUT_MODIFICATIONS=$(grep -c "Sluggish attack:.*using modified timeout" benchmark/logs/primary-*.log 2>/dev/null | awk '{sum += $1} END {print sum}')
    echo "  Total Timeout Modifications: $TIMEOUT_MODIFICATIONS"
    
    # Count ASR tracking events
    ASR_TRACKING=$(grep -c "ASR TRACKING:" benchmark/logs/primary-*.log 2>/dev/null | awk '{sum += $1} END {print sum}')
    echo "  ASR Tracking Events: $ASR_TRACKING"
    
    # Get network performance
    CONSENSUS_TPS=$(grep "Consensus TPS" benchmark/logs/primary-*.log 2>/dev/null | tail -1 | grep -o '[0-9,]\+' | head -1)
    if [ ! -z "$CONSENSUS_TPS" ]; then
        echo "  Network TPS: $CONSENSUS_TPS"
    fi
    
    # Show which node was the attacker
    echo ""
    echo "🎯 ATTACK ANALYSIS:"
    echo "=================="
    for i in {0..3}; do
        TIMEOUT_CHANGES=$(grep -c "Sluggish attack:.*using modified timeout" benchmark/logs/primary-$i.log 2>/dev/null || echo "0")
        TIMEOUT_CHANGES_NUM=$(echo "$TIMEOUT_CHANGES" | tr -d '\n' | head -c 10)
        if [ "${TIMEOUT_CHANGES_NUM:-0}" -gt 0 ] 2>/dev/null; then
            echo "  Attacker Node: Primary-$i ($TIMEOUT_CHANGES_NUM timeout modifications)"
        fi
    done
    
    # Show victim nodes (nodes with 0 timeout modifications)
    echo "  Victim Nodes:"
    for i in {0..3}; do
        TIMEOUT_CHANGES=$(grep -c "Sluggish attack:.*using modified timeout" benchmark/logs/primary-$i.log 2>/dev/null || echo "0")
        TIMEOUT_CHANGES_NUM=$(echo "$TIMEOUT_CHANGES" | tr -d '\n' | head -c 10)
        if [ "${TIMEOUT_CHANGES_NUM:-0}" -eq 0 ] 2>/dev/null; then
            echo "    - Primary-$i (0 modifications - victim)"
        fi
    done
    
    # Display ASR results
    echo ""
    echo "📊 ATTACK SUCCESS RATE (ASR):"
    echo "============================="
    echo "  Final ASR: $FINAL_ASR"
    
    # Compare with paper
    echo ""
    echo "📊 COMPARISON WITH PAPER:"
    echo "========================"
    echo "  Paper's Target: 82.4%"
    echo "  Our ASR: $FINAL_ASR"
    
    # Simple comparison (extract number from percentage)
    ASR_NUM=$(echo $FINAL_ASR | sed 's/%//')
    if [ ! -z "$ASR_NUM" ] && [ "$ASR_NUM" != "0" ]; then
        DIFF=$(echo "scale=2; $ASR_NUM - 82.4" | bc -l 2>/dev/null || echo "0.00")
        if (( $(echo "$ASR_NUM >= 75" | bc -l 2>/dev/null || echo "0") )); then
            echo "  Difference: ${DIFF}%"
            if (( $(echo "$ASR_NUM >= 80" | bc -l 2>/dev/null || echo "0") )); then
                echo "  ✅ ASR is close to paper's target!"
            else
                echo "  ⚠️  ASR is below paper's target but attack is working"
            fi
        else
            echo "  ⚠️  ASR is significantly below paper's target"
            echo "  💡 Consider adjusting SLUGGISH_TIMEOUT_MULTIPLIER"
        fi
    fi

else
    echo "  ❌ No logs found - Attack may have failed"
fi

# Step 6: Summary
echo ""
echo "🎉 SLUGGISH ATTACK EXECUTION COMPLETED!"
echo "====================================="
echo "  Logs: sluggish_attack.log"
echo "  Build log: build.log"
echo ""
echo "🔍 To analyze results manually:"
echo "  grep 'Sluggish attack:' sluggish_attack.log | head -10"
echo "  grep -c 'delaying header broadcast' sluggish_attack.log"
echo ""
echo "📖 Sluggish Attack Theory:"
echo "  - Attackers delay block propagation to gain information advantage"
echo "  - Creates frontrunning opportunities by seeing victim transactions first"
echo "  - Timing window allows attackers to frontrun with better positioning"
echo ""
echo "🎯 Expected Outcome: Attacker blocks arrive later but with frontrunning advantage"

# ASR Measurement Summary
echo ""
echo "📊 ASR MEASUREMENT SUMMARY:"
echo "=========================="
echo "  ASR Calculation: Based on global total order from consensus commits"
echo "  Methodology: Attacker blocks ordered before victim blocks"
echo "  Paper Target: 82.4% ASR"
echo "  Status: ✅ Real-time ASR measurement from consensus data"
