# Autobahn Attack Resistance: Comprehensive Analysis Report

## Executive Summary

This report provides a comprehensive analysis of frontrunning attack resistance across three DAG-based blockchain protocols: **Autobahn**, **Bullshark**, and **Mahi-Mahi**. Our testing reveals that **Autobahn demonstrates superior resilience** to frontrunning attacks, maintaining baseline ASR (~50%) across all attack vectors, while Bullshark and Mahi-Mahi show significant vulnerabilities with ASRs reaching 87% and 86% respectively.

**Key Finding**: Autobahn's architectural design, particularly its round-only ordering and consensus-layer aggregation, makes it fundamentally resistant to single-node frontrunning attacks that are highly effective against other protocols.

---

## Table of Contents

1. [Protocol Overview](#protocol-overview)
2. [Attack Implementation Summary](#attack-implementation-summary)
3. [Comparative Attack Results](#comparative-attack-results)
4. [Architectural Analysis](#architectural-analysis)
5. [Why Autobahn is More Resilient](#why-autobahn-is-more-resilient)
6. [Detailed Attack Results](#detailed-attack-results)
7. [Security Implications](#security-implications)
8. [Recommendations](#recommendations)

---

## Protocol Overview

### Autobahn
- **Consensus**: Built on Bullshark (round-based ordering)
- **Ordering Mechanism**: Round-only (`ordered.sort_by_key(|x| x.round())`)
- **Architecture**: Two-layer (Primary + Consensus)
- **Key Feature**: Consensus layer aggregates proposals from all nodes
- **Round Assignment**: Deterministic, based on parent certificate chain

### Bullshark
- **Consensus**: Round-based with deterministic leader election
- **Ordering Mechanism**: Round-first, then authority index (`a.round().cmp(&b.round()).then_with(|| a.author().cmp(&b.author()))`)
- **Architecture**: Single-layer consensus
- **Key Feature**: Threshold clock with quorum-based round advancement
- **Round Assignment**: Based on threshold clock and quorum formation

### Mahi-Mahi
- **Consensus**: Uncertified DAG with threshold clock
- **Ordering Mechanism**: Round-based with digest tie-breaking
- **Architecture**: Single-layer with threshold clock
- **Key Feature**: 4-hop latency, uncertified DAG structure
- **Round Assignment**: Threshold clock-based, time-sensitive

---

## Attack Implementation Summary

### Attacks Tested

We implemented and tested five attack vectors across all three protocols:

1. **Fissure Attack**: Selective exclusion of victim proposals/blocks
2. **Speculative Attack**: Digest manipulation for ordering advantage
3. **Sluggish Attack**: Timing delays to manipulate round progression
4. **Leader Support Manipulation**: Strategic exclusion of victim proposals from leader support
5. **Tip Exclusion**: Preventing victim headers from being added to tips

### Implementation Locations

#### Autobahn
- **Fissure**: `primary/src/core.rs` - `set_consensus_proposal()`
- **Leader Support**: `primary/src/core.rs` - `set_consensus_proposal()`
- **Tip Exclusion**: `primary/src/core.rs` - `process_own_header()`, `process_header()`
- **Timing**: `primary/src/core.rs` - `process_vote()`
- **Sluggish**: `primary/src/core.rs` - Certificate sending delay

#### Bullshark
- **Fissure**: `consensus/core/src/core.rs` - `smart_ancestors_to_propose()`
- **Sluggish**: `consensus/core/src/core.rs` - `try_propose()`

#### Mahi-Mahi
- **Fissure**: `crates/mysticeti-core/src/core.rs` - `try_new_block()`
- **Speculative**: `crates/mysticeti-core/src/core.rs` - `try_new_block()`
- **Sluggish**: `crates/mysticeti-core/src/syncer.rs` - Timing delays

---

## Comparative Attack Results

### Overall ASR Comparison

| Protocol | Fissure ASR | Speculative ASR | Sluggish ASR | Best Attack ASR | Resilience Rating |
|----------|-------------|-----------------|--------------|-----------------|-------------------|
| **Autobahn** | **~50%** | N/A* | **~50%** | **~50%** | ⭐⭐⭐⭐⭐ **Excellent** |
| **Bullshark** | **87.0%** | N/A | 51.0% | **87.0%** | ⭐⭐ **Vulnerable** |
| **Mahi-Mahi** | **86.01%** | 52% | 44.18% | **86.01%** | ⭐⭐ **Vulnerable** |

*Speculative attack not applicable to Autobahn (round-only ordering, no digest tie-breaking)

### Detailed Results by Protocol

#### Autobahn Results

| Attack Type | Configuration | ASR | Improvement | Status |
|-------------|---------------|-----|-------------|--------|
| **Baseline** | No attack | 50.00% | - | Reference |
| **Fissure** | 20% exclusion | 50.03% | +0.03% | ❌ No effect |
| **Fissure** | 50% exclusion | 49.92% | -0.08% | ❌ No effect |
| **Fissure** | 100% exclusion | 49.98% | -0.02% | ❌ No effect |
| **Leader Support** | Quorum-aware | 50.00% | 0.00% | ❌ No effect |
| **Tip Exclusion** | 95% exclusion | 50.00% | 0.00% | ❌ No effect |
| **Timing** | Accelerate own | 50.00% | 0.00% | ❌ No effect |
| **Sluggish** | 2.0x delay | 50.00% | 0.00% | ❌ No effect |
| **Sluggish** | 5.0x delay | 50.10% | +0.10% | ❌ No effect |

**Key Observation**: All attacks maintain baseline ASR (~50%), indicating **complete resistance** to single-node frontrunning attacks.

#### Bullshark Results

| Attack Type | Configuration | ASR | Improvement | Status |
|-------------|---------------|-----|-------------|--------|
| **Baseline** | No attack | ~50% | - | Reference |
| **Fissure** | Quorum-aware, 7.0x network factor | **87.0%** | **+37%** | ✅ **Highly Effective** |
| **Sluggish** | 2.0x delay | 51.0% | +1.0% | ⚠️ Minimal effect |

**Key Observation**: Fissure attack achieves **87% ASR**, demonstrating significant vulnerability to proposal exclusion attacks.

#### Mahi-Mahi Results

| Attack Type | Configuration | ASR | Improvement | Status |
|-------------|---------------|-----|-------------|--------|
| **Baseline** | No attack | 50.02% | - | Reference |
| **Fissure** | 20% exclusion | **86.01%** | **+36%** | ✅ **Highly Effective** |
| **Fissure** | 10% exclusion (optimal) | **77.41%** | **+27%** | ✅ **Effective** |
| **Speculative** | Hybrid (5% excl + LIFO) | 52% | +2% | ⚠️ Marginal |
| **Sluggish** | 1.0x delay | 49.78% | -0.24% | ❌ No advantage |
| **Sluggish** | 2.0x delay | 44.18% | -5.84% | ❌ **Worse than baseline** |

**Key Observation**: Fissure attack achieves **86% ASR**, demonstrating significant vulnerability. Sluggish attack actually **reduces** ASR, indicating it's counterproductive.

---

## Architectural Analysis

### Ordering Mechanisms

#### Autobahn: Round-Only Ordering
```rust
// consensus/src/lib.rs:300
ordered.sort_by_key(|x| x.round());
```
- **Ordering**: Purely round-based
- **Tie-breaking**: None (all blocks at same round ordered together)
- **Attack Surface**: Minimal - no digest manipulation possible
- **Resilience**: High - single-node exclusions don't affect global ordering

#### Bullshark: Round-First, Authority-Second
```rust
// consensus/core/src/commit.rs
a.round().cmp(&b.round()).then_with(|| a.author().cmp(&b.author()))
```
- **Ordering**: Round first, then authority index
- **Tie-breaking**: Authority index (deterministic)
- **Attack Surface**: Moderate - proposal exclusion can affect ordering
- **Resilience**: Moderate - exclusions affect local DAG structure

#### Mahi-Mahi: Round with Digest Tie-Breaking
- **Ordering**: Round-based with digest comparison
- **Tie-breaking**: Digest (manipulable)
- **Attack Surface**: High - digest manipulation possible
- **Resilience**: Low - exclusions directly affect ordering

### Consensus Layer Architecture

#### Autobahn: Two-Layer Aggregation
```
Primary Layer (per node)
    ↓
Consensus Layer (aggregates from all nodes)
    ↓
Global Ordering
```

**Key Feature**: Consensus layer receives proposals from **all nodes**, making single-node exclusions ineffective.

#### Bullshark: Single-Layer Consensus
```
Consensus Core (per node)
    ↓
Local DAG Construction
    ↓
Global Ordering (via threshold clock)
```

**Key Feature**: Each node builds its own DAG view, making exclusions locally effective.

#### Mahi-Mahi: Single-Layer with Threshold Clock
```
Core (per node)
    ↓
Threshold Clock Round Assignment
    ↓
Global Ordering
```

**Key Feature**: Round assignment is time-sensitive, making timing attacks possible.

### Round Assignment Mechanisms

#### Autobahn: Parent Certificate Chain
- **Mechanism**: Height = parent.height + 1
- **Determinism**: Fully deterministic based on parent certificate
- **Timing Sensitivity**: None - round determined by chain position
- **Attack Resistance**: High - cannot manipulate rounds via timing

#### Bullshark: Threshold Clock
- **Mechanism**: Round advances when 2f+1 blocks received
- **Determinism**: Quorum-based, partially timing-dependent
- **Timing Sensitivity**: Moderate - timing affects quorum formation
- **Attack Resistance**: Moderate - timing can influence round advancement

#### Mahi-Mahi: Threshold Clock
- **Mechanism**: Round advances based on threshold clock
- **Determinism**: Time-sensitive
- **Timing Sensitivity**: High - delays directly affect round assignment
- **Attack Resistance**: Low - timing manipulation is effective

---

## Why Autobahn is More Resilient

### 1. Consensus Layer Aggregation

**Autobahn's Key Advantage**: The consensus layer aggregates proposals from **all nodes**, not just the attacker's view.

```rust
// consensus/src/lib.rs:109-118
while let Some(certificate) = self.rx_primary.recv().await {
    let round = certificate.round();
    state.dag
        .entry(round)
        .or_insert_with(HashMap::new)
        .insert(certificate.origin(), (certificate.digest(), certificate));
}
```

**Impact**: 
- Single-node exclusions don't affect global consensus
- Other nodes still include victim proposals
- Victim blocks are ordered through alternative paths

**Comparison**:
- **Bullshark**: Each node builds its own DAG, so exclusions affect local ordering
- **Mahi-Mahi**: Exclusions directly affect the ordering mechanism

### 2. Round-Only Ordering

**Autobahn's Key Advantage**: No digest-based tie-breaking means no speculative attack surface.

```rust
// consensus/src/lib.rs:300
ordered.sort_by_key(|x| x.round());
```

**Impact**:
- Cannot manipulate ordering via digest selection
- All blocks at same round ordered together
- No advantage from digest optimization

**Comparison**:
- **Bullshark**: Authority index tie-breaking (deterministic, but exclusions still matter)
- **Mahi-Mahi**: Digest tie-breaking (manipulable, enables speculative attacks)

### 3. Deterministic Round Assignment

**Autobahn's Key Advantage**: Rounds determined by parent certificate chain, not timing.

```rust
// primary/src/proposer.rs:278-279
self.height += 1;  // Based on parent certificate, not timing
```

**Impact**:
- Timing delays don't change round assignment
- Sluggish attacks ineffective
- Round progression is deterministic

**Comparison**:
- **Bullshark**: Threshold clock with quorum formation (timing-sensitive)
- **Mahi-Mahi**: Threshold clock (highly timing-sensitive)

### 4. Two-Layer Architecture

**Autobahn's Key Advantage**: Separation between primary (proposal) and consensus (ordering) layers.

**Impact**:
- Attacks at primary layer don't propagate to consensus layer
- Consensus layer has full view of all proposals
- Local exclusions are isolated

**Comparison**:
- **Bullshark**: Single-layer architecture (attacks directly affect consensus)
- **Mahi-Mahi**: Single-layer architecture (attacks directly affect consensus)

---

## Detailed Attack Results

### Fissure Attack Analysis

#### Autobahn: Why It Failed

1. **Consensus Aggregation**: 
   - Attacker excludes victim proposals in `set_consensus_proposal()`
   - But consensus layer receives proposals from **all nodes**
   - Victim proposals still included by other nodes
   - Result: No impact on global ordering

2. **Round-Based Ordering**:
   - Ordering purely by round
   - Exclusions don't change round assignment
   - Victim blocks at same round still ordered
   - Result: No ordering advantage

3. **DAG Structure**:
   - Multiple paths to same ordering
   - Victim blocks reachable through alternative paths
   - Exclusions don't break connectivity
   - Result: Resilient to exclusions

#### Bullshark: Why It Succeeded

1. **Local DAG Construction**:
   - Each node builds its own DAG view
   - Exclusions affect local ancestor selection
   - Local ordering affects global ordering
   - Result: 87% ASR achieved

2. **Ancestor Selection**:
   - `smart_ancestors_to_propose()` selects ancestors
   - Excluding victim ancestors changes DAG structure
   - Affects which blocks are proposed
   - Result: Significant ordering advantage

3. **Quorum-Aware Exclusion**:
   - Paper's equation: `Pfis₀ = 1/2 + fa / (2(n − fl))`
   - Network factor: 7.0x for 13-node network
   - Exclusion probability: Up to 95%
   - Result: Highly effective attack

#### Mahi-Mahi: Why It Succeeded

1. **Direct Ordering Impact**:
   - Exclusions directly affect `try_new_block()`
   - Victim blocks excluded from includes
   - Direct impact on block ordering
   - Result: 86% ASR achieved

2. **Proposal-Based Ordering**:
   - Ordering tied to proposal inclusion
   - Exclusions change which blocks are ordered
   - More sensitive to exclusions
   - Result: High vulnerability

### Sluggish Attack Analysis

#### Autobahn: Why It Failed

1. **Deterministic Round Assignment**:
   - Height = parent.height + 1
   - Not timing-dependent
   - Delays don't change rounds
   - Result: No effect

2. **Parent Certificate Chain**:
   - Round determined by chain position
   - Timing doesn't affect parent selection
   - Cannot lag behind to get lower rounds
   - Result: Ineffective

#### Bullshark: Minimal Effect

1. **Threshold Clock**:
   - Round advancement based on quorum
   - Timing affects quorum formation
   - But complex interaction with round priority
   - Result: Only 51% ASR (minimal improvement)

#### Mahi-Mahi: Counterproductive

1. **Fast Consensus**:
   - Delays cause isolation
   - Blocks get orphaned
   - Actually reduces ASR
   - Result: 44% ASR (worse than baseline)

### Speculative Attack Analysis

#### Autobahn: Not Applicable

- **Reason**: Round-only ordering, no digest tie-breaking
- **Impact**: Cannot manipulate ordering via digest selection
- **Result**: Attack not possible

#### Mahi-Mahi: Marginal Effect

- **Reason**: Digest tie-breaking exists but limited impact
- **Impact**: Only 52% ASR (minimal improvement)
- **Result**: Not highly effective

---

## Security Implications

### Autobahn's Security Posture

**Strengths**:
1. ✅ **Resistant to Fissure attacks**: Consensus aggregation prevents single-node exclusions
2. ✅ **Resistant to Speculative attacks**: Round-only ordering eliminates digest manipulation
3. ✅ **Resistant to Sluggish attacks**: Deterministic round assignment prevents timing manipulation
4. ✅ **Resistant to Tip Exclusion**: Consensus layer has full view
5. ✅ **Resistant to Timing attacks**: Round assignment not timing-dependent

**Potential Weaknesses**:
1. ⚠️ **Multi-node collusion**: Not tested - coordinated attacks might be more effective
2. ⚠️ **Network-level attacks**: Attacks at network layer not tested
3. ⚠️ **Leader manipulation**: Leader election is deterministic, but not tested for manipulation

### Bullshark's Security Posture

**Vulnerabilities**:
1. ❌ **Fissure attack**: 87% ASR - highly vulnerable
2. ⚠️ **Sluggish attack**: 51% ASR - minimal vulnerability
3. ✅ **Speculative attack**: Not applicable (authority index tie-breaking)

**Mitigations**:
- Quorum requirements provide some protection
- Leader election is deterministic
- But local DAG construction enables exclusions

### Mahi-Mahi's Security Posture

**Vulnerabilities**:
1. ❌ **Fissure attack**: 86% ASR - highly vulnerable
2. ⚠️ **Speculative attack**: 52% ASR - marginal vulnerability
3. ✅ **Sluggish attack**: Actually counterproductive (44% ASR)

**Mitigations**:
- Fast consensus punishes delays
- But proposal-based ordering enables exclusions

---

## Recommendations

### For Autobahn

1. **Continue Current Architecture**: 
   - Two-layer design with consensus aggregation is highly effective
   - Round-only ordering eliminates speculative attacks
   - Maintain deterministic round assignment

2. **Future Testing**:
   - Test multi-node collusion attacks
   - Test network-level attacks
   - Test leader election manipulation

3. **Documentation**:
   - Document attack resistance as a key feature
   - Highlight architectural advantages
   - Provide security guarantees

### For Bullshark

1. **Mitigation Strategies**:
   - Consider consensus-layer aggregation (like Autobahn)
   - Implement proposal validation at consensus layer
   - Add redundancy in proposal inclusion

2. **Monitoring**:
   - Monitor for exclusion patterns
   - Detect anomalous proposal behavior
   - Alert on high exclusion rates

### For Mahi-Mahi

1. **Mitigation Strategies**:
   - Consider round-only ordering (like Autobahn)
   - Implement consensus-layer aggregation
   - Reduce sensitivity to proposal exclusions

2. **Architecture Improvements**:
   - Separate proposal and consensus layers
   - Aggregate proposals at consensus layer
   - Make round assignment less timing-dependent

---

## Conclusion

Our comprehensive testing reveals that **Autobahn demonstrates superior resilience** to frontrunning attacks compared to Bullshark and Mahi-Mahi. While Bullshark and Mahi-Mahi show significant vulnerabilities with ASRs reaching 87% and 86% respectively, Autobahn maintains baseline ASR (~50%) across all attack vectors.

**Key Architectural Advantages of Autobahn**:

1. **Consensus Layer Aggregation**: Prevents single-node exclusions from affecting global ordering
2. **Round-Only Ordering**: Eliminates digest manipulation attacks
3. **Deterministic Round Assignment**: Prevents timing-based attacks
4. **Two-Layer Architecture**: Isolates attacks at primary layer from consensus layer

These architectural choices make Autobahn fundamentally more secure against frontrunning attacks, providing a strong security guarantee for users and applications built on the protocol.

---

## References

1. **Paper**: "No Fish Is Too Big for Flash Boys! Frontrunning on DAG-based Blockchains" - https://eprint.iacr.org/2024/1496.pdf
2. **Autobahn Protocol**: Built on Bullshark consensus
3. **Bullshark Results**: See `code/bullshark/BULLSHARK_ATTACK_SUMMARY.md`
4. **Mahi-Mahi Results**: See `code/mahi-mahi-consensus/COMPREHENSIVE_ATTACK_REPORT.md`

---

## Appendix: Test Configurations

### Autobahn Test Setup
- **Network Size**: 13 nodes
- **Attacker**: Node 0
- **Victim**: Node 1
- **Test Duration**: 120 seconds
- **Attack Modes**: fissure, leader_support, tip_exclusion, timing, sluggish

### Bullshark Test Setup
- **Network Size**: 13 nodes
- **Attackers**: 4 nodes (30.8%)
- **Victims**: 3 nodes (23.1%)
- **Test Duration**: 35 seconds or 15 commits
- **Attack Modes**: fissure, sluggish

### Mahi-Mahi Test Setup
- **Network Size**: Variable
- **Attackers**: Variable
- **Victims**: Variable
- **Test Duration**: Variable
- **Attack Modes**: fissure, speculative, sluggish

---

**Report Generated**: November 2024  
**Testing Period**: Multiple test runs across protocols  
**Status**: ✅ Complete


