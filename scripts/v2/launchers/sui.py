"""SuiLauncher — runs Sui/Mysticeti consensus attack tests via cargo test.

Direct invocation of cargo test against the Sui workspace, with optional
v2 Coordinator sidecar for per-node policy, coordination, and bribery.
When V2_COORDINATOR_URL is unset, the Rust hooks fall back to the
env-var-driven paper-1 path.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable, Optional

from ..coordinator import CoordinatorServer, CoordinatorState
from ..coordinator_client import CoordinatorClient
from ..schema import V2Config
from ..sweeper import Launcher, RunRequest, RunResult

REPO_ROOT = Path(__file__).resolve().parents[3]
SUI_MANIFEST = str(REPO_ROOT / "code" / "sui" / "Cargo.toml")

_SUI_TEST_NAMES = {
    "fissure": "fissure_attack_test::test_fissure_attack_asr_dynamic",
    "speculative": "speculative_attack_test::test_speculative_attack_asr_dynamic",
    "sluggish": "sluggish_attack_test::test_sluggish_attack_asr_dynamic",
    "mysticeti_lvw": "mysticeti_lvw_attack_test::test_mysticeti_lvw_attack_asr_dynamic",
    "mysticeti_lvw_fissure": "mysticeti_lvw_attack_test::test_mysticeti_lvw_attack_asr_dynamic",
    "mysticeti_eclipse": "mysticeti_lvw_attack_test::test_mysticeti_lvw_attack_asr_dynamic",
    "mysticeti_eclipse_lvw": "mysticeti_lvw_attack_test::test_mysticeti_lvw_attack_asr_dynamic",
}


class SuiLauncher:
    """v2 launcher for Sui/Mysticeti consensus attack tests."""

    name = "sui"

    def __init__(
        self,
        use_coordinator: Optional[bool] = None,
        on_coordinator_ready: Optional[
            Callable[[CoordinatorServer, V2Config, int], Optional[threading.Thread]]
        ] = None,
    ) -> None:
        self.use_coordinator = use_coordinator
        self.on_coordinator_ready = on_coordinator_ready

    def supports(self, protocol: str) -> bool:
        return protocol == "sui"

    def _should_use_coordinator(self, cfg: V2Config) -> bool:
        if self.use_coordinator is not None:
            return self.use_coordinator
        return bool(cfg.adversary.policies)

    def _start_coordinator(self, cfg: V2Config) -> CoordinatorServer:
        state = CoordinatorState()
        server = CoordinatorServer(state=state)
        server.start()
        client = CoordinatorClient(server.url)
        victim_profile_payload = (
            {
                "distribution": cfg.victims.profit.distribution,
                "params": dict(cfg.victims.profit.params),
                "seed": cfg.runtime.seed,
            }
            if cfg.victims.workload != "single"
            or cfg.victims.profit.distribution != "uniform"
            else None
        )
        briber_payload = None
        if cfg.adversary.bribery.enabled:
            briber_payload = {
                "type": cfg.adversary.bribery.type,
                "settlement": cfg.adversary.bribery.settlement,
                "budget": cfg.adversary.bribery.budget,
                "response_policy": cfg.adversary.bribery.response_policy
                or "reject_all",
                "response_policy_params": dict(
                    cfg.adversary.bribery.response_policy_params
                ),
                "bribed_honest": list(cfg.adversary.bribery.bribed_honest),
                "seed": cfg.runtime.seed,
            }
        client.init(
            policies=[
                {
                    "group_id": p.group_id,
                    "members": list(p.members),
                    "family": p.family,
                    "strategy": p.strategy,
                    "params": dict(p.params),
                }
                for p in cfg.adversary.policies
            ],
            coordination_policy=cfg.adversary.coordination.policy,
            information=cfg.adversary.coordination.information,
            seed=cfg.runtime.seed,
            victim_profile=victim_profile_payload,
            briber=briber_payload,
            defection_node_id=cfg.adversary.coordination.defection_node_id,
        )
        return server

    def run(self, request: RunRequest) -> RunResult:
        cfg = request.config
        strategy = cfg.dag_strategy

        test_name = _SUI_TEST_NAMES.get(strategy)
        if test_name is None:
            raise ValueError(
                f"SuiLauncher: unknown dag_strategy={strategy!r}. "
                f"Known: {list(_SUI_TEST_NAMES.keys())}"
            )

        cmd = [
            "cargo", "test",
            "--manifest-path", SUI_MANIFEST,
            "--package", "consensus-core",
            "--lib", test_name,
            "--", "--nocapture",
        ]

        subprocess_env = os.environ.copy()
        subprocess_env["ATTACK_MODE"] = strategy
        subprocess_env["ATTACK_TYPE"] = cfg.attack_family
        subprocess_env["NUM_NODES"] = str(cfg.num_nodes)
        subprocess_env["ATTACKER_RATIO"] = str(
            cfg.raw.get("environment", {}).get("ATTACKER_RATIO", "0.308")
        )
        subprocess_env["VICTIM_RATIO"] = str(
            cfg.raw.get("environment", {}).get("VICTIM_RATIO", "0.231")
        )
        # For compound modes the test reads ATTACK_MODE_OVERRIDE
        if strategy in ("mysticeti_lvw_fissure", "mysticeti_eclipse",
                        "mysticeti_eclipse_lvw"):
            subprocess_env["ATTACK_MODE_OVERRIDE"] = strategy
        # Strategy-specific params
        if strategy == "speculative":
            subprocess_env["SPECULATIVE_P_MAX"] = str(
                cfg.raw.get("environment", {}).get("SPECULATIVE_P_MAX", "50")
            )
        if strategy == "sluggish":
            subprocess_env["SLUGGISH_TIMEOUT_MULTIPLIER"] = str(
                cfg.raw.get("environment", {}).get("SLUGGISH_TIMEOUT_MULTIPLIER", "2.0")
            )
        # Test harness params
        subprocess_env.setdefault("COLLECTION_DURATION", "45")
        subprocess_env.setdefault("MIN_COMMITS", str(cfg.num_nodes + 10))
        subprocess_env.setdefault("GC_DEPTH", "10")

        # Coordinator sidecar
        coord: Optional[CoordinatorServer] = None
        side_thread: Optional[threading.Thread] = None
        if self._should_use_coordinator(cfg):
            coord = self._start_coordinator(cfg)
            subprocess_env["V2_COORDINATOR_URL"] = coord.url
            if cfg.adversary.bribery.enabled and cfg.adversary.bribery.bribed_honest:
                subprocess_env["V2_BRIBED_HONEST"] = ",".join(
                    str(x) for x in cfg.adversary.bribery.bribed_honest
                )
            if cfg.victims.victim_node_ids:
                subprocess_env["V2_VICTIM_NODE_IDS"] = ",".join(
                    str(x) for x in cfg.victims.victim_node_ids
                )
            if self.on_coordinator_ready is not None:
                side_thread = self.on_coordinator_ready(coord, cfg, request.rep)

        # Remove NO_ATTACK if present (we want the attack active)
        subprocess_env.pop("NO_ATTACK", None)

        start = time.time()
        try:
            completed = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=str(REPO_ROOT),
                timeout=self._compute_timeout(cfg),
                check=False,
                env=subprocess_env,
            )
            output = completed.stdout + completed.stderr
            exit_code = completed.returncode
        except subprocess.TimeoutExpired as te:
            stdout_b = te.stdout or b""
            stderr_b = te.stderr or b""
            if isinstance(stdout_b, bytes):
                stdout_b = stdout_b.decode("utf-8", "replace")
            if isinstance(stderr_b, bytes):
                stderr_b = stderr_b.decode("utf-8", "replace")
            output = stdout_b + stderr_b
            exit_code = -124

        coord_metrics: Optional[dict] = None
        if coord is not None:
            if side_thread is not None:
                side_thread.join(timeout=30.0)
            try:
                coord_metrics = CoordinatorClient(coord.url).metrics()
            except Exception:
                coord_metrics = None

        if coord is not None:
            coord.stop()
        duration = time.time() - start

        metrics = self._parse_markers(output, cfg.attack_family)
        if coord_metrics is not None:
            metrics["coordinator_metrics"] = coord_metrics
        if metrics.get("committed_order") and cfg.adversary.policies:
            metrics["per_policy_asr"] = _compute_per_policy_asr(
                committed_order=metrics["committed_order"],
                cfg=cfg,
            )
        return RunResult(
            raw_output=output,
            run_id=request.run_id,
            exit_code=exit_code,
            metrics=metrics,
            duration_sec=duration,
            auditor_findings=[],
            runtime_violations=[],
        )

    def _compute_timeout(self, cfg: V2Config) -> int:
        if cfg.dag_strategy == "sluggish":
            return 600
        return 300

    @staticmethod
    def _parse_markers(output: str, attack_family: str) -> dict:
        asr = _grep_last("FINAL_ASR_RESULT:", output)
        if asr is not None:
            asr = asr.rstrip("%").strip()
        all_pairs = _grep_last("FINAL_ALL_PAIRS_ASR:", output)
        if all_pairs is not None:
            all_pairs = all_pairs.rstrip("%").strip()
        near1 = _grep_last("FINAL_NEAR1_ASR:", output)
        if near1 is not None:
            near1 = near1.rstrip("%").strip()
        near2 = _grep_last("FINAL_NEAR2_ASR:", output)
        if near2 is not None:
            near2 = near2.rstrip("%").strip()
        committed_order = _grep_last_json_array("FINAL_COMMITTED_ORDER:", output)

        def _f(x):
            try:
                return float(x)
            except (TypeError, ValueError):
                return None

        return {
            "asr": _f(asr),
            "asr_all_pairs": _f(all_pairs),
            "asr_near1": _f(near1),
            "asr_near2": _f(near2),
            "asr_l1": None,
            "asr_l2": None,
            "asr_histogram": None,
            "per_policy_asr": None,
            "committed_order": committed_order,
            "raw_backrun": None,
            "raw_sandwich": None,
        }


def _grep_last(marker: str, output: str) -> Optional[str]:
    matches = [
        line.split(marker, 1)[1].strip()
        for line in output.splitlines()
        if marker in line
    ]
    return matches[-1] if matches else None


def _grep_last_json_array(marker: str, output: str) -> Optional[list]:
    raw = _grep_last(marker, output)
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return None


def _compute_per_policy_asr(
    committed_order: list[dict],
    cfg: V2Config,
) -> dict[str, float]:
    n = cfg.num_nodes
    victim_ratio = float(
        cfg.raw.get("environment", {}).get("VICTIM_RATIO", "0.231")
    )
    victim_count = round(n * victim_ratio)
    victim_ids = set(range(n - victim_count, n))

    if cfg.victims.victim_node_ids:
        victim_ids = set(cfg.victims.victim_node_ids)

    policy_members: dict[str, set[int]] = {}
    for p in cfg.adversary.policies:
        policy_members[p.group_id] = set(int(m) for m in p.members)

    results: dict[str, float] = {}
    for gid, members in policy_members.items():
        att_positions = [
            (e["position"], e["creator"])
            for e in committed_order
            if e["creator"] in members
        ]
        vic_positions = [
            (e["position"], e["creator"])
            for e in committed_order
            if e["creator"] in victim_ids
        ]
        if not att_positions or not vic_positions:
            results[gid] = 0.0
            continue
        success = sum(
            1 for ap, _ in att_positions for vp, _ in vic_positions if ap < vp
        )
        total = len(att_positions) * len(vic_positions)
        results[gid] = (success / total * 100.0) if total > 0 else 0.0
    return results
