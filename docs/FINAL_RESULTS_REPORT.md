# MEV Attack Analysis: Final Results Report

**Research Paper**: [No Fish Is Too Big for Flash Boys! Frontrunning on DAG-based Blockchains](https://eprint.iacr.org/2024/1496.pdf)  
**Authors**: Iliya Mirzaei, Mohammad Javad Amiri  
**Institution**: Stony Brook University  
**Date**: December 2024

---

## Executive Summary

This report presents the final results of our comprehensive MEV (Maximal Extractable Value) vulnerability analysis across **7 DAG-based blockchain consensus protocols**. We implemented and tested three frontrunning attack strategies (Fissure, Speculative, and Sluggish) to measure Attack Success Rate (ASR) and identify architectural patterns that influence protocol security.

### Key Finding

**Protocol architecture fundamentally determines MEV resistance.** Single-layer consensus protocols with local DAG manipulation are highly vulnerable (87-92% ASR), while multi-layer architectures with consensus aggregation maintain baseline fairness (~50% ASR).

---

## Attack Success Rate Summary

| Protocol | Baseline | Fissure | Speculative | Sluggish | Best Attack | Resistance Level |
|----------|----------|---------|-------------|----------|-------------|------------------|
| **Narwhal-Tusk** | 50% | 88.5% | 70.1% | 99.9% | Sluggish (99.9%) | **Highly Vulnerable** |
| **Bullshark** | 50% | 91.9% | 97.8% | 89.9% | Speculative (97.8%) | **Highly Vulnerable** |
| **MEVSUI** | 50% | 91.9% | 92.5% | 92.2% | Speculative (92.5%) | **Highly Vulnerable** |
| **Mahi-Mahi** | 50% | 86.0% | 52.0% | 44.0% | Fissure (86.0%) | Moderate |
| **AlephBFT** | 31% | 52.3% | 0.0% | 54.1% | Sluggish (54.1%) | Moderate |
| **Mysticeti** | 47% | 45.0% | 40.0% | 40.0% | Fissure (45.0%) | Resistant |
| **Autobahn** | 50% | ~50% | N/A | ~50% | None (~50%) | **Highly Resistant** |

> **Note**: ASR of ~50% represents baseline (fair random ordering). Values significantly above 50% indicate successful attacks.

---

## Protocol Analysis

### 1. Bullshark (Sui Network)
**Vulnerability: CRITICAL**

| Attack | ASR | Implementation |
|--------|-----|----------------|
| Fissure | 91.9% | Parent exclusion in `proposer.rs` |
| Speculative | 97.8% | Hash manipulation for ordering advantage |
| Sluggish | 89.9% | Timing delays in certificate processing |

**Why Vulnerable:**
- Single-layer consensus allows local DAG manipulation
- Round-first ordering with authority index tie-breaking is exploitable
- Ancestor exclusion directly affects proposal selection

### 2. MEVSUI (Bullshark Fork)
**Vulnerability: CRITICAL**

| Attack | ASR | Implementation |
|--------|-----|----------------|
| Fissure | 91.9% | Same as Bullshark |
| Speculative | 92.5% | Hash manipulation for ordering advantage |
| Sluggish | 92.2% | Timing delays in certificate processing |

**Why Vulnerable:**
- Inherits Bullshark's single-layer architecture
- MEV mitigation patches ineffective against consensus-layer attacks
- Same ordering mechanism as Bullshark

### 3. Mahi-Mahi
**Vulnerability: MODERATE**

| Attack | ASR | Implementation |
|--------|-----|----------------|
| Fissure | 86.0% | Aggressive parent exclusion |
| Speculative | 52.0% | Ineffective (hash not used for ordering) |
| Sluggish | 44.0% | Counterproductive (4-hop latency punishes delays) |

**Why Partially Resistant:**
- Fast 4-hop consensus punishes timing delays
- Uncertified DAG structure limits Speculative effectiveness
- Fissure remains highly effective due to parent manipulation

### 4. AlephBFT (Aleph Zero)
**Vulnerability: MODERATE**

| Attack | ASR | Implementation |
|--------|-----|----------------|
| Fissure | 52.3% | Parent exclusion in `collector.rs` |
| Speculative | 0.0% | Not applicable (virtual voting) |
| Sluggish | 54.1% | 11ms processing delay (optimized) |

**Why Partially Resistant:**
- Virtual voting aggregates across entire network, diluting attacker influence
- Hash manipulation doesn't affect ordering in virtual voting system
- Monotonicity property limits ordering changes
- Lower baseline (31%) suggests inherent ordering bias

### 5. Mysticeti
**Vulnerability: LOW**

| Attack | ASR | Implementation |
|--------|-----|----------------|
| Fissure | 45.0% | Wave-aware exclusion in `core.rs` |
| Speculative | 40.0% | Limited by certification requirements |
| Sluggish | 40.0% | Timing manipulation ineffective |

**Why Resistant:**
- Wave-based structure (leader → voting → decision) limits timing attacks
- Transaction certification requires >2/3 stake votes
- Strong finality guarantees prevent reordering

### 6. Autobahn
**Vulnerability: MINIMAL**

| Attack | ASR | Implementation |
|--------|-----|----------------|
| Fissure | ~50% | Tip exclusion ineffective |
| Speculative | N/A | Round-only ordering |
| Sluggish | ~50% | Certificate delay ineffective |

**Why Highly Resistant:**
- Two-layer architecture (Primary + Consensus) isolates attacks
- Consensus-layer aggregation from ALL nodes neutralizes single-node exclusions
- Round-only ordering eliminates digest manipulation attacks
- Deterministic round assignment prevents timing attacks

### 7. Narwhal-Tusk
**Vulnerability: CRITICAL**

| Attack | ASR | Implementation |
|--------|-----|----------------|
| Fissure | 88.5% | Parent exclusion + priority sorting in `order_dag` |
| Speculative | 70.1% | LOP digest mining (50 candidates) |
| Sluggish | 99.9% | Delayed block injection exploits round-ordering |

**Why Highly Vulnerable:**
- Round-based ordering allows delayed blocks to be ordered first
- LOP (Lexicographic Ordering Protocol) is exploitable via digest grinding
- Priority sorting in consensus layer amplifies Fissure effectiveness
- Sluggish attack saturates the vulnerability (99.92% ASR)

---

## Architectural Defenses Identified

### Effective Defenses

1. **Consensus-Layer Aggregation** (Autobahn)
   - Collect proposals from ALL nodes, not just local views
   - Single-node exclusions become ineffective when honest nodes include victim blocks

2. **Wave-Based Consensus** (Mysticeti)
   - 3-round wave structure limits timing manipulation
   - Certification requirements prevent premature ordering

3. **Virtual Voting** (AlephBFT)
   - Global aggregation dilutes 30% attacker stake
   - Monotonicity property ensures ordering consistency

4. **Two-Layer Architecture** (Autobahn, Narwhal-Tusk)
   - Separate proposal and ordering layers
   - Isolates mempool from consensus decisions

5. **Round-Only Ordering** (Autobahn)
   - Eliminates digest/hash manipulation attacks
   - Deterministic assignment prevents timing exploitation

### Ineffective Defenses

1. **Simple MEV mitigation patches** (MEVSUI) - Still ~92% ASR
2. **Fast consensus without ordering protection** - Bullshark still vulnerable despite performance

---

## Test Configuration

### Standard 13-Node Setup
```
Network Size: 13 nodes
Attackers: 4 nodes (30.8%) - indices 0-3
Victims: 3 nodes (23.1%) - indices 10-12
Honest: 6 nodes (46.1%) - indices 4-9
Test Duration: 35-120 seconds
```

### ASR Calculation Methodology
```
For all pairs (attacker_block, victim_block):
  If attacker_round >= victim_round:  # Attacker witnessed victim
    If attacker_height < victim_height:  # Attacker ordered first
      success++
    total_pairs++

ASR = success / total_pairs
```

---

## Conclusions

### Protocol Ranking (Most to Least Vulnerable)

1. **Narwhal-Tusk** - 99.9% ASR (Sluggish) - Round-ordering fully exploitable
2. **Bullshark** - 97.8% ASR (Speculative) - Single-layer highly vulnerable
3. **MEVSUI** - 92.5% ASR (Speculative) - Bullshark fork, MEV patches ineffective
4. **Mahi-Mahi** - 86.0% ASR (Fissure) - Fast consensus helps, but Fissure effective
5. **AlephBFT** - 54.1% ASR (Sluggish) - Virtual voting dilutes attacker influence
6. **Mysticeti** - 45.0% ASR (Fissure) - Wave-based structure limits attacks
7. **Autobahn** - ~50% ASR (baseline) - Consensus aggregation neutralizes all attacks

### Recommendations for Protocol Designers

1. **Adopt two-layer architecture** separating proposal from ordering
2. **Implement consensus-layer aggregation** from all nodes
3. **Use round-only ordering** without digest tie-breaking
4. **Require certification/voting** before commitment
5. **Consider virtual voting** for diluting attacker influence

### Future Work

1. Large-scale network testing (100 nodes)
2. Geo-distributed deployment analysis
3. Economic MEV quantification
4. Combined attack strategies

---

## Repository Structure

```
/Users/iliya/Dev/Blockchain/
├── code/
│   ├── bullshark/          # Bullshark implementation with attacks
│   ├── mysticeti/          # Mysticeti implementation with attacks
│   ├── mahi-mahi-consensus/# Mahi-Mahi implementation with attacks
│   ├── autobahn-artifact/  # Autobahn implementation with attacks
│   ├── alephbft/           # AlephBFT implementation with attacks
│   ├── mevsui/             # MEVSUI fork (same as Bullshark)
│   └── narwhal/            # Narwhal-Tusk implementation
├── docs/
│   ├── COMPREHENSIVE_PROTOCOL_ATTACK_ANALYSIS.md  # Detailed analysis
│   └── NARWHAL_TUSK_ATTACKS.md                    # Protocol-specific details
└── NEDBDAY_Abstract.tex    # Conference submission abstract
```

---

**Report Generated**: December 19, 2024
