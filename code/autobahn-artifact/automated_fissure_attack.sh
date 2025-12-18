#!/bin/bash
# Automated Fissure Attack Test for Autobahn
# Uses fab local task with environment variables

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Configuration
ATTACKER_ID=0
VICTIM_ID=1
EXCLUSION_PROBABILITY=0.20
DURATION=120

echo "============================================================"
echo "🎯 AUTOBAHN FISSURE ATTACK - AUTOMATED TEST"
echo "============================================================"
echo "Attacker: Node $ATTACKER_ID"
echo "Victim: Node $VICTIM_ID"
echo "Exclusion Probability: $EXCLUSION_PROBABILITY"
echo "Duration: ${DURATION}s"
echo "============================================================"
echo ""

# Create a modified fabfile that includes attack environment variables
cat > benchmark/fabfile_attack.py << 'FABEOF'
# Copyright(C) Facebook, Inc. and its affiliates.
from fabric import task
import os
import subprocess
from math import ceil
from os.path import basename, splitext
from time import sleep

from benchmark.commands import CommandMaker
from benchmark.config import Key, LocalCommittee, NodeParameters, BenchParameters, ConfigError
from benchmark.logs import LogParser, ParseError
from benchmark.utils import Print, BenchError, PathMaker

class AttackLocalBench:
    BASE_PORT = 3000

    def __init__(self, bench_parameters_dict, node_parameters_dict, attacker_id=0, victim_id=1, exclusion_prob=0.20):
        try:
            self.bench_parameters = BenchParameters(bench_parameters_dict)
            self.node_parameters = NodeParameters(node_parameters_dict)
            self.attacker_id = attacker_id
            self.victim_id = victim_id
            self.exclusion_prob = exclusion_prob
        except ConfigError as e:
            raise BenchError('Invalid nodes or bench parameters', e)

    def __getattr__(self, attr):
        return getattr(self.bench_parameters, attr)

    def _background_run(self, command, log_file, env_vars=None):
        name = splitext(basename(log_file))[0]
        if env_vars:
            env_str = ' '.join([f'{k}={v}' for k, v in env_vars.items()])
            cmd = f'{env_str} {command} 2> {log_file}'
        else:
            cmd = f'{command} 2> {log_file}'
        subprocess.run(['tmux', 'new', '-d', '-s', name, cmd], check=True)

    def _kill_nodes(self):
        try:
            cmd = CommandMaker.kill().split()
            subprocess.run(cmd, stderr=subprocess.DEVNULL)
        except subprocess.SubprocessError as e:
            raise BenchError('Failed to kill testbed', e)

    def run(self, debug=False):
        assert isinstance(debug, bool)
        Print.heading('Starting Fissure attack benchmark')

        # Kill any previous testbed.
        self._kill_nodes()
        
        try:
            Print.info('Setting up testbed...')
            nodes, rate = self.nodes[0], self.rate[0]

            # Cleanup all files.
            cmd = f'{CommandMaker.clean_logs()} ; {CommandMaker.cleanup()}'
            subprocess.run([cmd], shell=True, stderr=subprocess.DEVNULL)
            sleep(0.5)

            # Recompile the latest code.
            cmd = CommandMaker.compile().split()
            subprocess.run(cmd, check=True, cwd=PathMaker.node_crate_path())

            # Create alias for the client and nodes binary.
            cmd = CommandMaker.alias_binaries(PathMaker.binary_path())
            subprocess.run([cmd], shell=True)

            # Generate configuration files.
            keys = []
            key_files = [PathMaker.key_file(i) for i in range(nodes)]
            for filename in key_files:
                cmd = CommandMaker.generate_key(filename).split()
                subprocess.run(cmd, check=True)
                keys += [Key.from_file(filename)]

            names = [x.name for x in keys]
            committee = LocalCommittee(names, self.BASE_PORT, self.workers)
            committee.print(PathMaker.committee_file())

            self.node_parameters.print(PathMaker.parameters_file())

            # Run the clients
            workers_addresses = committee.workers_addresses(self.faults)
            rate_share = ceil(rate / committee.workers())
            for i, addresses in enumerate(workers_addresses):
                for (id, address) in addresses:
                    cmd = CommandMaker.run_client(
                        address,
                        self.tx_size,
                        rate_share,
                        [x for y in workers_addresses for _, x in y]
                    )
                    log_file = PathMaker.client_log_file(i, id)
                    self._background_run(cmd, log_file)

            # Run the primaries (with attack env vars for attacker)
            for i, address in enumerate(committee.primary_addresses(self.faults)):
                cmd = CommandMaker.run_primary(
                    PathMaker.key_file(i),
                    PathMaker.committee_file(),
                    PathMaker.db_path(i),
                    PathMaker.parameters_file(),
                    debug=debug
                )
                log_file = PathMaker.primary_log_file(i)
                
                # Add attack environment variables for attacker node
                env_vars = None
                if i == self.attacker_id:
                    env_vars = {
                        'ATTACK_MODE': 'fissure',
                        'ATTACKER_ID': str(self.attacker_id),
                        'VICTIM_ID': str(self.victim_id),
                        'EXCLUSION_PROBABILITY': str(self.exclusion_prob),
                        'RUST_LOG': 'info'
                    }
                
                self._background_run(cmd, log_file, env_vars)

            # Run the workers
            for i, addresses in enumerate(workers_addresses):
                for (id, address) in addresses:
                    cmd = CommandMaker.run_worker(
                        PathMaker.key_file(i),
                        PathMaker.committee_file(),
                        PathMaker.db_path(i, id),
                        PathMaker.parameters_file(),
                        id,
                        debug=debug
                    )
                    log_file = PathMaker.worker_log_file(i, id)
                    self._background_run(cmd, log_file)

            # Wait for all transactions to be processed.
            Print.info(f'Running benchmark ({self.duration} sec)...')
            sleep(self.duration)
            self._kill_nodes()

            # Parse logs and return the parser.
            Print.info('Parsing logs...')
            return LogParser.process(PathMaker.logs_path(), faults=self.faults)

        except (subprocess.SubprocessError, ParseError) as e:
            self._kill_nodes()
            raise BenchError('Failed to run benchmark', e)

@task
def fissure_attack(ctx, debug=True):
    ''' Run Fissure attack benchmark on localhost '''
    bench_params = {
        'faults': 0,
        'nodes': [13],
        'workers': 1,
        'co-locate': True,
        'rate': [50_000],
        'tx_size': 512,
        'duration': 120,
        'runs': 1,
        'simulate_partition': False,
    }
    node_params = {
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
        'use_fast_sync': True,
        'use_exponential_timeouts': False,
    }
    try:
        ret = AttackLocalBench(bench_params, node_params, attacker_id=0, victim_id=1, exclusion_prob=0.20).run(debug)
        print(ret.result())
        
        # Calculate ASR
        print("\n" + "="*60)
        print("Calculating ASR...")
        print("="*60)
        import subprocess
        import glob
        log_files = glob.glob(PathMaker.logs_path() + "/primary-*.log")
        if log_files:
            subprocess.run(['python3', 'scripts/calculate-fissure-asr.py'] + log_files)
    except BenchError as e:
        Print.error(e)
FABEOF

# Run the attack test
cd benchmark
export ATTACK_MODE=fissure
export ATTACKER_ID=$ATTACKER_ID
export VICTIM_ID=$VICTIM_ID
export EXCLUSION_PROBABILITY=$EXCLUSION_PROBABILITY

echo "Running Fissure attack test..."
fab -f fabfile_attack.py fissure_attack

echo ""
echo "✅ Test complete!"





