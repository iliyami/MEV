#!/bin/bash
# Comprehensive Fissure Attack ASR Testing Script

cd "$(dirname "$0")/mysticeti-core" || exit 1

echo "=========================================="
echo "MYSTICETI FISSURE ATTACK ASR TESTING"
echo "=========================================="
echo ""

ASR_VALUES=()
RUN_COUNT=5

for i in $(seq 1 $RUN_COUNT); do
    echo "=== Run $i/$RUN_COUNT ==="
    
    # Run test and extract ASR
    ASR=$(RUST_LOG=warn timeout 120 cargo test --release test_fissure_attack_asr_13_nodes -- --nocapture 2>&1 | \
        grep "Attack Success Rate" | \
        grep -oE '[0-9]+\.?[0-9]*%' | \
        head -1 | \
        sed 's/%//')
    
    if [ -n "$ASR" ]; then
        echo "  ASR: ${ASR}%"
        ASR_VALUES+=($ASR)
    else
        echo "  ⚠️  Failed to extract ASR"
    fi
    
    echo ""
    sleep 2
done

if [ ${#ASR_VALUES[@]} -gt 0 ]; then
    echo "=========================================="
    echo "RESULTS SUMMARY"
    echo "=========================================="
    echo ""
    
    # Calculate statistics
    SUM=0
    for val in "${ASR_VALUES[@]}"; do
        SUM=$(echo "$SUM + $val" | bc)
    done
    
    AVG=$(echo "scale=2; $SUM / ${#ASR_VALUES[@]}" | bc)
    
    # Find min and max
    MIN=${ASR_VALUES[0]}
    MAX=${ASR_VALUES[0]}
    for val in "${ASR_VALUES[@]}"; do
        if (( $(echo "$val < $MIN" | bc -l) )); then
            MIN=$val
        fi
        if (( $(echo "$val > $MAX" | bc -l) )); then
            MAX=$val
        fi
    done
    
    echo "Total Runs: ${#ASR_VALUES[@]}"
    echo "ASR Values: ${ASR_VALUES[*]}"
    echo ""
    echo "Average ASR: ${AVG}%"
    echo "Min ASR: ${MIN}%"
    echo "Max ASR: ${MAX}%"
    echo ""
    echo "=========================================="
else
    echo "⚠️  No valid ASR values collected"
    exit 1
fi


