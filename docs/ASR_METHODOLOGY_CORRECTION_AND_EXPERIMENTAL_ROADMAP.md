# ASR Methodology Correction & Experimental Roadmap

**Research Paper**: [No Fish Is Too Big for Flash Boys! Frontrunning on DAG-based Blockchains](https://eprint.iacr.org/2024/1496.pdf)  
**Date**: 2025-11-29  
**Status**: Critical Methodology Fix Required

---

## Executive Summary

This document identifies a **critical methodology inconsistency** in our ASR (Attack Success Rate) measurements across all 7 protocols and provides a comprehensive roadmap to:
1. Fix ASR calculation to align with the paper's methodology
2. Standardize experimental setup across all protocols
3. Implement rigorous experimental methodology for publication-quality results

---

## Part 1: Critical ASR Methodology Correction

### 1.1 Problem Identified

**Current State**: All 7 protocols use **inconsistent ASR calculation methods** that deviate from the paper's methodology.

### 1.2 Paper's Correct Methodology (Re-analyzed)

Based on careful re-examination of the paper:

#### **Matching Strategy: All-Pairs (NOT One-to-One)**

**Evidence from Paper**:
- **Equation 1**: `F_0^fis = 1/2 + fa/(2(n-fl))` shows ASR increases with number of attackers (fa)
- **Figure 7**: ASR grows from ~52% (fa=1) to ~94% (fa=9) - this relationship only makes sense with all-pairs matching
- **Section 5.2**: "All frontrunning attackers attack the same victim blocks" - implies all attackers can target all victims

**Implication**: Each attacker block can attempt to frontrun each victim block. This is **all-pairs matching**, not one-to-one.

#### **Round Filtering: `attacker_round ≥ victim_round` (No Strict Window)**

**Evidence from Paper**:
- **Appendix A**: Explicitly analyzes "Attacks across Anchors"
- **Equations 3, 8, 10**: Models account for blocks ordered by different anchors
- **Cross-round attacks**: Paper analyzes ordering delays spanning multiple rounds

**Implication**: Only requirement is that attacker creates block **after** witnessing victim (`att_round >= vic_round`). No strict round difference window (like `<= 3`).

#### **Height Definition: Position in Finalization Sequence**

**Evidence from Paper**:
- **Section 5.1**: "blocks are associated with a new label block height to indicate the committed order of blocks"

**Implication**: Height = index in finalized sequence, NOT round number. This is correctly implemented in all protocols.

#### **ASR Formula**

```
ASR = (# attacker blocks with height < victim height) / (total attacker-victim pairs)

Where pairs are all combinations where:
- attacker_round ≥ victim_round (attacker creates block after witnessing victim)
- Success: attacker_height < victim_height (attacker block ordered before victim block)
```

### 1.3 Current Protocol Status

| Protocol | Current Approach | Issue | Correct Approach Needed |
|----------|-----------------|-------|------------------------|
| **Bullshark** | All-pairs + `round_diff <= 3` | ❌ Too restrictive | All-pairs + `att_round >= vic_round` |
| **MEVSUI** | All-pairs + `round_diff <= 3` | ❌ Too restrictive | All-pairs + `att_round >= vic_round` |
| **Narwhal-Tusk** | Attacker-centric | ❌ Not all-pairs | All-pairs + `att_round >= vic_round` |
| **Mysticeti** | All-pairs (no filtering) | ❌ Missing round filter | All-pairs + `att_round >= vic_round` |
| **Mahi-Mahi** | All-pairs (no filtering) | ❌ Missing round filter | All-pairs + `att_round >= vic_round` |
| **Autobahn** | All-pairs (no filtering) | ❌ Missing round filter | All-pairs + `att_round >= vic_round` |
| **AlephBFT** | One-to-one (closest) | ❌ Wrong matching | All-pairs + `att_round >= vic_round` |

### 1.4 Correct Implementation Template

```rust
fn calculate_asr(finalized_blocks: &[Block]) -> f64 {
    // Extract attacker and victim blocks with (height, round)
    let attacker_blocks: Vec<(usize, Round)> = extract_blocks(finalized_blocks, ATTACKER_INDICES);
    let victim_blocks: Vec<(usize, Round)> = extract_blocks(finalized_blocks, VICTIM_INDICES);
    
    let mut successes = 0;
    let mut total_pairs = 0;
    
    // ALL-PAIRS matching (not one-to-one)
    for (att_height, att_round) in &attacker_blocks {
        for (vic_height, vic_round) in &victim_blocks {
            // Filter: attacker created block AFTER witnessing victim
            if *att_round >= *vic_round {
                total_pairs += 1;
                
                // Success: attacker block height < victim block height
                if *att_height < *vic_height {
                    successes += 1;
                }
            }
        }
    }
    
    if total_pairs == 0 {
        return 0.0;
    }
    
    let asr = (successes as f64 / total_pairs as f64) * 100.0;
    asr / 100.0  // Return as fraction
}
```

### 1.5 Impact Assessment

**Expected Changes**:
- **AlephBFT**: ASR will likely **increase** (one-to-one → all-pairs = more pairs counted)
- **Bullshark/MEVSUI**: ASR may **increase** (removing `round_diff <= 3` restriction = more pairs counted)
- **Mysticeti/Mahi-Mahi/Autobahn**: ASR may **decrease** (adding `att_round >= vic_round` filter = fewer pairs counted)
- **Narwhal-Tusk**: ASR may **change** (attacker-centric → all-pairs = different counting method)

**Critical**: All protocols need re-measurement after fix.

---

## Part 2: Experimental Roadmap for Publication-Quality Results

### 2.1 Standardization Requirements

#### **Task 1: Standardize Experimental Setup**

**Objective**: Ensure all protocols use identical test configurations for fair comparison.

**Requirements**:
- **Network Size**: Standardize to 13 nodes (primary), with scalability tests at 25, 50, 100
- **Attacker Ratio**: Standardize to 30.8% (4/13 attackers) for primary tests
- **Victim Ratio**: Standardize to 23.1% (3/13 victims) for primary tests
- **Test Duration**: Standardize to 35 seconds or until 500+ finalized blocks (whichever first)
- **Metrics**: Consistent ASR calculation, block counts, timing measurements

**Implementation Steps**:
1. Create unified configuration file format (YAML/JSON)
2. Update all protocol test scripts to read from unified config
3. Validate all protocols can run with same configuration
4. Document any protocol-specific constraints

**Files to Create/Modify**:
- `experimental_config.yaml` - Unified configuration template
- `code/*/run_standardized_test.sh` - Standardized test scripts per protocol
- `scripts/validate_config.sh` - Config validation script

**Success Criteria**:
- All 7 protocols can run with identical base configuration
- Results are directly comparable across protocols

---

### 2.2 Baseline Experiments

#### **Task 2: Run Baseline Experiments with Confidence Intervals**

**Objective**: Establish reliable baseline ASR measurements with statistical rigor.

**Requirements**:
- **Runs per Configuration**: Minimum 10 runs (preferably 20-30 for better statistics)
- **Confidence Intervals**: Calculate 95% confidence intervals for all ASR measurements
- **Baseline Tests**: Run "no attack" baseline for all protocols
- **Statistical Reporting**: Mean, standard deviation, confidence intervals, min/max

**Implementation Steps**:
1. Create automated baseline test runner
2. Implement statistical analysis script (mean, std, CI calculation)
3. Run baseline tests for all 7 protocols (10+ runs each)
4. Generate baseline report with confidence intervals

**Files to Create**:
- `scripts/run_baseline_experiments.sh` - Automated baseline runner
- `scripts/calculate_statistics.py` - Statistical analysis script
- `results/baseline_experiments/` - Baseline results directory

**Success Criteria**:
- Baseline ASR with 95% CI for all 7 protocols
- Statistical significance established
- Reproducible baseline measurements

---

### 2.3 Multi-Scale Network Testing

#### **Task 3: Dynamic Network Size Testing (13, 25, 50, 100 nodes)**

**Objective**: Understand how attack effectiveness scales with network size.

**Requirements**:
- **Network Sizes**: 13, 25, 50, 100 nodes
- **Dynamic Configuration**: Test scripts must accept network size as parameter
- **Proportional Scaling**: Attacker/victim ratios scale proportionally
  - 13 nodes: 4 attackers, 3 victims (30.8%, 23.1%)
  - 25 nodes: 8 attackers, 6 victims (32%, 24%)
  - 50 nodes: 15 attackers, 12 victims (30%, 24%)
  - 100 nodes: 30 attackers, 23 victims (30%, 23%)
- **Duration Scaling**: Adjust test duration based on network size (larger networks may need longer)

**Implementation Steps**:
1. Create dynamic configuration system that accepts network size
2. Update all protocol test scripts to support variable network sizes
3. Implement network size-specific test duration calculation
4. Create multi-scale test runner script
5. Run tests across all network sizes for all protocols

**Files to Create/Modify**:
- `experimental_config.yaml` - Add `network_size` parameter
- `scripts/run_multi_scale_tests.sh` - Multi-scale test runner
- `code/*/run_standardized_test.sh` - Support variable network sizes
- `results/multi_scale_experiments/` - Results directory

**Success Criteria**:
- All protocols can run with 13, 25, 50, 100 nodes
- ASR measurements collected for all network sizes
- Scalability trends identified

---

### 2.4 Variable Attacker Ratio Testing

#### **Task 4: Variable Attacker Ratio Testing (10%, 20%, 33%)**

**Objective**: Understand how attack effectiveness varies with attacker ratio.

**Requirements**:
- **Attacker Ratios**: 10%, 20%, 33% (maximum Byzantine tolerance)
- **Network Size**: 13 nodes (primary), optionally test at other sizes
- **Victim Ratio**: Keep constant at ~23% or scale proportionally
- **Multiple Runs**: 10+ runs per configuration for statistical significance

**Test Configurations**:
- **10% Attackers**: 1 attacker (7.7%), 3 victims (23.1%), 9 honest (69.2%)
- **20% Attackers**: 3 attackers (23.1%), 3 victims (23.1%), 7 honest (53.8%)
- **33% Attackers**: 4 attackers (30.8%), 3 victims (23.1%), 6 honest (46.1%)

**Implementation Steps**:
1. Create attacker ratio test configuration generator
2. Update test scripts to accept attacker ratio parameter
3. Run tests for all attacker ratios across all protocols
4. Analyze ASR vs attacker ratio relationship

**Files to Create**:
- `scripts/run_attacker_ratio_tests.sh` - Attacker ratio test runner
- `results/attacker_ratio_experiments/` - Results directory
- `scripts/analyze_attacker_ratio.py` - Analysis script

**Success Criteria**:
- ASR measurements for 10%, 20%, 33% attacker ratios
- Relationship between ASR and attacker ratio established
- Comparison with paper's Equation 1: `F_0^fis = 1/2 + fa/(2(n-fl))`

---

### 2.5 Network Latency Sensitivity Analysis

#### **Task 5: Network Latency Sensitivity Analysis (10ms, 50ms, 100ms, 200ms)**

**Objective**: Understand how network latency affects attack effectiveness.

**Requirements**:
- **Latency Values**: 10ms, 50ms, 100ms, 200ms (simulated network delays)
- **Baseline**: 0ms (local network) for comparison
- **Protocol Support**: Not all protocols may support latency simulation
- **Multiple Runs**: 10+ runs per latency configuration

**Implementation Steps**:
1. Identify latency simulation mechanisms for each protocol
2. Create latency injection scripts/configurations
3. Run tests across all latency values for all protocols
4. Analyze ASR vs latency relationship

**Files to Create**:
- `scripts/inject_latency.sh` - Latency injection script
- `scripts/run_latency_tests.sh` - Latency sensitivity test runner
- `results/latency_experiments/` - Results directory
- `scripts/analyze_latency_sensitivity.py` - Analysis script

**Success Criteria**:
- ASR measurements for all latency values
- Latency sensitivity curves for all protocols
- Identification of protocols most/least sensitive to latency

---

### 2.6 Variable Load Testing

#### **Task 6: Variable Load Testing (100, 500, 1000, 5000 tx/s)**

**Objective**: Understand how transaction load affects attack effectiveness.

**Requirements**:
- **Load Values**: 100, 500, 1000, 5000 transactions per second
- **Baseline**: No load or minimal load for comparison
- **Protocol Support**: Not all protocols may support load generation
- **Multiple Runs**: 10+ runs per load configuration

**Implementation Steps**:
1. Identify load generation mechanisms for each protocol
2. Create load generation scripts/configurations
3. Run tests across all load values for all protocols
4. Analyze ASR vs load relationship

**Files to Create**:
- `scripts/generate_load.sh` - Load generation script
- `scripts/run_load_tests.sh` - Load testing runner
- `results/load_experiments/` - Results directory
- `scripts/analyze_load_sensitivity.py` - Analysis script

**Success Criteria**:
- ASR measurements for all load values
- Load sensitivity curves for all protocols
- Identification of protocols most/least sensitive to load

---

### 2.7 Attack Implementation Documentation

#### **Task 7: Attack Implementation Documentation**

**Objective**: Create comprehensive documentation of attack implementations across all protocols for reproducibility and understanding.

**Requirements**:
- **Code Locations**: Document exact file paths and line numbers for attack code
- **Integration Points**: Identify where attacks are integrated into protocol code
- **Protocol-Specific Adaptations**: Document how attacks are adapted for each protocol's architecture
- **Configuration**: Document all environment variables, parameters, and configuration options
- **Testing Infrastructure**: Document test setup, execution, and result collection

**Documentation Structure** (per protocol):
1. **Attack Integration Points**
   - Fissure Attack: Parent selection logic location
   - Speculative Attack: Data/digest selection location
   - Sluggish Attack: Timing/delay injection location

2. **Code Modifications**
   - Files modified
   - Functions modified/added
   - Key code snippets with explanations

3. **Protocol-Specific Adaptations**
   - How attacks adapt to protocol architecture
   - Protocol-specific constraints and considerations
   - Differences from paper's generic description

4. **Configuration & Parameters**
   - Environment variables
   - Attack parameters (exclusion probabilities, delays, etc.)
   - Network configuration

5. **Testing & Validation**
   - Test file locations
   - How to run tests
   - How to verify attacks are active
   - How to extract results

**Implementation Steps**:
1. Audit all attack implementations across all 7 protocols
2. Document code locations and integration points
3. Document protocol-specific adaptations
4. Create standardized documentation template
5. Generate comprehensive documentation for each protocol
6. Create cross-protocol comparison document

**Files to Create**:
- `docs/attack_implementations/` - Documentation directory
- `docs/attack_implementations/PROTOCOL_ATTACK_IMPLEMENTATION.md` - Per-protocol docs
- `docs/attack_implementations/ATTACK_IMPLEMENTATION_COMPARISON.md` - Cross-protocol comparison
- `docs/attack_implementations/INTEGRATION_POINTS.md` - Integration points summary
- `docs/attack_implementations/REPRODUCIBILITY_GUIDE.md` - How to reproduce all attacks

**Success Criteria**:
- Complete documentation for all 7 protocols
- All attack code locations documented
- Protocol-specific adaptations clearly explained
- Reproducibility guide enables others to replicate experiments
- Cross-protocol comparison highlights differences

---

### 2.8 Statistical Analysis

#### **Task 8: Statistical Analysis with Significance Tests**

**Objective**: Provide rigorous statistical analysis for publication.

**Requirements**:
- **T-tests**: Compare ASR between protocols, attack types, configurations
- **ANOVA**: Analyze variance across multiple factors (protocol, attack type, network size, etc.)
- **Correlation Analysis**: Identify relationships between variables (attacker ratio, network size, latency, load)
- **Effect Size**: Calculate effect sizes (Cohen's d) for significant differences
- **Multiple Comparisons**: Apply Bonferroni correction for multiple comparisons

**Statistical Tests Needed**:
1. **Protocol Comparison**: T-tests comparing ASR between protocols
2. **Attack Type Comparison**: T-tests comparing Fissure vs Speculative vs Sluggish
3. **Network Size Effect**: ANOVA for network size (13, 25, 50, 100)
4. **Attacker Ratio Effect**: ANOVA for attacker ratio (10%, 20%, 33%)
5. **Latency Effect**: ANOVA for latency (0ms, 10ms, 50ms, 100ms, 200ms)
6. **Load Effect**: ANOVA for load (0, 100, 500, 1000, 5000 tx/s)
7. **Correlation Analysis**: Pearson correlation between ASR and independent variables

**Implementation Steps**:
1. Create statistical analysis script (Python with scipy/statsmodels)
2. Implement all required statistical tests
3. Generate comprehensive statistical report
4. Create visualizations (box plots, correlation matrices, effect size plots)

**Files to Create**:
- `scripts/statistical_analysis.py` - Main statistical analysis script
- `scripts/generate_statistical_report.py` - Report generator
- `results/statistical_analysis/` - Statistical results directory
- `results/statistical_analysis/figures/` - Statistical visualizations

**Success Criteria**:
- Complete statistical analysis report
- All significance tests performed
- Effect sizes calculated
- Publication-ready statistical tables and figures

---

### 2.9 Protocol-Specific Deep Dive Analysis

#### **Task 9: Protocol-Specific Architectural Analysis**

**Objective**: Provide detailed analysis explaining why each protocol shows specific ASR values based on architectural design choices.

**Requirements**:
- **Architectural Analysis**: Deep dive into each protocol's design
- **ASR Explanation**: Explain why each protocol achieves its specific ASR values
- **Design Choices**: Analyze how design choices affect attack resistance
- **Trade-offs**: Document security vs performance trade-offs
- **Comparative Analysis**: Compare architectural differences across protocols

**Analysis Structure** (per protocol):
1. **Architecture Overview**
   - Protocol design principles
   - Key architectural components
   - Ordering mechanism details

2. **Attack Resistance Mechanisms**
   - Built-in security features
   - Design choices that resist attacks
   - Mechanisms that limit attack effectiveness

3. **Vulnerability Analysis**
   - Why attacks are effective (if high ASR)
   - Why attacks are ineffective (if low ASR)
   - Architectural weaknesses exploited by attacks

4. **ASR Explanation**
   - Why protocol achieves specific ASR values
   - Relationship between architecture and ASR
   - Comparison with theoretical expectations

5. **Design Trade-offs**
   - Security vs performance trade-offs
   - Attack resistance vs other properties
   - Design decisions and their implications

6. **Comparative Analysis**
   - How this protocol differs from others
   - Why it shows different ASR values
   - Lessons learned for protocol design

**Protocol-Specific Analysis Topics**:

**Narwhal-Tusk (High ASR ~87-88%)**:
- Why round-based ordering with digest tie-breaking is vulnerable
- How parent exclusion affects ordering
- Why speculative attack is highly effective

**Bullshark (Very High ASR ~87-97%)**:
- Why round-first ordering is vulnerable
- Authority index tie-breaking weakness
- Why speculative attack achieves 97.8% ASR

**Mysticeti (Moderate ASR ~40%)**:
- Wave-based structure protection
- Genesis protection mechanisms
- Why attacks are limited to ~40%

**Mahi-Mahi (High ASR ~86%)**:
- Similarities to Bullshark vulnerability
- Threshold clock mechanism
- Why it shows high ASR despite optimizations

**Autobahn (Baseline ASR ~50%)**:
- Consensus-layer aggregation protection
- Round-only ordering (no tie-breaking)
- Why attacks are completely ineffective

**MEVSUI (Moderate-High ASR ~72-74%)**:
- Bullshark-based architecture
- MEV mitigation mechanisms
- Why it shows better resistance than Bullshark

**AlephBFT (Moderate ASR ~52%)**:
- Virtual voting system protection
- Monotonicity property
- ControlHash mechanism
- Why attacks are limited despite single-layer design

**Implementation Steps**:
1. Collect all experimental results (after ASR fix and experiments)
2. Analyze ASR values for each protocol
3. Study protocol architectures in detail
4. Identify architectural factors affecting ASR
5. Create protocol-specific analysis documents
6. Create comparative analysis document
7. Generate architectural insights and recommendations

**Files to Create**:
- `docs/protocol_analysis/` - Analysis directory
- `docs/protocol_analysis/PROTOCOL_ARCHITECTURAL_ANALYSIS.md` - Per-protocol analysis
- `docs/protocol_analysis/COMPARATIVE_ARCHITECTURAL_ANALYSIS.md` - Cross-protocol comparison
- `docs/protocol_analysis/ASR_ARCHITECTURE_CORRELATION.md` - ASR vs architecture correlation
- `docs/protocol_analysis/DESIGN_RECOMMENDATIONS.md` - Design recommendations

**Success Criteria**:
- Complete architectural analysis for all 7 protocols
- Clear explanation of ASR values based on architecture
- Identification of key architectural factors affecting attack resistance
- Comparative analysis highlighting differences
- Design recommendations for future protocols

---

## Part 3: Implementation Priority & Timeline

### 3.1 Critical Path (Must Do First)

1. **Fix ASR Calculation** (All Protocols) - **CRITICAL**
   - Priority: **P0** (Blocks everything else)
   - Estimated Time: 2-3 days
   - Impact: All current ASR measurements are invalid

2. **Standardize Experimental Setup** (All Protocols)
   - Priority: **P0** (Required for fair comparison)
   - Estimated Time: 3-5 days
   - Impact: Enables all other experiments

3. **Baseline Experiments** (All Protocols)
   - Priority: **P0** (Required baseline)
   - Estimated Time: 2-3 days
   - Impact: Establishes baseline for comparison

4. **Attack Implementation Documentation** (All Protocols)
   - Priority: **P0** (Required for reproducibility)
   - Estimated Time: 3-4 days
   - Impact: Enables reproducibility and understanding

### 3.2 High Priority (For Publication)

5. **Multi-Scale Network Testing**
   - Priority: **P1**
   - Estimated Time: 5-7 days
   - Impact: Shows scalability properties

6. **Variable Attacker Ratio Testing**
   - Priority: **P1**
   - Estimated Time: 3-5 days
   - Impact: Validates paper's Equation 1

7. **Statistical Analysis**
   - Priority: **P1**
   - Estimated Time: 3-5 days
   - Impact: Publication-quality rigor

8. **Protocol-Specific Deep Dive Analysis**
   - Priority: **P1** (Required for paper)
   - Estimated Time: 5-7 days
   - Impact: Explains results and provides insights

### 3.3 Medium Priority (Nice to Have)

9. **Network Latency Sensitivity**
   - Priority: **P2**
   - Estimated Time: 4-6 days
   - Impact: Real-world applicability

10. **Variable Load Testing**
   - Priority: **P2**
   - Estimated Time: 4-6 days
   - Impact: Real-world applicability

---

## Part 4: Implementation Details

### 4.1 Unified Configuration Format

**File**: `experimental_config.yaml`

```yaml
# Unified Experimental Configuration
experiment:
  name: "standardized_attack_test"
  protocol: "alephbft"  # alephbft, bullshark, mevsui, narwhal-tusk, mysticeti, mahi-mahi, autobahn
  
network:
  size: 13  # 13, 25, 50, 100
  attacker_ratio: 0.308  # 0.10, 0.20, 0.33
  victim_ratio: 0.231
  latency_ms: 0  # 0, 10, 50, 100, 200
  load_tx_per_sec: 0  # 0, 100, 500, 1000, 5000

attack:
  mode: "fissure"  # fissure, speculative, sluggish
  parameters:
    fissure:
      exclusion_probability: 0.95
    speculative:
      p_max: 50
    sluggish:
      timeout_multiplier: 2.0
      processing_delay_ms: 11

test:
  duration_seconds: 35
  min_finalized_blocks: 500
  runs: 10  # Number of runs for statistical analysis
  output_dir: "results/experiment_name"

asr_calculation:
  method: "all_pairs"  # all_pairs (paper-aligned)
  round_filter: "attacker_round >= victim_round"
  height_definition: "finalization_position"
```

### 4.2 Standardized Test Script Template

**File**: `scripts/run_standardized_test.sh`

```bash
#!/bin/bash
# Standardized Test Runner for All Protocols

set -e

CONFIG_FILE="${1:-experimental_config.yaml}"
PROTOCOL=$(yq eval '.experiment.protocol' "$CONFIG_FILE")
NETWORK_SIZE=$(yq eval '.network.size' "$CONFIG_FILE")
ATTACKER_RATIO=$(yq eval '.network.attacker_ratio' "$CONFIG_FILE")
VICTIM_RATIO=$(yq eval '.network.victim_ratio' "$CONFIG_FILE")
ATTACK_MODE=$(yq eval '.attack.mode' "$CONFIG_FILE")
RUNS=$(yq eval '.test.runs' "$CONFIG_FILE")
OUTPUT_DIR=$(yq eval '.test.output_dir' "$CONFIG_FILE")

mkdir -p "$OUTPUT_DIR"

echo "Running standardized test:"
echo "  Protocol: $PROTOCOL"
echo "  Network Size: $NETWORK_SIZE"
echo "  Attacker Ratio: $ATTACKER_RATIO"
echo "  Attack Mode: $ATTACK_MODE"
echo "  Runs: $RUNS"

for run in $(seq 1 $RUNS); do
    echo "Run $run/$RUNS..."
    
    # Protocol-specific test execution
    case "$PROTOCOL" in
        alephbft)
            cd code/alephbft
            export ATTACK_MODE="$ATTACK_MODE"
            export ATTACKER_RATIO="$ATTACKER_RATIO"
            export VICTIM_RATIO="$VICTIM_RATIO"
            ./run_all_attacks.sh > "$OUTPUT_DIR/run_${run}.log" 2>&1
            ;;
        bullshark)
            # ... protocol-specific execution
            ;;
        # ... other protocols
    esac
    
    # Extract ASR from log
    python3 scripts/extract_asr.py "$OUTPUT_DIR/run_${run}.log" > "$OUTPUT_DIR/run_${run}_asr.txt"
done

# Calculate statistics
python3 scripts/calculate_statistics.py "$OUTPUT_DIR" > "$OUTPUT_DIR/statistics.txt"
```

### 4.3 ASR Calculation Fix Template

**File**: `scripts/asr_calculation_template.rs`

```rust
/// Paper-aligned ASR calculation
/// 
/// Methodology:
/// - All-pairs matching (all attacker blocks × all victim blocks)
/// - Filter: attacker_round >= victim_round (attacker creates block after witnessing victim)
/// - Success: attacker_height < victim_height (attacker block ordered before victim block)
/// - ASR = successes / total_pairs
fn calculate_asr_paper_aligned(
    finalized_blocks: &[Block],
    attacker_indices: &[usize],
    victim_indices: &[usize],
) -> f64 {
    // Extract blocks with (height, round)
    // Height = position in finalization sequence (index in finalized_blocks)
    let mut attacker_blocks: Vec<(usize, Round)> = Vec::new();
    let mut victim_blocks: Vec<(usize, Round)> = Vec::new();
    
    for (height, block) in finalized_blocks.iter().enumerate() {
        let creator_idx = block.creator_index();
        if attacker_indices.contains(&creator_idx) {
            attacker_blocks.push((height, block.round()));
        }
        if victim_indices.contains(&creator_idx) {
            victim_blocks.push((height, block.round()));
        }
    }
    
    let mut successes = 0;
    let mut total_pairs = 0;
    
    // ALL-PAIRS matching (not one-to-one)
    for (att_height, att_round) in &attacker_blocks {
        for (vic_height, vic_round) in &victim_blocks {
            // Filter: attacker created block AFTER witnessing victim
            if *att_round >= *vic_round {
                total_pairs += 1;
                
                // Success: attacker block height < victim block height
                if *att_height < *vic_height {
                    successes += 1;
                }
            }
        }
    }
    
    if total_pairs == 0 {
        return 0.0;
    }
    
    (successes as f64 / total_pairs as f64) * 100.0
}
```

---

## Part 5: Validation & Quality Assurance

### 5.1 Validation Checklist

- [ ] ASR calculation matches paper's methodology (all-pairs, `att_round >= vic_round`)
- [ ] All protocols use identical base configuration
- [ ] Baseline ASR measured with 10+ runs and confidence intervals
- [ ] Attack implementation documentation complete for all protocols
- [ ] Multi-scale testing completed (13, 25, 50, 100 nodes)
- [ ] Variable attacker ratio testing completed (10%, 20%, 33%)
- [ ] Network latency sensitivity analysis completed
- [ ] Variable load testing completed
- [ ] Statistical analysis with significance tests completed
- [ ] Protocol-specific architectural analysis completed
- [ ] All results reproducible with provided scripts
- [ ] Documentation complete and clear

### 5.2 Quality Metrics

- **Reproducibility**: All experiments must be reproducible with single command
- **Statistical Rigor**: Minimum 10 runs per configuration, confidence intervals reported
- **Consistency**: All protocols use same methodology and configuration
- **Completeness**: All planned experiments completed
- **Documentation**: Clear documentation for all scripts and results

---

## Part 6: Expected Outcomes

### 6.1 Corrected ASR Measurements

After fixing ASR calculation:
- All protocols will have paper-aligned ASR measurements
- Direct comparison across protocols will be valid
- Results will match paper's methodology

### 6.2 Comprehensive Experimental Results

- **Baseline ASR**: With confidence intervals for all protocols
- **Scalability Analysis**: ASR vs network size curves
- **Attacker Ratio Analysis**: Validation of paper's Equation 1
- **Latency Sensitivity**: Real-world applicability insights
- **Load Sensitivity**: Performance under different loads
- **Statistical Significance**: Rigorous statistical analysis

### 6.3 Attack Implementation Documentation

- **Complete Documentation**: All attack implementations documented
- **Code Locations**: Exact file paths and integration points
- **Protocol Adaptations**: How attacks adapt to each protocol
- **Reproducibility Guide**: Step-by-step reproduction instructions
- **Cross-Protocol Comparison**: Differences in attack implementations

### 6.4 Protocol-Specific Analysis

- **Architectural Analysis**: Deep dive into each protocol's design
- **ASR Explanation**: Why each protocol achieves specific ASR values
- **Design Trade-offs**: Security vs performance analysis
- **Comparative Insights**: Architectural differences and their impact
- **Design Recommendations**: Lessons for future protocol design

### 6.5 Publication-Ready Material

- Reproducible experimental setup
- Comprehensive results with statistical rigor
- Clear methodology aligned with paper
- Complete attack implementation documentation
- Protocol-specific architectural analysis
- Publication-quality figures and tables

---

## Part 7: Next Steps

### Immediate Actions (Week 1)

1. **Fix ASR Calculation** (All 7 Protocols)
   - Update ASR calculation functions
   - Re-run all attack tests
   - Document changes

2. **Create Unified Configuration System**
   - Design YAML configuration format
   - Create configuration parser
   - Update all protocol test scripts

3. **Run Baseline Experiments**
   - Execute 10+ baseline runs per protocol
   - Calculate confidence intervals
   - Generate baseline report

4. **Attack Implementation Documentation** (Start)
   - Audit attack implementations
   - Document code locations
   - Create documentation template

### Short-term (Weeks 2-4)

5. **Multi-Scale Network Testing**
6. **Variable Attacker Ratio Testing**
7. **Statistical Analysis Implementation**
8. **Complete Attack Implementation Documentation**

### Medium-term (Weeks 5-8)

9. **Network Latency Sensitivity**
10. **Variable Load Testing**
11. **Protocol-Specific Deep Dive Analysis** (After all experiments)
12. **Comprehensive Results Analysis**

---

## Conclusion

This roadmap addresses:
1. **Critical methodology fix**: Align ASR calculation with paper (all-pairs matching, `att_round >= vic_round`)
2. **Standardization**: Ensure fair comparison across protocols
3. **Rigorous experimentation**: Publication-quality results with statistical rigor
4. **Comprehensive analysis**: Multi-factor experimental design (network size, attacker ratio, latency, load)
5. **Attack documentation**: Complete documentation of implementations for reproducibility
6. **Protocol analysis**: Deep dive into architectural reasons for ASR values
7. **Statistical rigor**: Significance tests, confidence intervals, and effect sizes

**Total Tasks**: 9 experimental tasks + ASR methodology fix

**Estimated Total Time**: 8-10 weeks for complete implementation

**Priority**: 
1. Fix ASR calculation first (blocks everything else)
2. Standardize experimental setup
3. Run baseline experiments
4. Complete attack implementation documentation
5. Execute all experimental tasks
6. Perform protocol-specific analysis (after experiments)

---

**Document Version**: 1.0  
**Last Updated**: 2025-11-29  
**Status**: Ready for Implementation

