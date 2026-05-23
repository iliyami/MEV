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
import json
import os
import re
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
BUILD_CACHE_DIR = BASE_DIR / ".build-cache"


def get_docker_resource_limits() -> tuple[float | None, int | None]:
    """Best-effort discovery of Docker daemon CPU/memory limits."""
    try:
        result = subprocess.run(
            ["docker", "info", "--format", "{{.NCPU}} {{.MemTotal}}"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None, None

    if result.returncode != 0:
        return None, None

    parts = result.stdout.strip().split()
    if len(parts) != 2:
        return None, None

    try:
        cpus = float(parts[0])
    except ValueError:
        cpus = None

    try:
        memory_bytes = int(parts[1])
    except ValueError:
        memory_bytes = None

    return cpus, memory_bytes


def parse_memory_limit(value: str) -> int | None:
    match = re.fullmatch(r"\s*([0-9]+(?:\.[0-9]+)?)\s*([bkmgBKMG]?)\s*", value)
    if not match:
        return None

    amount = float(match.group(1))
    unit = match.group(2).lower()
    multiplier = {
        "": 1,
        "b": 1,
        "k": 1024,
        "m": 1024 ** 2,
        "g": 1024 ** 3,
    }[unit]
    return int(amount * multiplier)


def format_memory_limit(memory_bytes: int) -> str:
    mebibytes = max(1, memory_bytes // (1024 ** 2))
    return f"{mebibytes}m"


def load_config(config_path: str) -> dict:
    """Load experiment configuration from YAML file."""
    with open(config_path, 'r') as f:
        return yaml.safe_load(f)


def extract_final_json_marker(output: str, marker: str) -> dict:
    matches = [
        line.split(marker, 1)[1].strip()
        for line in output.splitlines()
        if marker in line
    ]
    if not matches:
        return {}
    try:
        return json.loads(matches[-1])
    except json.JSONDecodeError:
        return {}


def load_result_output(results_mount: Path) -> str:
    parts = []
    for filename in ("test_output.log", "asr_output.log"):
        path = results_mount / filename
        if path.exists():
            parts.append(path.read_text(errors="replace"))
    return "\n".join(parts)


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
    
    env = os.environ.copy()
    # Allow environment to override, default to 0 for maximum compatibility on CloudLab
    env["DOCKER_BUILDKIT"] = os.environ.get("DOCKER_BUILDKIT", "1")
    
    cmd = [
        "docker", "build",
        "-t", tag,
        "-f", str(dockerfile_path),
    ]
    if env["DOCKER_BUILDKIT"] != "0":
        cmd.append("--progress=plain")
    cmd.append(str(protocol_path))
    
    print(f"  Command: {' '.join(cmd)}")
    
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
    BUILD_CACHE_DIR.mkdir(exist_ok=True)
    target_cache_mount = BUILD_CACHE_DIR / f"{config['protocol']['name']}-target"
    target_cache_mount.mkdir(exist_ok=True)
    
    print(f"\nRunning attack test: {test_name}")
    print(f"  Image: {tag}")
    print(f"  Attack Mode: {env_vars.get('ATTACK_MODE', 'unknown')}")

    available_cpus, available_memory = get_docker_resource_limits()
    
    # Delete stale result file if it exists
    asr_file = results_mount / "asr_result.txt"
    if asr_file.exists():
        asr_file.unlink()
    for stale_name in ("test_output.log", "asr_output.log"):
        stale_path = results_mount / stale_name
        if stale_path.exists():
            stale_path.unlink()
    
    # Build docker run command
    protocol_path = CODE_DIR / config['protocol']['path']
    cmd = [
        "docker", "run", "--rm",
        "--cap-add=NET_ADMIN", # Enable Traffic Control (tc)
        "-v", f"{results_mount}:/app/results",
        "-e", f"TEST_NAME={test_name}",
        "--label", "mev.runner=test_runner",
        "--label", f"mev.protocol={config['protocol']['name']}",
        "--label", f"mev.experiment={config['experiment']['name']}",
    ]

    if config['protocol']['name'] != "autobahn":
        cmd.extend(["-v", f"{target_cache_mount}:/app/target"])

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
        # Default mounts for Mysticeti/Mahi-Mahi
        script_mounts = [
            ("automated_fissure_attack.sh", "/app/automated_fissure_attack.sh"),
            ("automated_speculative_attack.sh", "/app/automated_speculative_attack.sh"),
            ("automated_sluggish_attack.sh", "/app/automated_sluggish_attack.sh"),
            ("automated_baseline.sh", "/app/automated_baseline.sh"),
            ("benchmark/benchmark/local.py", "/app/benchmark/benchmark/local.py"),
            ("scripts/legacy_automation/automated_fissure_attack.sh", "/app/scripts/legacy_automation/automated_fissure_attack.sh"),
            ("scripts/legacy_automation/automated_speculative_attack.sh", "/app/scripts/legacy_automation/automated_speculative_attack.sh"),
            ("scripts/legacy_automation/automated_sluggish_attack.sh", "/app/scripts/legacy_automation/automated_sluggish_attack.sh"),
            ("scripts/calculate-fissure-asr.py", "/app/scripts/calculate-fissure-asr.py"),
            ("scripts/calculate-sluggish-asr.py", "/app/scripts/calculate-sluggish-asr.py"),
            ("scripts/calculate-speculative-asr.py", "/app/scripts/calculate-speculative-asr.py"),
            ("docker/mev-test/run_attack_test.sh", "/app/docker/mev-test/run_attack_test.sh"),
        ]

    for local_rel, container_path in script_mounts:
        local_full = protocol_path / local_rel
        if local_full.exists():
            cmd.extend(["-v", f"{local_full}:{container_path}"])
        else:
            print(f"  Warning: Skipping mount for non-existent file: {local_rel}")
    
    # Add environment variables
    for key, value in env_vars.items():
        cmd.extend(["-e", f"{key}={value}"])
    
    # Add resource limits
    if 'cpus' in config['docker']:
        requested_cpus = float(config['docker']['cpus'])
        effective_cpus = requested_cpus
        if available_cpus is not None and requested_cpus > available_cpus:
            effective_cpus = available_cpus
            print(f"  Capping CPUs from {requested_cpus:g} to {effective_cpus:g} (Docker limit)")
        cmd.extend(["--cpus", f"{effective_cpus:g}"])
    if 'memory' in config['docker']:
        requested_memory = parse_memory_limit(str(config['docker']['memory']))
        effective_memory = requested_memory
        if (
            requested_memory is not None
            and available_memory is not None
            and requested_memory > available_memory
        ):
            effective_memory = available_memory
            print(
                f"  Capping memory from {config['docker']['memory']} to {format_memory_limit(effective_memory)} (Docker limit)"
            )

        if effective_memory is not None:
            cmd.extend(["--memory", format_memory_limit(effective_memory)])
        else:
            cmd.extend(["--memory", str(config['docker']['memory'])])
    
    cmd.append(tag)
    
    # Add protocol-specific command to override Dockerfile CMD
    if config['protocol']['name'] == "mysticeti":
        cmd.extend(["bash", "/app/docker/mev-test/run_attack_test.sh"])
    elif config['protocol']['name'] in ["alephbft", "autobahn"]:
        cmd.extend(["bash", "/app/run_attack_test.sh"])
    
    print(f"  Command: {' '.join(cmd[:10])}...")
    
    result = subprocess.run(cmd, capture_output=False)
    
    # Parse results
    asr_file = results_mount / "asr_result.txt"
    combined_output = load_result_output(results_mount)
    if asr_file.exists():
        with open(asr_file, 'r') as f:
            content = f.read()
            if "FINAL_ASR=" in content:
                asr_value = content.split("=")[1].strip()
                if asr_value == "UNKNOWN":
                    return {"asr": "UNKNOWN", "success": False, "output": combined_output}
                return {
                    "asr": asr_value,
                    "success": True,
                    "output": combined_output,
                    "backrun_stats": extract_final_json_marker(combined_output, "FINAL_BACKRUN_STATS:"),
                    "sandwich_stats": extract_final_json_marker(combined_output, "FINAL_SANDWICH_STATS:"),
                }

    asr = extract_final_asr(combined_output)
    if asr != "N/A":
        return {
            "asr": asr,
            "success": result.returncode == 0,
            "output": combined_output,
            "backrun_stats": extract_final_json_marker(combined_output, "FINAL_BACKRUN_STATS:"),
            "sandwich_stats": extract_final_json_marker(combined_output, "FINAL_SANDWICH_STATS:"),
        }

    return {"asr": "UNKNOWN", "success": False, "output": combined_output}


def extract_final_asr(output: str) -> str:
    matches = [line.split("FINAL_ASR_RESULT:", 1)[1].strip() for line in output.splitlines() if "FINAL_ASR_RESULT:" in line]
    if matches:
        return matches[-1].rstrip("%").strip()

    for line in output.splitlines():
        if "Attack Success Rate (ASR):" in line:
            try:
                return line.split("SR):", 1)[1].strip().rstrip("%")
            except (IndexError, AttributeError):
                continue
    return "N/A"


def run_local_test(config: dict) -> dict:
    """Run the attack test locally with cargo test."""
    env_vars = config['environment']
    protocol_name = config['protocol']['name']
    attack_mode = env_vars.get('ATTACK_MODE', 'fissure')

    dynamic_test_names = {
        "bullshark": {
            "fissure": "test_fissure_attack_asr_dynamic",
            "speculative": "test_speculative_attack_asr_dynamic",
            "sluggish": "test_sluggish_attack_asr_dynamic",
            "baseline": "test_baseline_13_nodes_no_attack",
        },
        "alephbft": {
            "fissure": "test_fissure_attack_asr_13_nodes",
            "speculative": "test_speculative_attack_asr_13_nodes",
            "sluggish": "test_sluggish_attack_asr_13_nodes",
            "baseline": "test_baseline_asr_13_nodes_no_attack",
        },
        "mysticeti": {
            "fissure": "test_fissure_attack_asr_13_nodes",
            "speculative": "test_speculative_attack_asr_13_nodes",
            "sluggish": "test_sluggish_attack_asr_13_nodes",
            "baseline": "test_baseline_asr_13_nodes",
        },
    }

    test_name = dynamic_test_names.get(protocol_name, {}).get(
        attack_mode,
        config['test'].get('test_name', config['experiment']['name']),
    )
    
    # Path to bullshark code
    protocol_path = CODE_DIR / config['protocol']['path']
    
    print(f"\nRunning local attack test: {test_name}")
    print(f"  Attack Mode: {attack_mode}")
    print(f"  CWD: {protocol_path}")
    
    # Determine if we should use cargo test or a script
    is_script = protocol_path.name == "mahi-mahi-consensus" or config['protocol'].get('use_scripts', False)
    
    if is_script:
        script_path = f"./scripts/legacy_automation/automated_{attack_mode}_attack.sh"
        cmd = ["bash", script_path]
    else:
        if protocol_name == "alephbft":
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
    
    output = result.stdout + result.stderr
    asr = extract_final_asr(output)
    
    return {
        "asr": asr, 
        "success": result.returncode == 0 and asr != "N/A",
        "output": output, # Sweeper might need this for logging
        "backrun_stats": extract_final_json_marker(output, "FINAL_BACKRUN_STATS:"),
        "sandwich_stats": extract_final_json_marker(output, "FINAL_SANDWICH_STATS:"),
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
    
    # v2 harness: when V2_VERBOSE_OUTPUT=1 is exported (set by BullsharkLauncher),
    # forward the full captured cargo/Docker stdout so the launcher's parent
    # process can grep for v2-emitted info!() markers (V2_VICTIM_PROFIT,
    # "v2 coordinator assigned policy", etc.). Paper-1 behavior (suppressed
    # output on success) is preserved when the env var is unset.
    if os.environ.get("V2_VERBOSE_OUTPUT") == "1" and result.get("output"):
        print("--- V2 VERBOSE TEST OUTPUT ---")
        print(result["output"])
        print("--- /V2 VERBOSE TEST OUTPUT ---")

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
    if result.get("backrun_stats"):
        print(f"FINAL_BACKRUN_STATS: {json.dumps(result['backrun_stats'], sort_keys=True)}")
    if result.get("sandwich_stats"):
        print(f"FINAL_SANDWICH_STATS: {json.dumps(result['sandwich_stats'], sort_keys=True)}")

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
