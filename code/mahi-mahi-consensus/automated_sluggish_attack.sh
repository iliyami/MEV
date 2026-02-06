#!/bin/bash
# Comprehensive Sluggish Attack Testing Suite for Mahi-Mahi
# Tests Pure Sluggish and Hybrid Sluggish with multiple parameter combinations

set -e

echo "=========================================="
echo "  COMPREHENSIVE SLUGGISH ATTACK TESTING"
echo "=========================================="
echo ""

# Change to project directory
cd /Users/iliya/Dev/Blockchain/code/mahi-mahi-consensus

# Build once at the beginning
echo "📦 Building Mahi-Mahi..."
cargo build --release 2>&1 | tail -3
if [ $? -ne 0 ]; then
    echo "❌ Build failed!"
    exit 1
fi
echo "✅ Build successful"
echo ""

# Cleanup previous runs aggressively
echo "🧹 Cleaning up previous processes..."
pkill -9 -f mysticeti > /dev/null 2>&1 || true
sleep 5

# Create results directory
RESULTS_DIR="logs/sluggish-comprehensive-results"
rm -rf $RESULTS_DIR
mkdir -p $RESULTS_DIR

# Test 1: Baseline (no attack)
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "TEST 1: Baseline (No Attack)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
unset ATTACK_MODE
unset ATTACKER_ID
unset VICTIM_ID
unset SLUGGISH_MULTIPLIER
unset HYBRID_EXCLUSION

./scripts/baseline-13nodes.sh > /dev/null 2>&1
BASELINE_ASR=$(python3 scripts/calculate-fissure-asr.py logs/baseline/v*.log 2>&1 | grep "FINAL ATTACK SUCCESS RATE" | grep -oE '[0-9]+\.[0-9]+')
echo "Baseline ASR: ${BASELINE_ASR}%"
echo "BASELINE,N/A,N/A,$BASELINE_ASR" >> $RESULTS_DIR/results.csv
echo ""

# Test 2: Pure Sluggish with different multipliers
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "TEST 2: Pure Sluggish (Various Multipliers)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
for mult in 1.5 2.0 2.5 3.0; do
    echo "Testing multiplier: ${mult}x..."
    ./scripts/sluggish-attack-13nodes.sh sluggish $mult > /dev/null 2>&1
    
    ASR=$(python3 scripts/calculate-sluggish-asr.py logs/sluggish-attack/v*.log 2>&1 | grep "FINAL ATTACK SUCCESS RATE" | grep -oE '[0-9]+\.[0-9]+')
    
    # Check participation rate
    ATT_LINES=$(wc -l logs/sluggish-attack/v0.log | awk '{print $1}')
    VIC_LINES=$(wc -l logs/sluggish-attack/v1.log | awk '{print $1}')
    AVG_LINES=$(ls logs/sluggish-attack/v*.log | xargs wc -l | tail -1 | awk '{print int($1/13)}')
    PARTICIPATION=$(echo "scale=1; $ATT_LINES * 100 / $AVG_LINES" | bc)
    
    echo "  Result: ${ASR}% ASR (Participation: ${PARTICIPATION}%)"
    echo "PURE_SLUGGISH,$mult,N/A,$ASR,$PARTICIPATION" >> $RESULTS_DIR/results.csv
    
    # Copy logs for later analysis
    mkdir -p $RESULTS_DIR/pure-${mult}x
    cp logs/sluggish-attack/v*.log $RESULTS_DIR/pure-${mult}x/
done
echo ""

# Test 3: Hybrid Light (5% exclusion, various multipliers)
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "TEST 3: Hybrid Light (5% Exclusion)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
for mult in 1.5 2.0 2.5; do
    echo "Testing multiplier: ${mult}x with 5% exclusion..."
    ./scripts/sluggish-attack-13nodes.sh hybrid_sluggish $mult 0.05 > /dev/null 2>&1
    
    ASR=$(python3 scripts/calculate-sluggish-asr.py logs/sluggish-attack/v*.log 2>&1 | grep "FINAL ATTACK SUCCESS RATE" | grep -oE '[0-9]+\.[0-9]+')
    
    # Check participation rate
    ATT_LINES=$(wc -l logs/sluggish-attack/v0.log | awk '{print $1}')
    AVG_LINES=$(ls logs/sluggish-attack/v*.log | xargs wc -l | tail -1 | awk '{print int($1/13)}')
    PARTICIPATION=$(echo "scale=1; $ATT_LINES * 100 / $AVG_LINES" | bc)
    
    echo "  Result: ${ASR}% ASR (Participation: ${PARTICIPATION}%)"
    echo "HYBRID_LIGHT,$mult,0.05,$ASR,$PARTICIPATION" >> $RESULTS_DIR/results.csv
    
    # Copy logs
    mkdir -p $RESULTS_DIR/hybrid-light-${mult}x
    cp logs/sluggish-attack/v*.log $RESULTS_DIR/hybrid-light-${mult}x/
done
echo ""

# Test 4: Hybrid Medium (10% exclusion)
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "TEST 4: Hybrid Medium (10% Exclusion)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
./scripts/sluggish-attack-13nodes.sh hybrid_sluggish 2.0 0.10 > /dev/null 2>&1

ASR=$(python3 scripts/calculate-sluggish-asr.py logs/sluggish-attack/v*.log 2>&1 | grep "FINAL ATTACK SUCCESS RATE" | grep -oE '[0-9]+\.[0-9]+')

ATT_LINES=$(wc -l logs/sluggish-attack/v0.log | awk '{print $1}')
AVG_LINES=$(ls logs/sluggish-attack/v*.log | xargs wc -l | tail -1 | awk '{print int($1/13)}')
PARTICIPATION=$(echo "scale=1; $ATT_LINES * 100 / $AVG_LINES" | bc)

echo "Result: ${ASR}% ASR (Participation: ${PARTICIPATION}%)"
echo "HYBRID_MEDIUM,2.0,0.10,$ASR,$PARTICIPATION" >> $RESULTS_DIR/results.csv

mkdir -p $RESULTS_DIR/hybrid-medium-10
cp logs/sluggish-attack/v*.log $RESULTS_DIR/hybrid-medium-10/
echo ""

# Test 5: Hybrid Aggressive (15% and 20% exclusion)
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "TEST 5: Hybrid Aggressive (15-20% Exclusion)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
for excl in 0.15 0.20; do
    echo "Testing ${excl} exclusion rate..."
    ./scripts/sluggish-attack-13nodes.sh hybrid_sluggish 2.5 $excl > /dev/null 2>&1
    
    ASR=$(python3 scripts/calculate-sluggish-asr.py logs/sluggish-attack/v*.log 2>&1 | grep "FINAL ATTACK SUCCESS RATE" | grep -oE '[0-9]+\.[0-9]+')
    
    ATT_LINES=$(wc -l logs/sluggish-attack/v0.log | awk '{print $1}')
    AVG_LINES=$(ls logs/sluggish-attack/v*.log | xargs wc -l | tail -1 | awk '{print int($1/13)}')
    PARTICIPATION=$(echo "scale=1; $ATT_LINES * 100 / $AVG_LINES" | bc)
    
    if (( $(echo "$PARTICIPATION < 50" | bc -l) )); then
        echo "  Result: ${ASR}% ASR (Participation: ${PARTICIPATION}%) ⚠️  ISOLATED"
    else
        echo "  Result: ${ASR}% ASR (Participation: ${PARTICIPATION}%)"
    fi
    echo "HYBRID_AGGRESSIVE,2.5,$excl,$ASR,$PARTICIPATION" >> $RESULTS_DIR/results.csv
    
    mkdir -p $RESULTS_DIR/hybrid-aggressive-$(echo $excl | sed 's/0\.//')
    cp logs/sluggish-attack/v*.log $RESULTS_DIR/hybrid-aggressive-$(echo $excl | sed 's/0\.//')/
done
echo ""

# Generate final comparison
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "          FINAL COMPARISON"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Strategy,Multiplier,Exclusion,ASR,Participation" > $RESULTS_DIR/summary.csv
cat $RESULTS_DIR/results.csv >> $RESULTS_DIR/summary.csv

echo "| Strategy | Multiplier | Exclusion | ASR | Participation | Status |"
echo "|----------|------------|-----------|-----|---------------|--------|"
while IFS=',' read -r strategy mult excl asr part; do
    if [ "$strategy" = "BASELINE" ]; then
        printf "| %-20s | %-10s | %-9s | %5s%% | %-13s | %-6s |\n" "Baseline" "N/A" "N/A" "$asr" "100%" "✅"
    else
        status="✅"
        if (( $(echo "$part < 50" | bc -l 2>/dev/null || echo "0") )); then
            status="❌ ISOLATED"
        elif (( $(echo "$part < 80" | bc -l 2>/dev/null || echo "0") )); then
            status="⚠️  DEGRADED"
        fi
        
        excl_display="N/A"
        if [ "$excl" != "N/A" ]; then
            excl_display="$(echo "$excl * 100" | bc)%"
        fi
        
        printf "| %-20s | %-10s | %-9s | %5s%% | %-13s | %-6s |\n" "$strategy" "${mult}x" "$excl_display" "$asr" "${part}%" "$status"
    fi
done < $RESULTS_DIR/results.csv

echo ""
echo "Results saved to: $RESULTS_DIR/"
echo "Full logs available in subdirectories"
echo ""
echo "🎯 BEST STRATEGIES:"
echo "-------------------"
# Find best ASR (excluding isolated runs)
best_asr=0
best_strategy=""
while IFS=',' read -r strategy mult excl asr part; do
    if [ "$strategy" != "BASELINE" ] && (( $(echo "$part >= 80" | bc -l 2>/dev/null || echo "0") )); then
        if (( $(echo "$asr > $best_asr" | bc -l 2>/dev/null || echo "0") )); then
            best_asr=$asr
            best_strategy="$strategy (${mult}x, ${excl} excl)"
        fi
    fi
done < $RESULTS_DIR/results.csv

echo "Highest Sustainable ASR: ${best_asr}% - $best_strategy"
echo ""
echo "FINAL_ASR_RESULT: ${best_asr}%"
echo "📊 COMPARISON WITH OTHER PROTOCOLS:"
echo "- Mysticeti Sluggish: 40% ASR"
echo "- Mahi-Mahi Fissure: 86% ASR"
echo "- Mahi-Mahi Speculative: ~52% ASR"
echo "- Mahi-Mahi Sluggish (Best): ${best_asr}% ASR"
echo ""
echo "✅ ALL TESTS COMPLETE!"





