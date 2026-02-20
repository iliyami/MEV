#!/bin/bash
# Force disable sccache to avoid "Operation not permitted" errors
export RUSTC_WRAPPER=""
export TMPDIR="$(pwd)/../../../../../tmp"

# Ensure we are in the right directory
cd "$(dirname "$0")/../code/bullshark/consensus/core"

echo "🚀 Building and Running Speculative Backrun Locally..."

# Check if we can run cargo
if ! command -v cargo &> /dev/null; then
    echo "Error: cargo not found. Please install Rust."
    exit 1
fi

set -x
# Run Speculative Backrun
# We use the specific test function and pass all required env vars
ATTACK_MODE=speculative \
ATTACK_TYPE=${ATTACK_TYPE:-backrun} \
ATTACKER_RATIO=${ATTACKER_RATIO:-0.308} \
VICTIM_RATIO=${VICTIM_RATIO:-0.231} \
NUM_NODES=${NUM_NODES:-13} \
SPECULATIVE_P_MAX=50 \
cargo test \
    --package consensus-core \
    --lib -- test_speculative_attack_asr_dynamic --nocapture

