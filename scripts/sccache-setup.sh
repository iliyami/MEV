#!/bin/bash
# sccache Setup Script for DAG Blockchain Projects
# This script configures sccache for faster Rust compilation across all protocols

set -e

echo "🚀 Setting up sccache for Rust compilation caching..."
echo ""

# Check if sccache is installed
if ! command -v sccache &> /dev/null; then
    echo "❌ sccache not found. Installing via Homebrew..."
    brew install sccache
fi

# Configure sccache
export RUSTC_WRAPPER=sccache
export SCCACHE_CACHE_SIZE="20G"
export SCCACHE_DIR="$HOME/.cache/sccache"

# Create cache directory
mkdir -p "$SCCACHE_DIR"

echo "✅ sccache configured:"
echo "   RUSTC_WRAPPER: $RUSTC_WRAPPER"
echo "   SCCACHE_CACHE_SIZE: $SCCACHE_CACHE_SIZE"
echo "   SCCACHE_DIR: $SCCACHE_DIR"
echo ""

# Add to shell config if not already present
SHELL_CONFIG="$HOME/.zshrc"
if ! grep -q "RUSTC_WRAPPER=sccache" "$SHELL_CONFIG" 2>/dev/null; then
    echo "" >> "$SHELL_CONFIG"
    echo "# sccache for faster Rust builds (added by MEV research project)" >> "$SHELL_CONFIG"
    echo "export RUSTC_WRAPPER=sccache" >> "$SHELL_CONFIG"
    echo "export SCCACHE_CACHE_SIZE=\"20G\"" >> "$SHELL_CONFIG"
    echo "export SCCACHE_DIR=\"\$HOME/.cache/sccache\"" >> "$SHELL_CONFIG"
    echo "✅ Added sccache config to $SHELL_CONFIG"
else
    echo "ℹ️  sccache already configured in $SHELL_CONFIG"
fi

# Start sccache server
sccache --start-server 2>/dev/null || true

# Show current stats
echo ""
echo "📊 sccache status:"
sccache --show-stats

echo ""
echo "🎉 sccache setup complete!"
echo ""
echo "To use in current shell, run:"
echo "   source $SHELL_CONFIG"
echo "   OR"
echo "   export RUSTC_WRAPPER=sccache"
