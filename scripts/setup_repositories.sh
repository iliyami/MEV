#!/bin/bash
# Setup script for cloning and building Bullshark and Tusk repositories

set -e

echo "=== Bullshark and Tusk Repository Setup ==="
echo "This script will clone and build the necessary repositories for reproducing the paper results."
echo

# Check if we're in the right directory
if [ ! -f "README.md" ]; then
    echo "Error: Please run this script from the project root directory"
    exit 1
fi

# Check if Rust is installed
if ! command -v cargo &> /dev/null; then
    echo "Rust is not installed. Installing Rust..."
    curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
    source ~/.cargo/env
    echo "Rust installed successfully"
else
    echo "Rust is already installed: $(cargo --version)"
fi

# Create code directory if it doesn't exist
mkdir -p code

echo
echo "=== Cloning Repositories ==="

# Clone Narwhal and Tusk (Facebook Research)
if [ ! -d "code/narwhal-tusk" ]; then
    echo "Cloning Narwhal and Tusk repository..."
    cd code
    git clone https://github.com/facebookresearch/narwhal.git narwhal-tusk
    cd narwhal-tusk
    echo "Checking out main branch..."
    git checkout main
    cd ../..
    echo "Narwhal and Tusk repository cloned successfully"
else
    echo "Narwhal and Tusk repository already exists, updating..."
    cd code/narwhal-tusk
    git pull origin main
    cd ../..
fi

# Clone Bullshark (Mysten Labs Sui)
if [ ! -d "code/bullshark" ]; then
    echo "Cloning Bullshark (Sui) repository..."
    cd code
    git clone https://github.com/MystenLabs/sui.git bullshark
    cd bullshark
    echo "Checking out main branch..."
    git checkout main
    cd ../..
    echo "Bullshark repository cloned successfully"
else
    echo "Bullshark repository already exists, updating..."
    cd code/bullshark
    git pull origin main
    cd ../..
fi

echo
echo "=== Building Repositories ==="

# Build Narwhal and Tusk
echo "Building Narwhal and Tusk..."
cd code/narwhal-tusk
echo "Installing dependencies..."
cargo build --release
echo "Running tests..."
cargo test --release
cd ../..

# Build Bullshark
echo "Building Bullshark..."
cd code/bullshark
echo "Installing dependencies..."
cargo build --release
echo "Running tests..."
cargo test --release
cd ../..

echo
echo "=== Setup Complete ==="
echo "Repositories have been cloned and built successfully!"
echo
echo "Next steps:"
echo "1. Review the documentation in docs/phase2_setup.md"
echo "2. Set up Docker environment: docker/setup_docker.sh"
echo "3. Run baseline experiments: scripts/run_baseline.sh"
echo
echo "Repository locations:"
echo "- Narwhal/Tusk: code/narwhal-tusk/"
echo "- Bullshark: code/bullshark/"

