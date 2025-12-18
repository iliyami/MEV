#!/usr/bin/env python3
"""
Run Fissure Attack on Autobahn with 13 nodes
"""

import subprocess
import sys
import os
from math import ceil
from time import sleep
from pathlib import Path

# Change to script directory
SCRIPT_DIR = Path(__file__).parent.absolute()
os.chdir(SCRIPT_DIR)

# Add benchmark to path
sys.path.insert(0, str(SCRIPT_DIR / "benchmark"))

from benchmark.commands import CommandMaker
from benchmark.config import Key, LocalCommittee, NodeParameters, BenchParameters
from benchmark.utils import PathMaker

def main():
    # Configuration
    NODES = 13
    WORKERS = 1
    DURATION = 120
    ATTACKER_ID = 0
    VICTIM_ID = 1
    EXCLUSION_PROB = 1.0  # 100% exclusion probability (always exclude for maximum ASR)
    ATTACK_MODE = "sluggish"  # Options: "fissure", "leader_support", "tip_exclusion", "timing", or "sluggish"
    VICTIM_DELAY_MS = 50  # Delay victim vote processing by this many milliseconds
    SLUGGISH_TIMEOUT_MULTIPLIER = 5.0  # Multiplier for sluggish attack delay (5.0x = 500ms delay if base is 100ms)
    
    print("="*60)
    print(f"🎯 AUTOBAHN {ATTACK_MODE.upper()} ATTACK TEST")
    print("="*60)
    print(f"Nodes: {NODES}")
    print(f"Attacker: Node {ATTACKER_ID}")
    print(f"Victim: Node {VICTIM_ID}")
    print(f"Attack Mode: {ATTACK_MODE}")
    if ATTACK_MODE == "sluggish":
        print(f"Sluggish Timeout Multiplier: {SLUGGISH_TIMEOUT_MULTIPLIER}x")
    else:
        print(f"Exclusion Probability: {EXCLUSION_PROB}")
    print(f"Duration: {DURATION}s")
    print("="*60)
    print()
    
    # Kill any existing nodes
    print("Killing existing nodes...")
    subprocess.run(CommandMaker.kill().split(), stderr=subprocess.DEVNULL)
    sleep(1)
    
    # Cleanup
    print("Cleaning up...")
    subprocess.run([f'{CommandMaker.clean_logs()} ; {CommandMaker.cleanup()}'], shell=True, stderr=subprocess.DEVNULL)
    sleep(0.5)
    
    # Check if binaries already exist
    binary_path = os.path.join(SCRIPT_DIR, PathMaker.binary_path().replace('..', '.'))
    node_binary = os.path.join(binary_path, 'node')
    client_binary = os.path.join(binary_path, 'benchmark_client')
    
    # Always check if we need to rebuild (primary might have changed)
    primary_lib = os.path.join(SCRIPT_DIR, "target", "release", "libprimary.rlib")
    node_binary_mtime = os.path.getmtime(node_binary) if os.path.exists(node_binary) else 0
    primary_lib_mtime = os.path.getmtime(primary_lib) if os.path.exists(primary_lib) else 0
    
    # Force rebuild if primary library is newer
    if os.path.exists(node_binary) and os.path.exists(client_binary):
        if node_binary_mtime > primary_lib_mtime:
            print("✅ Binaries already exist and up-to-date, skipping build...")
        else:
            print("⚠️  Primary library is newer than node binary, but build may fail. Continuing with existing binary...")
    else:
        # Build (try debug if release fails)
        print("Building...")
        # Build from workspace root, not node directory
        try:
            subprocess.run(CommandMaker.compile().split(), check=True, cwd=SCRIPT_DIR, timeout=600)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            print(f"⚠️  Build failed: {e}")
            print("Trying to build without hotstuff...")
            # Try building without hotstuff (which has compilation errors)
            try:
                subprocess.run(['cargo', 'build', '--release', '--features', 'benchmark', '--exclude', 'hotstuff'], 
                             check=True, cwd=SCRIPT_DIR, timeout=600)
            except:
                print("⚠️  Build still failed, but continuing with existing binary if available...")
            # Update binary path for debug
            import benchmark.utils
            from os.path import join
            original_binary_path = benchmark.utils.PathMaker.binary_path
            benchmark.utils.PathMaker.binary_path = lambda: join('..', 'target', 'debug')
            binary_path = os.path.join(SCRIPT_DIR, PathMaker.binary_path().replace('..', '.'))
    
    # Create aliases (binary_path already set above)
    # Remove existing symlinks/directories
    for link in ['node', 'benchmark_client']:
        if os.path.exists(link):
            if os.path.islink(link) or os.path.isfile(link):
                os.remove(link)
            elif os.path.isdir(link):
                import shutil
                shutil.rmtree(link)
    subprocess.run([CommandMaker.alias_binaries(binary_path)], shell=True)
    
    # Generate keys
    print("Generating keys...")
    keys = []
    for i in range(NODES):
        cmd = CommandMaker.generate_key(PathMaker.key_file(i)).split()
        subprocess.run(cmd, check=True)
        keys.append(Key.from_file(PathMaker.key_file(i)))
    
    # Create committee
    names = [x.name for x in keys]
    committee = LocalCommittee(names, 3000, WORKERS)
    committee.print(PathMaker.committee_file())
    
    # Create parameters
    node_params = NodeParameters({
        'timeout_delay': 1_000,
        'header_size': 1_000,
        'max_header_delay': 100,
        'gc_depth': 50,
        'sync_retry_delay': 10_000,
        'sync_retry_nodes': 3,
        'batch_size': 500_000,
        'max_batch_delay': 100,
        'use_optimistic_tips': True,
        'use_parallel_proposals': True,
        'k': 4,
        'use_fast_path': True,
        'fast_path_timeout': 200,
        'use_ride_share': False,
        'car_timeout': 2000,
        'simulate_asynchrony': False,
        'asynchrony_start': 20_000,
        'asynchrony_duration': 10_000,
        'use_fast_sync': True,
        'use_exponential_timeouts': False,
    })
    node_params.print(PathMaker.parameters_file())
    
    # Start primaries
    print("Starting primaries...")
    for i, address in enumerate(committee.primary_addresses(0)):
        cmd = CommandMaker.run_primary(
            PathMaker.key_file(i),
            PathMaker.committee_file(),
            PathMaker.db_path(i),
            PathMaker.parameters_file(),
            debug=False
        )
        log_file = PathMaker.primary_log_file(i)
        
        # Add attack env vars for attacker
        env = os.environ.copy()
        if i == ATTACKER_ID:
            env['ATTACK_MODE'] = 'fissure'
            env['ATTACKER_ID'] = str(ATTACKER_ID)
            env['VICTIM_ID'] = str(VICTIM_ID)
            env['EXCLUSION_PROBABILITY'] = str(EXCLUSION_PROB)
            env['RUST_LOG'] = 'info'
        
        # Run in tmux
        name = f"primary-{i}"
        if i == ATTACKER_ID:
            # Pass env vars explicitly to tmux using env command
            env_vars = {
                'ATTACK_MODE': ATTACK_MODE,
                'ATTACKER_ID': str(ATTACKER_ID),
                'VICTIM_ID': str(VICTIM_ID),
                'EXCLUSION_PROBABILITY': str(EXCLUSION_PROB),
                'VICTIM_DELAY_MS': str(VICTIM_DELAY_MS),
                'SLUGGISH_TIMEOUT_MULTIPLIER': str(SLUGGISH_TIMEOUT_MULTIPLIER),
                'RUST_LOG': 'info'
            }
            # Use env command to set variables
            env_parts = [f'{k}={v}' for k, v in env_vars.items()]
            env_cmd = 'env ' + ' '.join(env_parts)
            full_cmd = f'{env_cmd} {cmd} 2> {log_file}'
            print(f"🔧 Starting attacker node {i} with: ATTACK_MODE={ATTACK_MODE} ATTACKER_ID={ATTACKER_ID} VICTIM_ID={VICTIM_ID}")
        else:
            full_cmd = f'{cmd} 2> {log_file}'
        subprocess.run(['tmux', 'new', '-d', '-s', name, 'bash', '-c', full_cmd], check=True)
    
    # Start workers
    print("Starting workers...")
    workers_addresses = committee.workers_addresses(0)
    for i, addresses in enumerate(workers_addresses):
        for (id, address) in addresses:
            cmd = CommandMaker.run_worker(
                PathMaker.key_file(i),
                PathMaker.committee_file(),
                PathMaker.db_path(i, id),
                PathMaker.parameters_file(),
                id,
                debug=False
            )
            log_file = PathMaker.worker_log_file(i, id)
            name = f"worker-{i}-{id}"
            subprocess.run(['tmux', 'new', '-d', '-s', name, f'{cmd} 2> {log_file}'], check=True)
    
    # Start clients
    print("Starting clients...")
    sleep(5)  # Wait for nodes to start
    rate_share = ceil(50000 / committee.workers())
    for i, addresses in enumerate(workers_addresses):
        for (id, address) in addresses:
            cmd = CommandMaker.run_client(
                address,
                512,
                rate_share,
                [x for y in workers_addresses for _, x in y]
            )
            log_file = PathMaker.client_log_file(i, id)
            name = f"client-{i}-{id}"
            subprocess.run(['tmux', 'new', '-d', '-s', name, f'{cmd} 2> {log_file}'], check=True)
    
    # Wait
    print(f"\nRunning test for {DURATION} seconds...")
    sleep(DURATION)
    
    # Stop
    print("Stopping nodes...")
    subprocess.run(CommandMaker.kill().split(), stderr=subprocess.DEVNULL)
    
    # Calculate ASR
    print("\n" + "="*60)
    print("Calculating ASR...")
    print("="*60)
    log_files = list(Path(PathMaker.logs_path()).glob("primary-*.log"))
    if log_files:
        cmd = ['python3', 'scripts/calculate-fissure-asr.py'] + [str(f) for f in log_files]
        subprocess.run(cmd)
    else:
        print("⚠️  No log files found!")
    
    print("\n✅ Test complete!")

if __name__ == "__main__":
    main()

