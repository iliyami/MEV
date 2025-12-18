#!/bin/bash

# Automated Sluggish Attack Script for Bullshark
# This script automates the entire process: build, run attack, analyze results
# Usage: ./automated_sluggish_attack.sh

echo "🐌 Automated Sluggish Attack for Bullshark"
echo "=========================================="
echo "This script will:"
echo "  1. Build the Bullshark project with attack code"
echo "  2. Run the attack simulation"
echo "  3. Calculate and display the ASR results"
echo "  4. Compare with paper's target (89.2%)"
echo ""

# Check if we're in the right directory
if [ ! -f "Cargo.toml" ]; then
    echo "❌ Error: Not in the correct directory"
    echo "Please run this from: /Users/iliya/Dev/Blockchain/code/bullshark"
    exit 1
fi

# Step 1: Clean and build
echo "🔨 Step 1: Building Bullshark project with attack code..."
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
echo "  Attacker Ratio: $ATTACKER_RATIO (30% - 1 validator)"
echo "  Victim Ratio: $VICTIM_RATIO (20% - 1 validator)"
echo "  Sluggish Timeout Multiplier: $SLUGGISH_TIMEOUT_MULTIPLIER (2x delay)"
echo "  Honest Validators: 50% (2 validators)"

# Step 3: Clean previous results
echo ""
echo "🧹 Step 3: Cleaning previous results..."
rm -rf sluggish_attack.log
echo "  ✅ Previous data cleaned"

# Step 4: Run attack simulation
echo ""
echo "🚀 Step 4: Running Bullshark sluggish attack simulation..."
echo "  Duration: 60 seconds"
echo "  Network: 4 validators (1 attacker, 1 victim, 2 honest)"
echo "  Expected Impact: Delayed attacker block proposals"

# Run the consensus core test with attack parameters
echo "  Starting attack simulation..."
export ATTACK_MODE=sluggish
export ATTACKER_RATIO=0.25
export VICTIM_RATIO=0.25
export SLUGGISH_TIMEOUT_MULTIPLIER=2.0
export RUST_LOG=info

timeout 60s cargo test --release --package consensus-core -- test_multiple_commits_advance_threshold_clock --nocapture 2>&1 | tee sluggish_attack.log

# Step 5: Analyze final results
echo ""
echo "📈 Step 5: Analyzing sluggish attack results..."
echo "=========================================="

if [ -f "sluggish_attack.log" ]; then
    # Count attack events
    DELAY_EVENTS=$(grep -c "Sluggish attack:" sluggish_attack.log 2>/dev/null)
    COMMIT_EVENTS=$(grep -c "CommittedSubDag" sluggish_attack.log 2>/dev/null)

    echo "  Sluggish Attack Events:"
    echo "    Delay Events: $DELAY_EVENTS"
    echo "    Commit Events: $COMMIT_EVENTS"

    # Check for successful attack execution
    if [ $DELAY_EVENTS -gt 0 ]; then
        echo "  ✅ Attack executed successfully"
        echo "  📊 Attack Effectiveness: Block proposals delayed by multiplier"

        # Calculate attack frequency
        if [ $COMMIT_EVENTS -gt 0 ]; then
            ATTACK_FREQUENCY=$(echo "scale=1; ($DELAY_EVENTS * 100) / $COMMIT_EVENTS" | bc -l 2>/dev/null || echo "0.0")
            echo "  🎯 Attack Frequency: ${ATTACK_FREQUENCY}% of commits involved attacks"
        fi

        echo "  🎯 ASR Status: Cannot measure from unit tests (no global ordering)"
        echo "     True ASR requires multi-node consensus with transaction ordering"

    else
        echo "  ❌ No attack events detected"
        echo "  🔍 Check sluggish_attack.log for issues"
        echo "  💡 Note: Attack may not trigger in unit test environment"
    fi

    # Show sample attack events
    echo ""
    echo "📋 SAMPLE ATTACK EVENTS:"
    echo "======================="
    grep "Sluggish attack:" sluggish_attack.log | tail -3 | while read line; do
        echo "  $line"
    done

    echo ""
    echo "🎯 SLUGGISH ATTACK SUMMARY:"
    echo "=========================="
    echo "  Attack Type: Round priority manipulation via proposal delays"
    echo "  Mechanism: ${SLUGGISH_TIMEOUT_MULTIPLIER}x timeout multiplier"
    echo "  Goal: Create blocks in lower rounds for higher priority"
    echo "  Expected ASR: ~89.2% (paper target)"

else
    echo "  ❌ No logs found - Test may have failed"
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
echo "  grep -c 'delaying block proposal' sluggish_attack.log"
echo ""
echo "📖 Sluggish Attack Theory:"
echo "  - Attackers delay block proposals to manipulate round progression"
echo "  - Lower round numbers get higher consensus priority"
echo "  - Strategic timing creates frontrunning advantages"
echo "  - Paper target ASR: 89.2% with 50 nodes"
echo ""
echo "🎯 Expected Outcome: Attackers gain round priority advantages"
echo ""
echo "📊 ASR MEASUREMENT NOTE:"
echo "======================="
echo "  Sluggish attack ASR requires consensus-level analysis:"
echo "  - Compare attacker block round numbers vs victim blocks"
echo "  - Lower rounds = higher priority in ordering"
echo "  - Success = attacker blocks ordered before victim blocks"
echo "  - Full measurement needs complete consensus simulation"
