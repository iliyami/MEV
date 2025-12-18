# Fissure Attack Implementation on Autobahn

**Date**: November 8, 2025  
**Protocol**: Autobahn (built on Bullshark)  
**Paper Reference**: [Frontrunning Attacks on DAG-based Blockchains](https://eprint.iacr.org/2024/1496.pdf)

## Summary

Successfully implemented the Fissure attack on Autobahn consensus protocol. The attack selectively excludes victim proposals from consensus messages, preventing victim blocks from being included in the DAG structure.

## Implementation Details

### Attack Location
- **File**: `primary/src/core.rs`
- **Function**: `set_consensus_proposal()` (line ~862)
- **Mechanism**: Filters out victim proposals from the `proposals` HashMap before they're included in consensus Prepare messages

### Code Changes

1. **Added `rand` dependency** to `primary/Cargo.toml`
2. **Added `use rand::Rng;`** import in `core.rs`
3. **Implemented Fissure attack logic** in `set_consensus_proposal()`:
   - Reads environment variables: `ATTACK_MODE`, `ATTACKER_ID`, `VICTIM_ID`, `EXCLUSION_PROBABILITY`
   - Maps attacker/victim IDs to PublicKeys using sorted BTreeMap order
   - Filters victim proposals with configurable exclusion probability
   - Logs exclusion events for verification

### Environment Variables

```bash
export ATTACK_MODE=fissure
export ATTACKER_ID=0        # Node index (0-based)
export VICTIM_ID=1          # Node index (0-based)
export EXCLUSION_PROBABILITY=0.20  # 20% exclusion rate
export RUST_LOG=info        # Enable logging
```

## Test Scripts

### 1. Automated Test Script
- **File**: `run_fissure_attack.py`
- **Usage**: `python3 run_fissure_attack.py`
- **Features**:
  - Runs 13 nodes locally
  - Sets attack environment variables for attacker node
  - Automatically calculates ASR after test completes

### 2. ASR Calculator
- **File**: `scripts/calculate-fissure-asr.py`
- **Usage**: `python3 scripts/calculate-fissure-asr.py logs/primary-*.log`
- **Features**:
  - Parses "Committed B{height}({author})" log messages
  - Maps public keys to indices using sorted order (matching BTreeMap)
  - Calculates Attack Success Rate (ASR)
  - Shows block distribution and attack effectiveness

### 3. Shell Script (Alternative)
- **File**: `scripts/fissure-attack-13nodes.sh`
- **Usage**: `./scripts/fissure-attack-13nodes.sh`
- **Features**: Standalone shell script for running the attack

## Running the Attack

### Quick Start

```bash
cd /Users/iliya/Dev/Blockchain/code/autobahn-artifact
python3 run_fissure_attack.py
```

### Manual Run

1. **Set environment variables** (for attacker node only):
   ```bash
   export ATTACK_MODE=fissure
   export ATTACKER_ID=0
   export VICTIM_ID=1
   export EXCLUSION_PROBABILITY=0.20
   export RUST_LOG=info
   ```

2. **Run nodes** using fab:
   ```bash
   cd benchmark
   fab local
   ```

3. **Calculate ASR**:
   ```bash
   python3 scripts/calculate-fissure-asr.py logs/primary-*.log
   ```

## Expected Results

Based on the paper and similar protocols:
- **Expected ASR**: 85-95% (similar to Bullshark's 87% Fissure ASR)
- **Baseline ASR**: ~50% (random ordering)

## Attack Mechanism

The Fissure attack works by:

1. **Proposal Exclusion**: When the attacker creates a consensus Prepare message, it excludes victim proposals with probability P (default 20%)

2. **DAG Disconnection**: Excluded proposals prevent victim blocks from being referenced in the attacker's DAG

3. **Ordering Advantage**: Isolated victim blocks are committed later, giving attacker blocks ordering priority

4. **Result**: Attacker transactions are ordered before victim transactions across blocks

## Verification

Check attack logs for:
```
🎯 FISSURE: Attacker {pk} excluding victim {pk} proposal at slot {s} view {v}
🎯 FISSURE: Excluded {n} victim proposals from slot {s} view {v}
```

## Notes

- Autobahn uses a **chain-based parent structure** (single `parent_cert`) unlike some DAG protocols
- Proposals in consensus messages represent **tips from different validators**
- Exclusion happens at the **consensus proposal level**, not at the header parent level
- The attack is **compatible with Autobahn's optimistic tips and parallel proposals** features

## Next Steps

1. Run the test script to measure actual ASR
2. Calibrate exclusion probability for optimal results
3. Compare with Bullshark results (expected similar ASR)
4. Document findings in comprehensive report





