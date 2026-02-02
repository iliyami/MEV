#!/usr/bin/env python3
"""
MEV Attack Test Runner
======================
Reads experiment YAML configuration and runs attacks via Docker.

Usage:
    python3 test_runner.py config/experiment_template.yaml
    python3 test_runner.py config/experiment_template.yaml --build
"""

import argparse
import os
import subprocess
import sys
import yaml
from pathlib import Path

# Base paths
BASE_DIR = Path(__file__).parent.parent
CODE_DIR = BASE_DIR / "code"
RESULTS_DIR = BASE_DIR / "results"


def load_config(config_path: str) -> dict:
    """Load experiment configuration from YAML file."""
    with open(config_path, 'r') as f:
        return yaml.safe_load(f)


def build_docker_image(config: dict) -> bool:
    """Build the Docker image for the specified protocol."""
    protocol = config['protocol']['name']
    protocol_path = CODE_DIR / config['protocol']['path']
    dockerfile_path = protocol_path / "docker" / "mev-test" / "Dockerfile"
    tag = config['docker']['tag']
    
    if not dockerfile_path.exists():
        print(f"ERROR: Dockerfile not found at {dockerfile_path}")
        return False
    
    print(f"Building Docker image: {tag}")
    print(f"  Protocol: {protocol}")
    print(f"  Context: {protocol_path}")
    
    cmd = [
        "docker", "build",
        "-t", tag,
        "-f", str(dockerfile_path),
        str(protocol_path)
    ]
    
    result = subprocess.run(cmd, capture_output=False)
    return result.returncode == 0


def run_attack_test(config: dict) -> dict:
    """Run the attack test in Docker container."""
    tag = config['docker']['tag']
    test_name = config['test']['test_name']
    env_vars = config['environment']
    
    # Create results directory
    RESULTS_DIR.mkdir(exist_ok=True)
    results_mount = RESULTS_DIR / config['experiment']['name']
    results_mount.mkdir(exist_ok=True)
    
    print(f"\nRunning attack test: {test_name}")
    print(f"  Image: {tag}")
    print(f"  Attack Mode: {env_vars.get('ATTACK_MODE', 'unknown')}")
    
    # Build docker run command
    cmd = [
        "docker", "run", "--rm",
        "--cap-add=NET_ADMIN", # Enable Traffic Control (tc)
        "-v", f"{results_mount}:/app/results",
        "-e", f"TEST_NAME={test_name}",
    ]
    
    # Add environment variables
    for key, value in env_vars.items():
        cmd.extend(["-e", f"{key}={value}"])
    
    # Add resource limits
    if 'cpus' in config['docker']:
        cmd.extend(["--cpus", config['docker']['cpus']])
    if 'memory' in config['docker']:
        cmd.extend(["--memory", config['docker']['memory']])
    
    cmd.append(tag)
    
    print(f"  Command: {' '.join(cmd[:10])}...")
    
    result = subprocess.run(cmd, capture_output=False)
    
    # Parse results
    asr_file = results_mount / "asr_result.txt"
    if asr_file.exists():
        with open(asr_file, 'r') as f:
            content = f.read()
            if "FINAL_ASR=" in content:
                asr_value = content.split("=")[1].strip()
                if asr_value == "UNKNOWN":
                    return {"asr": "UNKNOWN", "success": False}
                return {"asr": asr_value, "success": True}
    
    return {"asr": "UNKNOWN", "success": False}


def run_local_test(config: dict) -> dict:
    """Run the attack test locally with cargo test."""
    test_name = config['test']['test_name']
    env_vars = config['environment']
    
    # Path to bullshark code
    protocol_path = CODE_DIR / config['protocol']['path']
    
    print(f"\nRunning local attack test: {test_name}")
    print(f"  Attack Mode: {env_vars.get('ATTACK_MODE', 'unknown')}")
    print(f"  CWD: {protocol_path}")
    
    # Build cargo test command
    cmd = [
        "cargo", "test", "--release",
        "--package", "consensus-core",
        test_name,
        "--", "--nocapture"
    ]
    
    # Merge current environment with config environment
    current_env = os.environ.copy()
    for key, value in env_vars.items():
        current_env[key] = str(value)
    
    # Special handle for speculative attack p_max if in config but not env
    if 'SPECULATIVE_P_MAX' not in current_env and 'speculative_p_max' in config.get('test', {}):
        current_env['SPECULATIVE_P_MAX'] = str(config['test']['speculative_p_max'])

    print(f"  Command: {' '.join(cmd)}")
    
    # Run from the protocol directory
    result = subprocess.run(cmd, cwd=str(protocol_path), capture_output=False, env=current_env)
    
    return {"asr": "CHECK_LOGS", "success": result.returncode == 0}


def verify_parity(config: dict, result: dict) -> bool:
    """Check if the ASR result matches expected within tolerance."""
    expected = config['output']['expected_asr']
    tolerance = config['output']['tolerance_percent']
    
    try:
        actual = float(result['asr'])
    except (ValueError, TypeError):
        print(f"ERROR: Could not parse ASR value: {result['asr']}")
        return False
    
    lower = max(0.0, expected - tolerance)
    upper = min(100.0, expected + tolerance)
    
    passed = lower <= actual <= upper
    
    print(f"\n{'=' * 50}")
    print("PARITY CHECK")
    print(f"{'=' * 50}")
    print(f"  Expected ASR: {expected}% (±{tolerance}%)")
    print(f"  Actual ASR:   {actual}%")
    print(f"  Range:        [{lower}%, {upper}%]")
    print(f"  Result:       {'PASSED' if passed else 'FAILED'}")
    print(f"{'=' * 50}")
    
    return passed


def main():
    parser = argparse.ArgumentParser(description="MEV Attack Test Runner")
    parser.add_argument("config", help="Path to experiment YAML config file")
    parser.add_argument("--build", action="store_true", help="Build Docker image before running")
    parser.add_argument("--build-only", action="store_true", help="Only build, don't run tests")
    parser.add_argument("--local", action="store_true", help="Run natively with cargo test (no Docker)")
    args = parser.parse_args()
    
    # Load configuration
    print(f"Loading config: {args.config}")
    config = load_config(args.config)
    
    print(f"\nExperiment: {config['experiment']['name']}")
    print(f"Description: {config['experiment']['description']}")
    
    # Build if requested
    if args.build or args.build_only:
        if not build_docker_image(config):
            print("ERROR: Docker build failed")
            sys.exit(1)
        if args.build_only:
            print("Build complete. Exiting.")
            sys.exit(0)
    
    # Run the test
    if args.local:
        result = run_local_test(config)
    else:
        result = run_attack_test(config)
    
    if not result['success']:
        print("ERROR: Test execution failed")
        sys.exit(1)
    
    # Local runs might not produce the same asr_result.txt format depending on the environment
    if args.local and result['asr'] == "CHECK_LOGS":
        print("\nLocal test completed. Please check the logs above for ASR results.")
        sys.exit(0)
    
    # Verify parity
    if verify_parity(config, result):
        print("\n✓ PARITY VERIFIED - Ready for AWS migration")
        sys.exit(0)
    else:
        print("\n✗ PARITY FAILED - Do not migrate to AWS")
        sys.exit(1)


if __name__ == "__main__":
    main()
