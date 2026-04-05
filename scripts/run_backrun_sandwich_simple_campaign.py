#!/usr/bin/env python3
import argparse
import os
import shlex
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

PROTOCOL_CONFIGS = [
    ("bullshark", "config/simple_campaign_bullshark.yaml"),
    ("alephbft", "config/simple_campaign_alephbft.yaml"),
    ("mysticeti", "config/simple_campaign_mysticeti.yaml"),
    ("autobahn", "config/simple_campaign_autobahn.yaml"),
]

LOCAL_PROTOCOLS = {"bullshark", "alephbft", "mysticeti"}

ATTACK_MODES = ["fissure", "speculative", "sluggish"]
ATTACK_TYPES = ["backrun", "sandwich"]


def run(cmd, env=None, dry_run=False):
    env_prefix = ""
    if env is not None:
        overrides = []
        for key, value in env.items():
            if os.environ.get(key) != value:
                overrides.append(f"{key}={shlex.quote(str(value))}")
        if overrides:
            env_prefix = " ".join(overrides) + " "
    print(f"\n$ {env_prefix}{' '.join(cmd)}", flush=True)
    if dry_run:
        return
    subprocess.run(cmd, cwd=ROOT, env=env, check=True)


def main():
    parser = argparse.ArgumentParser(description="Run simple backrun/sandwich campaigns for selected protocols.")
    parser.add_argument("--out", default="back_sand_results.csv")
    parser.add_argument("--skip-build", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="Print the planned commands without executing them")
    parser.add_argument("--protocol", action="append", choices=[name for name, _ in PROTOCOL_CONFIGS], help="Limit to one or more protocols")
    args = parser.parse_args()

    selected = [item for item in PROTOCOL_CONFIGS if not args.protocol or item[0] in args.protocol]
    out_path = args.out

    for protocol_name, config_path in selected:
        needs_docker = protocol_name not in LOCAL_PROTOCOLS
        if not args.skip_build and needs_docker:
            run(["python3", "scripts/test_runner.py", config_path, "--build-only"], dry_run=args.dry_run)

        for attack_type in ATTACK_TYPES:
            for attack_mode in ATTACK_MODES:
                env = os.environ.copy()
                env["ATTACK_MODE"] = attack_mode
                run(
                    [
                        "python3",
                        "scripts/experiment_sweeper.py",
                        "--config",
                        config_path,
                        "--experiments",
                        "simple",
                        "--type",
                        attack_type,
                        "--out",
                        out_path,
                        *(["--local"] if protocol_name in LOCAL_PROTOCOLS else []),
                        *(["--dry-run"] if args.dry_run else []),
                    ],
                    env=env,
                    dry_run=args.dry_run,
                )


if __name__ == "__main__":
    main()
