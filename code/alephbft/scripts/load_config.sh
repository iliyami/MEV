#!/bin/bash
# Configuration Loader for AlephBFT Experiments
# Parses YAML configuration file and exports environment variables
#
# Usage: source scripts/load_config.sh [config_file]
#   If config_file is not provided, uses experimental_config.yaml in current directory

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ALEPHBFT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
CONFIG_FILE="${1:-$ALEPHBFT_DIR/experimental_config.yaml}"

if [ ! -f "$CONFIG_FILE" ]; then
    echo "Error: Configuration file not found: $CONFIG_FILE" >&2
    exit 1
fi

# Check if Python 3 is available
if ! command -v python3 &> /dev/null; then
    echo "Error: python3 is required but not found" >&2
    exit 1
fi

# Try to parse YAML using Python
# This script will work if pyyaml is installed: pip3 install pyyaml
python3 << EOF
import sys
import os

try:
    import yaml
except ImportError:
    print("Error: pyyaml is required. Install it with: pip3 install pyyaml", file=sys.stderr)
    sys.exit(1)

config_file = "$CONFIG_FILE"

try:
    with open(config_file, 'r') as f:
        config = yaml.safe_load(f)
except Exception as e:
    print(f"Error: Failed to parse YAML file: {e}", file=sys.stderr)
    sys.exit(1)

# Export environment variables
def export_var(name, value):
    if value is None:
        return
    # Convert to string and escape special characters
    value_str = str(value).replace('"', '\\"').replace('$', '\\$')
    print(f'export {name}="{value_str}"')

# Network configuration
if 'network' in config:
    network = config['network']
    export_var('NETWORK_SIZE', network.get('size'))
    export_var('ATTACKER_RATIO', network.get('attacker_ratio'))
    export_var('VICTIM_RATIO', network.get('victim_ratio'))

# Attack configuration
if 'attack' in config:
    attack = config['attack']
    export_var('ATTACK_MODE', attack.get('mode'))
    
    if 'parameters' in attack:
        params = attack['parameters']
        if 'fissure' in params:
            export_var('FISSURE_EXCLUSION_PROBABILITY', params['fissure'].get('exclusion_probability'))
        if 'speculative' in params:
            export_var('SPECULATIVE_P_MAX', params['speculative'].get('p_max'))
        if 'sluggish' in params:
            export_var('SLUGGISH_PROCESSING_DELAY_MS', params['sluggish'].get('processing_delay_ms'))

# Test configuration
if 'test' in config:
    test = config['test']
    export_var('TEST_DURATION_SECONDS', test.get('duration_seconds'))
    export_var('TEST_MIN_FINALIZED_BLOCKS', test.get('min_finalized_blocks'))
    export_var('TEST_RUNS', test.get('runs'))
    export_var('TEST_OUTPUT_DIR', test.get('output_dir'))

# ASR calculation configuration
if 'asr_calculation' in config:
    asr = config['asr_calculation']
    export_var('ASR_METHOD', asr.get('method'))
    export_var('ASR_ROUND_FILTER', asr.get('round_filter'))
    export_var('ASR_HEIGHT_DEFINITION', asr.get('height_definition'))
EOF

# Source the exported variables
eval "$(python3 << 'PYTHON_SCRIPT'
import sys
import os

try:
    import yaml
except ImportError:
    print("Error: pyyaml is required. Install it with: pip3 install pyyaml", file=sys.stderr)
    sys.exit(1)

config_file = "$CONFIG_FILE"

try:
    with open(config_file, 'r') as f:
        config = yaml.safe_load(f)
except Exception as e:
    print(f"Error: Failed to parse YAML file: {e}", file=sys.stderr)
    sys.exit(1)

# Export environment variables
def export_var(name, value):
    if value is None:
        return
    # Convert to string and escape special characters
    value_str = str(value).replace('"', '\\"').replace('$', '\\$')
    print(f'export {name}="{value_str}"')

# Network configuration
if 'network' in config:
    network = config['network']
    export_var('NETWORK_SIZE', network.get('size'))
    export_var('ATTACKER_RATIO', network.get('attacker_ratio'))
    export_var('VICTIM_RATIO', network.get('victim_ratio'))

# Attack configuration
if 'attack' in config:
    attack = config['attack']
    export_var('ATTACK_MODE', attack.get('mode'))
    
    if 'parameters' in attack:
        params = attack['parameters']
        if 'fissure' in params:
            export_var('FISSURE_EXCLUSION_PROBABILITY', params['fissure'].get('exclusion_probability'))
        if 'speculative' in params:
            export_var('SPECULATIVE_P_MAX', params['speculative'].get('p_max'))
        if 'sluggish' in params:
            export_var('SLUGGISH_PROCESSING_DELAY_MS', params['sluggish'].get('processing_delay_ms'))

# Test configuration
if 'test' in config:
    test = config['test']
    export_var('TEST_DURATION_SECONDS', test.get('duration_seconds'))
    export_var('TEST_MIN_FINALIZED_BLOCKS', test.get('min_finalized_blocks'))
    export_var('TEST_RUNS', test.get('runs'))
    export_var('TEST_OUTPUT_DIR', test.get('output_dir'))

# ASR calculation configuration
if 'asr_calculation' in config:
    asr = config['asr_calculation']
    export_var('ASR_METHOD', asr.get('method'))
    export_var('ASR_ROUND_FILTER', asr.get('round_filter'))
    export_var('ASR_HEIGHT_DEFINITION', asr.get('height_definition'))
PYTHON_SCRIPT
)"

echo "Configuration loaded from: $CONFIG_FILE"
echo "  NETWORK_SIZE: ${NETWORK_SIZE:-not set}"
echo "  ATTACKER_RATIO: ${ATTACKER_RATIO:-not set}"
echo "  ATTACK_MODE: ${ATTACK_MODE:-not set}"





