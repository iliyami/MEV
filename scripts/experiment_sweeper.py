import yaml
import os
import subprocess
import itertools
import csv
import time
from datetime import datetime

# --- CONFIGURATION ---
BASE_CONFIG = "config/grand_experiment.yaml"
RESULTS_FILE = "experiment_results.csv"
REPETITIONS = 1 # Set to 5 for full paper run

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
            [0.1], [0.5], [1.0] # Low, Med, High
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
    }
}

def load_base_config():
    with open(BASE_CONFIG, 'r') as f:
        return yaml.safe_load(f)

def run_experiment(config_override, attack_mode, exp_name, rep_id):
    # 1. Prepare Configuration
    config = load_base_config()
    
    # Override values
    for k, v in config_override.items():
        config['environment'][k] = str(v)
    
    config['environment']['ATTACK_MODE'] = attack_mode
    
    # Set correct test name based on attack mode
    test_name_map = {
        "fissure": "test_fissure_attack_asr_dynamic",
        "speculative": "test_speculative_attack_asr_dynamic",
        "sluggish": "test_sluggish_attack_asr_dynamic"
    }
    config['test']['test_name'] = test_name_map[attack_mode]

    # Save temp config
    temp_config_path = f"config/temp_sweep_{exp_name}_{rep_id}.yaml"
    with open(temp_config_path, 'w') as f:
        yaml.dump(config, f)

    print(f"--> Running {exp_name} | {attack_mode} | Rep {rep_id} | {config_override}")
    
    # 2. Run Test using existing runner
    # We use --build only on the first run of the day, usually we skip it for speed if image exists
    # Here we assume image assumes fresh build not needed for EVERY param change (env vars handle it)
    cmd = ["python3", "scripts/test_runner.py", temp_config_path]
    
    start_time = time.time()
    try:
        # 100 Nodes can take up to 40-50 minutes to complete a high-repetition or high-latency run
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=3600) # 60 min timeout
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
    
    print(f"  <-- Result: ASR={asr}% (Exit: {exit_code})")

    # Cleanup
    if os.path.exists(temp_config_path):
        os.remove(temp_config_path)

    return {
        "timestamp": datetime.now().isoformat(),
        "experiment": exp_name,
        "attack_mode": attack_mode,
        "rep": rep_id,
        "asr": asr,
        "duration": duration,
        "exit_code": exit_code,
        **config_override
    }

def load_existing_results():
    if not os.path.exists(RESULTS_FILE):
        return set()
    
    results = set()
    with open(RESULTS_FILE, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Create a unique key for each run: (experiment, attack_mode, rep, params)
            # We use a stable string representation for the params
            param_keys = ["NUM_NODES", "ATTACKER_RATIO", "SPECULATIVE_P_MAX", 
                          "SLUGGISH_TIMEOUT_MULTIPLIER", "DAG_STATE_CACHED_ROUNDS", 
                          "SYNC_TIMEOUT_MS", "GC_DEPTH", "LATENCY_JITTER"]
            param_vals = tuple(row.get(pk, "") for pk in param_keys)
            key = (row['experiment'], row['attack_mode'], row['rep'], param_vals)
            results.add(key)
    return results

def main():
    # 0. Load existing progress
    existing_results = load_existing_results()
    print(f"Loaded {len(existing_results)} existing results. Resuming...")

    # Initialize CSV
    file_exists = os.path.exists(RESULTS_FILE)
    with open(RESULTS_FILE, 'a', newline='') as csvfile:
        fieldnames = ["timestamp", "experiment", "attack_mode", "rep", "asr", "duration", "exit_code", 
                      "NUM_NODES", "ATTACKER_RATIO", "SPECULATIVE_P_MAX", "SLUGGISH_TIMEOUT_MULTIPLIER",
                      "DAG_STATE_CACHED_ROUNDS", "SYNC_TIMEOUT_MS", "GC_DEPTH", "LATENCY_JITTER"]
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames, extrasaction='ignore')
        if not file_exists:
            writer.writeheader()

        # SELECT MODE VIA ENV VAR OR ARG
        target_attack = os.environ.get("ATTACK_MODE", "fissure")
        print(f"=== STARTING SWEEP FOR ATTACK: {target_attack} ===")
        
        # Determine relevant experiments
        relevant_experiments = ["scaling", "defense_memory", "defense_network", "defense_gc", "env_latency"]
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

                # Run Repetitions
                for r in range(1, REPETITIONS + 1):
                    # Check if already done
                    param_keys = ["NUM_NODES", "ATTACKER_RATIO", "SPECULATIVE_P_MAX", 
                                  "SLUGGISH_TIMEOUT_MULTIPLIER", "DAG_STATE_CACHED_ROUNDS", 
                                  "SYNC_TIMEOUT_MS", "GC_DEPTH", "LATENCY_JITTER"]
                    # Current values for lookup (defaults empty)
                    current_vals = tuple(str(override.get(pk, "")) for pk in param_keys)
                    key = (exp_name, target_attack, str(r), current_vals)
                    
                    if key in existing_results:
                        print(f"  [-] Skipping {exp_name} | {target_attack} | Rep {r} (Already recorded)")
                        continue

                    data = run_experiment(override, target_attack, exp_name, r)
                    writer.writerow(data)
                    csvfile.flush() # CRITICAL: Write to disk immediately
                    os.fsync(csvfile.fileno()) # Force OS to flush buffers

if __name__ == "__main__":
    main()
