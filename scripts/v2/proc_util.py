"""Subprocess helper for the launchers.

`run_capture` runs a child in its own session/process-group and, on timeout,
SIGKILLs the WHOLE group before reaping. Plain `subprocess.run(timeout=...)`
only kills the direct child, so a `cargo test` that times out leaves its test
binary (a grandchild) orphaned and burning CPU — the amd008 Sui-n=49 incident,
where orphaned `consensus_core-*` processes climbed host load. This prevents
that class of leak for every launcher.
"""

from __future__ import annotations

import os
import signal
import subprocess


def _kill_group(proc: subprocess.Popen) -> None:
    """SIGKILL the child's whole process group; fall back to the child alone."""
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            proc.kill()
        except OSError:
            pass


def run_capture(
    cmd: list[str],
    cwd: str,
    env: dict,
    timeout: float,
) -> tuple[str, int]:
    """Run `cmd`, capturing stdout+stderr, bounded by `timeout` seconds.

    Returns (combined_output, exit_code). On timeout the whole process group is
    killed and exit_code is -124 (the launchers' timeout convention), with a
    marker appended to the captured output.
    """
    proc = subprocess.Popen(
        cmd,
        cwd=cwd,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,  # own process group -> group-kill on timeout
    )
    try:
        out, err = proc.communicate(timeout=timeout)
        return (out or "") + (err or ""), proc.returncode
    except subprocess.TimeoutExpired:
        _kill_group(proc)
        try:
            out, err = proc.communicate(timeout=15)
        except subprocess.TimeoutExpired:
            out, err = "", ""
        tail = (out or "") + (err or "")
        return (
            tail + f"\n[TIMEOUT: process group killed after {timeout:.0f}s]\n",
            -124,
        )
