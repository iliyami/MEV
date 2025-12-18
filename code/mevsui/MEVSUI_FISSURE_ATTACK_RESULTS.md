# MEVSUI Fissure Attack Results

## Summary

This document reports the results of implementing and testing the Fissure attack on the MEVSUI fork of Sui/Bullshark. MEVSUI is a fork focused on MEV mitigation, and this test evaluates whether those mitigations are effective against the Fissure attack.

## Test Configuration

- **Network Size**: 13 nodes
- **Attackers**: 4 nodes (~30.8%, indices 0-3)
- **Victims**: 3 nodes (~23.1%, indices 10-12)
- **Honest Nodes**: 6 nodes (~46.1%, indices 4-9)
- **Transactions**: 50 transactions
- **Test Duration**: 35 seconds or 15 commits (whichever comes first)
- **Attack Mode**: Fissure (ancestor exclusion)

## Attack Implementation

The Fissure attack was implemented in `consensus/core/src/core.rs` by:

1. **Integration Point**: `smart_ancestors_to_propose()` function
2. **Attack Logic**: Pre-processing ancestors to exclude victim blocks before selection
3. **Quorum-Aware Exclusion**: Conservative exclusion logic that maintains quorum requirements:
   - Requires 20% margin above quorum threshold for safe exclusion
   - Uses reduced probability (50% of base) when margin is tight
   - Never excludes if it would break quorum

### Key Functions Added

- `preprocess_ancestors_for_fissure_attack()` - Main attack logic with quorum-aware exclusion
- `is_victim_block()` - Victim node detection
- `calculate_exclusion_probability()` - Paper's equation implementation
- `should_exclude_victim_block()` - Probability-based exclusion decision
- `FissureAttackMetrics` - Attack performance tracking

## Results

### Attack Success Rate (ASR)

| Metric | Value |
|--------|-------|
| **MEVSUI ASR** | **71.2%** |
| **Bullshark Baseline** | ~87.0% |
| **Difference** | -15.8 percentage points |
| **ASR Calculation** | 1090/1530 pairs |

### Analysis

1. **MEV Mitigation Effectiveness**: The ASR of 71.2% is **16 percentage points lower** than Bullshark's 87%, suggesting that MEVSUI's mitigations or the more conservative quorum-aware exclusion logic may be providing some protection.

2. **Attack Still Effective**: Despite the lower ASR, 71.2% is still significantly above the baseline (50%), indicating the Fissure attack remains effective on MEVSUI.

3. **Quorum-Aware Exclusion**: The conservative quorum-aware exclusion logic prevents breaking consensus but may reduce attack effectiveness compared to more aggressive exclusion strategies.

## Comparison with Bullshark

| Protocol | ASR | Notes |
|----------|-----|-------|
| **Bullshark** | ~87.0% | Original implementation with aggressive exclusion |
| **MEVSUI** | **71.2%** | More conservative quorum-aware exclusion |

### Key Differences

1. **Quorum Protection**: MEVSUI implementation uses more conservative quorum-aware exclusion to prevent consensus failures
2. **Exclusion Probability**: Reduced exclusion probability when quorum margin is tight
3. **Safety Margin**: Requires 20% margin above quorum threshold for safe exclusion

## Code Differences from Bullshark

The MEVSUI implementation differs from Bullshark in:

1. **More Conservative Exclusion**: 
   - Requires 20% margin above quorum threshold
   - Uses 50% probability when margin is tight
   - Never excludes if it would break quorum

2. **API Differences**:
   - `CommitConsumer::new()` instead of `CommitConsumerArgs::new()`
   - Same core consensus logic structure

## Conclusion

The Fissure attack achieved a **71.2% ASR** on MEVSUI, which is:
- **16 percentage points lower** than Bullshark's 87%
- **Still significantly above baseline** (50%), indicating the attack remains effective
- **Suggests partial MEV mitigation** or the conservative quorum-aware exclusion is working

The lower ASR could be due to:
1. MEV mitigations in MEVSUI
2. More conservative quorum-aware exclusion logic
3. Different consensus behavior in the fork

Further investigation would be needed to determine if the lower ASR is due to intentional MEV mitigations or the more conservative attack implementation.

## Files Modified

1. `consensus/core/src/core.rs` - Added Fissure attack functions
2. `consensus/core/src/fissure_attack_test.rs` - Created test file
3. `consensus/core/src/lib.rs` - Added test module
4. `automated_fissure_attack.sh` - Created automation script

## Test Execution

To run the test:

```bash
cd code/mevsui
export ATTACK_MODE="fissure"
export ATTACKER_RATIO="0.308"
export VICTIM_RATIO="0.231"
cargo test --release --package consensus-core --lib fissure_attack_test::test_fissure_attack_asr_13_nodes -- --nocapture
```

Or use the automated script:

```bash
./automated_fissure_attack.sh
```


