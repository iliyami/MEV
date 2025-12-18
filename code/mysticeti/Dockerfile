# Mysticeti Multi-Node Docker Setup
FROM rust:1.72-slim

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
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy the entire Mysticeti project
COPY . .

# Build the project in release mode
RUN cargo build --release

# Create directories for node data
RUN mkdir -p /app/data/node{1,2,3,4}

# Expose ports for each node
EXPOSE 8000 8001 8002 8003

# Default command to run a single node
CMD ["cargo", "run", "--release", "--bin", "mysticeti"]
