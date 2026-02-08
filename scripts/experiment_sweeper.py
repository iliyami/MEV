import argparse
import sys
import yaml
import os
import subprocess
import itertools
import csv
import time
from datetime import datetime

# --- CONFIGURATION (DEFAULTS) ---
DEFAULT_BASE_CONFIG = "config/grand_experiment.yaml"
DEFAULT_RESULTS_FILE = "experiment_results.csv"

# --- GLOBAL FIELDNAMES ---
FIELDNAMES = [
    "timestamp", "protocol", "experiment", "attack_mode", "rep", "asr", "duration", "exit_code", 
    "NUM_NODES", "ATTACKER_RATIO", "SPECULATIVE_P_MAX", "SLUGGISH_TIMEOUT_MULTIPLIER",
    "DAG_STATE_CACHED_ROUNDS", "SYNC_TIMEOUT_MS", "GC_DEPTH", "LATENCY_JITTER",
    "HEADER_SIZE", "MAX_HEADER_DELAY", "BATCH_SIZE", "MAX_BATCH_DELAY", "NUM_WORKERS",
    "WAVE_LENGTH", "NUMBER_OF_LEADERS", "SPECULATIVE_STRATEGY",
    "EXCLUSION_PROBABILITY", "HYBRID_EXCLUSION", "SLUGGISH_MULTIPLIER", "VICTIM_RATIO"
]

# Keys that define the experiment's unique configuration (for deduplication)
# Excludes metadata like timestamp, asr, etc.
PARAM_KEYS = [k for k in FIELDNAMES if k not in ["timestamp", "protocol", "experiment", "attack_mode", "rep", "asr", "duration", "exit_code"]]

# Define the Experiment Matrix
# Each key acts as a "dimension" we can sweep over independently.
# When sweeping one dimension, others stay at their default (index 0).

EXPERIMENTS = {
    # 1. Global Scaling
    "scaling": {
        "params": ["NUM_NODES"],
        "values": [
            [13], [25], [50], [100]
        ]
    },
    
    # 2. Attack Power (Offense) - Context dependent
    "offense_fissure": {
        "params": ["ATTACKER_RATIO"],
        "values": [
            [0.1], [0.2], [0.33] # Low, Med, High
        ]
    },
    "offense_speculative": {
        "params": ["SPECULATIVE_P_MAX"],
        "values": [
            [5], [20], [50] # Low, Med, High (Brute force candidate count)
        ]
    },
    "offense_sluggish": {
        "params": ["SLUGGISH_TIMEOUT_MULTIPLIER"],
        "values": [
            [1.5], [2.0], [5.0] # Low, Med, High
        ]
    },

    # 3. Defense - Protocol Memory
    "defense_memory": {
        "params": ["DAG_STATE_CACHED_ROUNDS"],
        "values": [
            [1], [2], [5], [20] # Lower values (1, 2) are more critical
        ]
    },
    
    # 4. Defense - Network Patience
    "defense_network": {
        "params": ["SYNC_TIMEOUT_MS"],
        "values": [
            [500], [2000], [5000]
        ]
    },
    
     # 5. Defense - Garbage Collection
    "defense_gc": {
        "params": ["GC_DEPTH"],
        "values": [
            [5], [10], [50]
        ]
    },

    # 6. Environment - Network Jitter/Latency
    "env_latency": {
        "params": ["LATENCY_JITTER"],
        "values": [
            ["50ms 10ms"], ["150ms 30ms"], ["300ms 50ms"] # Low(WAN), Med(Cross-C), High(Global)
        ]
    },

    # 7. Protocol Specific - Narwhal Header Optimization
    "defense_header": {
        "params": ["HEADER_SIZE", "MAX_HEADER_DELAY"],
        "values": [
            [500, 100], [1000, 200], [2000, 500]
        ]
    },

    # 8. Protocol Specific - Narwhal Batching Optimization
    "defense_batching": {
        "params": ["BATCH_SIZE", "MAX_BATCH_DELAY"],
        "values": [
            [250000, 100], [500000, 200], [1000000, 500]
        ]
    },

    # 9. Protocol Specific - Narwhal Worker Scaling
    "scaling_workers": {
        "params": ["NUM_WORKERS"],
        "values": [
            [1], [2], [4], [8]
        ]
    },

    # 10. Protocol Specific - Mahi-Mahi (Mysticeti) Wave Length
    "mahimahi_wave": {
        "params": ["WAVE_LENGTH"],
        "values": [
            [3], [5], [8], [12]
        ]
    },

    # 11. Protocol Specific - Mahi-Mahi (Mysticeti) Leaders Count
    "mahimahi_leaders": {
        "params": ["NUMBER_OF_LEADERS"],
        "values": [
            [2], [4], [6], [8]
        ]
    },

    # 12. Protocol Specific - Mahi-Mahi (Mysticeti) Speculative Strategy
    "mahimahi_strategy": {
        "params": ["SPECULATIVE_STRATEGY"],
        "values": [
            ["simple"], ["sophisticated"], ["traversal"], ["smart"], ["hybrid"]
        ]
    }
}

def load_base_config(config_path):
    with open(config_path, 'r') as f:
        return yaml.safe_load(f)

def run_experiment(config_override, attack_mode, exp_name, rep_id, base_config_path, local_mode=False, no_build=False):
    # 0. Create logs directory in /tmp where we have permissions
    log_dir = "/tmp/mev_logs"
    os.makedirs(log_dir, exist_ok=True)
    log_file = f"{log_dir}/{attack_mode}_{exp_name}_rep{rep_id}_{int(time.time())}.log"

    # 1. Prepare Configuration
    config = load_base_config(base_config_path)
    
    # Override values
    for k, v in config_override.items():
        config['environment'][k] = str(v)
    
    config['environment']['ATTACK_MODE'] = attack_mode
    num_nodes = int(config_override.get('NUM_NODES', config['environment'].get('NUM_NODES', 13)))
    if num_nodes >= 50:
        config['environment']['DURATION'] = "300" 
        config['environment']['LEADER_TIMEOUT'] = "5000"
    if num_nodes >= 100:
        config['environment']['DURATION'] = "600" # 10 minutes
        config['environment']['LEADER_TIMEOUT'] = "10000" # 10 seconds
    
    if no_build:
        config['environment']['NO_BUILD'] = "1"
    
    # Set correct test name based on attack mode
    if config['protocol']['name'] in ['bullshark', 'narwhal']:
        test_name_map = {
            "fissure": "test_fissure_attack_asr_dynamic",
            "speculative": "test_speculative_attack_asr_dynamic",
            "sluggish": "test_sluggish_attack_asr_dynamic"
        }
        config['test']['test_name'] = test_name_map.get(attack_mode, config['test'].get('test_name'))
    else:
        # For other protocols (mahimahi, etc.), use the default name from config or fallback
        # The internal scripts in their Docker images handle the ATTACK_MODE branches.
        config['test']['test_name'] = config.get('test', {}).get('test_name', f"test_{config['protocol']['name']}_attack")

    # Save temp config with attack_mode to avoid collisions in multi-terminal runs
    temp_config_path = f"config/temp_sweep_{attack_mode}_{exp_name}_{rep_id}.yaml"
    with open(temp_config_path, 'w') as f:
        yaml.dump(config, f)

    print(f"--> Running {exp_name} | {attack_mode} | Rep {rep_id} | {config_override}")
    
    # 2. Run Test using existing runner
    cmd = [sys.executable, "scripts/test_runner.py", temp_config_path]
    if local_mode:
        cmd.append("--local")
    
    start_time = time.time()
    try:
        # 100 Nodes Sluggish can take > 60 minutes
        num_nodes = int(config['environment'].get('NUM_NODES', 0))
        timeout = 7200 if (attack_mode == "sluggish" and num_nodes >= 50) else 3600
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        output = result.stdout + result.stderr
        exit_code = result.returncode
    except subprocess.TimeoutExpired as e:
        print(f"  !!! TIMEOUT after {e.timeout}s !!!")
        output = (e.stdout.decode() if e.stdout else "") + (e.stderr.decode() if e.stderr else "")
        exit_code = -124 # Standard timeout exit code
    duration = time.time() - start_time

    # 3. Parse ASR
    asr = "N/A"
    if "FINAL_ASR_RESULT:" in output:
        for line in output.splitlines():
            if "FINAL_ASR_RESULT:" in line:
                asr = line.split("FINAL_ASR_RESULT:")[1].strip().replace("%", "")
                break
    
    # Save log for debugging
    with open(log_file, "w") as f:
        f.write(output)

    if asr == "N/A":
        print(f"  <-- !!! FAILED: ASR={asr}% (Exit: {exit_code}) | Log: {log_file}")
        # Print a snippet of the error (last 10 lines)
        error_snippet = "\n".join(output.splitlines()[-15:])
        print(f"      [Last 15 lines of log]:\n{error_snippet}")
    else:
        print(f"  <-- Result: ASR={asr}% (Exit: {exit_code})")

    # Cleanup
    if os.path.exists(temp_config_path):
        os.remove(temp_config_path)

    return {
        "timestamp": datetime.now().isoformat(),
        "protocol": config['protocol']['name'],
        "experiment": exp_name,
        "attack_mode": attack_mode,
        "rep": rep_id,
        "asr": asr,
        "duration": duration,
        "exit_code": exit_code,
        **config_override
    }

def load_existing_results(results_file):
    if not os.path.exists(results_file):
        return set()
    
    results = set()
    with open(results_file, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Create a unique key for each run: (protocol, experiment, attack_mode, rep, params)
            # Standardize param values to strings and handle empty/missing columns
            param_vals = []
            for pk in PARAM_KEYS:
                val = row.get(pk, "")
                if val is None or val == "None": val = ""
                param_vals.append(str(val))
            param_vals = tuple(param_vals)

            # ONLY skip if we actually got a valid ASR result (0.0 is often a simulation failure)
            asr_val = row.get('asr', "N/A")
            if asr_val not in [None, "N/A", "", "0.0", "0.00", "0%"]:
                key = (row['protocol'], row['experiment'], row['attack_mode'], str(row['rep']), param_vals)
                results.add(key)
    return results

def deduplicate_results(results_file):
    """Reads the results file and keeps only the latest entry for each unique experiment key."""
    if not os.path.exists(results_file):
        return
    
    unique_results = {}
    fieldnames = []
    
    with open(results_file, 'r') as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        if not fieldnames or 'protocol' not in fieldnames:
             return # Let main handle migration or new header
             
        for row in reader:
            # Standardize param values
            param_vals = []
            for pk in PARAM_KEYS:
                val = row.get(pk, "")
                if val is None or val == "None": val = ""
                param_vals.append(str(val))
            param_vals = tuple(param_vals)
            
            key = (row['protocol'], row['experiment'], row['attack_mode'], str(row['rep']), param_vals)
            
            # Keep the latest entry, but prioritize successful ones over N/A/0.0
            asr_val = row.get('asr', "N/A")
            is_valid = asr_val not in [None, "N/A", "", "0.0", "0.00", "0%"]
            
            if is_valid:
                if key not in unique_results or unique_results[key].get('asr') in [None, "N/A", "", "0.0", "0.00", "0%"]:
                    unique_results[key] = row
            # If not valid, only keep if we don't have anything better (allows seeing failure but won't block re-runs)
            elif key not in unique_results:
                 unique_results[key] = row

    with open(results_file, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES, extrasaction='ignore')
        writer.writeheader()
        for row in unique_results.values():
            # Clean row of any keys not in FIELDNAMES (fixes "None" key issues)
            clean_row = {k: v for k, v in row.items() if k in FIELDNAMES}
            writer.writerow(clean_row)
    
    print(f"Deduplicated {results_file}: Kept {len(unique_results)} unique entries.")

def main():
    parser = argparse.ArgumentParser(description="Multi-Attack Parameter Sweeper")
    parser.add_argument("--config", default=DEFAULT_BASE_CONFIG, help="Base YAML config (default: grand_experiment.yaml)")
    parser.add_argument("--experiments", help="Comma-separated list of experiments to run (e.g. scaling,offense_speculative)")
    parser.add_argument("--local", action="store_true", help="Run tests locally via cargo instead of Docker")
    parser.add_argument("--out", default=DEFAULT_RESULTS_FILE, help=f"Output CSV file for results (default: {DEFAULT_RESULTS_FILE})")
    parser.add_argument("--no-build", action="store_true", help="Skip building binary inside Docker (use existing)")
    args = parser.parse_args()

    results_file = args.out

    # 0. Clean up and load existing progress
    deduplicate_results(results_file)
    existing_results = load_existing_results(results_file)
    print(f"Loaded {len(existing_results)} existing results. Resuming...")

    # Determine Repetitions from config
    config = load_base_config(args.config)
    repetitions = int(config.get('test', {}).get('REPETITIONS', 1))

    # Initialize CSV
    file_exists = os.path.exists(results_file)
    target_protocol = config['protocol']['name']
    with open(results_file, 'a', newline='') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=FIELDNAMES, extrasaction='ignore')
        if not file_exists:
            writer.writeheader()

        # SELECT MODE VIA ENV VAR
        target_attack = os.environ.get("ATTACK_MODE", "fissure")
        print(f"=== STARTING SWEEP FOR ATTACK: {target_attack} ===")
        
        # Determine relevant experiments
        if args.experiments:
            relevant_experiments = [e.strip() for e in args.experiments.split(",")]
        else:
            # 1. Common Experiments (All Protocols)
            relevant_experiments = [
                "scaling", "env_latency"
            ]
            
            # 2. Protocol-Specific Experiments
            if target_protocol in ['bullshark', 'narwhal', 'tusk']:
                relevant_experiments.extend([
                    "defense_memory",   # DAG_STATE_CACHED_ROUNDS
                    "defense_network",  # SYNC_TIMEOUT_MS
                    "defense_gc",       # GC_DEPTH
                    "defense_header",   # HEADER_SIZE, MAX_HEADER_DELAY
                    "defense_batching", # BATCH_SIZE, MAX_BATCH_DELAY
                    "scaling_workers"   # NUM_WORKERS
                ])
            elif target_protocol == "mahimahi":
                relevant_experiments.extend([
                    "mahimahi_wave",    # WAVE_LENGTH
                    "mahimahi_leaders", # NUMBER_OF_LEADERS
                    "mahimahi_strategy" # SPECULATIVE_STRATEGY
                ])
            
            # 3. Attack-Specific Experiments
            if target_attack == "fissure":
                relevant_experiments.append("offense_fissure")
            elif target_attack == "speculative":
                relevant_experiments.append("offense_speculative")
            elif target_attack == "sluggish":
                relevant_experiments.append("offense_sluggish")

        for exp_name in relevant_experiments:
            if exp_name not in EXPERIMENTS: continue
            exp_config = EXPERIMENTS[exp_name]
            params = exp_config["params"]
            value_sets = exp_config["values"]

            for values in value_sets:
                # Construct override dict
                override = {}
                for i, param in enumerate(params):
                    override[param] = values[i]

                # Skip 100 nodes for sluggish attack to save time
                if target_attack == "sluggish" and override.get("NUM_NODES", 0) > 50:
                    print(f"  [-] Skipping {exp_name} | {target_attack} | {override['NUM_NODES']} nodes (Capped at 50)")
                    continue

                # Run Repetitions
                for r in range(1, repetitions + 1):
                    # Check if already done
                    
                    # Construct full parameter state (MATCHING CSV FORMAT)
                    # We only include the override values because non-overridden values are written as empty strings to the CSV
                    current_vals = []
                    for pk in PARAM_KEYS:
                        # Only use the override. If not in override, it will be an empty string in the CSV.
                        val = override.get(pk, "")
                        if val is None or val == "None": val = ""
                        current_vals.append(str(val))
                    current_vals = tuple(current_vals)
                    
                    key = (target_protocol, exp_name, target_attack, str(r), current_vals)
                    
                    if key in existing_results:
                        print(f"  [-] Skipping {exp_name} | {target_attack} | Rep {r} (Already recorded for {target_protocol})")
                        continue

                    data = run_experiment(override, target_attack, exp_name, r, args.config, local_mode=args.local, no_build=args.no_build)
                    
                    # ONLY record if we got a non-zero ASR (0.0 usually means simulation liveness failure)
                    asr_result = str(data.get('asr', '0.0'))
                    if asr_result not in ["N/A", "0.0", "0.00", "0", "0%"]:
                        writer.writerow(data)
                        csvfile.flush() # CRITICAL: Write to disk immediately
                        os.fsync(csvfile.fileno()) # Force OS to flush buffers
                    else:
                        print(f"  [!] Not recording result with ASR={asr_result}% (Likely simulation failure)")

                    # Wait 10s between repetitions to allow Docker/OS cleanup (Mahi-Mahi only)
                    if "mahi" in target_protocol.lower():
                        print("  [Sweeper] Cooling down 10s for Mahi-Mahi cleanup...")
                        try:
                            # NUCLEAR OPTION: Force cleanup of any stuck containers on the host
                            subprocess.run("docker rm -f $(docker ps -aq)", shell=True, stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
                        except Exception:
                            pass
                        time.sleep(10)

if __name__ == "__main__":
    main()
