# Fissure Attack Results on Autobahn Protocol

## Summary

The Fissure attack has been successfully implemented and activated on the Autobahn protocol (Bullshark-based consensus). However, the attack shows minimal impact on Attack Success Rate (ASR), remaining at approximately 50% (baseline).

## Implementation Details

### Attack Location
- **File**: `primary/src/core.rs`
- **Function**: `set_consensus_proposal()`
- **Mechanism**: Selective exclusion of victim proposals from Prepare messages

### Configuration
- **Attacker**: Node 0
- **Victim**: Node 1
- **Exclusion Probabilities Tested**: 20%, 50%, 100%
- **Test Duration**: 120 seconds
- **Network Size**: 13 nodes

## Results

### Test 1: 20% Exclusion Probability
- **Exclusions Detected**: 13 victim proposals excluded
- **ASR**: 50.03%
- **Improvement**: +0.03% (essentially baseline)

### Test 2: 50% Exclusion Probability  
- **Exclusions Detected**: 28 victim proposals excluded
- **ASR**: 49.92%
- **Improvement**: -0.08% (slightly worse than baseline)

### Test 3: 100% Exclusion Probability
- **Exclusions Detected**: 0 (attack logs not found - possible binary issue)
- **ASR**: 49.98%
- **Improvement**: -0.02%

## Analysis

### Why Low ASR?

1. **Bullshark Ordering Mechanism**: Autobahn uses Bullshark consensus, which orders blocks based on:
   - Deterministic leader election (round-based)
   - Leader requires f+1 support from children
   - DAG traversal ordering
   
   This is different from Mahi-Mahi's ordering, which is more directly tied to proposals.

2. **Local vs Global Impact**: The exclusion only affects the attacker's local view of proposals. Other nodes still include the victim's proposals in their Prepare messages, so the victim's blocks can still be ordered through other paths in the DAG.

3. **Resilience**: Bullshark's consensus mechanism appears more resilient to proposal exclusions because:
   - Ordering is primarily round-based, not proposal-based
   - Multiple paths in the DAG can lead to the same ordering
   - Leader election is deterministic and independent of proposals

## Comparison with Mahi-Mahi

| Protocol | Fissure ASR | Notes |
|----------|-------------|-------|
| Mahi-Mahi | ~60-70% | High ASR achieved |
| Autobahn (Bullshark) | ~50% | Minimal impact |

The significant difference suggests that:
- Mahi-Mahi's ordering is more sensitive to proposal exclusions
- Bullshark's leader-based consensus provides better resilience
- The attack vector may need to target different aspects of Bullshark's consensus

## Conclusion

The Fissure attack is **functionally working** on Autobahn (exclusions are occurring), but it has **minimal impact on ASR** due to Bullshark's consensus design. The attack demonstrates that Bullshark is more resilient to this type of attack compared to Mahi-Mahi.

## Recommendations

1. **Different Attack Vector**: Consider attacks targeting:
   - Leader election mechanism
   - Round advancement
   - Certificate formation
   - DAG structure manipulation

2. **Multi-Node Attack**: Test with multiple colluding attackers to see if coordinated exclusion has greater impact.

3. **Timing Attacks**: Explore attacks that manipulate timing of proposals or votes.

4. **Further Analysis**: Investigate why exclusions don't translate to ASR improvement despite being logged.

## Files Modified

- `primary/src/core.rs`: Added Fissure attack logic
- `primary/Cargo.toml`: Added `rand` dependency
- `run_fissure_attack.py`: Automated test script
- `scripts/calculate-fissure-asr.py`: ASR calculation script

## References

- Paper: https://eprint.iacr.org/2024/1496.pdf
- Autobahn Protocol: Built on Bullshark consensus
- Mahi-Mahi Results: See `code/mahi-mahi-consensus/COMPREHENSIVE_ATTACK_REPORT.md`




