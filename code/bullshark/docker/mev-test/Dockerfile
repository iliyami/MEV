# Bullshark MEV Attack Test Container
# Optimized for running consensus attack tests
FROM rust:latest

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
    iproute2 \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy the entire Bullshark project
COPY . .

# Build the consensus tests in release mode
RUN cargo build --release --package consensus-core

# Create results directory
RUN mkdir -p /app/results

# Default environment variables (can be overridden)
ENV ATTACK_MODE="fissure"
ENV ATTACKER_RATIO="0.308"
ENV VICTIM_RATIO="0.231"
ENV RUST_LOG="info"

# Entrypoint script to run tests
COPY docker/mev-test/run_attack_test.sh /app/run_attack_test.sh
RUN chmod +x /app/run_attack_test.sh

# Default command
CMD ["/app/run_attack_test.sh"]
