# Narwhal+Tusk Multi-Node Docker Setup
FROM rust:1.70-slim

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
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy the entire narwhal-tusk project
COPY . .

# Install Python dependencies for benchmarking
RUN cd benchmark && pip3 install -r requirements.txt

# Build the project in release mode
RUN cargo build --release

# Create directories for node data
RUN mkdir -p /app/data/node{1,2,3,4}

# Expose ports for each node
EXPOSE 3000 3001 3002 3003

# Default command to run a single node
CMD ["cargo", "run", "--release", "--bin", "primary"]
