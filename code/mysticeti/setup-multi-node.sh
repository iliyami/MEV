#!/bin/bash

# Mysticeti Multi-Node Setup Script
set -e

echo "🚀 Setting up Mysticeti Multi-Node Environment"

# Check if Docker is installed
if ! command -v docker &> /dev/null; then
    echo "❌ Docker is not installed. Please install Docker first."
    exit 1
fi

if ! command -v docker-compose &> /dev/null; then
    echo "❌ Docker Compose is not installed. Please install Docker Compose first."
    exit 1
fi

# Create data directories
echo "📁 Creating data directories..."
mkdir -p data/node{1,2,3,4}

# Generate committee configuration
echo "⚙️  Generating committee configuration..."
cat > committee.json << EOF
{
  "authorities": {
    "1": {
      "primary": {
        "primary_to_primary": "http://mysticeti-node-1:8000",
        "worker_to_primary": "http://mysticeti-node-1:8000"
      },
      "stake": 1,
      "network_key": "primary-1-key"
    },
    "2": {
      "primary": {
        "primary_to_primary": "http://mysticeti-node-2:8000",
        "worker_to_primary": "http://mysticeti-node-2:8000"
      },
      "stake": 1,
      "network_key": "primary-2-key"
    },
    "3": {
      "primary": {
        "primary_to_primary": "http://mysticeti-node-3:8000",
        "worker_to_primary": "http://mysticeti-node-3:8000"
      },
      "stake": 1,
      "network_key": "primary-3-key"
    },
    "4": {
      "primary": {
        "primary_to_primary": "http://mysticeti-node-4:8000",
        "worker_to_primary": "http://mysticeti-node-4:8000"
      },
      "stake": 1,
      "network_key": "primary-4-key"
    }
  }
}
EOF

# Build Docker image
echo "🔨 Building Docker image..."
docker-compose build

echo "✅ Setup complete!"
echo ""
echo "To start the Mysticeti network:"
echo "  docker-compose up"
echo ""
echo "To run in background:"
echo "  docker-compose up -d"
echo ""
echo "To stop the network:"
echo "  docker-compose down"
echo ""
echo "To view logs:"
echo "  docker-compose logs -f"
echo ""
echo "To run benchmarks:"
echo "  docker-compose run benchmark-client"
echo ""
echo "Mysticeti Features:"
echo "  - Low-latency DAG consensus (3 message rounds)"
echo "  - Uncertified DAGs (no explicit certificates)"
echo "  - Fast commit path for asset transfers"
echo "  - Used in production by Sui blockchain"
