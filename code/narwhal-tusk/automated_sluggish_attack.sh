#!/bin/bash

echo "🐌 Automated Sluggish Attack for Narwhal-Tusk"
echo "============================================"
echo "This script will:"
echo "  1. Build the project with sluggish attack configuration"
echo "  2. Run the network with round-lagging attackers"
echo "  3. Calculate paper-aligned ASR results"
echo "  4. Compare with the paper's target (82.4%)"
echo ""

NARWHAL_TUSK_DIR=$(pwd)
BENCHMARK_DIR="$NARWHAL_TUSK_DIR/benchmark"
LOG_DIR="$BENCHMARK_DIR/logs"
BUILD_LOG="$NARWHAL_TUSK_DIR/build.log"
ATTACK_OUTPUT_LOG="$NARWHAL_TUSK_DIR/sluggish_attack_output.log"

export NUM_NODES=${1:-${NUM_NODES:-15}}
export ATTACKER_RATIO=${2:-${ATTACKER_RATIO:-0.33}}
export VICTIM_RATIO=${3:-${VICTIM_RATIO:-0.22}}
export DURATION=${4:-${DURATION:-35}}
export TEST_DURATION=$DURATION
export ATTACK_MODE=${ATTACK_MODE:-sluggish}
export SLUGGISH_TIMEOUT_MULTIPLIER=${SLUGGISH_TIMEOUT_MULTIPLIER:-2.0}
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
export PAPER_TARGET=${PAPER_TARGET:-82.4}

if [ "$PWD" == "/app" ]; then
    echo "⚠️ Running in /app, continuing..."
elif [ ! -d "$NARWHAL_TUSK_DIR" ]; then
    echo "❌ Error: Directory $NARWHAL_TUSK_DIR not found."
    exit 1
fi

if [ -f "target/release/primary" ] || [ -f "primary" ] || [ -f "target/release/node" ] || [ -f "node" ]; then
    echo "🔨 Step 1: Skipping build (binary already exists)"
    if [ ! -f "target/release/node" ] && [ -f "node" ]; then
        mkdir -p target/release
        cp node target/release/node
    fi
else
    echo "🔨 Step 1: Building project with sluggish attack code..."
    cd "$NARWHAL_TUSK_DIR"
    export RUSTC_WRAPPER=sccache
    cargo build --release
    echo "  ✅ Build successful"
fi
echo ""

echo "⚙️  Step 2: Configuring sluggish attack parameters..."
echo "  Attack Mode: $ATTACK_MODE"
echo "  Attacker Ratio: $ATTACKER_RATIO"
echo "  Victim Ratio: $VICTIM_RATIO"
echo "  Victim Count: $VICTIM_COUNT"
echo "  Timeout Multiplier: $SLUGGISH_TIMEOUT_MULTIPLIER"
echo "  Network Size: $NUM_NODES nodes"
echo "  Workers per Node: $NUM_WORKERS"
echo "  Duration: $DURATION seconds"
echo "  Minimum Same-Round Samples: $MIN_SAME_ROUND_SAMPLES"
echo "  RUST_LOG: $RUST_LOG"
echo ""

echo "🧹 Step 3: Cleaning previous results..."
rm -rf "$LOG_DIR"/* "$BUILD_LOG" "$ATTACK_OUTPUT_LOG" /app/results/logs/* > /dev/null 2>&1 || true
mkdir -p "$LOG_DIR" /app/results/logs
echo "  ✅ Previous logs cleaned"
echo ""

echo "🚀 Step 4: Running $NUM_NODES-node network with sluggish attack..."
echo "  Duration: $DURATION seconds"
echo "  Network: $NUM_NODES nodes"
echo "  Expected Same-Round ASR: ~$PAPER_TARGET%"
echo ""
echo "  Starting sluggish attack..."

cd "$BENCHMARK_DIR"
if [ -d "../venv" ]; then
    source ../venv/bin/activate
else
    echo "⚠️  No venv found, using system python/fab"
fi

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

FAB_EXIT=0
wait $FAB_PID || FAB_EXIT=$?

if [ "$FAB_EXIT" -eq 124 ]; then
    echo "  ❌ Sluggish attack timed out after ${FAB_TIMEOUT}s"
    echo "  Last 30 lines of fab output:"
    tail -n 30 "$ATTACK_OUTPUT_LOG" || true
    mkdir -p /app/results/logs
    cp "$LOG_DIR"/*.log /app/results/logs/ 2>/dev/null || true
elif [ "$FAB_EXIT" -ne 0 ]; then
    echo "  ❌ Sluggish attack exited with status $FAB_EXIT"
    echo "  Last 30 lines of fab output:"
    tail -n 30 "$ATTACK_OUTPUT_LOG" || true
    mkdir -p /app/results/logs
    cp "$LOG_DIR"/*.log /app/results/logs/ 2>/dev/null || true
else
    echo "  ✅ Sluggish attack completed successfully"
fi
echo ""

echo "📊 Step 5: Analyzing sluggish attack results..."
cp "$ATTACK_OUTPUT_LOG" /app/results/sluggish_attack_output.log 2>/dev/null || true

if [ ! "$(ls -A "$LOG_DIR" 2>/dev/null)" ]; then
    echo "⚠️ Warning: No logs found in $LOG_DIR!"
    echo "Checking if tmux sessions failed to start..."
    tmux ls || echo "No tmux sessions found."
    echo "Last 20 lines of attack output log ($ATTACK_OUTPUT_LOG):"
    tail -n 20 "$ATTACK_OUTPUT_LOG" || echo "Attack output log is empty or missing."
fi

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
            if m and m.group("mode") == "sluggish":
                latest = {
                    "path": os.path.basename(path),
                    "line": line.strip(),
                    "asr_a": float(m.group("asr_a")),
                    "asr_b": float(m.group("asr_b")),
                    "succ_a": int(m.group("succ_a")),
                    "total_a": int(m.group("total_a")),
                    "succ_b": int(m.group("succ_b")),
                    "total_b": int(m.group("total_b")),
                    "blocks": int(m.group("blocks")),
                }
    if latest:
        reports.append(latest)

if not reports:
    print("0.0\t0.0\t0\t0\t0\t0\tN/A\t0\t0.0")
    raise SystemExit(0)

max_blocks = max(r["blocks"] for r in reports)
top = [r for r in reports if r["blocks"] == max_blocks]
max_same_total = max(r["total_b"] for r in top)
top = [r for r in top if r["total_b"] == max_same_total]

median_b = statistics.median(r["asr_b"] for r in top)
chosen = min(top, key=lambda r: (abs(r["asr_b"] - median_b), r["path"]))
spread_b = max(r["asr_b"] for r in reports) - min(r["asr_b"] for r in reports)

print(
    f'{chosen["asr_b"]:.2f}\t{chosen["asr_a"]:.2f}\t{chosen["total_b"]}\t{chosen["total_a"]}\t'
    f'{chosen["blocks"]}\t{chosen["succ_b"]}\t{chosen["path"]}\t{len(reports)}\t{spread_b:.2f}'
)
PY
)

IFS=$'\t' read -r LATEST_ASR_B LATEST_ASR_A TOTAL_SAMPLES_B TOTAL_SAMPLES_A CHOSEN_BLOCKS TOTAL_SUCCESS CHOSEN_LOG REPORT_COUNT ASR_SPREAD <<< "$ASR_PARSE"
LATEST_ASR_B=${LATEST_ASR_B:-0.0}
LATEST_ASR_A=${LATEST_ASR_A:-0.0}
TOTAL_SAMPLES_B=${TOTAL_SAMPLES_B:-0}
TOTAL_SAMPLES_A=${TOTAL_SAMPLES_A:-0}
CHOSEN_BLOCKS=${CHOSEN_BLOCKS:-0}
TOTAL_SUCCESS=${TOTAL_SUCCESS:-0}
CHOSEN_LOG=${CHOSEN_LOG:-N/A}
REPORT_COUNT=${REPORT_COUNT:-0}
ASR_SPREAD=${ASR_SPREAD:-0.0}

FINAL_REPORTED_ASR="$LATEST_ASR_B"
RESULT_STATUS="VALID"
if [ "$TOTAL_SAMPLES_B" -lt "$MIN_SAME_ROUND_SAMPLES" ]; then
    FINAL_REPORTED_ASR="N/A"
    RESULT_STATUS="INSUFFICIENT_SAME_ROUND_SAMPLES"
fi

TOTAL_FAILURE=$(grep -c "ASR FAILURE" "$LOG_DIR"/primary-*.log | awk -F':' '{sum+=$2} END {print sum}')
if [ -z "$TOTAL_FAILURE" ]; then
    TOTAL_FAILURE=0
fi

TIMEOUT_EVENTS=$(grep -c "Sluggish attack: Node .* using modified timeout" "$LOG_DIR"/primary-*.log | awk -F':' '{sum+=$2} END {print sum}')
if [ -z "$TIMEOUT_EVENTS" ]; then
    TIMEOUT_EVENTS=0
fi

PROPOSAL_EVENTS=$(grep -c "Sluggish attack: Node .* proposing after intentional delay" "$LOG_DIR"/primary-*.log | awk -F':' '{sum+=$2} END {print sum}')
if [ -z "$PROPOSAL_EVENTS" ]; then
    PROPOSAL_EVENTS=0
fi

LAG_EVENTS=$(grep -c "SLUGGISH ATTACK: Delaying proposal to lag round" "$LOG_DIR"/primary-*.log | awk -F':' '{sum+=$2} END {print sum}')
if [ -z "$LAG_EVENTS" ]; then
    LAG_EVENTS=0
fi

echo "📈 SLUGGISH ASR CALCULATION:"
echo "============================"
echo "  Raw Same-Round ASR (ASR-B): $LATEST_ASR_B%"
echo "  Raw All-Pairs ASR (ASR-A): $LATEST_ASR_A%"
echo "  Reported ASR Result: $FINAL_REPORTED_ASR"
echo "  Same-Round Samples: $TOTAL_SAMPLES_B"
echo "  All-Pairs Samples: $TOTAL_SAMPLES_A"
echo "  Same-Round Sample Threshold: $MIN_SAME_ROUND_SAMPLES"
echo "  Result Status: $RESULT_STATUS"
echo "  Timeout Modification Events: $TIMEOUT_EVENTS"
echo "  Sluggish Proposal Events: $PROPOSAL_EVENTS"
echo "  Lag-Behind Events: $LAG_EVENTS"
echo "  Chosen Primary Log: $CHOSEN_LOG"
echo "  Chosen Report Blocks: $CHOSEN_BLOCKS"
echo "  Cross-Primary ASR Spread: $ASR_SPREAD points"
echo ""

echo "📊 COMPARISON WITH PAPER:"
echo "========================="
echo "  Paper's Target (Same-Round): $PAPER_TARGET%"
echo "  Raw Same-Round ASR: $LATEST_ASR_B%"
if [ "$FINAL_REPORTED_ASR" = "N/A" ]; then
    echo "  Reported ASR: N/A (insufficient same-round samples)"
    echo "FINAL_ASR_RESULT: N/A"
    echo "  Status: ⚠️ INVALID - insufficient same-round samples for a trustworthy ASR."
else
    echo "  Reported ASR: $FINAL_REPORTED_ASR%"
    echo "FINAL_ASR_RESULT: $FINAL_REPORTED_ASR%"
    DIFF=$(echo "$FINAL_REPORTED_ASR - $PAPER_TARGET" | bc)
    echo "  Difference: $DIFF%"
    if (( $(echo "$DIFF >= -5.0 && $DIFF <= 5.0" | bc -l) )); then
        echo "  Status: ✅ SUCCESS - ASR within acceptable range!"
    else
        echo "  Status: ❌ FAILURE - ASR outside acceptable range!"
    fi
fi
echo ""

echo "📋 LATEST SLUGGISH ATTACK EVENTS:"
echo "================================"
grep -h "Sluggish attack:" "$LOG_DIR"/primary-*.log | tail -5
echo ""

echo "💾 Step 6: Persisting logs to results directory..."
mkdir -p /app/results/logs
cp "$LOG_DIR"/primary-*.log /app/results/logs/ 2>/dev/null || true
echo "  ✅ Logs saved to /results/logs/"
echo ""

echo "🎉 AUTOMATED SLUGGISH ATTACK COMPLETED!"
echo "======================================="
echo "  Reported ASR: $FINAL_REPORTED_ASR"
echo "  Raw Same-Round ASR: $LATEST_ASR_B%"
echo "  Total Samples (Same-round): $TOTAL_SAMPLES_B"
echo "  Logs: /app/results/logs/"
