# Bullshark vs Mysticeti: Block Ordering Analysis

## 🔍 Key Finding: Round-First Ordering Difference

### Bullshark: **DR-First (Direct Round-First) Ordering**

**Code**: `code/bullshark/consensus/core/src/commit.rs:404-410`
```rust
pub(crate) fn sort_sub_dag_blocks(blocks: &mut [VerifiedBlock]) {
    blocks.sort_by(|a, b| {
        a.round()
            .cmp(&b.round())                    // PRIMARY: Round number (ascending)
            .then_with(|| a.author().cmp(&b.author()))  // SECONDARY: Authority index
    })
}
```

**Ordering Logic**:
1. **Primary**: Round number (lower rounds = higher priority)
2. **Secondary**: Authority index (tie-breaker)

**Why High ASR?**
- **Round priority**: Blocks with lower round numbers are ordered FIRST
- **Attack advantage**: Sluggish/Fissure attacks can create blocks in lower rounds
- **Direct impact**: Round number directly determines position in global order
- **Example**: Round 5 block always ordered before Round 6 block, regardless of authority

### Mysticeti: **Round-Only Ordering (Wave-Based Structure)**

**Code**: `code/mysticeti/mysticeti-core/src/consensus/linearizer.rs:68-70`
```rust
pub fn sort(&mut self) {
    self.blocks.sort_by_key(|x| x.round());  // ONLY round number, no authority tie-breaker
}
```

**Ordering Logic**:
1. **Only**: Round number (no explicit tie-breaker in sort)
2. **Wave Structure**: Rounds are organized in waves (leader, voting, decision rounds)

**Why Lower ASR?**
- **Wave-based consensus**: Rounds have semantic meaning (leader/voting/decision)
- **Different dynamics**: Wave structure may create less exploitable ordering patterns
- **Potential tie-breaker**: If rounds are equal, ordering might depend on block creation order or DAG structure
- **Less direct control**: Round manipulation may not translate directly to ordering advantage

## 📊 Comparison Table

| Aspect | Bullshark | Mysticeti |
|--------|-----------|-----------|
| **Primary Sort** | Round (ascending) | Round (ascending) |
| **Secondary Sort** | Authority index | None (implicit) |
| **Ordering Type** | DR-First (Direct Round-First) | Round-only |
| **Structure** | Round-based | Wave-based (3-round cycles) |
| **Round Priority** | ✅ Strong (direct ordering) | ⚠️ Moderate (wave semantics) |
| **Attack Exploitability** | ✅ High (round = position) | ⚠️ Lower (wave structure) |

## 🎯 Why Bullshark Gets High ASR

### 1. **Direct Round-to-Position Mapping**
```
Round 5 block → Position X
Round 6 block → Position X+1 (always after round 5)
```
**Attack**: Create blocks in lower rounds → Get earlier positions

### 2. **No Wave Constraints**
- Rounds are independent
- No semantic meaning attached to round numbers
- Round number directly = ordering priority

### 3. **Authority Tie-Breaker**
- Even with same round, deterministic ordering
- Still predictable based on authority index
- Attackers can control their authority indices

## 🎯 Why Mysticeti May Get Lower ASR

### 1. **Wave-Based Semantics**
```
Wave 1: Round 0 (leader), Round 1 (voting), Round 2 (decision)
Wave 2: Round 3 (leader), Round 4 (voting), Round 5 (decision)
```
**Constraint**: Round numbers have semantic meaning within waves

### 2. **Potential Implicit Tie-Breaking**
- If rounds are equal, ordering may depend on:
  - Block creation timestamp
  - DAG inclusion order
  - Anchor selection
- Less predictable than explicit authority index

### 3. **Wave Synchronization**
- Leaders must be committed in specific wave patterns
- Decision rounds vote on leader rounds
- Less direct control over ordering through round manipulation

## 🔬 Evidence from Code

### Bullshark Round Priority Exploitation
From `BULLSHARK_13_NODE_TEST_FIX.md`:
```
2. **Lower round numbers** = **Higher priority** in ordering
3. **Delayed proposals** → Attackers stay in earlier rounds longer
4. **Result**: Attacker blocks ordered before victim blocks in global ledger
```

### Mysticeti Wave Structure
From `code/mysticeti/mysticeti-core/src/syncer.rs`:
```rust
let wave_position = clock_round % 3; // 0=leader, 1=voting, 2=decision
```
This shows rounds have semantic meaning within 3-round waves.

## 📈 ASR Impact

### Bullshark
- **Fissure**: 87.0% ASR (can create lower-round blocks)
- **Sluggish**: 51.0% ASR (round manipulation)
- **Speculative**: 97.8% ASR (round-based ordering advantage)

### Mysticeti (Expected with Correct Methodology)
- **Fissure**: TBD (wave structure may limit round manipulation)
- **Sluggish**: TBD (wave synchronization may reduce advantage)
- **Speculative**: TBD (wave-based ordering less exploitable)

## ✅ Conclusion

**Bullshark's high ASR is due to DR-first (Direct Round-First) ordering**:
- Round number is the PRIMARY and STRONGEST ordering criterion
- Lower rounds = earlier positions (direct mapping)
- No semantic constraints on rounds

**Mysticeti's expected lower ASR is due to wave-based structure**:
- Rounds have semantic meaning (leader/voting/decision)
- Wave synchronization constraints
- Round manipulation may not translate directly to ordering advantage

**Both use round-based sorting, but:**
- Bullshark: Round = Direct Position Control ✅
- Mysticeti: Round = Wave Position (indirect) ⚠️


