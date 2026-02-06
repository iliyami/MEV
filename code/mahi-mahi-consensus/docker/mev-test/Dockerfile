# MEV-Mahi-Mahi Attack Simulation Dockerfile
FROM rust:latest

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    cmake \
    clang \
    libclang-dev \
    pkg-config \
    libssl-dev \
    python3 \
    python3-pip \
    git \
    bc \
    iproute2 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy the entire source code
COPY . .

# Build the project in release mode
RUN cargo build --release

# Set execution permissions for scripts
RUN chmod +x scripts/legacy_automation/*.sh scripts/*.sh docker/mev-test/run_attack_test.sh

# Entrypoint will be the run_attack_test.sh script
ENTRYPOINT ["/app/docker/mev-test/run_attack_test.sh"]
