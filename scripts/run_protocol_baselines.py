#!/usr/bin/env python3
"""
Sequential baseline runner for protocol-level ASR measurements.

It runs one protocol at a time, appends each finished result to baseline.csv
immediately, and stops on the first invalid baseline unless --continue-on-error
is given.
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import shlex
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional


def _get_working_yaml():
    root_dir = Path(__file__).resolve().parent.parent
    if (root_dir / "yaml").is_dir():
        if str(root_dir) not in sys.path:
            sys.path.insert(0, str(root_dir))
        if "yaml" in sys.modules:
            del sys.modules["yaml"]
        try:
            import yaml  # type: ignore
            if hasattr(yaml, "safe_load"):
                return yaml
        except Exception:
            pass

    for path in sys.path:
        if "site-packages" in path and os.path.isdir(os.path.join(path, "yaml")):
            sys.path.insert(0, path)
            if "yaml" in sys.modules:
                del sys.modules["yaml"]
            try:
                import yaml  # type: ignore
                if hasattr(yaml, "safe_load"):
                    return yaml
            except Exception:
                pass

    import yaml  # type: ignore
    return yaml


yaml = _get_working_yaml()

ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = ROOT / "results" / "baselines"
DEFAULT_CSV = ROOT / "baseline.csv"
STANDARD_NUM_NODES = "13"
STANDARD_ATTACKER_ID = "0"
STANDARD_VICTIM_ID = "1"
STANDARD_ATTACKER_RATIO = f"{1.0 / 13.0:.12f}"
STANDARD_VICTIM_RATIO = f"{1.0 / 13.0:.12f}"

CSV_FIELDS = [
    "timestamp",
    "protocol",
    "attempt",
    "status",
    "asr",
    "duration_sec",
    "runner",
    "command",
    "log_path",
    "notes",
]

ASR_PATTERNS = [
    re.compile(r"FINAL_ASR_RESULT:\s*([0-9]+(?:\.[0-9]+)?)%?"),
    re.compile(r"FINAL ATTACK SUCCESS RATE \(ASR\):\s*([0-9]+(?:\.[0-9]+)?)%"),
    re.compile(r"Baseline Attack Success Rate \(ASR\):\s*([0-9]+(?:\.[0-9]+)?)%"),
    re.compile(r"ASR \(Block-Pair Ordering\):\s*([0-9]+(?:\.[0-9]+)?)%"),
    re.compile(r"Attack Success Rate:\s*([0-9]+(?:\.[0-9]+)?)%"),
]


def load_yaml(path: Path) -> dict:
    with path.open("r") as f:
        return yaml.safe_load(f)


def parse_asr(text: str) -> Optional[float]:
    matches: List[str] = []
    for pattern in ASR_PATTERNS:
        matches.extend(pattern.findall(text))
    if not matches:
        return None
    try:
        return float(matches[-1])
    except ValueError:
        return None


def ensure_csv(path: Path) -> None:
    if path.exists():
        return
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()


def load_completed(path: Path) -> set[str]:
    if not path.exists():
        return set()
    completed = set()
    with path.open("r", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("status") == "success":
                completed.add(row["protocol"])
    return completed


def load_next_attempts(path: Path) -> Dict[str, int]:
    next_attempts: Dict[str, int] = {}
    if not path.exists():
        return next_attempts
    with path.open("r", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            protocol = row.get("protocol")
            if not protocol:
                continue
            try:
                attempt = int(row.get("attempt", "0") or 0)
            except ValueError:
                attempt = 0
            next_attempts[protocol] = max(next_attempts.get(protocol, 0), attempt + 1)
    return next_attempts


def append_row(path: Path, row: Dict[str, str]) -> None:
    ensure_csv(path)
    with path.open("a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writerow(row)


def shell_join(cmd: Iterable[str]) -> str:
    return " ".join(shlex.quote(part) for part in cmd)


def run_command(
    protocol: str,
    cmd: List[str],
    cwd: Path,
    env: Dict[str, str],
    log_path: Path,
    dry_run: bool,
) -> tuple[bool, Optional[float], float, str]:
    command_str = shell_join(cmd)
    if dry_run:
        return False, None, 0.0, f"[dry-run] {command_str}"

    start = time.time()
    with log_path.open("w") as log_file:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd),
            env=env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            text=True,
        )
    duration = time.time() - start
    output = log_path.read_text(errors="ignore")
    asr = parse_asr(output)
    success = proc.returncode == 0 and asr is not None and 0.0 <= asr <= 100.0
    return success, asr, duration, output


def make_narwhal_temp_config(tmp_dir: Path) -> Path:
    base = load_yaml(ROOT / "config" / "grand_experiment_narwhal.yaml")
    base["experiment"]["name"] = "narwhal_baseline_measurement"
    base["experiment"]["description"] = "Pure baseline ASR measurement for Narwhal-Tusk"
    base["test"]["test_name"] = "baseline_measurement"
    env = base["environment"]
    env["ATTACK_MODE"] = "baseline"
    env["NUM_NODES"] = STANDARD_NUM_NODES
    env["ATTACKER_RATIO"] = STANDARD_ATTACKER_RATIO
    env["VICTIM_RATIO"] = STANDARD_VICTIM_RATIO
    env["VICTIM_COUNT"] = "1"
    env["ASR_LOGGING_FREQUENCY"] = "1"
    env["ASR_REPORT_THRESHOLD"] = "1"
    env["MIN_BASELINE_SAMPLES"] = "3"
    base["output"] = {"expected_asr": 50.0, "tolerance_percent": 100.0}
    path = tmp_dir / "narwhal_baseline.yaml"
    path.write_text(yaml.safe_dump(base))
    return path


def make_autobahn_temp_config(tmp_dir: Path) -> Path:
    base = load_yaml(ROOT / "config" / "grand_experiment_autobahn.yaml")
    base["experiment"]["name"] = "autobahn_baseline_measurement"
    base["experiment"]["description"] = "Pure baseline ASR measurement for Autobahn"
    base["test"]["test_name"] = "baseline_measurement"
    env = base["environment"]
    env["ATTACK_MODE"] = "baseline"
    env["NUM_NODES"] = STANDARD_NUM_NODES
    env["ATTACKER_ID"] = STANDARD_ATTACKER_ID
    env["VICTIM_ID"] = STANDARD_VICTIM_ID
    base["output"] = {"expected_asr": 50.0, "tolerance_percent": 100.0}
    path = tmp_dir / "autobahn_baseline.yaml"
    path.write_text(yaml.safe_dump(base))
    return path


def make_local_baseline_env(config_path: Path, keep_ratios: bool = True) -> Dict[str, str]:
    env = {
        **os.environ.copy(),
        **{k: str(v) for k, v in load_yaml(config_path).get("environment", {}).items()},
    }

    removable = {
        "ATTACK_MODE",
        "ATTACKER_ID",
        "VICTIM_ID",
        "EXCLUSION_PROBABILITY",
        "VICTIM_DELAY_MS",
        "SPECULATIVE_P_MAX",
        "SPECULATIVE_REQUIRE_VICTIM",
        "SPECULATIVE_P_MAX_LIMIT",
        "SLUGGISH_TIMEOUT_MULTIPLIER",
        "AUTOBAHN_K",
        "SIMPLE_EXCLUSION_PROB",
        "HYBRID_EXCLUSION",
        "RUSTC_WRAPPER",
    }
    for key in removable:
        env.pop(key, None)

    if not keep_ratios:
        env.pop("ATTACKER_RATIO", None)
        env.pop("VICTIM_RATIO", None)

    env["NUM_NODES"] = STANDARD_NUM_NODES
    env["NETWORK_SIZE"] = STANDARD_NUM_NODES
    env["ATTACKER_RATIO"] = STANDARD_ATTACKER_RATIO
    env["VICTIM_RATIO"] = STANDARD_VICTIM_RATIO
    env["ATTACKER_ID"] = STANDARD_ATTACKER_ID
    env["VICTIM_ID"] = STANDARD_VICTIM_ID
    env["VICTIM_COUNT"] = "1"

    return env


def protocol_commands(tmp_dir: Path, build_docker: bool) -> Dict[str, Dict[str, object]]:
    narwhal_cfg = make_narwhal_temp_config(tmp_dir)
    autobahn_cfg = make_autobahn_temp_config(tmp_dir)

    build_flag = ["--build"] if build_docker else []

    return {
        "narwhal": {
            "runner": "docker",
            "cwd": ROOT,
            "env": os.environ.copy(),
            "cmd": [sys.executable, "scripts/test_runner.py", str(narwhal_cfg), *build_flag],
            "notes": "Narwhal 13-node pure baseline using node 0 versus node 1 with attack logic disabled.",
        },
        "bullshark": {
            "runner": "local",
            "cwd": ROOT / "code" / "bullshark",
            "env": make_local_baseline_env(ROOT / "config" / "local_verify_unified.yaml"),
            "cmd": ["cargo", "test", "--release", "--package", "consensus-core", "--lib", "sluggish_attack_test::test_baseline_13_nodes_no_attack", "--", "--nocapture"],
            "notes": "Local Bullshark baseline using node 0 versus node 1.",
        },
        "mysticeti": {
            "runner": "local",
            "cwd": ROOT / "code" / "mysticeti",
            "env": make_local_baseline_env(ROOT / "config" / "grand_experiment_mysticeti.yaml"),
            "cmd": ["cargo", "test", "--release", "--package", "mysticeti-core", "test_baseline_asr_13_nodes", "--", "--nocapture"],
            "notes": "Native Mysticeti baseline using node 0 versus node 1.",
        },
        "alephbft": {
            "runner": "local",
            "cwd": ROOT / "code" / "alephbft",
            "env": make_local_baseline_env(ROOT / "config" / "grand_experiment_alephbft.yaml"),
            "cmd": ["cargo", "test", "--release", "--package", "aleph-bft", "--lib", "attack_tests::fissure_attack_test::test_baseline_asr_13_nodes_no_attack", "--", "--nocapture"],
            "notes": "Native AlephBFT baseline using node 0 versus node 1.",
        },
        "mahimahi": {
            "runner": "local",
            "cwd": ROOT / "code" / "mahi-mahi-consensus",
            "env": make_local_baseline_env(ROOT / "config" / "grand_experiment_mahimahi.yaml", keep_ratios=False),
            "cmd": ["bash", "scripts/baseline-13nodes.sh"],
            "notes": "Shell baseline runner from mahi-mahi-consensus using node 0 versus node 1.",
        },
        "autobahn": {
            "runner": "docker",
            "cwd": ROOT,
            "env": os.environ.copy(),
            "cmd": [sys.executable, "scripts/test_runner.py", str(autobahn_cfg), *build_flag],
            "notes": "Autobahn 13-node pure baseline using node 0 versus node 1.",
        },
        "mevsui": {
            "runner": "local",
            "cwd": ROOT / "code" / "mevsui",
            "env": make_local_baseline_env(ROOT / "config" / "grand_experiment.yaml"),
            "cmd": ["cargo", "test", "--release", "--package", "consensus-core", "--lib", "fissure_attack_test::test_baseline_asr_dynamic", "--", "--nocapture"],
            "notes": "Local MEVSUI baseline using node 0 versus node 1 with ATTACK_MODE cleared.",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run protocol baselines sequentially and append results to baseline.csv")
    parser.add_argument("--protocols", default="narwhal,bullshark,mysticeti,alephbft,mahimahi,autobahn,mevsui", help="Comma-separated protocol order")
    parser.add_argument("--out", default=str(DEFAULT_CSV), help="Output CSV path")
    parser.add_argument("--max-attempts", type=int, default=3, help="Maximum attempts per protocol before failing")
    parser.add_argument("--retry-delay-seconds", type=int, default=10, help="Delay between failed attempts of the same protocol")
    parser.add_argument("--continue-on-error", action="store_true", help="Continue past a failed baseline")
    parser.add_argument("--force", action="store_true", help="Re-run protocols already recorded as success")
    parser.add_argument("--dry-run", action="store_true", help="Print commands without executing them")
    parser.add_argument("--no-build-docker", action="store_true", help="Do not rebuild Docker images for docker-based protocols")
    args = parser.parse_args()

    if args.max_attempts < 1:
        parser.error("--max-attempts must be at least 1")
    if args.retry_delay_seconds < 0:
        parser.error("--retry-delay-seconds must be non-negative")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = Path(args.out).resolve()
    ensure_csv(csv_path)
    completed = load_completed(csv_path)
    next_attempts = load_next_attempts(csv_path)

    with tempfile.TemporaryDirectory(prefix="baseline-runner-") as tmp_name:
        tmp_dir = Path(tmp_name)
        commands = protocol_commands(tmp_dir, build_docker=not args.no_build_docker)
        order = [p.strip() for p in args.protocols.split(",") if p.strip()]

        for protocol in order:
            if protocol not in commands:
                print(f"Unknown protocol: {protocol}", file=sys.stderr)
                return 1
            if protocol in completed and not args.force:
                print(f"[skip] {protocol}: already recorded as success in {csv_path}")
                continue

            entry = commands[protocol]
            cmd = list(entry["cmd"])  # type: ignore[arg-type]
            cwd = Path(entry["cwd"])  # type: ignore[arg-type]
            env = dict(entry["env"])  # type: ignore[arg-type]
            notes = str(entry["notes"])
            runner = str(entry["runner"])
            attempt = next_attempts.get(protocol, 1)
            attempts_left = args.max_attempts
            protocol_succeeded = False

            while attempts_left > 0:
                timestamp = datetime.now().isoformat()
                log_path = RESULTS_DIR / (
                    f"{timestamp.replace(':', '-').replace('.', '-')}_{protocol}_attempt{attempt}.log"
                )
                print(f"[run] {protocol} (attempt {attempt})")
                print(f"      cwd={cwd}")
                print(f"      cmd={shell_join(cmd)}")

                success, asr, duration, output = run_command(protocol, cmd, cwd, env, log_path, args.dry_run)

                if args.dry_run:
                    protocol_succeeded = True
                    break

                row = {
                    "timestamp": timestamp,
                    "protocol": protocol,
                    "attempt": str(attempt),
                    "status": "success" if success else "failed",
                    "asr": "" if asr is None else f"{asr:.4f}",
                    "duration_sec": f"{duration:.2f}",
                    "runner": runner,
                    "command": shell_join(cmd),
                    "log_path": str(log_path),
                    "notes": notes,
                }
                append_row(csv_path, row)
                next_attempts[protocol] = attempt + 1

                if success:
                    protocol_succeeded = True
                    completed.add(protocol)
                    print(f"[ok] {protocol}: baseline ASR={asr:.4f}%")
                    break

                print(f"[fail] {protocol}: baseline invalid, see {log_path}")
                tail = "\n".join(output.splitlines()[-20:])
                if tail:
                    print(tail)

                attempts_left -= 1
                attempt += 1
                if attempts_left == 0:
                    break

                if args.retry_delay_seconds > 0:
                    print(
                        f"[retry] {protocol}: waiting {args.retry_delay_seconds}s before attempt {attempt}"
                    )
                    time.sleep(args.retry_delay_seconds)

            if protocol_succeeded:
                continue

            if not args.continue_on_error:
                return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
