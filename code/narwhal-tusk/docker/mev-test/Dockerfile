# MEV-Narwhal+Tusk Attack Simulation Dockerfile
FROM rust:latest

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    cmake \
    clang \
    libclang-dev \
    pkg-config \
    libssl-dev \
    tmux \
    python3 \
    python3-pip \
    git \
    bc \
    iproute2 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# 1. Cache Python dependencies
COPY benchmark/requirements.txt benchmark/requirements.txt
RUN cd benchmark && pip3 install -r requirements.txt --break-system-packages || pip3 install -r requirements.txt

# 2. Cache Rust dependencies (The Skeleton Build)
# Copy only the manifests
COPY Cargo.toml Cargo.lock ./
COPY primary/Cargo.toml primary/Cargo.toml
COPY node/Cargo.toml node/Cargo.toml
COPY store/Cargo.toml store/Cargo.toml
COPY crypto/Cargo.toml crypto/Cargo.toml
COPY worker/Cargo.toml worker/Cargo.toml
COPY consensus/Cargo.toml consensus/Cargo.toml
COPY network/Cargo.toml network/Cargo.toml
COPY config/Cargo.toml config/Cargo.toml

# Create dummy source files for skeleton build
RUN mkdir -p primary/src && touch primary/src/lib.rs && \
    mkdir -p node/src && echo "fn main() {}" > node/src/main.rs && \
    echo "fn main() {}" > node/src/benchmark_client.rs && \
    mkdir -p store/src && touch store/src/lib.rs && \
    mkdir -p crypto/src && touch crypto/src/lib.rs && \
    mkdir -p worker/src && touch worker/src/lib.rs && \
    mkdir -p consensus/src && touch consensus/src/lib.rs && \
    mkdir -p network/src && touch network/src/lib.rs && \
    mkdir -p config/src && touch config/src/lib.rs

# Pre-build dependencies to cache them
RUN cargo build --release --features benchmark --package node

# 3. Copy the actual source code (only now)
COPY . .

# Force rebuild by touching all source files (fixes Cargo timestamp issues)
RUN find . -name "*.rs" -exec touch {} +

# Build the project in release mode with benchmark feature
RUN cargo build --release --features benchmark

# Set execution permissions for scripts
RUN chmod +x automated_fissure_attack.sh automated_speculative_attack.sh automated_sluggish_attack.sh docker/mev-test/run_attack_test.sh

# Entrypoint will be the run_attack_test.sh script
ENTRYPOINT ["/app/docker/mev-test/run_attack_test.sh"]
