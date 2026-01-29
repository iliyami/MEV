# AlephBFT MEV Attack Test Container
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
    iproute2 \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy the entire project
COPY . .

# Build the consensus tests in release mode
RUN cargo build --release --package aleph-bft

# Create results directory
RUN mkdir -p /app/results

# Default environment variables
ENV ATTACK_MODE="fissure"
ENV ATTACKER_RATIO="0.308"
ENV VICTIM_RATIO="0.231"
ENV RUST_LOG="info"

# Copy entrypoint script
COPY docker/mev-test/run_attack_test.sh /app/run_attack_test.sh
RUN chmod +x /app/run_attack_test.sh

CMD ["/app/run_attack_test.sh"]
