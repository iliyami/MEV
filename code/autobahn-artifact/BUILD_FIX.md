# Build Fix Instructions

## Issue
RocksDB compilation fails with Rust 1.90.0 due to bindgen 0.59.2 incompatibility.

## Solution: Use Older Rust Version

```bash
# Install Rust 1.70.0
rustup install 1.70.0

# Set it for this project
cd /Users/iliya/Dev/Blockchain/code/autobahn-artifact
rustup override set 1.70.0

# Build
cargo build --release --features benchmark
```

## Alternative: Quick Test Script

Create a script that switches Rust versions automatically:

```bash
#!/bin/bash
cd /Users/iliya/Dev/Blockchain/code/autobahn-artifact
rustup override set 1.70.0
cargo build --release --features benchmark
rustup override unset
```

## After Build Succeeds

Run the attack test:
```bash
python3 run_fissure_attack.py
```

Calculate ASR:
```bash
python3 scripts/calculate-fissure-asr.py logs/primary-*.log
```





