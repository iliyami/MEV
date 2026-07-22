"""Tests for proc_util.run_capture — the group-killing timeout wrapper.

Regression guard for the amd008 Sui-n=49 incident: a `cargo test` timeout must
kill its whole process group, so the test-binary grandchild can't orphan.
"""

from __future__ import annotations

import os
import time

from scripts.v2.proc_util import run_capture


def test_normal_completion_returns_output_and_code():
    out, code = run_capture(
        ["bash", "-c", "echo hello; echo boom >&2; exit 3"],
        cwd=".", env=dict(os.environ), timeout=10,
    )
    assert code == 3
    assert "hello" in out and "boom" in out


def test_timeout_returns_minus_124():
    out, code = run_capture(
        ["bash", "-c", "sleep 30"], cwd=".", env=dict(os.environ), timeout=1,
    )
    assert code == -124
    assert "TIMEOUT" in out


def test_timeout_kills_grandchild(tmp_path):
    sentinel = tmp_path / "grandchild_ran"
    # A grandchild that would touch the sentinel after 4s, while the parent
    # sleeps 30s. run_capture times out at 1s and group-kills everything.
    cmd = ["bash", "-c", f"( sleep 4; touch {sentinel} ) & sleep 30"]
    out, code = run_capture(cmd, cwd=".", env=dict(os.environ), timeout=1)
    assert code == -124
    # Past the grandchild's 4s delay: if the group-kill worked it never ran.
    time.sleep(5)
    assert not sentinel.exists(), "grandchild survived the timeout (orphan leak!)"
