# Copyright(C) Facebook, Inc. and its affiliates.
import os
import subprocess
from math import ceil
from os.path import basename, splitext
from time import sleep

from benchmark.commands import CommandMaker
from benchmark.config import Key, LocalCommittee, NodeParameters, BenchParameters, ConfigError
from benchmark.logs import LogParser, ParseError
from benchmark.utils import Print, BenchError, PathMaker


class LocalBench:
    BASE_PORT = 3000
    TMUX_LAUNCH_BATCH_SIZE = max(1, int(os.environ.get('TMUX_LAUNCH_BATCH_SIZE', '32')))

    def __init__(self, bench_parameters_dict, node_parameters_dict):
        try:
            self.bench_parameters = BenchParameters(bench_parameters_dict)
            self.node_parameters = NodeParameters(node_parameters_dict)
        except ConfigError as e:
            raise BenchError('Invalid nodes or bench parameters', e)

    def __getattr__(self, attr):
        return getattr(self.bench_parameters, attr)

    def _background_command(self, command, log_file):
        name = splitext(basename(log_file))[0]

        # PROPAGATE ATTACK ENV VARS: Ensure local simulation respects attack config
        attack_vars = [
            'ATTACK_MODE', 'ATTACKER_RATIO', 'VICTIM_RATIO',
            'VICTIM_COUNT', 'NUM_WORKERS',
            'SPECULATIVE_P_MAX', 'SLUGGISH_TIMEOUT_MULTIPLIER',
            'SPECULATIVE_TIMEOUT_MS', 'ASR_ROUND_WINDOW',
            'ASR_LOGGING_FREQUENCY', 'ASR_REPORT_THRESHOLD',
            'RUST_LOG'
        ]
        envs = ' '.join([f'{v}="{os.environ[v]}"' for v in attack_vars if v in os.environ])
        prefix = f'{envs} ' if envs else ''
        cmd = f'{prefix}{command} 2> {log_file}'
        return ['tmux', 'new', '-d', '-s', name, cmd]

    def _background_run(self, command, log_file):
        subprocess.run(self._background_command(command, log_file), check=True)

    def _background_run_many(self, commands):
        pending = []
        batch_size = self._tmux_batch_size(len(commands))
        for command, log_file in commands:
            pending.append(subprocess.Popen(self._background_command(command, log_file)))
            if len(pending) >= batch_size:
                self._wait_for_pending(pending)
                pending.clear()
        self._wait_for_pending(pending)

    @staticmethod
    def _wait_for_pending(processes):
        for process in processes:
            code = process.wait()
            if code != 0:
                raise subprocess.CalledProcessError(code, process.args)

    def _tmux_batch_size(self, command_count):
        # Large 50+/100-node runs create hundreds of tmux sessions. Starting
        # them too aggressively can starve the later node phases before the
        # benchmark even begins.
        nodes = self.nodes[0]
        if nodes >= 100:
            return min(self.TMUX_LAUNCH_BATCH_SIZE, 2)
        if nodes >= 50:
            return min(self.TMUX_LAUNCH_BATCH_SIZE, 8)
        if nodes >= 25 and command_count >= 100:
            return min(self.TMUX_LAUNCH_BATCH_SIZE, 16)
        return self.TMUX_LAUNCH_BATCH_SIZE

    def _kill_nodes(self):
        try:
            cmd = CommandMaker.kill().split()
            subprocess.run(cmd, stderr=subprocess.DEVNULL)
        except subprocess.SubprocessError as e:
            raise BenchError('Failed to kill testbed', e)

    def run(self, debug=False):
        assert isinstance(debug, bool)
        Print.heading('Starting local benchmark')

        # Kill any previous testbed.
        self._kill_nodes()

        try:
            Print.info('Setting up testbed...')
            nodes, rate = self.nodes[0], self.rate[0]

            # Cleanup all files.
            cmd = f'{CommandMaker.clean_logs()} ; {CommandMaker.cleanup()}'
            subprocess.run([cmd], shell=True, stderr=subprocess.DEVNULL)
            sleep(0.5)  # Removing the store may take time.

            # Recompile the latest code.
            # cmd = CommandMaker.compile().split()
            # subprocess.run(cmd, check=True, cwd=PathMaker.node_crate_path())

            # Create alias for the client and nodes binary.
            alias_cmd = f"rm -f node benchmark_client && ln -sf {PathMaker.binary_path()}/node . && ln -sf {PathMaker.binary_path()}/benchmark_client ."
            subprocess.run([alias_cmd], shell=True, check=True)

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

            workers_addresses = committee.workers_addresses(self.faults)
            rate_share = ceil(rate / committee.workers())

            # Run the primaries (except the faulty ones).
            primaries = []
            for i, address in enumerate(committee.primary_addresses(self.faults)):
                cmd = CommandMaker.run_primary(
                    PathMaker.key_file(i),
                    PathMaker.committee_file(),
                    PathMaker.db_path(i),
                    PathMaker.parameters_file(),
                    debug=debug
                )
                log_file = PathMaker.primary_log_file(i)
                primaries += [(cmd, log_file)]
            Print.info(f'Launching {len(primaries)} primaries...')
            self._background_run_many(primaries)

            # Run the workers (except the faulty ones).
            workers = []
            for i, addresses in enumerate(workers_addresses):
                for (id, address) in addresses:
                    cmd = CommandMaker.run_worker(
                        PathMaker.key_file(i),
                        PathMaker.committee_file(),
                        PathMaker.db_path(i, id),
                        PathMaker.parameters_file(),
                        id,  # The worker's id.
                        debug=debug
                    )
                    log_file = PathMaker.worker_log_file(i, id)
                    workers += [(cmd, log_file)]
            Print.info(f'Launching {len(workers)} workers...')
            self._background_run_many(workers)

            if nodes >= 25:
                settle_secs = 5 if nodes >= 50 else 2
                Print.info(f'Allowing nodes to settle for {settle_secs} sec...')
                sleep(settle_secs)

            # Run the clients after nodes are online. Launching all clients
            # first at 50+ nodes causes startup thrash and delays worker bring-up.
            clients = []
            for i, addresses in enumerate(workers_addresses):
                for (id, address) in addresses:
                    cmd = CommandMaker.run_client(
                        address,
                        self.tx_size,
                        rate_share,
                        [x for y in workers_addresses for _, x in y]
                    )
                    log_file = PathMaker.client_log_file(i, id)
                    clients += [(cmd, log_file)]
            Print.info(f'Launching {len(clients)} clients...')
            self._background_run_many(clients)

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
