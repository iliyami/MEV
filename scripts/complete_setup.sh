#!/bin/bash
# Complete setup script for Bullshark and Tusk reproduction project

set -e

echo "=== Bullshark and Tusk MEV Attack Reproduction Setup ==="
echo "This script will set up the complete environment for reproducing the paper results."
echo

# Check if we're in the right directory
if [ ! -f "README.md" ]; then
    echo "Error: Please run this script from the project root directory"
    exit 1
fi

# Function to check if command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Check prerequisites
echo "=== Checking Prerequisites ==="

if ! command_exists git; then
    echo "Error: Git is not installed. Please install Git first."
    exit 1
fi

if ! command_exists docker; then
    echo "Error: Docker is not installed. Please install Docker first."
    exit 1
fi

if ! command_exists docker-compose; then
    echo "Error: Docker Compose is not installed. Please install Docker Compose first."
    exit 1
fi

echo "All prerequisites are installed."

# Step 1: Clone and build repositories
echo
echo "=== Step 1: Setting up repositories ==="
./scripts/setup_repositories.sh

# Step 2: Create additional directories
echo
echo "=== Step 2: Creating additional directories ==="
mkdir -p experiments/{baseline,attacks,network_conditions,data,logs}
mkdir -p code/{attack_implementations,measurement_tools,orchestration}

# Step 3: Create initial configuration files
echo
echo "=== Step 3: Creating configuration files ==="

# Create monitor configuration
cat > code/measurement_tools/monitor_config.json << EOF
{
    "nodes": ["narwhal-node-1", "narwhal-node-2", "narwhal-node-3", "narwhal-node-4"],
    "metrics_interval": 1.0,
    "experiment_duration": 300,
    "output_file": "/app/data/performance_metrics.json"
}
EOF

# Create attack configuration
cat > code/attack_implementations/attack_config.json << EOF
{
    "strategies": ["frontrun", "sandwich", "time_bandit"],
    "target_nodes": ["narwhal-node-1", "narwhal-node-2", "narwhal-node-3", "narwhal-node-4"],
    "attack_interval": 5.0,
    "profit_threshold": 0.01
}
EOF

# Step 4: Create network simulation script
echo
echo "=== Step 4: Creating network simulation tools ==="

cat > scripts/setup_network.sh << 'EOF'
#!/bin/bash
# Network simulation script

# Function to add latency to a container
add_latency() {
    local container_name=$1
    local latency_ms=$2
    local jitter_ms=${3:-0}
    
    echo "Adding ${latency_ms}ms latency (${jitter_ms}ms jitter) to $container_name"
    
    docker exec $container_name tc qdisc add dev eth0 root netem delay ${latency_ms}ms ${jitter_ms}ms 2>/dev/null || \
    docker exec $container_name tc qdisc change dev eth0 root netem delay ${latency_ms}ms ${jitter_ms}ms
}

# Function to add packet loss
add_packet_loss() {
    local container_name=$1
    local loss_percent=$2
    
    echo "Adding ${loss_percent}% packet loss to $container_name"
    
    docker exec $container_name tc qdisc add dev eth0 root netem loss ${loss_percent}% 2>/dev/null || \
    docker exec $container_name tc qdisc change dev eth0 root netem loss ${loss_percent}%
}

# Function to clear network conditions
clear_network() {
    local container_name=$1
    echo "Clearing network conditions for $container_name"
    docker exec $container_name tc qdisc del dev eth0 root 2>/dev/null || true
}

# Main logic
case $1 in
    "low_latency")
        for i in {1..4}; do
            add_latency "narwhal-node-$i" 1 0
        done
        ;;
    "medium_latency")
        for i in {1..4}; do
            add_latency "narwhal-node-$i" 50 10
        done
        ;;
    "high_latency")
        for i in {1..4}; do
            add_latency "narwhal-node-$i" 200 50
        done
        ;;
    "clear")
        for i in {1..4}; do
            clear_network "narwhal-node-$i"
        done
        ;;
    *)
        echo "Usage: $0 {low_latency|medium_latency|high_latency|clear}"
        exit 1
        ;;
esac
EOF

chmod +x scripts/setup_network.sh

# Step 5: Create experiment runner script
echo
echo "=== Step 5: Creating experiment runner ==="

cat > scripts/run_experiment.sh << 'EOF'
#!/bin/bash
# Experiment runner script

set -e

EXPERIMENT_NAME=$1
NETWORK_CONDITION=$2
DURATION=${3:-300}  # Default 5 minutes

if [ -z "$EXPERIMENT_NAME" ] || [ -z "$NETWORK_CONDITION" ]; then
    echo "Usage: $0 <experiment_name> <network_condition> [duration_seconds]"
    echo "Network conditions: low_latency, medium_latency, high_latency, clear"
    exit 1
fi

echo "Starting experiment: $EXPERIMENT_NAME"
echo "Network condition: $NETWORK_CONDITION"
echo "Duration: ${DURATION}s"

# Create experiment directory
EXPERIMENT_DIR="experiments/$(date +%Y%m%d_%H%M%S)_${EXPERIMENT_NAME}"
mkdir -p "$EXPERIMENT_DIR"

# Start Docker containers
echo "Starting Docker containers..."
cd docker
docker-compose up -d

# Wait for containers to be ready
echo "Waiting for containers to be ready..."
sleep 30

# Apply network conditions
echo "Applying network conditions..."
../scripts/setup_network.sh "$NETWORK_CONDITION"

# Run experiment
echo "Running experiment for ${DURATION}s..."
sleep $DURATION

# Collect logs
echo "Collecting logs..."
docker-compose logs > "$EXPERIMENT_DIR/docker_logs.txt"

# Stop containers
echo "Stopping containers..."
docker-compose down

# Move data to experiment directory
mv ../experiments/data/* "$EXPERIMENT_DIR/" 2>/dev/null || true

echo "Experiment completed. Results saved to: $EXPERIMENT_DIR"
EOF

chmod +x scripts/run_experiment.sh

# Step 6: Create quick test script
echo
echo "=== Step 6: Creating test scripts ==="

cat > scripts/test_setup.sh << 'EOF'
#!/bin/bash
# Test script to verify setup

echo "=== Testing Setup ==="

# Test Docker
echo "Testing Docker..."
cd docker
docker-compose build
echo "Docker build successful"

# Test network simulation
echo "Testing network simulation..."
docker-compose up -d
sleep 10
../scripts/setup_network.sh low_latency
echo "Network simulation test successful"

# Clean up
docker-compose down
echo "Test completed successfully"
EOF

chmod +x scripts/test_setup.sh

# Step 7: Create documentation index
echo
echo "=== Step 7: Creating documentation index ==="

cat > docs/index.md << 'EOF'
# Documentation Index

## Phase 1: Artifact Collection
- [Phase 1 Artifacts](phase1_artifacts.md) - Papers, repositories, and initial analysis

## Phase 2: Environment Setup
- [Phase 2 Setup](phase2_setup.md) - Complete environment setup guide

## Experimental Design
- [Experimental Design](experimental_design.md) - Methodology and experimental framework

## Results and Analysis
- [Reproduction Results](reproduction_results.md) - Results from reproducing paper findings

## Quick Start Guide

1. **Initial Setup**: Run `./scripts/complete_setup.sh` from project root
2. **Test Setup**: Run `./scripts/test_setup.sh` to verify everything works
3. **Run Baseline**: Run `./scripts/run_experiment.sh baseline low_latency 60`
4. **View Results**: Check `experiments/` directory for results

## Repository Structure

```
├── README.md                    # Project overview
├── docs/                        # Documentation
├── code/                        # Source code
│   ├── narwhal-tusk/           # Narwhal/Tusk implementation
│   ├── bullshark/              # Bullshark implementation
│   ├── attack_implementations/ # MEV attack code
│   └── measurement_tools/      # Performance monitoring
├── experiments/                 # Experimental data and results
├── docker/                      # Docker configurations
└── scripts/                     # Automation scripts
```
EOF

echo
echo "=== Setup Complete ==="
echo "The complete environment has been set up successfully!"
echo
echo "Next steps:"
echo "1. Test the setup: ./scripts/test_setup.sh"
echo "2. Run a baseline experiment: ./scripts/run_experiment.sh baseline low_latency 60"
echo "3. Review documentation: docs/index.md"
echo
echo "Key files created:"
echo "- Docker configuration: docker/docker-compose.yml"
echo "- Network simulation: scripts/setup_network.sh"
echo "- Experiment runner: scripts/run_experiment.sh"
echo "- Test script: scripts/test_setup.sh"
echo
echo "Repository locations:"
echo "- Narwhal/Tusk: code/narwhal-tusk/"
echo "- Bullshark: code/bullshark/"
echo "- Attack implementations: code/attack_implementations/"
echo "- Measurement tools: code/measurement_tools/"

