# Phase 1: Artifact Collection and Analysis

## Overview
This document details the artifacts collected during Phase 1 of reproducing the Bullshark and Tusk consensus paper results.

## Key Papers Identified

### 1. Narwhal and Tusk Paper
- **Title**: "Narwhal and Tusk: A DAG-based Mempool and Efficient BFT Consensus"
- **Authors**: George Danezis, Eleftherios Kokoris Kogias, Alberto Sonnino, Alexander Spiegelman
- **arXiv ID**: 2105.11827
- **URL**: https://arxiv.org/abs/2105.11827
- **Publication Date**: May 2021

**Key Contributions**:
- Introduces Narwhal: a DAG-based mempool for high-throughput transaction processing
- Introduces Tusk: a BFT consensus protocol built on top of Narwhal
- Separates mempool (Narwhal) from consensus (Tusk) for better performance
- Achieves high throughput while maintaining BFT properties

### 2. Bullshark Paper
- **Title**: "Bullshark: DAG BFT Protocols Made Practical"
- **Authors**: Alexander Spiegelman, Neil Giridharan, Alberto Sonnino, Lefteris Kokoris-Kogias
- **arXiv ID**: 2201.05677
- **URL**: https://arxiv.org/abs/2201.05677
- **Publication Date**: January 2022

**Key Contributions**:
- Optimized version of Tusk for synchronous environments
- Improves upon Tusk's performance in good network conditions
- Maintains safety and liveness properties
- Practical implementation considerations

## Code Repositories

### 1. Narwhal and Tusk Implementation
- **Repository**: https://github.com/facebookresearch/narwhal
- **Organization**: Facebook Research
- **Language**: Rust
- **Status**: Active development
- **Key Components**:
  - Narwhal mempool implementation
  - Tusk consensus implementation
  - Benchmarking tools
  - Network simulation capabilities

### 2. Bullshark Implementation
- **Repository**: https://github.com/MystenLabs/sui/tree/main/narwhal/consensus/src/bullshark
- **Organization**: Mysten Labs (Sui blockchain)
- **Language**: Rust
- **Status**: Production implementation in Sui
- **Key Components**:
  - Bullshark consensus implementation
  - Integration with Sui blockchain
  - Performance optimizations

## Protocol Architecture Analysis

### Narwhal (DAG Mempool)
- **Purpose**: High-throughput transaction mempool using DAG structure
- **Key Features**:
  - DAG-based transaction ordering
  - Parallel transaction processing
  - Efficient gossip protocol
  - Fault tolerance

### Tusk (BFT Consensus)
- **Purpose**: Byzantine Fault Tolerant consensus on top of Narwhal
- **Key Features**:
  - Asynchronous BFT consensus
  - Works with Narwhal's DAG structure
  - Handles up to f < n/3 Byzantine failures
  - Deterministic finality

### Bullshark (Optimized Tusk)
- **Purpose**: Synchronous-optimized version of Tusk
- **Key Features**:
  - Better performance in good network conditions
  - Maintains Tusk's safety properties
  - Practical implementation optimizations
  - Used in production Sui blockchain

## Experimental Parameters (From Papers)

### Network Topology
- **Node counts**: Typically 4-16 nodes for experiments
- **Network model**: Partially synchronous
- **Latency ranges**: 1ms (LAN) to 300ms (WAN)
- **Bandwidth**: Varies by experiment

### Transaction Workloads
- **Transaction sizes**: Variable (typically 1KB-10KB)
- **Throughput targets**: 100-1000+ transactions per second
- **Workload patterns**: Poisson arrival, bursty patterns

### Attack Scenarios
- **Byzantine failures**: Up to f < n/3 malicious nodes
- **Network attacks**: Message delays, partitions
- **MEV attacks**: Frontrunning, sandwich attacks (to be implemented)

## Implementation Details

### Technology Stack
- **Language**: Rust (both implementations)
- **Dependencies**: 
  - Cryptographic libraries
  - Network protocols (TCP/UDP)
  - Serialization (bincode, serde)
  - Async runtime (tokio)

### Build Requirements
- **Rust**: Latest stable version
- **Cargo**: Package manager
- **System dependencies**: Varies by platform

### Configuration
- **Node configuration**: JSON/YAML config files
- **Network parameters**: Latency, bandwidth, topology
- **Consensus parameters**: Timeouts, batch sizes

## Next Steps for Phase 2

### Environment Setup
1. **Clone repositories** and verify build process
2. **Set up Docker containers** for reproducible experiments
3. **Configure network simulation** tools (tc/netem)
4. **Implement measurement tools** for performance metrics

### Baseline Experiments
1. **Run without attacks** to establish baseline performance
2. **Measure key metrics**: throughput, latency, finality time
3. **Validate against paper results** for baseline scenarios

### Attack Implementation
1. **Study existing attack implementations** (if any)
2. **Implement MEV attacks** as described in research goals
3. **Create attack scenarios** matching paper experiments

## Resources and References

### Additional Papers
- Look for follow-up papers by the same authors
- Check for implementation details in Sui documentation
- Review related work on DAG-based consensus

### Community Resources
- **Mysten Labs Discord/Forum**: For implementation questions
- **Facebook Research**: For Narwhal-specific issues
- **Sui Documentation**: For Bullshark production usage

### Tools and Libraries
- **Network simulation**: tc, netem, Mininet
- **Containerization**: Docker, Docker Compose
- **Monitoring**: Prometheus, Grafana (if needed)
- **Data analysis**: Python, R, or similar

## Questions for Further Investigation

1. **Exact experimental parameters**: What were the specific network conditions, node counts, and transaction workloads used in the original papers?

2. **Attack implementations**: Are there existing implementations of MEV attacks on these protocols, or do we need to implement them from scratch?

3. **Performance baselines**: What were the exact performance numbers reported in the papers for baseline scenarios?

4. **Reproducibility**: Are there specific commits, configurations, or datasets that should be used for exact reproduction?

5. **Extensions**: What additional experiments beyond the original papers would be most valuable for the MEV research goals?
