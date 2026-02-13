# Autobahn MEV Attack Test Container
FROM rust:1.78-slim-bookworm

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    cmake \
    clang \
    libclang-dev \
    pkg-config \
    libssl-dev \
    curl \
    git \
    python3 \
    python3-pip \
    tmux \
    iproute2 \
    procps \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy the entire project
COPY . .

# Build the project in release mode with benchmark features
# We build the node crate which contains both 'node' and 'benchmark_client'
RUN cargo build --release --manifest-path node/Cargo.toml --features benchmark

# Create results directory
RUN mkdir -p /app/results

# Default environment variables
ENV ATTACK_MODE="fissure"
ENV ATTACKER_ID="0"
ENV VICTIM_ID="1"
ENV RUST_LOG="info"

# Copy entrypoint script (this will be mounted or copied)
COPY docker/mev-test/run_attack_test.sh /app/run_attack_test.sh
RUN chmod +x /app/run_attack_test.sh

CMD ["/app/run_attack_test.sh"]
