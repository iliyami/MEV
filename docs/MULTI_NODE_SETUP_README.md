# DAG Blockchain Projects - Multi-Node Setup

This repository contains Docker-based multi-node setups for various DAG-based blockchain consensus protocols.

## 🎯 Available Projects

### ✅ Ready to Run

1. **Narwhal + Tusk** - DAG-based mempool and BFT consensus
2. **Sui (Bullshark)** - Bullshark consensus protocol implementation
3. **Mysticeti** - Low-latency DAG consensus with fast commit path

### ❌ Not Available

- **Shoal++ (Bolt)** - Repository not found
- **Autobahn** - Repository not found  
- **BBCA-Chain** - Repository not found
- **Sailfish** - Repository not found (recent paper)

## 🚀 Quick Start

### Prerequisites

- Docker (https://docs.docker.com/get-docker/)
- Docker Compose (https://docs.docker.com/compose/install/)
- At least 8GB RAM and 20GB free disk space

### Setup All Projects

```bash
# Run the comprehensive setup script
./setup-all-projects.sh
```

### Setup Individual Projects

#### Narwhal + Tusk

```bash
cd code/narwhal-tusk
./setup-multi-node.sh
docker-compose up
```

#### Sui (Bullshark)

```bash
cd code/bullshark
./setup-multi-node.sh
docker-compose up
```

#### Mysticeti

```bash
cd code/mysticeti
./setup-multi-node.sh
docker-compose up
```

## 📊 Project Details

### Narwhal + Tusk

- **Consensus**: Tusk (BFT consensus on DAG)
- **Nodes**: 4 nodes with 1 worker each
- **Ports**: 3000-3003
- **Features**: 
  - DAG-based mempool
  - BFT consensus
  - Benchmarking tools
  - Fabric-based deployment

**Architecture**:
```
Primary Node 1 (Port 3000) ←→ Primary Node 2 (Port 3001)
       ↕                           ↕
Worker 1-1                    Worker 2-1
       ↕                           ↕
Primary Node 3 (Port 3002) ←→ Primary Node 4 (Port 3003)
       ↕                           ↕
Worker 3-1                    Worker 4-1
```

### Sui (Bullshark)

- **Consensus**: Bullshark (DAG-based consensus)
- **Nodes**: 4 validator nodes
- **Ports**: 9000-9007 (RPC + WebSocket)
- **Features**:
  - Move smart contracts
  - Asset-oriented programming
  - High throughput
  - Low latency

**Architecture**:
```
Validator 1 (9000/9001) ←→ Validator 2 (9002/9003)
       ↕                        ↕
Validator 3 (9004/9005) ←→ Validator 4 (9006/9007)
```

### Mysticeti

- **Consensus**: Low-latency DAG consensus (3 message rounds)
- **Nodes**: 4 validator nodes
- **Ports**: 8000-8003
- **Features**:
  - Uncertified DAGs (no explicit certificates)
  - Fast commit path for asset transfers
  - Production deployment in Sui blockchain
  - 80% latency reduction vs Bullshark

**Architecture**:
```
Validator 1 (8000) ←→ Validator 2 (8001)
       ↕                    ↕
Validator 3 (8002) ←→ Validator 4 (8003)
```

## 🔧 Configuration

### Network Configuration

Each project uses Docker networks for inter-node communication:

- **Narwhal+Tusk**: `172.20.0.0/16`
- **Sui**: `172.21.0.0/16`
- **Mysticeti**: `172.22.0.0/16`

### Node Configuration

#### Narwhal+Tusk
- Committee size: 4 nodes
- Workers per node: 1
- Fault tolerance: 0 (for testing)
- Transaction size: 512 bytes
- Batch size: 500KB

#### Sui
- Validator count: 4
- Consensus enabled: Yes
- Event processing: Enabled
- Indexer: Enabled
- Checkpoint reader: Enabled

#### Mysticeti
- Validator count: 4
- Consensus: Low-latency DAG (3 message rounds)
- Fast commit path: Enabled
- Uncertified DAGs: Yes
- Production ready: Used by Sui blockchain

## 🧪 Testing & Benchmarking

### Narwhal+Tusk Benchmarks

```bash
cd code/narwhal-tusk
docker-compose run benchmark-client
```

Available benchmark parameters:
- Input rate: 1,000-50,000 tx/s
- Transaction size: 512B
- Duration: 60s
- Committee size: 4 nodes

### Sui Testing

```bash
cd code/bullshark
docker-compose exec sui-client cargo run --release --bin sui -- client
```

### Mysticeti Testing

```bash
cd code/mysticeti
docker-compose run benchmark-client
```

## 📈 Monitoring

### View Logs

```bash
# All services
docker-compose logs -f

# Specific service
docker-compose logs -f narwhal-node-1
docker-compose logs -f sui-node-1
```

### Check Status

```bash
# Running containers
docker-compose ps

# Resource usage
docker stats
```

## 🛠️ Troubleshooting

### Common Issues

1. **Port conflicts**: Ensure ports 3000-3003 and 9000-9007 are available
2. **Memory issues**: Increase Docker memory limit to at least 8GB
3. **Build failures**: Ensure you have sufficient disk space (20GB+)

### Reset Environment

```bash
# Stop all services
docker-compose down

# Remove volumes (WARNING: deletes all data)
docker-compose down -v

# Rebuild images
docker-compose build --no-cache
```

## 📚 Research Applications

### MEV Analysis

These setups enable research into:

1. **Leader Election Prediction**
   - Narwhal+Tusk: Round-robin (predictable)
   - Sui: Stake-weighted (probabilistic)

2. **Transaction Ordering**
   - DAG structure analysis
   - Batch processing behavior
   - Consensus timing

3. **Network Effects**
   - Latency impact on consensus
   - Throughput under different loads
   - Fault tolerance behavior

### Experimentation

1. **Network Simulation**
   - Add network delays with `tc` (traffic control)
   - Simulate packet loss
   - Test under various network conditions

2. **Load Testing**
   - Vary transaction rates
   - Test different transaction sizes
   - Measure consensus latency

3. **Attack Scenarios**
   - Byzantine node behavior
   - Network partitioning
   - Transaction flooding

## 🔗 Useful Commands

```bash
# Start all services in background
docker-compose up -d

# Stop all services
docker-compose down

# View logs in real-time
docker-compose logs -f

# Execute commands in running container
docker-compose exec narwhal-node-1 bash
docker-compose exec sui-node-1 bash

# Scale services (if supported)
docker-compose up --scale narwhal-node=6

# Clean up everything
docker-compose down -v --rmi all
```

## 📖 References

- [Narwhal and Tusk Paper](https://arxiv.org/pdf/2105.11827.pdf)
- [Bullshark Paper](https://arxiv.org/pdf/2209.05633.pdf)
- [Sui Documentation](https://docs.sui.io/)
- [Docker Compose Documentation](https://docs.docker.com/compose/)

## 🤝 Contributing

To add support for additional DAG-based blockchain projects:

1. Create a new directory in `code/`
2. Add Dockerfile and docker-compose.yml
3. Create setup script
4. Update this README
5. Test the multi-node setup

## 📄 License

This setup follows the same licenses as the original projects:
- Narwhal+Tusk: Apache 2.0
- Sui: Apache 2.0
