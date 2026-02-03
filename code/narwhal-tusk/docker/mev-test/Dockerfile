# MEV-Narwhal+Tusk Attack Simulation Dockerfile
FROM rust:1.78-slim

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
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy the entire project
COPY . .

# Install Python dependencies for benchmarking
RUN cd benchmark && pip3 install -r requirements.txt --break-system-packages || pip3 install -r requirements.txt

# Create necessary directories
RUN mkdir -p /app/results /app/benchmark/logs

# Build the project in release mode
RUN cargo build --release

# Set execution permissions for scripts
RUN chmod +x automated_fissure_attack.sh automated_speculative_attack.sh automated_sluggish_attack.sh docker/mev-test/run_attack_test.sh

# Entrypoint will be the run_attack_test.sh script
ENTRYPOINT ["/app/docker/mev-test/run_attack_test.sh"]
