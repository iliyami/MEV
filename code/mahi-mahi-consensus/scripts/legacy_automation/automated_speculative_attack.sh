#!/bin/bash

# Automated Speculative Attack Testing Script for Mahi-Mahi (Mysticeti)
# This script runs all attack strategies and compares results

set -e

echo "========================================"
echo "    AUTOMATED SPECULATIVE ATTACK TEST   "
echo "          Mahi-Mahi (Mysticeti)         "
echo "========================================"
echo ""

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
NODES=${NUM_NODES:-13}
DURATION=${DURATION:-120}

# Step 1: Clean and build
echo -e "${BLUE}🔨 Step 1: Building Mahi-Mahi project with attack code...${NC}"
# Skip clean if NO_CLEAN is set
if [ -z "$NO_CLEAN" ]; then
    echo "  Cleaning previous build..."
    cargo clean > /dev/null 2>&1
fi

# Check if binary exists already
# Check if binary exists already to skip build in Docker if it was built in previous layer
if [ ! -z "$NO_BUILD" ]; then
    echo "  ⏩ NO_BUILD set, skipping build..."
elif [ -f "./target/release/mysticeti" ]; then
    echo "  ✅ Binary already exists, skipping build"
else
    echo "  Building release binary (this may take 2-3 minutes)..."
    cargo build --release 2>/dev/null || cargo build
    echo "  ✅ Build successful"
fi

# Clean up any previous logs
rm -rf logs/
mkdir -p logs/baseline
mkdir -p logs/speculative-attack

# Function to extract ASR from output
extract_asr() {
    local file=$1
    grep -E "FINAL ATTACK SUCCESS RATE" "$file" | sed -E 's/.*FINAL ATTACK SUCCESS RATE \(ASR\): ([0-9.]+)%.*/\1/' | tail -1
}

# Run baseline test
echo -e "${BLUE}===== Running Baseline Test =====${NC}"
# Ensure attack mode is completely unset for baseline
unset ATTACK_MODE
unset ATTACKER_ID
unset VICTIM_ID
unset SPECULATIVE_STRATEGY
echo -e "${YELLOW}Environment: ATTACK_MODE unset (baseline)${NC}"
./scripts/baseline-13nodes.sh
mv logs/v*.log logs/baseline/ 2>/dev/null || true
echo ""

# Run Smart strategy test (NEW - highest ASR expected)
echo -e "${GREEN}===== Running Smart Strategy Test =====${NC}"
export ATTACK_MODE=speculative
export ATTACKER_ID=0
export VICTIM_ID=1
export SPECULATIVE_STRATEGY=smart
echo -e "${YELLOW}Environment: ATTACK_MODE=$ATTACK_MODE, ATTACKER_ID=$ATTACKER_ID, VICTIM_ID=$VICTIM_ID, SPECULATIVE_STRATEGY=$SPECULATIVE_STRATEGY${NC}"
./scripts/speculative-attack-13nodes.sh
mv logs/v*.log logs/speculative-attack/ 2>/dev/null || true
python3 scripts/calculate-speculative-asr.py logs/speculative-attack/v*.log > asr_smart.txt
cat asr_smart.txt
echo ""

# Run Simple strategy test
echo -e "${BLUE}===== Running Simple Strategy Test =====${NC}"
export ATTACK_MODE=speculative
export ATTACKER_ID=0
export VICTIM_ID=1
export SPECULATIVE_STRATEGY=simple
export SIMPLE_EXCLUSION_PROB=0.05  # 5% exclusion
echo -e "${YELLOW}Environment: ATTACK_MODE=$ATTACK_MODE, ATTACKER_ID=$ATTACKER_ID, VICTIM_ID=$VICTIM_ID, SPECULATIVE_STRATEGY=$SPECULATIVE_STRATEGY, SIMPLE_EXCLUSION_PROB=$SIMPLE_EXCLUSION_PROB${NC}"
./scripts/speculative-attack-13nodes.sh
mv logs/v*.log logs/speculative-attack/ 2>/dev/null || true
python3 scripts/calculate-speculative-asr.py logs/speculative-attack/v*.log > asr_simple.txt
cat asr_simple.txt
echo ""

# Run Sophisticated strategy test
echo -e "${BLUE}===== Running Sophisticated Strategy Test =====${NC}"
export ATTACK_MODE=speculative
export ATTACKER_ID=0
export VICTIM_ID=1
export SPECULATIVE_STRATEGY=sophisticated
export SPECULATIVE_P_MAX=5  # p_max = 5
unset SIMPLE_EXCLUSION_PROB  # Clear simple exclusion prob
echo -e "${YELLOW}Environment: ATTACK_MODE=$ATTACK_MODE, ATTACKER_ID=$ATTACKER_ID, VICTIM_ID=$VICTIM_ID, SPECULATIVE_STRATEGY=$SPECULATIVE_STRATEGY, SPECULATIVE_P_MAX=$SPECULATIVE_P_MAX${NC}"
./scripts/speculative-attack-13nodes.sh
mv logs/v*.log logs/speculative-attack/ 2>/dev/null || true
python3 scripts/calculate-speculative-asr.py logs/speculative-attack/v*.log > asr_sophisticated.txt
cat asr_sophisticated.txt
echo ""

# Run Hybrid strategy test
echo -e "${BLUE}===== Running Hybrid Strategy Test =====${NC}"
export ATTACK_MODE=speculative
export ATTACKER_ID=0
export VICTIM_ID=1
export SPECULATIVE_STRATEGY=hybrid
echo -e "${YELLOW}Environment: ATTACK_MODE=$ATTACK_MODE, ATTACKER_ID=$ATTACKER_ID, VICTIM_ID=$VICTIM_ID, SPECULATIVE_STRATEGY=$SPECULATIVE_STRATEGY${NC}"
./scripts/speculative-attack-13nodes.sh
mv logs/v*.log logs/speculative-attack/ 2>/dev/null || true
python3 scripts/calculate-speculative-asr.py logs/speculative-attack/v*.log > asr_hybrid.txt
cat asr_hybrid.txt
echo ""

# Summary Report
echo -e "${GREEN}========================================"
echo "           ATTACK COMPARISON            "
echo "========================================${NC}"
echo ""

# Display results in a formatted table
echo -e "${BLUE}Strategy Results:${NC}"
echo "----------------------------------------"
printf "%-20s | %10s | %15s\n" "Strategy" "ASR (%)" "Expected ASR"
echo "----------------------------------------"

# Extract ASR values from the files
SMART_ASR=$(sed -n 's/.*FINAL ATTACK SUCCESS RATE (ASR): \([0-9.]*\).*/\1/p' asr_smart.txt 2>/dev/null | head -1 || echo "N/A")
SIMPLE_ASR=$(sed -n 's/.*FINAL ATTACK SUCCESS RATE (ASR): \([0-9.]*\).*/\1/p' asr_simple.txt 2>/dev/null | head -1 || echo "N/A")
SOPHISTICATED_ASR=$(sed -n 's/.*FINAL ATTACK SUCCESS RATE (ASR): \([0-9.]*\).*/\1/p' asr_sophisticated.txt 2>/dev/null | head -1 || echo "N/A")
HYBRID_ASR=$(sed -n 's/.*FINAL ATTACK SUCCESS RATE (ASR): \([0-9.]*\).*/\1/p' asr_hybrid.txt 2>/dev/null | head -1 || echo "N/A")

printf "%-20s | %10s | %15s\n" "Smart (NEW)" "$SMART_ASR" "TBD"
printf "%-20s | %10s | %15s\n" "Simple" "$SIMPLE_ASR" "~57%"
printf "%-20s | %10s | %15s\n" "Sophisticated" "$SOPHISTICATED_ASR" "~0% (ineffective)"
printf "%-20s | %10s | %15s\n" "Hybrid" "$HYBRID_ASR" "~78%"
echo "----------------------------------------"
echo ""

# Find best strategy
echo -e "${GREEN}Best Strategy Analysis:${NC}"
BEST_STRATEGY="None"
BEST_ASR=0

# Function to compare ASR values
compare_asr() {
    local strategy=$1
    local asr=$2
    
    # Check if ASR is a valid number
    if [[ $asr =~ ^[0-9]+\.?[0-9]*$ ]]; then
        # Compare using bc for floating point comparison
        if (( $(echo "$asr > $BEST_ASR" | bc -l) )); then
            BEST_ASR=$asr
            BEST_STRATEGY=$strategy
        fi
    fi
}

compare_asr "Smart" "$SMART_ASR"
compare_asr "Simple" "$SIMPLE_ASR"
compare_asr "Sophisticated" "$SOPHISTICATED_ASR"
compare_asr "Hybrid" "$HYBRID_ASR"

echo -e "${YELLOW}🏆 Best Strategy: $BEST_STRATEGY with ASR of ${BEST_ASR}%${NC}"
echo ""

# Standardized output for test runner
echo "FINAL_ASR_RESULT: ${BEST_ASR}%"

echo -e "${GREEN}All tests completed successfully!${NC}"
echo "Logs available in:"
echo "  - logs/baseline/ (baseline test)"
echo "  - logs/speculative-attack/ (attack tests)"
echo ""
echo "ASR results saved to:"
echo "  - asr_smart.txt"
echo "  - asr_simple.txt"
echo "  - asr_sophisticated.txt"
echo "  - asr_hybrid.txt"