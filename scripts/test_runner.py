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
from pathlib import Path

# Robust YAML import to avoid shadowing by local folders or broken venv
def _get_working_yaml():
    # Try current directory first (where we restored the working copy)
    root_dir = Path(__file__).parent.parent.resolve()
    if (root_dir / 'yaml').is_dir():
        if str(root_dir) not in sys.path:
            sys.path.insert(0, str(root_dir))
        if 'yaml' in sys.modules:
            del sys.modules['yaml']
        try:
            import yaml
            if hasattr(yaml, 'safe_load'): return yaml
        except: pass

    # Try site-packages
    for path in sys.path:
        if 'site-packages' in path and os.path.isdir(os.path.join(path, 'yaml')):
            sys.path.insert(0, path)
            if 'yaml' in sys.modules: del sys.modules['yaml']
            try:
                import yaml
                if hasattr(yaml, 'safe_load'): return yaml
            except: pass
    
    # Fallback
    import yaml
    return yaml

yaml = _get_working_yaml()

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
        "--progress=plain",
        str(protocol_path)
    ]
    
    print(f"  Command: {' '.join(cmd)}")
    
    env = os.environ.copy()
    # Allow environment to override, default to 0 for maximum compatibility on CloudLab
    env["DOCKER_BUILDKIT"] = os.environ.get("DOCKER_BUILDKIT", "1")
    
    result = subprocess.run(cmd, env=env, capture_output=False)
    return result.returncode == 0


def run_attack_test(config: dict) -> dict:
    """Run the attack test in Docker container."""
    tag = config['docker']['tag']
    test_name = config['test'].get('test_name', config['experiment']['name'])
    env_vars = config['environment']
    
    # Create results directory
    RESULTS_DIR.mkdir(exist_ok=True)
    results_mount = RESULTS_DIR / config['experiment']['name']
    results_mount.mkdir(exist_ok=True)
    
    print(f"\nRunning attack test: {test_name}")
    print(f"  Image: {tag}")
    print(f"  Attack Mode: {env_vars.get('ATTACK_MODE', 'unknown')}")
    
    # Delete stale result file if it exists
    asr_file = results_mount / "asr_result.txt"
    if asr_file.exists():
        asr_file.unlink()
    
    # Build docker run command
    protocol_path = CODE_DIR / config['protocol']['path']
    # Build docker run command
    protocol_path = CODE_DIR / config['protocol']['path']
    cmd = [
        "docker", "run", "--rm",
        "--cap-add=NET_ADMIN", # Enable Traffic Control (tc)
        "-v", f"{results_mount}:/app/results",
        "-e", f"TEST_NAME={test_name}",
    ]

    # Mount local fixed scripts over the container's scripts to avoid rebuilds
    # Protocol-specific script mappings
    script_mounts = []
    if config['protocol']['name'] == "alephbft":
        script_mounts = [
            ("docker/mev-test/run_attack_test.sh", "/app/run_attack_test.sh"),
        ]
    elif config['protocol']['name'] == "autobahn":
        script_mounts = [
            ("docker/mev-test/run_attack_test.sh", "/app/run_attack_test.sh"),
            ("scripts/calculate-fissure-asr.py", "/app/scripts/calculate-fissure-asr.py"),
        ]
    else:
        # Default mounts for Bullshark/Mysticeti
        script_mounts = [
            ("docker/mev-test/run_attack_test.sh", "/app/run_attack_test.sh"),
            # Mount source code for rapid iteration
            ("consensus/core", "/app/consensus/core"),
            ("scripts/legacy_automation/automated_fissure_attack.sh", "/app/scripts/legacy_automation/automated_fissure_attack.sh"),
            ("scripts/legacy_automation/automated_speculative_attack.sh", "/app/scripts/legacy_automation/automated_speculative_attack.sh"),
            ("scripts/legacy_automation/automated_sluggish_attack.sh", "/app/scripts/legacy_automation/automated_sluggish_attack.sh"),
            ("scripts/calculate-fissure-asr.py", "/app/scripts/calculate-fissure-asr.py"),
            ("scripts/calculate-sluggish-asr.py", "/app/scripts/calculate-sluggish-asr.py"),
            ("scripts/calculate-speculative-asr.py", "/app/scripts/calculate-speculative-asr.py"),
        ]

    for local_rel, container_path in script_mounts:
        # Check if it's a global script or protocol-specific
        if local_rel.startswith("scripts/"):
            local_full = BASE_DIR / local_rel
        else:
            local_full = protocol_path / local_rel
            
        if local_full.exists():
            cmd.extend(["-v", f"{local_full}:{container_path}"])
        else:
            print(f"  Warning: Skipping mount for non-existent file: {local_rel} (checked {local_full})")
    
    # Add environment variables
    for key, value in env_vars.items():
        cmd.extend(["-e", f"{key}={value}"])
    
    # Add resource limits
    if 'cpus' in config['docker']:
        cmd.extend(["--cpus", config['docker']['cpus']])
    if 'memory' in config['docker']:
        cmd.extend(["--memory", config['docker']['memory']])
    
    cmd.append(tag)
    
    # Add protocol-specific command to override Dockerfile CMD
    if config['protocol']['name'] == "mysticeti":
        cmd.append("/app/docker/mev-test/run_attack_test.sh")
    elif config['protocol']['name'] in ["alephbft", "autobahn"]:
        cmd.append("/app/run_attack_test.sh")
    
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
    
    # Determine if we should use cargo test or a script
    is_script = protocol_path.name == "mahi-mahi-consensus" or config['protocol'].get('use_scripts', False)
    
    if is_script:
        attack_mode = env_vars.get('ATTACK_MODE', 'fissure')
        script_path = f"./scripts/legacy_automation/automated_{attack_mode}_attack.sh"
        cmd = ["bash", script_path]
    else:
        if config['protocol']['name'] == "alephbft":
            package_name = "aleph-bft"
        else:
            package_name = config['protocol'].get('package_name', 'consensus-core')
            
        cmd = [
            "cargo", "test", "--release",
            "--package", package_name,
            test_name,
            "--", "--nocapture"
        ]
    
    # Merge current environment with config environment
    current_env = os.environ.copy()
    for key, value in env_vars.items():
        current_env[key] = str(value)

    # Force disable sccache for local runs to avoid "Operation not permitted"
    current_env["RUSTC_WRAPPER"] = ""
    
    # Set TMPDIR to a local writable directory to avoid sandbox issues with rustc
    # Use a 'tmp' directory in the project root
    local_tmp_dir = (BASE_DIR / "tmp").resolve()
    try:
        local_tmp_dir.mkdir(parents=True, exist_ok=True)
        current_env["TMPDIR"] = str(local_tmp_dir)
    except Exception:
        # Fallback if we can't create the directory
        pass
    
    # Special handle for speculative attack p_max if in config but not env
    if 'SPECULATIVE_P_MAX' not in current_env and 'speculative_p_max' in config.get('test', {}):
        current_env['SPECULATIVE_P_MAX'] = str(config['test']['speculative_p_max'])

    # Parse LATENCY_JITTER for local jitter simulation (added to network.rs)
    # Only fallback if LATENCY_MS/JITTER_MS are not already set directly
    if 'LATENCY_JITTER' in current_env:
        try:
            parts = current_env['LATENCY_JITTER'].split()
            if len(parts) >= 1 and 'LATENCY_MS' not in current_env:
                current_env['LATENCY_MS'] = parts[0].replace('ms', '')
            if len(parts) >= 2 and 'JITTER_MS' not in current_env:
                current_env['JITTER_MS'] = parts[1].replace('ms', '')
        except Exception:
            pass

    print(f"  Command: {' '.join(cmd)}")
    
    # Run from the protocol directory
    result = subprocess.run(cmd, cwd=str(protocol_path), capture_output=True, text=True, env=current_env)
    
    asr = "N/A"
    output = result.stdout + result.stderr
    
    # Handle standardized ASR output from scripts
    if "FINAL_ASR_RESULT:" in output:
        for line in output.splitlines():
            if "FINAL_ASR_RESULT:" in line:
                asr = line.split("FINAL_ASR_RESULT:")[1].strip().replace("%", "")
                break
    elif "Attack Success Rate (ASR):" in output:
        # Format used by AlephBFT
        for line in output.splitlines():
            if "Attack Success Rate (ASR):" in line:
                # Extract XX.XX from "Attack Success Rate (ASR): XX.XX%"
                try:
                    asr = line.split("SR):")[1].strip().replace("%", "")
                except (IndexError, AttributeError):
                    pass
                break
    
    return {
        "asr": asr, 
        "success": result.returncode == 0 and asr != "N/A",
        "output": output # Sweeper might need this for logging
    }


def verify_parity(config: dict, result: dict) -> bool:
    """Check if the ASR result matches expected within tolerance."""
    expected = (config.get('output') or {}).get('expected_asr', 50.0)
    tolerance = config.get('output', {}).get('tolerance_percent', 100.0)
    
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
        if 'output' in result:
            print("\n--- TEST OUTPUT ---")
            print(result['output'])
            print("-------------------\n")
        sys.exit(1)
    
    # Local runs might not produce the same asr_result.txt format depending on the environment
    if args.local and result['asr'] == "CHECK_LOGS":
        print("\nLocal test completed. Please check the logs above for ASR results.")
        sys.exit(0)
    
    # Explicitly print ASR so sweeper can pick it up
    print(f"FINAL_ASR_RESULT: {result['asr']}%")

    # Verify parity
    if verify_parity(config, result):
        print("\n✓ PARITY VERIFIED - Ready for AWS migration")
        sys.exit(0)
    else:
        print("\n✗ PARITY FAILED - Do not migrate to AWS (Warning only)")
        # Return success anyway so Sweeper records the data
        sys.exit(0)


if __name__ == "__main__":
    main()
