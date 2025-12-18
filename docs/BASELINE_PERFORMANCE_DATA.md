# Baseline Performance Data from DAG Blockchain Repositories

## 📊 **Available Performance Baselines**

### ✅ **1. Narwhal + Tusk (Original Paper Data)**
**Source**: `code/narwhal-tusk/benchmark/data/` (from our previous analysis)

| Configuration | Throughput | Latency | Notes |
|---------------|------------|---------|-------|
| 4 nodes, 1 worker | ~46k tx/s | ~464ms | Original Tusk paper results |
| 4 nodes, 2 workers | ~80k tx/s | ~520ms | Higher worker count |
| 4 nodes, 4 workers | ~120k tx/s | ~600ms | Maximum workers |

**Key Findings**:
- **Peak Performance**: ~120k tx/s with 4 workers per node
- **Latency Range**: 464-600ms depending on worker configuration
- **Transaction Size**: 512 bytes
- **Committee Size**: 4 nodes (f=0)

---

### ✅ **2. Sui (Bullshark) - Production Performance Claims**
**Source**: `code/bullshark/docs/content/concepts/sui-architecture/consensus.mdx`

| Configuration | Throughput | Latency | Notes |
|---------------|------------|---------|-------|
| 10 nodes | 300k tx/s | <1000ms | Before latency crosses 1s |
| 50 nodes | 400k tx/s | <1000ms | Before latency exceeds 1s |
| Average | 200k tx/s | ~500ms | Sustained performance |

**Key Findings**:
- **Theoretical Claims**: Up to 400k tx/s with 50 nodes
- **Average Performance**: 200k tx/s at ~500ms latency
- **Protocol**: Mysticeti (low-latency DAG consensus)
- **Features**: 3 message rounds, parallel block proposals

**Available Benchmarks**:
- `sui-single-node-benchmark`: Single node performance testing
- `sui-rpc-benchmark`: RPC performance across different access methods
- AWS orchestrator: Multi-node distributed benchmarking

---

### ✅ **3. Mysticeti - Research Implementation**
**Source**: `code/mysticeti/` (Research prototype)

| Configuration | Throughput | Latency | Notes |
|---------------|------------|---------|-------|
| 4 nodes (default) | 500 tx/s | 60s duration | Default benchmark config |
| 10 nodes | 200 tx/s | 180s duration | Example from orchestrator |
| Variable | Configurable | Configurable | Flexible benchmarking |

**Key Features**:
- **Low-latency DAG consensus**: 3 message rounds
- **Fast commit path**: Optimized for asset transfers
- **Uncertified DAGs**: No explicit certificates needed
- **Production Ready**: Used by Sui blockchain

**Available Tools**:
- `orchestrator`: Multi-node benchmarking with Prometheus/Grafana
- Configurable transaction sizes, loads, and durations
- Support for fault injection and monitoring

---

### ✅ **4. Autobahn - SOSP'24 Artifact Results**
**Source**: `code/autobahn-artifact/paper-results/` (Experimental data)

#### **Performance Under Ideal Conditions (4 nodes)**

| Protocol | Throughput | End-to-End Latency | Consensus Latency | Input Rate |
|----------|------------|-------------------|-------------------|------------|
| **Autobahn** | **231,689 tx/s** | **268 ms** | **220 ms** | 237,000 tx/s |
| **Bullshark** | **227,863 tx/s** | **578 ms** | **481 ms** | 237,000 tx/s |
| **BatchedHS** | **189,046 tx/s** | **333 ms** | **206 ms** | 190,000 tx/s |
| **VanillaHS** | **14,892 tx/s** | **408 ms** | **226 ms** | 15,000 tx/s |

#### **Scalability Results (n=20 nodes)**

| Protocol | Throughput | Latency | Input Load |
|----------|------------|---------|------------|
| **Autobahn** | **~227k tx/s** | **~303 ms** | 233,000 tx/s |
| **Bullshark** | **~227k tx/s** | **~631 ms** | 232,500 tx/s |
| **BatchedHS** | **~112k tx/s** | **~308 ms** | 112,500 tx/s |
| **VanillaHS** | **~1.5k tx/s** | **~2002 ms** | 1,600 tx/s |

#### **Fault Tolerance (Leader Failures)**

| Protocol | Blip Duration | Hangover Duration | Recovery Time |
|----------|---------------|-------------------|---------------|
| **Autobahn** | 1s | ~0.1s (effectively 0) | 23.5s total |
| **VanillaHS** | 1s (effectively 3s) | ~4.9s | 31.4s total |

#### **Network Partition Resilience (20s partition)**

| Protocol | Blip Duration | Hangover Duration | Total Recovery |
|----------|---------------|-------------------|----------------|
| **Autobahn** | 20s | ~1.7s | 29.6s total |
| **Bullshark** | 20s | ~9.1s | 36.2s total |
| **BatchedHS** | 20s | ~9.5s | 35s total |
| **VanillaHS** | 20s | ~20.4s | 49s total |

**Key Findings**:
- **Autobahn**: Best latency (268ms) with high throughput (231k tx/s)
- **Bullshark**: Similar throughput but 2x higher latency (578ms)
- **BatchedHS**: Good balance of throughput and latency
- **VanillaHS**: Poor performance, especially at scale

---

## 🎯 **Performance Comparison Summary**

### **Throughput Ranking (4 nodes)**
1. **Autobahn**: 231,689 tx/s ⭐
2. **Bullshark**: 227,863 tx/s
3. **BatchedHS**: 189,046 tx/s
4. **Narwhal+Tusk**: ~120k tx/s (4 workers)
5. **VanillaHS**: 14,892 tx/s

### **Latency Ranking (4 nodes)**
1. **Autobahn**: 268ms ⭐
2. **BatchedHS**: 333ms
3. **VanillaHS**: 408ms
4. **Narwhal+Tusk**: ~464ms
5. **Bullshark**: 578ms

### **Fault Tolerance Ranking**
1. **Autobahn**: ~0.1s hangover ⭐
2. **BatchedHS**: ~9.5s hangover
3. **Bullshark**: ~9.1s hangover
4. **VanillaHS**: ~20.4s hangover

---

## 📈 **MEV Research Implications**

### **High MEV Potential Protocols**
1. **Autobahn**: Highest throughput + lowest latency = maximum MEV opportunity
2. **Bullshark**: High throughput but higher latency = medium MEV potential
3. **Sui (Mysticeti)**: Production claims of 200k+ tx/s = high MEV potential

### **Low MEV Potential Protocols**
1. **Narwhal+Tusk**: Lower throughput, predictable round-robin = limited MEV
2. **VanillaHS**: Very low throughput = minimal MEV opportunity

### **Research Opportunities**
- **Autobahn**: Test MEV attacks on highest-performing protocol
- **Bullshark vs Autobahn**: Compare MEV resistance between similar throughput protocols
- **Fault Tolerance**: Test MEV during network partitions and leader failures
- **Scalability**: Analyze MEV behavior as node count increases

---

## 🔬 **Available Experimental Data**

### **Raw Data Files**
- **Narwhal+Tusk**: 67+ benchmark result files in `benchmark/data/`
- **Autobahn**: 12+ experimental result files in `paper-results/main-graph/`
- **Mysticeti**: Configurable benchmarking with orchestrator
- **Sui**: Single-node and RPC benchmarking tools

### **Configuration Files**
- **Autobahn**: Complete experiment configs in `experiment-configs/`
- **Mysticeti**: Flexible parameter configuration
- **Narwhal+Tusk**: Multiple worker and node configurations

### **Monitoring Tools**
- **Mysticeti**: Prometheus + Grafana integration
- **Autobahn**: Detailed latency over time measurements
- **Sui**: RPC performance monitoring

---

## ✅ **Ready for MEV Research**

We now have comprehensive baseline performance data from **4 different DAG consensus protocols**:

1. **Narwhal+Tusk**: Original DAG mempool + BFT consensus
2. **Sui (Bullshark/Mysticeti)**: Production blockchain with high performance claims
3. **Mysticeti**: Research prototype with low-latency optimizations
4. **Autobahn**: Experimental high-speed BFT with best performance

**Next Steps**: Use these baselines to design and execute MEV attack experiments across different protocols, comparing their resistance to transaction ordering manipulation under various network conditions and fault scenarios.
