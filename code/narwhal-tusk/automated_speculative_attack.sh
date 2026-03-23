#!/bin/bash

# Exit immediately if a command exits with a non-zero status.
# set -e removed

# --- Configuration ---
NARWHAL_TUSK_DIR=$(pwd)
BENCHMARK_DIR="$NARWHAL_TUSK_DIR/benchmark"
LOG_DIR="$BENCHMARK_DIR/logs"
BUILD_LOG="$NARWHAL_TUSK_DIR/build.log"
ATTACK_OUTPUT_LOG="$NARWHAL_TUSK_DIR/speculative_attack_output.log"

# Attack Parameters (Dynamic with defaults, can be overridden by env or arguments)
# Priority: Positional Argument > Env Var > Default
export NUM_NODES=${1:-${NUM_NODES:-15}}
export ATTACKER_RATIO=${2:-${ATTACKER_RATIO:-0.33}}
export VICTIM_RATIO=${3:-${VICTIM_RATIO:-0.22}}
export DURATION=${4:-${DURATION:-35}}
export TEST_DURATION=$DURATION
export ATTACK_MODE=${ATTACK_MODE:-speculative}
export NUM_WORKERS=${NUM_WORKERS:-8}
export VICTIM_COUNT=${VICTIM_COUNT:-1}
export ASR_LOGGING_FREQUENCY=${ASR_LOGGING_FREQUENCY:-1}
export ASR_REPORT_THRESHOLD=${ASR_REPORT_THRESHOLD:-1}
if [ -z "${MIN_SAME_ROUND_SAMPLES:-}" ]; then
    if [ "$NUM_NODES" -ge 100 ]; then
        export MIN_SAME_ROUND_SAMPLES=5
    else
        export MIN_SAME_ROUND_SAMPLES=1
    fi
fi
export RUST_LOG=${ATTACK_RUST_LOG:-info}
if [ -z "${TMUX_LAUNCH_BATCH_SIZE:-}" ]; then
    if [ "$NUM_NODES" -ge 100 ]; then
        export TMUX_LAUNCH_BATCH_SIZE=2
    elif [ "$NUM_NODES" -ge 50 ]; then
        export TMUX_LAUNCH_BATCH_SIZE=8
    else
        export TMUX_LAUNCH_BATCH_SIZE=32
    fi
fi

PAPER_ASR_TARGET=86.3 # Paper's speculative attack ASR for Tusk

echo "🎯 Automated Speculative Attack for Narwhal-Tusk"
echo "================================================"
echo "This script will:"
echo "  1. Build the project with speculative attack code"
echo "  2. Run the 15-node network with speculative attack"
echo "  3. Calculate and display the ASR results"
echo "  4. Compare with paper's target (86.3%)"
echo ""

# --- Step 1: Build project with attack code (skip if already built) ---
if [ -f "target/release/primary" ] || [ -f "primary" ] || [ -f "target/release/node" ] || [ -f "node" ]; then
    echo "🔨 Step 1: Skipping build (binary already exists)"
    # Ensure binary is in the place fab local expects if it's named 'node'
    if [ ! -f "target/release/node" ] && [ -f "node" ]; then
        mkdir -p target/release
        cp node target/release/node
    fi
else
    echo "🔨 Step 1: Building project with speculative attack code..."
    cd "$NARWHAL_TUSK_DIR"
    export RUSTC_WRAPPER=sccache
    cargo build --release
    echo "  ✅ Build successful"
fi
echo ""

# --- Step 2: Configure attack parameters ---
echo "⚙️  Step 2: Configuring speculative attack parameters..."
echo "  Attack Mode: $ATTACK_MODE"
echo "  Attacker Ratio: $ATTACKER_RATIO"
echo "  Victim Ratio: $VICTIM_RATIO"
echo "  Victim Count: $VICTIM_COUNT"
echo "  Network Size: $NUM_NODES nodes"
echo "  Workers per Node: $NUM_WORKERS"
echo "  tmux Launch Batch Size: $TMUX_LAUNCH_BATCH_SIZE"
echo "  Duration: $DURATION seconds"
echo "  Minimum Same-Round Samples: $MIN_SAME_ROUND_SAMPLES"
echo "  RUST_LOG: $RUST_LOG"
echo ""

# --- Step 3: Clean previous results ---
echo "🧹 Step 3: Cleaning previous results..."
rm -rf "$LOG_DIR"/* "$BUILD_LOG" "$ATTACK_OUTPUT_LOG" /app/results/logs/* > /dev/null 2>&1 || true
mkdir -p "$LOG_DIR" /app/results/logs
echo "  ✅ Previous logs cleaned"
echo ""

# --- Step 4: Run 4-node network with speculative attack ---
echo "🚀 Step 4: Running ${NUM_NODES}-node network with speculative attack..."
echo "  Duration: $DURATION seconds"
echo "  Network: $NUM_NODES nodes"
echo "  Expected ASR: ~80-90%"
echo ""
echo "  Starting speculative attack..."

cd "$BENCHMARK_DIR"
if [ -d "../venv" ]; then
    source ../venv/bin/activate
else
    echo "⚠️  No venv found, using system python/fab"
fi

# Run the local benchmark in the background and capture output.
# The old fixed 90s timeout is too short once we move beyond ~15 nodes,
# causing partial runs that get reported as synthetic 0.0% ASR.
PROCESS_COUNT=$((NUM_NODES * (2 * NUM_WORKERS + 1)))
STARTUP_BUFFER=$((45 + NUM_NODES + (NUM_WORKERS * 2)))
SCALE_BUFFER=0
if [ "$NUM_NODES" -ge 100 ]; then
    SCALE_BUFFER=$((PROCESS_COUNT + 480))
elif [ "$NUM_NODES" -ge 50 ]; then
    SCALE_BUFFER=$((PROCESS_COUNT + 240))
elif [ "$NUM_NODES" -ge 25 ]; then
    SCALE_BUFFER=$((PROCESS_COUNT / 3 + 120))
fi
FAB_TIMEOUT=$((TEST_DURATION + STARTUP_BUFFER + SCALE_BUFFER))
echo "  Fabric timeout budget: ${FAB_TIMEOUT}s"
timeout --signal=INT --kill-after=30s "${FAB_TIMEOUT}" stdbuf -oL -eL fab local > "$ATTACK_OUTPUT_LOG" 2>&1 &
FAB_PID=$!

echo "  Monitoring attack progress (logs will appear in $LOG_DIR/)..."
echo "  (This will run for approximately $TEST_DURATION seconds)"

# Wait for the benchmark to finish or timeout
FAB_EXIT=0
wait $FAB_PID || FAB_EXIT=$?

if [ "$FAB_EXIT" -eq 124 ]; then
    echo "  ❌ Speculative attack timed out after ${FAB_TIMEOUT}s"
    echo "  Last 30 lines of fab output:"
    tail -n 30 "$ATTACK_OUTPUT_LOG" || true
    mkdir -p /app/results/logs
    cp "$LOG_DIR"/*.log /app/results/logs/ 2>/dev/null || true
    echo "  Active tmux sessions at timeout:"
    tmux ls || echo "No tmux sessions found."
    mkdir -p /app/results/tmux_snapshots
    tmux ls -F '#S' 2>/dev/null | head -n 12 | while read -r session_name; do
        [ -z "$session_name" ] && continue
        tmux capture-pane -pt "$session_name" -S -200 > "/app/results/tmux_snapshots/${session_name}.log" 2>/dev/null || true
    done
elif [ "$FAB_EXIT" -ne 0 ]; then
    echo "  ❌ Speculative attack exited with status $FAB_EXIT"
    echo "  Last 30 lines of fab output:"
    tail -n 30 "$ATTACK_OUTPUT_LOG" || true
    mkdir -p /app/results/logs
    cp "$LOG_DIR"/*.log /app/results/logs/ 2>/dev/null || true
else
    echo "  ✅ Speculative attack completed successfully"
fi
echo ""

# --- Step 5: Analyze attack results ---
echo "📊 Step 5: Analyzing speculative attack results..."

cp "$ATTACK_OUTPUT_LOG" /app/results/speculative_attack_output.log 2>/dev/null || true

if [ ! "$(ls -A "$LOG_DIR" 2>/dev/null)" ]; then
    echo "⚠️ Warning: No logs found in $LOG_DIR!"
    echo "Checking if tmux sessions failed to start..."
    tmux ls || echo "No tmux sessions found."
    echo "Last 20 lines of attack output log ($ATTACK_OUTPUT_LOG):"
    tail -n 20 "$ATTACK_OUTPUT_LOG" || echo "Attack output log is empty or missing."
fi

# Identify the latest primary log
LATEST_PRIMARY_LOG=$(ls -t "$LOG_DIR"/primary-*.log 2>/dev/null | head -1)

if [ -z "$(ls -A "$LOG_DIR" 2>/dev/null)" ]; then
    LATEST_ASR="0.0"
    LATEST_ASR_A="0.0"
    TOTAL_SAMPLES="0"
    CHOSEN_BLOCKS="0"
    CHOSEN_LOG="N/A"
else
    # Parse the latest ASR report from every primary and choose the most complete
    # cluster view: max committed blocks, then max same-round sample count. This
    # avoids arbitrary "tail -1" selection from one lagging primary.
    ASR_PARSE=$(
        python3 - "$LOG_DIR" <<'PY'
import glob
import os
import re
import statistics
import sys

log_dir = sys.argv[1]
pattern = re.compile(
    r'ASR REPORT \((?P<mode>[^)]+)\): '
    r'ASR-A \(All-Pairs\): (?P<asr_a>[0-9.]+)% \((?P<succ_a>\d+)/(?P<total_a>\d+)\) \| '
    r'ASR-B \(Same-Round\): (?P<asr_b>[0-9.]+)% \((?P<succ_b>\d+)/(?P<total_b>\d+)\) \| '
    r'Blocks: (?P<blocks>\d+)'
)

reports = []
for path in glob.glob(os.path.join(log_dir, "primary-*.log")):
    latest = None
    with open(path, "r", errors="ignore") as f:
        for line in f:
            m = pattern.search(line)
            if m:
                latest = {
                    "path": os.path.basename(path),
                    "line": line.strip(),
                    "asr_a": float(m.group("asr_a")),
                    "asr_b": float(m.group("asr_b")),
                    "total_a": int(m.group("total_a")),
                    "total_b": int(m.group("total_b")),
                    "blocks": int(m.group("blocks")),
                }
    if latest:
        reports.append(latest)

if not reports:
    print("0.0\t0.0\t0\t0\tN/A\tNONE\t0.0\t0\t0")
    raise SystemExit(0)

max_blocks = max(r["blocks"] for r in reports)
top = [r for r in reports if r["blocks"] == max_blocks]
max_same_total = max(r["total_b"] for r in top)
top = [r for r in top if r["total_b"] == max_same_total]

# Use the median ASR among the most-complete views to avoid one outlier node.
median_b = statistics.median(r["asr_b"] for r in top)
median_a = statistics.median(r["asr_a"] for r in top)
chosen = min(top, key=lambda r: (abs(r["asr_b"] - median_b), r["path"]))

spread_b = max(r["asr_b"] for r in reports) - min(r["asr_b"] for r in reports)
print(
    f'{chosen["asr_b"]:.2f}\t{chosen["asr_a"]:.2f}\t{chosen["total_b"]}\t{chosen["blocks"]}\t'
    f'{chosen["path"]}\t{chosen["line"]}\t{spread_b:.2f}\t{len(reports)}\t{max_blocks}'
)
PY
    )

    IFS=$'\t' read -r LATEST_ASR LATEST_ASR_A TOTAL_SAMPLES CHOSEN_BLOCKS CHOSEN_LOG ASR_LINE ASR_SPREAD REPORT_COUNT MAX_BLOCKS <<< "$ASR_PARSE"

    if [ -z "$LATEST_ASR" ]; then
        LATEST_ASR="0.0"
    fi
    if [ -z "$LATEST_ASR_A" ]; then
        LATEST_ASR_A="0.0"
    fi
    if [ -z "$TOTAL_SAMPLES" ]; then
        TOTAL_SAMPLES="0"
    fi
    if [ -z "$CHOSEN_BLOCKS" ]; then
        CHOSEN_BLOCKS="0"
    fi
    if [ -z "$CHOSEN_LOG" ]; then
        CHOSEN_LOG="N/A"
    fi
fi

# Reject low-sample ASRs so the sweeper does not record statistically empty wins.
FINAL_REPORTED_ASR="$LATEST_ASR"
RESULT_STATUS="VALID"
if [ "$TOTAL_SAMPLES" -lt "$MIN_SAME_ROUND_SAMPLES" ]; then
    FINAL_REPORTED_ASR="N/A"
    RESULT_STATUS="INSUFFICIENT_SAME_ROUND_SAMPLES"
fi

# Get total ASR success events
TOTAL_SUCCESS=$(grep -c "ASR SUCCESS" "$LOG_DIR"/primary-*.log | awk -F':' '{sum+=$2} END {print sum}')
if [ -z "$TOTAL_SUCCESS" ]; then
    TOTAL_SUCCESS=0
fi

# Get total ASR failure events
TOTAL_FAILURE=$(grep -c "ASR FAILURE" "$LOG_DIR"/primary-*.log | awk -F':' '{sum+=$2} END {print sum}')
if [ -z "$TOTAL_FAILURE" ]; then
    TOTAL_FAILURE=0
fi

# Get total speculative attack events
SPECULATIVE_EVENTS=$(grep -c "Speculative attack:" "$LOG_DIR"/primary-*.log | awk -F':' '{sum+=$2} END {print sum}')
if [ -z "$SPECULATIVE_EVENTS" ]; then
    SPECULATIVE_EVENTS=0
fi

# Identify attacker node (the one with speculative events)
ATTACKER_NODE=$(grep "Speculative attack:" "$LOG_DIR"/primary-*.log | head -1 | awk -F'/' '{print $NF}' | awk -F'-' '{print $1"-"$2}')
if [ -z "$ATTACKER_NODE" ]; then
    ATTACKER_NODE="N/A"
fi

echo "📈 SPECULATIVE ASR CALCULATION:"
echo "==============================="
echo "  Raw Same-Round ASR (ASR-B): $LATEST_ASR%"
echo "  Final ASR (All-Pairs / ASR-A): $LATEST_ASR_A%"
echo "  Reported ASR Result: $FINAL_REPORTED_ASR"
echo "  ASR Success Events: $TOTAL_SUCCESS"
echo "  ASR Failure Events: $TOTAL_FAILURE"
echo "  Speculative Events: $SPECULATIVE_EVENTS"
echo "  Same-Round Samples: $TOTAL_SAMPLES"
echo "  Same-Round Sample Threshold: $MIN_SAME_ROUND_SAMPLES"
echo "  Result Status: $RESULT_STATUS"
echo "  Chosen Primary Log: $CHOSEN_LOG"
echo "  Chosen Report Blocks: $CHOSEN_BLOCKS"
if [ ! -z "$ASR_SPREAD" ]; then
    echo "  Cross-Primary ASR Spread: $ASR_SPREAD points"
fi
echo ""

echo "🎯 SPECULATIVE ATTACK ANALYSIS:"
echo "==============================="
# Try to safely extract just the node integer if possible
ATTACKER_NODE_ID=$(echo "$ATTACKER_NODE" | sed -n 's/.*primary-\([0-9]*\)\.log.*/\1/p')
if [ -z "$ATTACKER_NODE_ID" ]; then
    ATTACKER_NODE_ID="-1"
fi

echo "  Attacker Node: $ATTACKER_NODE ($SPECULATIVE_EVENTS events)"
echo "  Configured Victim Count: $VICTIM_COUNT"
echo "  Victim identity is committee-order based and is not reconstructed here."
echo ""

echo "📊 COMPARISON WITH PAPER:"
echo "========================="
echo "  Paper's Target: $PAPER_ASR_TARGET%"
echo "  Raw Same-Round ASR: $LATEST_ASR%"
if [ "$FINAL_REPORTED_ASR" = "N/A" ]; then
    echo "  Reported ASR: N/A (insufficient same-round samples)"
    echo "FINAL_ASR_RESULT: N/A"
    echo "  Status: ⚠️ INVALID - insufficient same-round samples for a trustworthy ASR."
else
    echo "  Reported ASR: $FINAL_REPORTED_ASR%"
    echo "FINAL_ASR_RESULT: $FINAL_REPORTED_ASR%"
    DIFFERENCE=$(echo "$FINAL_REPORTED_ASR - $PAPER_ASR_TARGET" | bc)
    echo "  Difference: $DIFFERENCE%"
    if (( $(echo "$DIFFERENCE >= -5.0 && $DIFFERENCE <= 5.0" | bc -l) )); then
        echo "  Status: ✅ SUCCESS - ASR within acceptable range!"
    else
        echo "  Status: ❌ FAILURE - ASR outside acceptable range!"
    fi
fi
echo ""

echo "📋 LATEST SPECULATIVE ATTACK EVENTS:"
echo "====================================="
grep "Speculative attack:" "$LOG_DIR"/primary-*.log | tail -3
echo ""

# --- Step 6: Persist logs to results directory ---
echo "💾 Step 6: Persisting logs to results directory..."
mkdir -p /app/results/logs
cp "$LOG_DIR"/primary-*.log /app/results/logs/ 2>/dev/null || true
echo "  ✅ Logs saved to /results/logs/"

echo ""
echo "🎉 AUTOMATED SPECULATIVE ATTACK COMPLETED!"
echo "=========================================="
echo "  Reported ASR: $FINAL_REPORTED_ASR"
echo "  Raw Same-Round ASR: $LATEST_ASR%"
echo "  Total Samples (Same-round): $TOTAL_SAMPLES"
echo "  Logs: /app/results/logs/"
echo ""
echo "🔍 To analyze results manually:"
echo "  grep 'ASR CALCULATION.*Overall' $LOG_DIR/primary-*.log | tail -5"
echo "  grep -c 'Speculative attack:' $LOG_DIR/primary-*.log"
echo ""
echo "📖 For detailed analysis, see: $NARWHAL_TUSK_DIR/SPECULATIVE_ATTACK_IMPLEMENTATION.md"
echo ""
echo "🎯 Expected ASR: 80-90% (matching paper's 86.3%)"
echo "   This was the ACTUAL speculative attack on the real network!"
