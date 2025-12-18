# Bullshark and Tusk MEV Attack Reproduction Project

This project aims to reproduce the results from the Bullshark and Tusk consensus papers and extend the research to study MEV (Maximal Extractable Value) attacks on DAG-based blockchain systems.

## Project Overview

Based on meeting notes, the research objectives are:
1. **Reproduce Bullshark and Tusk results** - Validate original paper findings
2. **Study MEV attacks on DAGs** - Frontrunning and other MEV strategies
3. **Empirical analysis** - Test under different network conditions (latency, distribution, jitter)
4. **Extend to other DAG systems** - IOTA, Hedera, Fantom, Avalanche

## Key Papers

### Primary Papers
- **Narwhal and Tusk**: "Narwhal and Tusk: A DAG-based Mempool and Efficient BFT Consensus"
  - Authors: George Danezis, Eleftherios Kokoris Kogias, Alberto Sonnino, Alexander Spiegelman
  - arXiv: [2105.11827](https://arxiv.org/abs/2105.11827)

- **Bullshark**: "Bullshark: DAG BFT Protocols Made Practical"
  - Authors: Alexander Spiegelman, Neil Giridharan, Alberto Sonnino, Lefteris Kokoris-Kogias
  - arXiv: [2201.05677](https://arxiv.org/abs/2201.05677)

## Code Repositories

### Official Implementations
- **Narwhal and Tusk**: [Facebook Research Narwhal](https://github.com/facebookresearch/narwhal)
- **Bullshark**: [Mysten Labs Sui - Bullshark Implementation](https://github.com/MystenLabs/sui/tree/main/narwhal/consensus/src/bullshark)

## Project Structure

```
├── README.md                           # This file
├── docs/                              # Documentation
│   ├── phase1_artifacts.md            # Phase 1 findings and analysis
│   ├── phase2_setup.md                # Phase 2 environment setup
│   ├── experimental_design.md         # Experimental methodology
│   └── reproduction_results.md        # Results and analysis
├── code/                              # Source code and implementations
│   ├── narwhal-tusk/                  # Narwhal and Tusk implementation
│   ├── bullshark/                     # Bullshark implementation
│   ├── attack_implementations/        # MEV attack implementations
│   ├── measurement_tools/             # Performance measurement tools
│   └── orchestration/                 # Docker and deployment scripts
├── experiments/                       # Experimental configurations and results
│   ├── baseline/                      # Baseline performance tests
│   ├── attacks/                       # MEV attack experiments
│   ├── network_conditions/            # Different network scenarios
│   └── data/                          # Raw experimental data
├── scripts/                           # Automation and utility scripts
└── docker/                            # Docker configurations
```

## Phase 1: Artifact Collection ✅

### Completed Tasks
- [x] Located primary papers (Narwhal/Tusk and Bullshark)
- [x] Found official code repositories
- [x] Identified key authors and affiliations (Mysten Labs, Facebook Research)

### Key Findings
- **Narwhal**: DAG-based mempool for high-throughput transaction processing
- **Tusk**: BFT consensus protocol built on top of Narwhal
- **Bullshark**: Optimized version of Tusk for synchronous environments
- **Implementation**: Both protocols implemented in Rust
- **Organization**: Facebook Research (Narwhal) and Mysten Labs (Bullshark)

## Phase 2: Environment Setup (In Progress)

### Current Status
- Setting up development environment
- Preparing Docker containers for reproducible experiments
- Configuring network simulation tools

### Next Steps
1. Clone and build the repositories
2. Set up Docker orchestration
3. Configure network simulation (tc/netem)
4. Implement measurement tools
5. Run baseline experiments

## Experimental Design

### Network Conditions to Test
- **Latency**: 1ms (LAN), 20-50ms (intra-DC), 100-300ms (inter-region)
- **Jitter**: None, low (5-20ms), high (50-150ms)
- **Partitions**: Short (1-5s), long (30-120s)
- **Node counts**: 4-7 (small), 16 (medium), 50+ (large)

### MEV Attack Types
1. **Frontrunning**: Detect profitable transactions and submit higher-priority versions
2. **Sandwich attacks**: Frontrun + backrun around target transactions
3. **Time-bandit attacks**: Influence ordering through block production
4. **Network manipulation**: Delay/re-route messages to bias ordering

### Metrics to Measure
- Attack success rate
- Profit per attack
- Transaction ordering divergence
- Time-to-finality
- Throughput and latency impact
- Resource costs for attackers

## Getting Started

1. **Clone repositories**:
   ```bash
   git clone https://github.com/facebookresearch/narwhal.git code/narwhal-tusk/
   git clone https://github.com/MystenLabs/sui.git code/bullshark/
   ```

2. **Set up environment**:
   ```bash
   cd code/narwhal-tusk/
   # Follow build instructions in repository
   ```

3. **Run baseline experiments**:
   ```bash
   # See scripts/ directory for automation
   ```

## Timeline

- **Week 1**: Phase 1 (Artifact collection) ✅
- **Week 2**: Phase 2 (Environment setup) 🔄
- **Week 3**: Phase 3 (Baseline validation)
- **Week 4**: Phase 4 (Attack reproduction)
- **Week 5**: Phase 5 (Results validation)
- **Week 6**: Analysis and documentation

## Contact

For questions about this reproduction project, refer to the meeting notes in `MeetingSummary.txt`.
