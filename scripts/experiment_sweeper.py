import argparse
import sys
import os
import json

# Robust YAML import to avoid shadowing by local folders or broken venv
def _get_working_yaml():
    # Try current directory first (where we restored the working copy)
    root_dir = os.getcwd()
    if os.path.isdir(os.path.join(root_dir, 'yaml')):
        if root_dir not in sys.path:
            sys.path.insert(0, root_dir)
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
    "timestamp", "protocol", "experiment", "attack_mode", "attack_type", "rep", "asr", "asr_l1", "asr_l2", "asr_histogram", "duration", "exit_code", 
    "NUM_NODES", "ATTACKER_RATIO", "ATTACKER_ID", "FRONT_ATTACKER_ID", "BACK_ATTACKER_ID", "VICTIM_ID", "SPECULATIVE_P_MAX", "SLUGGISH_TIMEOUT_MULTIPLIER", "SLUGGISH_MULTIPLIER",
    "DAG_STATE_CACHED_ROUNDS", "SYNC_TIMEOUT_MS", "GC_DEPTH", "LATENCY_JITTER", "LATENCY_MS", "JITTER_MS",
    "HEADER_SIZE", "MAX_HEADER_DELAY", "BATCH_SIZE", "MAX_BATCH_DELAY", "NUM_WORKERS",
    "WAVE_LENGTH", "NUMBER_OF_LEADERS", "SPECULATIVE_STRATEGY", "EXCLUSION_PROBABILITY", "HYBRID_EXCLUSION", 
    "SIMPLE_EXCLUSION_PROB", "VICTIM_RATIO", "VICTIM_COUNT", "ATTACK_TYPE", "SANDWICH_METRIC_MODE", "ALEPH_ELECTION_LOOKAHEAD", "ALEPH_COORD_REQUEST_DELAY_MS", "ALEPH_HASH_SORT_SEED",
    "AUTOBAHN_K", "AUTOBAHN_FAST_PATH_TIMEOUT", "AUTOBAHN_USE_FAST_PATH"
]

# Keys that define the experiment's unique configuration (for deduplication)
# Excludes metadata like timestamp, asr, etc.
PARAM_KEYS = [
    k
    for k in FIELDNAMES
    if k
    not in [
        "timestamp",
        "protocol",
        "experiment",
        "attack_mode",
        "attack_type",
        "rep",
        "asr",
        "asr_l1",
        "asr_l2",
        "asr_histogram",
        "duration",
        "exit_code",
    ]
]

INVALID_ASR_VALUES = {"", "N/A"}


def is_success_exit_code(value):
    try:
        return int(value) == 0
    except (TypeError, ValueError):
        return False


def is_recordable_result(asr_value, exit_code):
    return is_valid_asr(asr_value) and is_success_exit_code(exit_code)

# Define the Experiment Matrix
# Each key acts as a "dimension" we can sweep over independently.
# When sweeping one dimension, others stay at their default (index 0).

EXPERIMENTS = {
    "simple": {
        "params": ["NUM_NODES"],
        "values": [[13]]
    },
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

    "env_geodist": {
        "params": ["LATENCY_MS", "JITTER_MS"],
        "values": [
            [50, 5], [100, 10], [200, 20], [500, 50] # Latency sweeps with 10% jitter
        ]
    },

    # 7. Attack Strength - Exclusion Intensity
    "offense_exclusion": {
        "params": ["EXCLUSION_PROBABILITY"],
        "values": [
            [0.1], [0.3], [0.5], [0.75], [0.9]
        ]
    },

    # 8. Attack Strategy - Speculative Behavior
    "mysticeti_strategy": {
        "params": ["SPECULATIVE_STRATEGY"],
        "values": [
            ["simple"], ["smart"], ["aggressive"]
        ]
    },

    # 9. Protocol Specific - Narwhal Header Optimization
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
    },

    # 13. Protocol Specific - Mysticeti Leader Timeout
    "mysticeti_timeout": {
        "params": ["LEADER_TIMEOUT_MS"],
        "values": [
            [500], [1000], [2000], [5000], [10000]
        ]
    },

    # 14. Attack Power - Certification Race
    "offense_certification_race": {
        "params": ["ATTACKER_RATIO"],
        "values": [
            [0.1], [0.2], [0.33]
        ]
    },
    
    # 15. AlephBFT Specific - Election Lookahead (Stability)
    "aleph_lookahead": {
        "params": ["ALEPH_ELECTION_LOOKAHEAD"],
        "values": [
            [2], [3], [5], [8]
        ]
    },

    # 16. AlephBFT Specific - Coordination Request Delay (Sync Speed)
    "aleph_sync_speed": {
        "params": ["ALEPH_COORD_REQUEST_DELAY_MS"],
        "values": [
            [50], [200], [1000]
        ]
    },

    # 17. AlephBFT Specific - Hash Sort Randomization (Speculative Resistance)
    "aleph_hash_randomization": {
        "params": ["ALEPH_HASH_SORT_SEED"],
        "values": [
            [0], [123], [456]
        ]
    },
    # 18. Autobahn Specific - K (Concurrency vs Security)
    "autobahn_k": {
        "params": ["AUTOBAHN_K"],
        "values": [
            [1], [2], [4], [8], [16]
        ]
    },
    # 19. Autobahn Specific - Fast Path Sensitivity
    "autobahn_fast_path": {
        "params": ["AUTOBAHN_FAST_PATH_TIMEOUT"],
        "values": [
            [50], [200], [500], [1000]
        ]
    }
}

def load_base_config(config_path):
    with open(config_path, 'r') as f:
        return yaml.safe_load(f)


def normalize_param_value(value):
    if value is None or value == "None":
        return ""
    return str(value)


def is_valid_asr(asr):
    if asr is None:
        return False
    return normalize_param_value(asr) not in INVALID_ASR_VALUES


def build_result_key(protocol, experiment, attack_mode, rep, params):
    param_vals = tuple(normalize_param_value(params.get(pk, "")) for pk in PARAM_KEYS)
    return (protocol, experiment, attack_mode, str(rep), param_vals)


def materialize_sweep_override(base_config, override, target_protocol, target_attack):
    realized = {k: normalize_param_value(v) for k, v in override.items()}
    base_env = base_config.get('environment', {})
    num_nodes = int(realized.get('NUM_NODES', base_env.get('NUM_NODES', 13)))

    if target_attack == "speculative" and "SPECULATIVE_P_MAX" not in realized:
        if target_protocol == "narwhal" and num_nodes >= 25:
            realized["SPECULATIVE_P_MAX"] = "100"
        else:
            # Verified on CloudLab that 50 hashes execute in <1ms, so this is
            # a safe default for the untuned speculative baseline.
            realized["SPECULATIVE_P_MAX"] = "50"

    return realized


def compute_outer_timeout(config, attack_mode, local_mode):
    num_nodes = int(config['environment'].get('NUM_NODES', 0))
    num_workers = int(config['environment'].get('NUM_WORKERS', 1))
    duration = int(config['environment'].get('DURATION', 120))

    if local_mode:
        return 10000 if (attack_mode == "sluggish" and num_nodes >= 50) else 7200

    if config['protocol']['name'] == 'narwhal' and num_nodes >= 25:
        process_count = num_nodes * (2 * num_workers + 1)
        startup_buffer = 45 + num_nodes + (num_workers * 2)
        scale_buffer = 0
        if num_nodes >= 100:
            scale_buffer = process_count + 480
        elif num_nodes >= 50:
            scale_buffer = process_count + 240
        else:
            scale_buffer = (process_count // 3) + 120
        fab_timeout = duration + startup_buffer + scale_buffer
        return fab_timeout + 300

    return 10000 if (attack_mode == "sluggish" and num_nodes >= 50) else 7200


def decode_timeout_stream(stream):
    if not stream:
        return ""
    if isinstance(stream, bytes):
        return stream.decode()
    return stream


def extract_final_asr(output):
    matches = [line.split("FINAL_ASR_RESULT:", 1)[1].strip() for line in output.splitlines() if "FINAL_ASR_RESULT:" in line]
    if not matches:
        return "N/A"
    return matches[-1].rstrip("%").strip()


def extract_final_json_marker(output, marker):
    import json

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


def cleanup_protocol_containers(config, reason=None):
    tag = config.get('docker', {}).get('tag')
    if not tag:
        return

    container_ids = []
    queries = [
        ["docker", "ps", "-aq", "--filter", "label=mev.runner=test_runner", "--filter", f"ancestor={tag}"],
        ["docker", "ps", "-aq", "--filter", f"ancestor={tag}"],
    ]
    for query in queries:
        try:
            listed = subprocess.run(query, capture_output=True, text=True, check=False)
        except (FileNotFoundError, subprocess.SubprocessError):
            return
        container_ids = [line.strip() for line in listed.stdout.splitlines() if line.strip()]
        if container_ids:
            break

    if not container_ids:
        return

    detail = f" ({reason})" if reason else ""
    print(f"  [Sweeper] Removing {len(container_ids)} stale {tag} container(s){detail}...")
    subprocess.run(
        ["docker", "rm", "-f", *container_ids],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )

def run_experiment(config_override, attack_mode, exp_name, rep_id, base_config_path, local_mode=False, no_build=False, dry_run=False):
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
    config['environment']['ATTACK_TYPE'] = str(config_override.get("ATTACK_TYPE", os.environ.get("ATTACK_TYPE", "frontrun")))
    num_nodes = int(config_override.get('NUM_NODES', config['environment'].get('NUM_NODES', 13)))
    duration = int(config['environment'].get('DURATION', 120))
    # STOCHASTIC DURATION: Add 0-20s jitter to break block-count determinism
    import random
    jitter_secs = random.randint(0, 20)
    config['environment']['DURATION'] = str(duration + jitter_secs)
    print(f"  [Stochastic] Duration jitter: +{jitter_secs}s (Total: {duration + jitter_secs}s)")

    if num_nodes >= 50:
        config['environment']['DURATION'] = "300" 
        config['environment']['LEADER_TIMEOUT'] = "5000"
    if num_nodes >= 100:
        config['environment']['DURATION'] = "600" # 10 minutes
        config['environment']['LEADER_TIMEOUT'] = "10000" # 10 seconds
    
    if no_build:
        config['environment']['NO_BUILD'] = "1"

    # Narwhal speculative runs need paper-aligned victim/worker defaults and
    # longer observation windows once the committee reaches 25 nodes.
    if config['protocol']['name'] == 'narwhal' and attack_mode == 'speculative':
        if 'NUM_WORKERS' not in config_override:
            config['environment']['NUM_WORKERS'] = "2" if num_nodes >= 100 else "8"
        if 'VICTIM_COUNT' not in config_override:
            config['environment']['VICTIM_COUNT'] = "1"
        if 'SPECULATIVE_GRACE_MS' not in config_override:
            config['environment']['SPECULATIVE_GRACE_MS'] = "15"
        if 'SPECULATIVE_REFRESH_PARENTS' not in config_override:
            config['environment']['SPECULATIVE_REFRESH_PARENTS'] = "0"
        if 'SPECULATIVE_REQUIRE_VICTIM' not in config_override:
            config['environment']['SPECULATIVE_REQUIRE_VICTIM'] = "1" if num_nodes >= 25 else "0"
        if 'SPECULATIVE_P_MAX_LIMIT' not in config_override and num_nodes >= 25:
            config['environment']['SPECULATIVE_P_MAX_LIMIT'] = "100"
        config['environment']['ASR_LOGGING_FREQUENCY'] = "1"
        config['environment']['ASR_REPORT_THRESHOLD'] = "1"
    elif config['protocol']['name'] == 'narwhal' and attack_mode == 'sluggish':
        if 'NUM_WORKERS' not in config_override:
            config['environment']['NUM_WORKERS'] = "1"
        if 'ATTACKER_RATIO' not in config_override:
            config['environment']['ATTACKER_RATIO'] = "0.5"
        if 'VICTIM_COUNT' not in config_override:
            config['environment']['VICTIM_COUNT'] = "1"
        if 'MIN_ALL_PAIR_SAMPLES' not in config_override:
            config['environment']['MIN_ALL_PAIR_SAMPLES'] = "5" if num_nodes >= 100 else "3"
        config['environment']['ASR_LOGGING_FREQUENCY'] = "1"
        config['environment']['ASR_REPORT_THRESHOLD'] = "1"

    # Ensure LATENCY_MS/JITTER_MS are explicitly passed if available in override
    # This prevents reliance on deprecated LATENCY_JITTER string parsing
    if 'LATENCY_MS' in config_override:
        config['environment']['LATENCY_MS'] = str(config_override['LATENCY_MS'])
    if 'JITTER_MS' in config_override:
        config['environment']['JITTER_MS'] = str(config_override['JITTER_MS'])
    if 'EXCLUSION_PROBABILITY' in config_override:
        config['environment']['EXCLUSION_PROBABILITY'] = str(config_override['EXCLUSION_PROBABILITY'])
    
    # Set correct test name based on attack mode
    if config['protocol']['name'] in ['bullshark', 'narwhal']:
        test_name_map = {
            "fissure": "test_fissure_attack_asr_dynamic",
            "speculative": "test_speculative_attack_asr_dynamic",
            "sluggish": "test_sluggish_attack_asr_dynamic"
        }
        config['test']['test_name'] = test_name_map.get(attack_mode, config['test'].get('test_name'))
    elif config['protocol']['name'] == "mysticeti":
        # Mysticeti uses test_{attack_mode}_attack_asr_13_nodes
        config['test']['test_name'] = f"test_{attack_mode}_attack_asr_13_nodes"
    elif config['protocol']['name'] == "alephbft":
        # AlephBFT uses attack_tests::{attack_mode}_attack_test::test_{attack_mode}_attack_asr_13_nodes
        config['test']['test_name'] = f"attack_tests::{attack_mode}_attack_test::test_{attack_mode}_attack_asr_13_nodes"
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

    if dry_run:
        print(f"  [dry-run] cmd={' '.join(cmd)}")
        if os.path.exists(temp_config_path):
            os.remove(temp_config_path)
        return None
    
    start_time = time.time()
    num_nodes = int(config['environment'].get('NUM_NODES', 0))
    if not local_mode and num_nodes >= 50:
        cleanup_protocol_containers(config, reason="pre-run cleanup")
        time.sleep(5)

    try:
        timeout = compute_outer_timeout(config, attack_mode, local_mode)
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        output = result.stdout + result.stderr
        exit_code = result.returncode
    except subprocess.TimeoutExpired as e:
        print(f"  !!! TIMEOUT after {e.timeout}s !!!")
        output = decode_timeout_stream(e.stdout) + decode_timeout_stream(e.stderr)
        exit_code = -124 # Standard timeout exit code
        if not local_mode:
            cleanup_protocol_containers(config, reason="post-timeout cleanup")
    duration = time.time() - start_time

    # 3. Parse ASR
    asr = extract_final_asr(output)
    backrun_stats = extract_final_json_marker(output, "FINAL_BACKRUN_STATS:")
    sandwich_stats = extract_final_json_marker(output, "FINAL_SANDWICH_STATS:")
    if sandwich_stats:
        asr = normalize_param_value(sandwich_stats.get("sesr", asr))
    
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
        "attack_type": config['environment'].get('ATTACK_TYPE', 'frontrun'),
        "rep": rep_id,
        "asr": asr,
        "asr_l1": backrun_stats.get("l1_asr", ""),
        "asr_l2": backrun_stats.get("l2_asr", ""),
        "asr_histogram": json.dumps(backrun_stats.get("histogram", ""), sort_keys=True)
        if isinstance(backrun_stats.get("histogram", ""), (dict, list))
        else backrun_stats.get("histogram", ""),
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
            asr_val = row.get('asr', "N/A")
            if is_recordable_result(asr_val, row.get('exit_code', "")):
                key = build_result_key(row['protocol'], row['experiment'], row['attack_mode'], row['rep'], row)
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
            key = build_result_key(row['protocol'], row['experiment'], row['attack_mode'], row['rep'], row)
            
            asr_val = row.get('asr', "N/A")
            is_valid = is_recordable_result(asr_val, row.get('exit_code', ""))
            
            if is_valid:
                if key not in unique_results or not is_recordable_result(
                    unique_results[key].get('asr'),
                    unique_results[key].get('exit_code', ""),
                ):
                    unique_results[key] = row
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


def ensure_results_header(results_file):
    if not os.path.exists(results_file):
        return
    if os.path.getsize(results_file) == 0:
        return

    with open(results_file, "r", newline="") as f:
        first_line = f.readline()

    if first_line.startswith("timestamp,"):
        return

    with open(results_file, "r", newline="") as f:
        body = f.read()

    with open(results_file, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(FIELDNAMES)
        f.write(body)

    print(f"Normalized headerless results file: {results_file}")

def main():
    parser = argparse.ArgumentParser(description="Multi-Attack Parameter Sweeper")
    parser.add_argument("--config", default=DEFAULT_BASE_CONFIG, help="Base YAML config (default: grand_experiment.yaml)")
    parser.add_argument("--experiments", help="Comma-separated list of experiments to run (e.g. scaling,offense_speculative)")
    parser.add_argument("--local", action="store_true", help="Run tests locally via cargo instead of Docker")
    parser.add_argument("--out", default=DEFAULT_RESULTS_FILE, help=f"Output CSV file for results (default: {DEFAULT_RESULTS_FILE})")
    parser.add_argument("--no-build", action="store_true", help="Skip building binary inside Docker (use existing)")
    parser.add_argument("--type", default="frontrun", choices=["frontrun", "backrun", "sandwich"], help="MEV attack type")
    parser.add_argument("--dry-run", action="store_true", help="Print planned runs without executing them or writing CSV output")
    args = parser.parse_args()

    results_file = args.out

    # 0. Clean up and load existing progress
    if args.dry_run:
        existing_results = set()
        print("Dry run enabled. No CSV output will be written.")
    else:
        ensure_results_header(results_file)
        deduplicate_results(results_file)
        existing_results = load_existing_results(results_file)
        print(f"Loaded {len(existing_results)} existing results. Resuming...")

    # Determine Repetitions from config
    config = load_base_config(args.config)
    repetitions = int(config.get('test', {}).get('REPETITIONS', 1))

    target_protocol = config['protocol']['name']
    csvfile = None
    writer = None
    if not args.dry_run:
        file_exists = os.path.exists(results_file) and os.path.getsize(results_file) > 0
        csvfile = open(results_file, 'a', newline='')
        writer = csv.DictWriter(csvfile, fieldnames=FIELDNAMES, extrasaction='ignore')
        if not file_exists:
            writer.writeheader()
    try:

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
            elif target_protocol == "alephbft":
                relevant_experiments.extend([
                    "offense_exclusion", # EXCLUSION_PROBABILITY
                    "aleph_lookahead",
                    "aleph_sync_speed",
                    "aleph_hash_randomization"
                ])
            elif target_protocol == "autobahn":
                relevant_experiments.extend([
                    "offense_exclusion", # EXCLUSION_PROBABILITY
                    "autobahn_k",
                    "autobahn_fast_path"
                ])
            elif target_protocol == "mysticeti":
                relevant_experiments.extend([
                    "mahimahi_wave",    # WAVE_LENGTH (Mahi only)
                    "mahimahi_leaders", # NUMBER_OF_LEADERS (Mahi only)
                    "mysticeti_strategy", # SPECULATIVE_STRATEGY (Mahi only)
                    "offense_exclusion"  # EXCLUSION_PROBABILITY (Both)
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
                override["ATTACK_TYPE"] = args.type
                if args.type == "sandwich" and os.environ.get("SANDWICH_METRIC_MODE"):
                    override["SANDWICH_METRIC_MODE"] = os.environ["SANDWICH_METRIC_MODE"]

                # Skip 100 nodes for mahimahi protocol to avoid consensus stalls
                # Other protocols (Bullshark/Narwhal) handle 100 nodes fine
                num_nodes = int(override.get("NUM_NODES", config.get('environment', {}).get('NUM_NODES', 0)))
                if num_nodes > 50:
                    if target_protocol == "mahimahi" or target_protocol == "mysticeti":
                        print(f"  [-] Skipping {exp_name} | {target_protocol} | {num_nodes} nodes (Scaling Limit)")
                        continue
                    if target_attack == "sluggish":
                        print(f"  [-] Skipping {exp_name} | {target_attack} | {num_nodes} nodes (Sluggish Scaling Limit)")
                        continue

                # Run Repetitions
                for r in range(1, repetitions + 1):
                    effective_override = materialize_sweep_override(config, override, target_protocol, target_attack)
                    key = build_result_key(target_protocol, exp_name, target_attack, r, effective_override)
                    
                    if key in existing_results:
                        print(f"  [-] Skipping {exp_name} | {target_attack} | Rep {r} (Already recorded for {target_protocol})")
                        continue

                    attempts = 2 if (not args.local and num_nodes >= 50) else 1
                    for attempt in range(1, attempts + 1):
                        if attempt > 1:
                            print(f"  [Sweeper] Retrying {exp_name} | {target_attack} | Rep {r} after timeout...")
                            cleanup_protocol_containers(config, reason="pre-retry cleanup")
                            time.sleep(20)

                        data = run_experiment(
                            effective_override,
                            target_attack,
                            exp_name,
                            r,
                            args.config,
                            local_mode=args.local,
                            no_build=args.no_build,
                            dry_run=args.dry_run,
                        )
                        if data is None:
                            break
                        if data.get('exit_code') != -124:
                            break
                    
                    # ONLY record if we got a non-zero ASR (0.0 usually means simulation liveness failure)
                    if data is None:
                        continue
                    asr_result = str(data.get('asr', '0.0'))
                    exit_code = data.get('exit_code', "")
                    if is_recordable_result(asr_result, exit_code):
                        writer.writerow(data)
                        csvfile.flush() # CRITICAL: Write to disk immediately
                        os.fsync(csvfile.fileno()) # Force OS to flush buffers
                        existing_results.add(build_result_key(target_protocol, exp_name, target_attack, r, data))
                    else:
                        print(
                            f"  [!] Not recording result with ASR={asr_result}% and exit={exit_code} "
                            "(Likely simulation failure)"
                        )

                    # Wait between repetitions to allow Docker/OS cleanup or socket release
                    if "mahi" in target_protocol.lower():
                        print("  [Sweeper] Cooling down 10s for Mahi-Mahi cleanup...")
                        try:
                            # NUCLEAR OPTION: Force cleanup of any stuck containers on the host
                            subprocess.run("docker rm -f $(docker ps -aq)", shell=True, stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
                        except Exception:
                            pass
                        time.sleep(10)
                    elif not args.local and num_nodes >= 50:
                        cleanup_protocol_containers(config, reason="post-run cooldown")
                        print("  [Sweeper] Cooling down 20s for large-scale Docker cleanup...")
                        time.sleep(20)
                    else:
                        # Local mode needs time for sockets to enter TIME_WAIT and clear
                        time.sleep(5)
    finally:
        if csvfile is not None:
            csvfile.close()

if __name__ == "__main__":
    main()
