#!/bin/bash
# Standardized Test Runner for AlephBFT
# Reads from YAML configuration and runs attack tests with statistical analysis
#
# Usage: ./run_standardized_test.sh [config_file] [attack_name] [runs]
#   config_file: YAML configuration file (default: experimental_config.yaml)
#   attack_name: Attack to run (fissure, speculative, sluggish, baseline, or "all")
#   runs: Number of runs for statistical analysis (default: from config or 1)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Parse arguments
CONFIG_FILE="${1:-experimental_config.yaml}"
ATTACK_TO_RUN="${2:-all}"
NUM_RUNS="${3:-${TEST_RUNS:-1}}"

echo "=========================================="
echo "AlephBFT Standardized Test Runner"
echo "=========================================="
echo ""
echo "Configuration: $CONFIG_FILE"
echo "Attack: $ATTACK_TO_RUN"
echo "Runs: $NUM_RUNS"
echo ""

# Load configuration from YAML
if [ ! -f "$CONFIG_FILE" ]; then
    echo "Error: Configuration file not found: $CONFIG_FILE" >&2
    exit 1
fi

echo "Loading configuration from: $CONFIG_FILE"
source scripts/load_config.sh "$CONFIG_FILE"
echo ""

# Results storage
RESULTS_DIR="${TEST_OUTPUT_DIR:-attack_results}"
mkdir -p "$RESULTS_DIR"

# Function to run a single test and extract ASR
run_single_test() {
    local attack_name=$1
    local attack_mode=$2
    local run_num=$3
    local extra_env=$4
    
    echo "Run $run_num/$NUM_RUNS: ${attack_name} attack..."
    
    # Set attack parameters
    export ATTACK_MODE="$attack_mode"
    
    # Set extra environment variables if provided
    if [ -n "$extra_env" ]; then
        eval "export $extra_env"
    fi
    
    # Build if needed (only on first run)
    if [ "$run_num" -eq 1 ]; then
        echo "Building AlephBFT..."
        cargo build --release --package aleph-bft 2>&1 | grep -E "(Compiling|Finished|error)" || true
        echo ""
    fi
    
    # Run test and capture output
    local output_file="$RESULTS_DIR/${attack_name}_run_${run_num}.log"
    local asr_file="$RESULTS_DIR/${attack_name}_run_${run_num}_asr.txt"
    
    case "$attack_mode" in
        "fissure")
            cargo test --release --package aleph-bft --lib attack_tests::fissure_attack_test::test_fissure_attack_asr_13_nodes -- --nocapture > "$output_file" 2>&1 || true
            ;;
        "speculative")
            cargo test --release --package aleph-bft --lib attack_tests::speculative_attack_test::test_speculative_attack_asr_13_nodes -- --nocapture > "$output_file" 2>&1 || true
            ;;
        "sluggish")
            cargo test --release --package aleph-bft --lib attack_tests::sluggish_attack_test::test_sluggish_attack_asr_13_nodes -- --nocapture > "$output_file" 2>&1 || true
            ;;
        "baseline")
            cargo test --release --package aleph-bft --lib attack_tests::fissure_attack_test::test_baseline_asr_13_nodes_no_attack -- --nocapture > "$output_file" 2>&1 || true
            ;;
        *)
            echo "Error: Unknown attack mode: $attack_mode" >&2
            return 1
            ;;
    esac
    
    # Extract ASR from output
    local asr=$(grep -oE "Attack Success Rate \(ASR\): [0-9]+\.[0-9]+%" "$output_file" 2>/dev/null | tail -1 | grep -oE "[0-9]+\.[0-9]+" || echo "")
    
    if [ -z "$asr" ]; then
        echo "  ❌ Could not extract ASR"
        echo "N/A" > "$asr_file"
        return 1
    fi
    
    echo "$asr" > "$asr_file"
    echo "  ✅ ASR: ${asr}%"
    return 0
}

# Function to calculate statistics
calculate_statistics() {
    local attack_name=$1
    local asr_file="$RESULTS_DIR/${attack_name}_statistics.txt"
    
    # Collect all ASR values
    local asr_values=()
    for i in $(seq 1 $NUM_RUNS); do
        local run_file="$RESULTS_DIR/${attack_name}_run_${i}_asr.txt"
        if [ -f "$run_file" ]; then
            local asr=$(cat "$run_file")
            if [ "$asr" != "N/A" ]; then
                asr_values+=("$asr")
            fi
        fi
    done
    
    if [ ${#asr_values[@]} -eq 0 ]; then
        echo "No valid ASR values found for $attack_name"
        return 1
    fi
    
    # Calculate statistics using Python
    # Convert bash array to Python list
    local asr_list="["
    for i in "${!asr_values[@]}"; do
        if [ $i -gt 0 ]; then
            asr_list+=", "
        fi
        asr_list+="${asr_values[$i]}"
    done
    asr_list+="]"
    
    python3 << EOF
import sys
import statistics

asr_values = [float(v) for v in $asr_list]

if len(asr_values) == 0:
    print("No valid ASR values")
    sys.exit(1)

mean = statistics.mean(asr_values)
median = statistics.median(asr_values)
stdev = statistics.stdev(asr_values) if len(asr_values) > 1 else 0.0
min_val = min(asr_values)
max_val = max(asr_values)

# 95% confidence interval (t-distribution approximation)
n = len(asr_values)
if n > 1:
    # Using t-value approximation for 95% CI (simplified)
    t_value = 1.96  # For large n, t approaches 1.96
    margin = t_value * (stdev / (n ** 0.5))
    ci_lower = mean - margin
    ci_upper = mean + margin
else:
    ci_lower = mean
    ci_upper = mean

print(f"Statistics for {attack_name}:")
print(f"  Runs: {n}")
print(f"  Mean: {mean:.2f}%")
print(f"  Median: {median:.2f}%")
print(f"  Std Dev: {stdev:.2f}%")
print(f"  Min: {min_val:.2f}%")
print(f"  Max: {max_val:.2f}%")
print(f"  95% CI: [{ci_lower:.2f}%, {ci_upper:.2f}%]")

# Save to file
with open("$asr_file", "w") as f:
    f.write(f"Statistics for {attack_name}:\n")
    f.write(f"  Runs: {n}\n")
    f.write(f"  Mean: {mean:.2f}%\n")
    f.write(f"  Median: {median:.2f}%\n")
    f.write(f"  Std Dev: {stdev:.2f}%\n")
    f.write(f"  Min: {min_val:.2f}%\n")
    f.write(f"  Max: {max_val:.2f}%\n")
    f.write(f"  95% CI: [{ci_lower:.2f}%, {ci_upper:.2f}%]\n")
EOF
}

# Run tests
if [ "$ATTACK_TO_RUN" = "all" ]; then
    ATTACKS=("fissure" "speculative" "sluggish")
else
    ATTACKS=("$ATTACK_TO_RUN")
fi

for attack in "${ATTACKS[@]}"; do
    echo "=========================================="
    echo "Running $attack attack ($NUM_RUNS runs)"
    echo "=========================================="
    echo ""
    
    case "$attack" in
        "fissure")
            for i in $(seq 1 $NUM_RUNS); do
                run_single_test "fissure" "fissure" "$i" ""
            done
            ;;
        "speculative")
            for i in $(seq 1 $NUM_RUNS); do
                run_single_test "speculative" "speculative" "$i" "SPECULATIVE_P_MAX=${SPECULATIVE_P_MAX:-50}"
            done
            ;;
        "sluggish")
            for i in $(seq 1 $NUM_RUNS); do
                run_single_test "sluggish" "sluggish" "$i" "SLUGGISH_PROCESSING_DELAY_MS=${SLUGGISH_PROCESSING_DELAY_MS:-11}"
            done
            ;;
        "baseline")
            for i in $(seq 1 $NUM_RUNS); do
                run_single_test "baseline" "baseline" "$i" ""
            done
            ;;
        *)
            echo "Error: Unknown attack: $attack" >&2
            exit 1
            ;;
    esac
    
    echo ""
    echo "Calculating statistics..."
    calculate_statistics "$attack"
    echo ""
done

echo "=========================================="
echo "Test Summary"
echo "=========================================="
echo ""
echo "Results saved in: $RESULTS_DIR/"
echo ""

# Display statistics for all attacks
for attack in "${ATTACKS[@]}"; do
    stats_file="$RESULTS_DIR/${attack}_statistics.txt"
    if [ -f "$stats_file" ]; then
        echo "--- $attack ---"
        cat "$stats_file"
        echo ""
    fi
done

echo "✅ All tests completed!"

