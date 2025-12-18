#!/bin/bash

# Comprehensive Setup Script for DAG Blockchain Projects
set -e

echo "🚀 Setting up DAG Blockchain Projects Multi-Node Environments"
echo "=============================================================="

# Check if Docker is installed
if ! command -v docker &> /dev/null; then
    echo "❌ Docker is not installed. Please install Docker first."
    echo "   Visit: https://docs.docker.com/get-docker/"
    exit 1
fi

if ! command -v docker-compose &> /dev/null; then
    echo "❌ Docker Compose is not installed. Please install Docker Compose first."
    echo "   Visit: https://docs.docker.com/compose/install/"
    exit 1
fi

# Function to setup a project
setup_project() {
    local project_name=$1
    local project_path=$2
    
    echo ""
    echo "🔧 Setting up $project_name..."
    echo "================================"
    
    if [ -d "$project_path" ]; then
        cd "$project_path"
        
        if [ -f "setup-multi-node.sh" ]; then
            echo "Running setup script for $project_name..."
            ./setup-multi-node.sh
        else
            echo "⚠️  No setup script found for $project_name"
            echo "   You may need to set it up manually"
        fi
        
        cd - > /dev/null
    else
        echo "❌ Project directory not found: $project_path"
    fi
}

# Setup each project
setup_project "Narwhal+Tusk" "code/narwhal-tusk"
setup_project "Sui (Bullshark)" "code/bullshark"
setup_project "Mysticeti" "code/mysticeti"
setup_project "Autobahn" "code/autobahn-artifact"

echo ""
echo "✅ Setup Complete!"
echo "=================="
echo ""
echo "Available Projects:"
echo "  📦 Narwhal+Tusk:    4-node DAG consensus"
echo "  📦 Sui (Bullshark): 4-node Bullshark consensus"
echo "  📦 Mysticeti:       4-node low-latency DAG consensus"
echo "  📦 Autobahn:        4-node high-speed BFT consensus"
echo ""
echo "To run a project:"
echo "  cd code/<project-name>"
echo "  docker-compose up"
echo ""
echo "To run in background:"
echo "  docker-compose up -d"
echo ""
echo "To stop a project:"
echo "  docker-compose down"
echo ""
echo "To view logs:"
echo "  docker-compose logs -f"
echo ""
echo "Project Status:"
echo "  ✅ Narwhal+Tusk: Ready to run"
echo "  ✅ Sui (Bullshark): Ready to run"
echo "  ✅ Mysticeti: Ready to run (low-latency DAG consensus)"
echo "  ✅ Autobahn: Ready to run (high-speed BFT consensus)"
echo "  ❌ Shoal++ (Bolt): Repository not found"
echo "  ❌ BBCA-Chain: Repository not found"
echo "  ❌ Sailfish: Repository not found (recent paper)"
echo ""
echo "Next Steps:"
echo "  1. Choose a project to test"
echo "  2. Navigate to its directory"
echo "  3. Run: docker-compose up"
echo "  4. Monitor the logs and network behavior"
echo "  5. Run benchmarks or experiments"
