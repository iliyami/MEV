#!/bin/bash

# Automated Fissure Attack Script for Mahi-Mahi
# This script automates the entire process: build, run attack, calculate ASR, compare with baseline
# Usage: ./automated_fissure_attack.sh
#
# Updated: November 6, 2025
# Uses real 13-node local network with actual consensus

echo "🎯 Automated Fissure Attack for Mahi-Mahi"
echo "=========================================="
echo "This script will:"
echo "  1. Build the Mahi-Mahi project with attack code"
echo "  2. Run baseline test (no attack) to measure natural ASR"
echo "  3. Run fissure attack test with 13 nodes"
echo "  4. Calculate and compare ASR results"
echo "  5. Show detailed metrics and recommendations"
echo ""

# Configuration
NODES=${NUM_NODES:-13}
DURATION=${DURATION:-120}
EXCLUSION_PROBABILITY=${EXCLUSION_PROBABILITY:-0.20}

# Step 1: Clean and build
echo "🔨 Step 1: Building Mahi-Mahi project with attack code..."
# Skip clean if NO_CLEAN is set
if [ -z "$NO_CLEAN" ]; then
    echo "  Cleaning previous build..."
    cargo clean > /dev/null 2>&1
fi

echo "  Building release binary (this may take 2-3 minutes)..."
# Check if binary exists already to skip build in Docker if it was built in previous layer
# Check if binary exists already to skip build in Docker if it was built in previous layer
if [ ! -z "$NO_BUILD" ]; then
    echo "  ⏩ NO_BUILD set, skipping build..."
elif [ -f "./target/release/mysticeti" ]; then
    echo "  ✅ Binary already exists, skipping build"
else
    BUILD_LOG=$(mktemp)
    cargo build --release > "$BUILD_LOG" 2>&1
    BUILD_EXIT_CODE=$?

    if [ $BUILD_EXIT_CODE -eq 0 ]; then
        echo "  ✅ Build successful"
        rm -f "$BUILD_LOG"
    else
        echo "  ❌ Build failed - showing last 20 lines of build log:"
        tail -20 "$BUILD_LOG"
        rm -f "$BUILD_LOG"
        exit 1
    fi
fi

# Step 2: Kill any lingering processes
echo ""
echo "🧹 Step 2: Cleaning up any lingering processes..."
pkill -f mysticeti > /dev/null 2>&1
sleep 2
echo "  ✅ Environment ready"

# Step 3: Run baseline test (no attack)
echo ""
echo "📊 Step 3: Running BASELINE test (no attack)..."
echo "==============================================="
echo "  Network: $NODES nodes (all honest)"
echo "  Duration: $DURATION seconds"
echo "  Purpose: Measure natural ordering ASR"
echo ""

BASELINE_OUTPUT=$(mktemp)
# Pass parameters to script
export NUM_NODES=$NODES
export DURATION=$DURATION
bash scripts/baseline-13nodes.sh > "$BASELINE_OUTPUT" 2>&1
BASELINE_EXIT_CODE=$?

if [ $BASELINE_EXIT_CODE -eq 0 ]; then
    echo "  ✅ Baseline test completed"
    
    # Extract baseline ASR
    BASELINE_ASR=$(grep "FINAL ATTACK SUCCESS RATE (ASR):" "$BASELINE_OUTPUT" | grep -oE '[0-9]+\.[0-9]+%' | head -1)
    
    if [ ! -z "$BASELINE_ASR" ]; then
        echo "  📊 Baseline ASR (natural ordering): $BASELINE_ASR"
    else
        echo "  ⚠️  Could not extract baseline ASR"
        BASELINE_ASR="Unknown"
    fi
else
    echo "  ❌ Baseline test failed"
    cat "$BASELINE_OUTPUT"
    rm -f "$BASELINE_OUTPUT"
    exit 1
fi

# Brief pause between tests
echo ""
echo "⏸️  Pausing 5 seconds before attack test..."
sleep 5

# Step 4: Run fissure attack test
echo ""
echo "🎯 Step 4: Running FISSURE ATTACK test..."
echo "========================================="
echo "  Attacker: Node ${ATTACKER_ID:-0}"
echo "  Victim: Node ${VICTIM_ID:-1}"
echo "  Exclusion Probability: $(echo "$EXCLUSION_PROBABILITY * 100" | bc | sed 's/\.00//')%"
echo "  Network: $NODES nodes (1 attacker, 1 victim, $((NODES-2)) honest)"
echo "  Duration: $DURATION seconds"
echo "  Expected ASR: ~86%"
echo ""

ATTACK_OUTPUT=$(mktemp)
# Pass parameters to script
export NUM_NODES=$NODES
export DURATION=$DURATION
export EXCLUSION_PROBABILITY=$EXCLUSION_PROBABILITY
bash scripts/fissure-attack-13nodes.sh > "$ATTACK_OUTPUT" 2>&1
ATTACK_EXIT_CODE=$?

if [ $ATTACK_EXIT_CODE -eq 0 ]; then
    echo "  ✅ Attack test completed"
else
    echo "  ❌ Attack test failed"
    cat "$ATTACK_OUTPUT"
    rm -f "$ATTACK_OUTPUT" "$BASELINE_OUTPUT"
    exit 1
fi

# Step 5: Extract and display results
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📊 STEP 5: RESULTS ANALYSIS"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Extract attack ASR
ATTACK_ASR=$(grep "FINAL ATTACK SUCCESS RATE (ASR):" "$ATTACK_OUTPUT" | grep -oE '[0-9]+\.[0-9]+%' | head -1)

# Extract detailed metrics from attack
ATTACK_PAIRS=$(grep "Total pairs analyzed:" "$ATTACK_OUTPUT" | grep -oE '[0-9,]+' | tr -d ',')
ATTACK_SUCCESS=$(grep "Successful frontrunning:" "$ATTACK_OUTPUT" | grep -oE '[0-9,]+' | tr -d ',')
ATTACKER_BLOCKS=$(grep "Attacker blocks (Node 0):" "$ATTACK_OUTPUT" | grep -oE '[0-9]+' | head -1)
VICTIM_BLOCKS=$(grep "Victim blocks (Node 1):" "$ATTACK_OUTPUT" | grep -oE '[0-9]+' | head -1)
EXCLUSIONS=$(grep "Fissure attack detected:" "$ATTACK_OUTPUT" | grep -oE '[0-9]+' | head -1)

echo "🎯 FISSURE ATTACK RESULTS:"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
if [ ! -z "$ATTACK_ASR" ]; then
    echo "  Attack Success Rate: $ATTACK_ASR"
else
    echo "  ⚠️  Could not extract attack ASR"
    ATTACK_ASR="Unknown"
fi

if [ ! -z "$EXCLUSIONS" ]; then
    echo "  Victim blocks excluded: $EXCLUSIONS"
fi

if [ ! -z "$ATTACKER_BLOCKS" ]; then
    echo "  Attacker blocks committed: $ATTACKER_BLOCKS"
fi

if [ ! -z "$VICTIM_BLOCKS" ]; then
    echo "  Victim blocks committed: $VICTIM_BLOCKS"
fi

if [ ! -z "$ATTACK_PAIRS" ]; then
    echo "  Total pairs analyzed: $(printf "%'d" "$ATTACK_PAIRS" 2>/dev/null || echo "$ATTACK_PAIRS")"
fi

if [ ! -z "$ATTACK_SUCCESS" ]; then
    echo "  Successful frontrunning: $(printf "%'d" "$ATTACK_SUCCESS" 2>/dev/null || echo "$ATTACK_SUCCESS")"
fi

echo ""
echo "📊 BASELINE RESULTS (for comparison):"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Natural ordering ASR: $BASELINE_ASR"

# Calculate improvement
if [ "$ATTACK_ASR" != "Unknown" ] && [ "$BASELINE_ASR" != "Unknown" ]; then
    ATTACK_NUM=$(echo "$ATTACK_ASR" | sed 's/%//')
    BASELINE_NUM=$(echo "$BASELINE_ASR" | sed 's/%//')
    IMPROVEMENT=$(echo "scale=2; $ATTACK_NUM - $BASELINE_NUM" | bc -l)
    
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "📈 IMPROVEMENT ANALYSIS:"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  Baseline ASR:     $BASELINE_ASR"
    echo "  Attack ASR:       $ATTACK_ASR"
    echo "  Improvement:      +${IMPROVEMENT}%"
    echo ""
    
    # Evaluation
    if (( $(echo "$ATTACK_NUM >= 85" | bc -l) )); then
        echo "  ✅ Status: HIGHLY EFFECTIVE ATTACK!"
        echo "  ⭐⭐⭐ Rating: EXCELLENT"
        echo "  💡 The attack provides massive ordering advantage"
    elif (( $(echo "$ATTACK_NUM >= 75" | bc -l) )); then
        echo "  ✅ Status: EFFECTIVE ATTACK"
        echo "  ⭐⭐ Rating: GOOD"
        echo "  💡 The attack provides significant ordering advantage"
    elif (( $(echo "$ATTACK_NUM >= 60" | bc -l) )); then
        echo "  ⚠️  Status: MODERATE ATTACK"
        echo "  ⭐ Rating: FAIR"
        echo "  💡 The attack provides some ordering advantage"
    else
        echo "  ❌ Status: INEFFECTIVE"
        echo "  ⚠️  Rating: POOR"
        echo "  💡 Attack needs optimization or calibration"
    fi
    
    # Show relative improvement
    if [ $(echo "$BASELINE_NUM > 0" | bc -l) -eq 1 ]; then
        RELATIVE_IMPROVEMENT=$(echo "scale=1; ($ATTACK_NUM - $BASELINE_NUM) / $BASELINE_NUM * 100" | bc -l)
        echo "  📊 Relative improvement: ${RELATIVE_IMPROVEMENT}% better than baseline"
    fi
fi

# Step 6: Technical details
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🔬 TECHNICAL DETAILS:"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Protocol: Mahi-Mahi (uncertified DAG, 4-hop latency)"
echo "  Attack Type: Fissure (selective parent exclusion)"
echo "  Exclusion Rate: 20% (calibrated for optimal results)"
echo "  Test Duration: 120 seconds per test"
echo "  Network Size: 13 nodes (local deployment)"
echo "  Measurement: Real consensus ordering from commit logs"
echo ""

# Step 7: Cost-benefit analysis
if [ ! -z "$ATTACKER_BLOCKS" ] && [ ! -z "$VICTIM_BLOCKS" ]; then
    EXPECTED_ATTACKER_PERCENTAGE=7.69  # 1/13 nodes
    ACTUAL_ATTACKER_PERCENTAGE=$(echo "scale=2; $ATTACKER_BLOCKS * 100 / ($ATTACKER_BLOCKS + $VICTIM_BLOCKS + ($VICTIM_BLOCKS * 11))" | bc -l 2>/dev/null || echo "N/A")
    
    if [ "$ACTUAL_ATTACKER_PERCENTAGE" != "N/A" ]; then
        THROUGHPUT_LOSS=$(echo "scale=0; 100 - ($ACTUAL_ATTACKER_PERCENTAGE * 100 / $EXPECTED_ATTACKER_PERCENTAGE)" | bc -l 2>/dev/null || echo "N/A")
        
        if [ "$THROUGHPUT_LOSS" != "N/A" ]; then
            echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
            echo "💰 COST-BENEFIT ANALYSIS:"
            echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
            echo "  Attacker throughput loss: ~${THROUGHPUT_LOSS}%"
            echo "  Ordering advantage gained: +${IMPROVEMENT}%"
            echo ""
            
            if (( $(echo "$IMPROVEMENT > $THROUGHPUT_LOSS / 2" | bc -l) )); then
                echo "  💡 Analysis: Attack is cost-effective for MEV scenarios"
                echo "     Ordering advantage outweighs throughput cost"
            else
                echo "  ⚠️  Analysis: High throughput cost relative to ordering gain"
                echo "     Consider adjusting exclusion probability"
            fi
            echo ""
        fi
    fi
fi

# Step 8: Comparison with other protocols
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📊 COMPARISON WITH OTHER PROTOCOLS:"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Protocol          | ASR (Fissure) | Vulnerability"
echo "  ----------------- | ------------- | --------------"
if [ "$ATTACK_ASR" != "Unknown" ]; then
    printf "  Mahi-Mahi (yours) | %-13s | " "$ATTACK_ASR"
    if (( $(echo "$ATTACK_NUM >= 85" | bc -l) )); then
        echo "Very High ⚠️"
    elif (( $(echo "$ATTACK_NUM >= 75" | bc -l) )); then
        echo "High ⚠️"
    else
        echo "Moderate"
    fi
else
    echo "  Mahi-Mahi (yours) | Unknown       | ?"
fi
echo "  Mysticeti         | ~50.5%        | Low (certified)"
echo "  Bullshark         | ~88%          | Very High"
echo "  Narwhal-Tusk      | ~87%          | Very High"
echo ""

# Step 9: Files and logs
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📁 FILES AND LOGS:"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Attack logs: logs/fissure-attack/v*.log"
echo "  Baseline logs: logs/baseline/v*.log"
echo "  Documentation: MAHI_MAHI_FISSURE_ASR_RESULTS.md"
echo "  Implementation: MAHI_MAHI_FINAL_IMPLEMENTATION.md"
echo ""
echo "  To view detailed attack logs:"
echo "    grep 'FISSURE' logs/fissure-attack/v0.log | head -20"
echo ""
echo "  To recalculate ASR manually:"
echo "    python3 scripts/calculate-fissure-asr.py logs/fissure-attack/v*.log"
echo ""

# Step 10: Manual reproduction
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🔄 TO REPRODUCE MANUALLY:"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Run baseline:"
echo "    bash scripts/baseline-13nodes.sh"
echo ""
echo "  Run attack:"
echo "    bash scripts/fissure-attack-13nodes.sh"
echo ""
echo "  Adjust exclusion probability:"
echo "    Edit scripts/fissure-attack-13nodes.sh"
echo "    Change: export EXCLUSION_PROBABILITY=0.20"
echo "    (Try 0.15-0.30 range, avoid >0.50)"
echo ""

# Final summary
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🎉 AUTOMATED MAHI-MAHI FISSURE ATTACK COMPLETED!"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "  📊 Baseline ASR: $BASELINE_ASR (natural ordering)"
echo "  🎯 Attack ASR: $ATTACK_ASR (with 20% exclusion)"

if [ "$ATTACK_ASR" != "Unknown" ] && [ "$BASELINE_ASR" != "Unknown" ]; then
    echo "  📈 Improvement: +${IMPROVEMENT}%"
    echo ""
    
    if (( $(echo "$ATTACK_NUM >= 85" | bc -l) )); then
        echo "  ✅ RESULT: HIGHLY EFFECTIVE ATTACK"
        echo "  💡 Mahi-Mahi is vulnerable to Fissure attack!"
    elif (( $(echo "$ATTACK_NUM >= 75" | bc -l) )); then
        echo "  ✅ RESULT: EFFECTIVE ATTACK"
        echo "  💡 Attack provides significant advantage"
    else
        echo "  ⚠️  RESULT: Needs optimization"
        echo "  💡 Try adjusting exclusion probability"
    fi
    
    # Standardized output for test runner
    echo ""
    echo "FINAL_ASR_RESULT: $ATTACK_ASR"
fi

echo ""
echo "  📖 For detailed analysis: MAHI_MAHI_FISSURE_ASR_RESULTS.md"
echo "  🔧 Implementation details: MAHI_MAHI_FINAL_IMPLEMENTATION.md"
echo ""
echo "  Test date: $(date '+%Y-%m-%d %H:%M:%S')"
echo ""

# Clean up temporary files
rm -f "$ATTACK_OUTPUT" "$BASELINE_OUTPUT"

# Return success if we got good ASR
if [ "$ATTACK_ASR" != "Unknown" ]; then
    ATTACK_NUM=$(echo "$ATTACK_ASR" | sed 's/%//')
    if (( $(echo "$ATTACK_NUM >= 75" | bc -l) )); then
        exit 0
    else
        exit 1
    fi
else
    exit 1
fi

