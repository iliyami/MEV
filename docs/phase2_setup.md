# Phase 2: Experimental Environment Setup

## Overview
This document outlines the setup process for creating a reproducible experimental environment to test Bullshark and Tusk consensus protocols and implement MEV attacks.

## Environment Requirements

### Hardware Requirements
- **CPU**: Multi-core processor (8+ cores recommended)
- **RAM**: 16GB+ recommended for running multiple nodes
- **Storage**: 50GB+ free space for code, data, and logs
- **Network**: Stable internet connection for downloading dependencies

### Software Requirements
- **Operating System**: Linux (Ubuntu 20.04+ recommended)
- **Docker**: Version 20.10+
- **Docker Compose**: Version 2.0+
- **Rust**: Latest stable version (1.70+)
- **Git**: For cloning repositories
- **Network tools**: tc, netem for network simulation

## Project Structure Setup

### Directory Structure
```
/home/mi/devs/Blockchain/
├── code/
│   ├── narwhal-tusk/          # Facebook Research implementation
│   ├── bullshark/             # Mysten Labs implementation
│   ├── attack_implementations/ # MEV attack code
│   ├── measurement_tools/     # Performance measurement tools
│   └── orchestration/         # Docker and deployment scripts
├── experiments/
│   ├── baseline/              # Baseline performance tests
│   ├── attacks/               # MEV attack experiments
│   ├── network_conditions/    # Different network scenarios
│   └── data/                  # Raw experimental data
├── docker/                    # Docker configurations
└── scripts/                   # Automation scripts
```

## Step-by-Step Setup Process

### Step 1: Clone Repositories

```bash
# Create project directories
mkdir -p /home/mi/devs/Blockchain/{code,experiments,docker,scripts}

# Clone Narwhal and Tusk (Facebook Research)
cd /home/mi/devs/Blockchain/code
git clone https://github.com/facebookresearch/narwhal.git narwhal-tusk
cd narwhal-tusk
git checkout main  # or specific commit if mentioned in paper

# Clone Bullshark (Mysten Labs)
cd /home/mi/devs/Blockchain/code
git clone https://github.com/MystenLabs/sui.git bullshark
cd bullshark
git checkout main  # or specific commit if mentioned in paper
```

### Step 2: Build Dependencies

```bash
# Install Rust (if not already installed)
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
source ~/.cargo/env

# Build Narwhal and Tusk
cd /home/mi/devs/Blockchain/code/narwhal-tusk
cargo build --release

# Build Bullshark (from Sui repository)
cd /home/mi/devs/Blockchain/code/bullshark
cargo build --release
```

### Step 3: Docker Environment Setup

#### Create Docker Compose Configuration

```yaml
# /home/mi/devs/Blockchain/docker/docker-compose.yml
version: '3.8'

services:
  # Narwhal/Tusk nodes
  narwhal-node-1:
    build:
      context: ../code/narwhal-tusk
      dockerfile: Dockerfile
    container_name: narwhal-node-1
    ports:
      - "8001:8000"
      - "9001:9000"
    environment:
      - NODE_ID=1
      - NETWORK_SIZE=4
    networks:
      - consensus-network
    volumes:
      - ../experiments/data:/app/data
      - ../experiments/logs:/app/logs

  narwhal-node-2:
    build:
      context: ../code/narwhal-tusk
      dockerfile: Dockerfile
    container_name: narwhal-node-2
    ports:
      - "8002:8000"
      - "9002:9000"
    environment:
      - NODE_ID=2
      - NETWORK_SIZE=4
    networks:
      - consensus-network
    volumes:
      - ../experiments/data:/app/data
      - ../experiments/logs:/app/logs

  narwhal-node-3:
    build:
      context: ../code/narwhal-tusk
      dockerfile: Dockerfile
    container_name: narwhal-node-3
    ports:
      - "8003:8000"
      - "9003:9000"
    environment:
      - NODE_ID=3
      - NETWORK_SIZE=4
    networks:
      - consensus-network
    volumes:
      - ../experiments/data:/app/data
      - ../experiments/logs:/app/logs

  narwhal-node-4:
    build:
      context: ../code/narwhal-tusk
      dockerfile: Dockerfile
    container_name: narwhal-node-4
    ports:
      - "8004:8000"
      - "9004:9000"
    environment:
      - NODE_ID=4
      - NETWORK_SIZE=4
    networks:
      - consensus-network
    volumes:
      - ../experiments/data:/app/data
      - ../experiments/logs:/app/logs

  # Transaction generator
  tx-generator:
    build:
      context: ../code/measurement_tools
      dockerfile: Dockerfile
    container_name: tx-generator
    depends_on:
      - narwhal-node-1
      - narwhal-node-2
      - narwhal-node-3
      - narwhal-node-4
    networks:
      - consensus-network
    volumes:
      - ../experiments/data:/app/data

  # MEV attacker
  mev-attacker:
    build:
      context: ../code/attack_implementations
      dockerfile: Dockerfile
    container_name: mev-attacker
    depends_on:
      - narwhal-node-1
      - narwhal-node-2
      - narwhal-node-3
      - narwhal-node-4
    networks:
      - consensus-network
    volumes:
      - ../experiments/data:/app/data

networks:
  consensus-network:
    driver: bridge
    ipam:
      config:
        - subnet: 172.20.0.0/16
```

#### Create Dockerfiles

```dockerfile
# /home/mi/devs/Blockchain/code/narwhal-tusk/Dockerfile
FROM rust:1.70-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    pkg-config \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy source code
COPY . .

# Build the application
RUN cargo build --release

# Create data and logs directories
RUN mkdir -p /app/data /app/logs

# Expose ports
EXPOSE 8000 9000

# Default command
CMD ["./target/release/narwhal-node"]
```

### Step 4: Network Simulation Setup

#### Install Network Tools
```bash
# Install traffic control tools
sudo apt-get update
sudo apt-get install -y iproute2 iputils-ping

# Verify tc is available
tc --version
```

#### Network Simulation Scripts

```bash
#!/bin/bash
# /home/mi/devs/Blockchain/scripts/setup_network.sh

# Function to add latency to a container
add_latency() {
    local container_name=$1
    local latency_ms=$2
    local jitter_ms=${3:-0}
    
    echo "Adding ${latency_ms}ms latency (${jitter_ms}ms jitter) to $container_name"
    
    docker exec $container_name tc qdisc add dev eth0 root netem delay ${latency_ms}ms ${jitter_ms}ms
}

# Function to add packet loss
add_packet_loss() {
    local container_name=$1
    local loss_percent=$2
    
    echo "Adding ${loss_percent}% packet loss to $container_name"
    
    docker exec $container_name tc qdisc add dev eth0 root netem loss ${loss_percent}%
}

# Function to create network partition
create_partition() {
    local group1=$1
    local group2=$2
    local duration=$3
    
    echo "Creating network partition between $group1 and $group2 for ${duration}s"
    
    # Block communication between groups
    for container1 in $group1; do
        for container2 in $group2; do
            docker exec $container1 iptables -A OUTPUT -d $(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' $container2) -j DROP
        done
    done
    
    # Restore after duration
    sleep $duration
    
    for container1 in $group1; do
        for container2 in $group2; do
            docker exec $container1 iptables -D OUTPUT -d $(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' $container2) -j DROP
        done
    done
}

# Example usage
case $1 in
    "low_latency")
        add_latency "narwhal-node-1" 1 0
        add_latency "narwhal-node-2" 1 0
        add_latency "narwhal-node-3" 1 0
        add_latency "narwhal-node-4" 1 0
        ;;
    "medium_latency")
        add_latency "narwhal-node-1" 50 10
        add_latency "narwhal-node-2" 50 10
        add_latency "narwhal-node-3" 50 10
        add_latency "narwhal-node-4" 50 10
        ;;
    "high_latency")
        add_latency "narwhal-node-1" 200 50
        add_latency "narwhal-node-2" 200 50
        add_latency "narwhal-node-3" 200 50
        add_latency "narwhal-node-4" 200 50
        ;;
    "partition")
        create_partition "narwhal-node-1 narwhal-node-2" "narwhal-node-3 narwhal-node-4" 30
        ;;
    *)
        echo "Usage: $0 {low_latency|medium_latency|high_latency|partition}"
        exit 1
        ;;
esac
```

### Step 5: Measurement Tools Setup

#### Create Performance Monitoring Script

```python
#!/usr/bin/env python3
# /home/mi/devs/Blockchain/code/measurement_tools/performance_monitor.py

import time
import json
import requests
import psutil
import docker
from datetime import datetime
import logging

class PerformanceMonitor:
    def __init__(self, config_file="monitor_config.json"):
        self.config = self.load_config(config_file)
        self.docker_client = docker.from_env()
        self.metrics = []
        self.start_time = time.time()
        
        # Setup logging
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler('performance.log'),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger(__name__)
    
    def load_config(self, config_file):
        """Load monitoring configuration"""
        default_config = {
            "nodes": ["narwhal-node-1", "narwhal-node-2", "narwhal-node-3", "narwhal-node-4"],
            "metrics_interval": 1.0,  # seconds
            "experiment_duration": 300,  # seconds
            "output_file": "performance_metrics.json"
        }
        
        try:
            with open(config_file, 'r') as f:
                config = json.load(f)
                return {**default_config, **config}
        except FileNotFoundError:
            return default_config
    
    def collect_node_metrics(self, node_name):
        """Collect metrics from a specific node"""
        try:
            container = self.docker_client.containers.get(node_name)
            stats = container.stats(stream=False)
            
            # Extract relevant metrics
            cpu_percent = self.calculate_cpu_percent(stats)
            memory_usage = stats['memory_stats']['usage']
            network_rx = stats['networks']['consensus-network']['rx_bytes']
            network_tx = stats['networks']['consensus-network']['tx_bytes']
            
            return {
                'timestamp': time.time(),
                'node': node_name,
                'cpu_percent': cpu_percent,
                'memory_usage': memory_usage,
                'network_rx': network_rx,
                'network_tx': network_tx
            }
        except Exception as e:
            self.logger.error(f"Error collecting metrics for {node_name}: {e}")
            return None
    
    def calculate_cpu_percent(self, stats):
        """Calculate CPU percentage from Docker stats"""
        cpu_delta = stats['cpu_stats']['cpu_usage']['total_usage'] - \
                   stats['precpu_stats']['cpu_usage']['total_usage']
        system_delta = stats['cpu_stats']['system_cpu_usage'] - \
                      stats['precpu_stats']['system_cpu_usage']
        
        if system_delta > 0 and cpu_delta > 0:
            return (cpu_delta / system_delta) * len(stats['cpu_stats']['cpu_usage']['percpu_usage']) * 100.0
        return 0.0
    
    def collect_consensus_metrics(self):
        """Collect consensus-specific metrics"""
        consensus_metrics = {}
        
        for node in self.config['nodes']:
            try:
                # Try to get consensus metrics from node API
                response = requests.get(f"http://localhost:800{node[-1]}/metrics", timeout=5)
                if response.status_code == 200:
                    consensus_metrics[node] = response.json()
            except Exception as e:
                self.logger.warning(f"Could not collect consensus metrics from {node}: {e}")
        
        return consensus_metrics
    
    def run_monitoring(self):
        """Main monitoring loop"""
        self.logger.info("Starting performance monitoring")
        
        while time.time() - self.start_time < self.config['experiment_duration']:
            timestamp = time.time()
            
            # Collect metrics from all nodes
            for node in self.config['nodes']:
                metrics = self.collect_node_metrics(node)
                if metrics:
                    self.metrics.append(metrics)
            
            # Collect consensus metrics
            consensus_metrics = self.collect_consensus_metrics()
            if consensus_metrics:
                self.metrics.append({
                    'timestamp': timestamp,
                    'type': 'consensus',
                    'data': consensus_metrics
                })
            
            time.sleep(self.config['metrics_interval'])
        
        self.save_metrics()
        self.logger.info("Performance monitoring completed")
    
    def save_metrics(self):
        """Save collected metrics to file"""
        output_file = self.config['output_file']
        with open(output_file, 'w') as f:
            json.dump(self.metrics, f, indent=2)
        self.logger.info(f"Metrics saved to {output_file}")

if __name__ == "__main__":
    monitor = PerformanceMonitor()
    monitor.run_monitoring()
```

### Step 6: Automation Scripts

#### Main Experiment Runner

```bash
#!/bin/bash
# /home/mi/devs/Blockchain/scripts/run_experiment.sh

set -e

EXPERIMENT_NAME=$1
NETWORK_CONDITION=$2
DURATION=${3:-300}  # Default 5 minutes

if [ -z "$EXPERIMENT_NAME" ] || [ -z "$NETWORK_CONDITION" ]; then
    echo "Usage: $0 <experiment_name> <network_condition> [duration_seconds]"
    echo "Network conditions: low_latency, medium_latency, high_latency, partition"
    exit 1
fi

echo "Starting experiment: $EXPERIMENT_NAME"
echo "Network condition: $NETWORK_CONDITION"
echo "Duration: ${DURATION}s"

# Create experiment directory
EXPERIMENT_DIR="/home/mi/devs/Blockchain/experiments/$(date +%Y%m%d_%H%M%S)_${EXPERIMENT_NAME}"
mkdir -p "$EXPERIMENT_DIR"

# Start Docker containers
echo "Starting Docker containers..."
cd /home/mi/devs/Blockchain/docker
docker-compose up -d

# Wait for containers to be ready
echo "Waiting for containers to be ready..."
sleep 30

# Apply network conditions
echo "Applying network conditions..."
/home/mi/devs/Blockchain/scripts/setup_network.sh "$NETWORK_CONDITION"

# Start performance monitoring
echo "Starting performance monitoring..."
cd /home/mi/devs/Blockchain/code/measurement_tools
python3 performance_monitor.py &
MONITOR_PID=$!

# Start transaction generator
echo "Starting transaction generator..."
docker-compose exec -d tx-generator python3 tx_generator.py --rate 100 --duration $DURATION

# Start MEV attacker (if applicable)
if [ "$EXPERIMENT_NAME" != "baseline" ]; then
    echo "Starting MEV attacker..."
    docker-compose exec -d mev-attacker python3 mev_attacker.py --strategy frontrun
fi

# Run experiment
echo "Running experiment for ${DURATION}s..."
sleep $DURATION

# Stop monitoring
kill $MONITOR_PID

# Collect logs
echo "Collecting logs..."
docker-compose logs > "$EXPERIMENT_DIR/docker_logs.txt"

# Stop containers
echo "Stopping containers..."
docker-compose down

# Move data to experiment directory
mv /home/mi/devs/Blockchain/experiments/data/* "$EXPERIMENT_DIR/" 2>/dev/null || true

echo "Experiment completed. Results saved to: $EXPERIMENT_DIR"
```

## Validation Steps

### 1. Verify Build Process
```bash
# Test Narwhal/Tusk build
cd /home/mi/devs/Blockchain/code/narwhal-tusk
cargo test

# Test Bullshark build
cd /home/mi/devs/Blockchain/code/bullshark
cargo test
```

### 2. Test Docker Setup
```bash
# Build and test Docker containers
cd /home/mi/devs/Blockchain/docker
docker-compose build
docker-compose up -d
docker-compose ps  # Verify all containers are running
docker-compose down
```

### 3. Test Network Simulation
```bash
# Test network simulation tools
/home/mi/devs/Blockchain/scripts/setup_network.sh low_latency
# Verify latency with ping
docker exec narwhal-node-1 ping -c 3 narwhal-node-2
```

### 4. Run Baseline Test
```bash
# Run a short baseline experiment
/home/mi/devs/Blockchain/scripts/run_experiment.sh baseline low_latency 60
```

## Troubleshooting

### Common Issues

1. **Build Failures**
   - Ensure Rust is properly installed
   - Check system dependencies
   - Verify network connectivity for downloading crates

2. **Docker Issues**
   - Ensure Docker daemon is running
   - Check available disk space
   - Verify Docker Compose version compatibility

3. **Network Simulation Issues**
   - Ensure running with appropriate permissions
   - Check if tc/netem tools are installed
   - Verify container network configuration

4. **Performance Issues**
   - Monitor system resources (CPU, memory)
   - Adjust container resource limits
   - Consider running fewer nodes for initial tests

## Next Steps

After completing Phase 2 setup:

1. **Run baseline experiments** to validate the environment
2. **Compare results** with paper baselines
3. **Implement MEV attacks** as described in research goals
4. **Extend to other DAG systems** (IOTA, Hedera, etc.)

## Resources

- [Docker Documentation](https://docs.docker.com/)
- [Linux Traffic Control](https://man7.org/linux/man-pages/man8/tc.8.html)
- [Rust Documentation](https://doc.rust-lang.org/)
- [Narwhal Repository](https://github.com/facebookresearch/narwhal)
- [Sui Repository](https://github.com/MystenLabs/sui)
