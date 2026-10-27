# Copyright(C) Facebook, Inc. and its affiliates.
import base64
import os
import subprocess
from math import ceil
from os.path import basename, splitext
from time import sleep

from benchmark.commands import CommandMaker
from benchmark.config import (
    Key,
    LocalCommittee,
    NodeParameters,
    BenchParameters,
    ConfigError,
)
from benchmark.logs import LogParser, ParseError
from benchmark.utils import Print, BenchError, PathMaker


class LocalBench:
    BASE_PORT = 3000

    def __init__(self, bench_parameters_dict, node_parameters_dict):
        try:
            self.bench_parameters = BenchParameters(bench_parameters_dict)
            self.node_parameters = NodeParameters(node_parameters_dict)
        except ConfigError as e:
            raise BenchError("Invalid nodes or bench parameters", e)

    def __getattr__(self, attr):
        return getattr(self.bench_parameters, attr)

    def _background_run(self, command, log_file):
        name = splitext(basename(log_file))[0]
        cmd = f"{command} 2> {log_file}"
        subprocess.run(["tmux", "new", "-d", "-s", name, cmd], check=True)

    def _kill_nodes(self):
        try:
            cmd = CommandMaker.kill().split()
            subprocess.run(cmd, stderr=subprocess.DEVNULL)
        except subprocess.SubprocessError as e:
            raise BenchError("Failed to kill testbed", e)

    def run(self, debug=False):
        assert isinstance(debug, bool)
        Print.heading("Starting local benchmark")

        # Kill any previous testbed.
        self._kill_nodes()

        try:
            Print.info("Setting up testbed...")
            nodes, rate = self.nodes[0], self.rate[0]
            arbitragers = self.arbitragers
            attack_type = self.attack_type

            # Cleanup all files.
            cmd = f"{CommandMaker.clean_logs()} ; {CommandMaker.cleanup()}"
            subprocess.run([cmd], shell=True, stderr=subprocess.DEVNULL)
            sleep(0.5)  # Removing the store may take time.

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
            committee = LocalCommittee(
                names,
                self.BASE_PORT,
                self.workers,
                self.faults,
                arbitragers,
                attack_type,
            )
            committee.print(PathMaker.committee_file())

            self.node_parameters.print(PathMaker.parameters_file())

            # Run the clients (they will wait for the nodes to be ready).
            workers_addresses = committee.workers_addresses(self.faults)
            rate_share = ceil(rate / committee.workers())
            for i, addresses in enumerate(workers_addresses):
                for id, address in addresses:
                    cmd = CommandMaker.run_client(
                        address,
                        self.tx_size,
                        rate_share,
                        [x for y in workers_addresses for _, x in y],
                    )
                    log_file = PathMaker.client_log_file(i, id)
                    self._background_run(cmd, log_file)

            # Front-running experiment (env FR_VICTIM_RATE): one extra client streams
            # victim-tagged transactions to worker 0 of the victim, the honest node with
            # the smallest public key (the Rust side's `victims()[0]`).
            fr_rate = int(os.environ.get("FR_VICTIM_RATE", "0"))
            if fr_rate > 0:
                types = [a["attack_type"] for a in committee.json["authorities"].values()]
                honest = [i for i, t in enumerate(types[: len(workers_addresses)]) if t == 0]
                victim = min(honest, key=lambda i: base64.b64decode(names[i]))
                vaddr = workers_addresses[victim][0][1]
                Print.info(f"Front-run victim: node {victim}, worker 0 at {vaddr}")
                # FR_VICTIM_SPRAY=1: the victim, like the attacker, also submits each
                # transaction to every validator (one client per validator, same ids).
                targets = [victim]
                if os.environ.get("FR_VICTIM_SPRAY") == "1":
                    targets += [i for i in range(len(workers_addresses)) if i != victim]
                for k, i in enumerate(targets):
                    cmd = CommandMaker.run_client(
                        workers_addresses[i][0][1],
                        self.tx_size,
                        fr_rate,
                        [x for y in workers_addresses for _, x in y],
                        victim=True,
                    )
                    name = "fr-victim.log" if k == 0 else f"fr-victim-copy-{i}.log"
                    self._background_run(cmd, f"{PathMaker.logs_path()}/{name}")

            # Run the primaries (except the faulty ones).
            for i, address in enumerate(committee.primary_addresses(self.faults)):
                cmd = CommandMaker.run_primary(
                    PathMaker.key_file(i),
                    PathMaker.committee_file(),
                    PathMaker.db_path(i),
                    PathMaker.parameters_file(),
                    debug=debug,
                )
                log_file = PathMaker.primary_log_file(i)
                self._background_run(cmd, log_file)

            # Run the workers (except the faulty ones).
            for i, addresses in enumerate(workers_addresses):
                for id, address in addresses:
                    cmd = CommandMaker.run_worker(
                        PathMaker.key_file(i),
                        PathMaker.committee_file(),
                        PathMaker.db_path(i, id),
                        PathMaker.parameters_file(),
                        id,  # The worker's id.
                        debug=debug,
                    )
                    log_file = PathMaker.worker_log_file(i, id)
                    self._background_run(cmd, log_file)

            # Wait for all transactions to be processed.
            Print.info(f"Running benchmark ({self.duration} sec)...")
            sleep(self.duration)
            self._kill_nodes()

            # Parse logs and return the parser.
            Print.info("Parsing logs...")
            return LogParser.process(
                PathMaker.logs_path(),
                attack_type=attack_type,
                arbitragers=arbitragers,
                faults=self.faults,
            )

        except (subprocess.SubprocessError, ParseError) as e:
            self._kill_nodes()
            raise BenchError("Failed to run benchmark", e)
