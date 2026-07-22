"""BullsharkLauncher — delegates v2 TM-Solo cells to the v1 test_runner.

Translation rules (TM-Solo only for P0):
    v2.attack_family   -> v1 environment.ATTACK_TYPE  ("frontrun"/"backrun"/"sandwich")
    v2.dag_strategy    -> v1 environment.ATTACK_MODE  ("fissure"/"speculative"/"sluggish")
    v2.adversary.policies[0].members -> implicit (uses v1's ATTACKER_RATIO)
    v2 forwards every v1 environment key the original raw config supplied so
    the v1 hooks see the exact same parameterization paper 1 used.

Multi-policy threat models (TM-Compete / TM-Collude / TM-Bribe) are explicitly
rejected by this launcher: the Bullshark v1 hooks only accept a single global
(family, strategy). Multi-policy wiring is a P1+ task and lives in a separate
launcher implementation (or extends this one with explicit per-slot env hints).
Rejecting them here prevents silent misexecution.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Callable, Optional

from ..auditor import RuntimeViolation
from ..coordinator import CoordinatorServer, CoordinatorState
from ..coordinator_client import CoordinatorClient
from ..schema import V2Config
from ..proc_util import run_capture
from ..sweeper import Launcher, RunRequest, RunResult

REPO_ROOT = Path(__file__).resolve().parents[3]

_BULLSHARK_TEST_NAMES = {
    "fissure": "test_fissure_attack_asr_dynamic",
    "speculative": "test_speculative_attack_asr_dynamic",
    "sluggish": "test_sluggish_attack_asr_dynamic",
    # DS4/DS5 withholding attacks (env-gated proposer hooks ported into core.rs).
    "withhold_baseline": "test_withhold_baseline_asr_dynamic",
    "withhold_silent": "test_withhold_silent_attack_asr_dynamic",
    "slw": "test_slw_attack_asr_dynamic",
}


class BullsharkLauncher:
    """v2 launcher backed by the v1 test_runner.

    Args:
        local_mode: pass --local to the v1 runner (paper 1 uses local execution
            for Bullshark; the runner falls back to `cargo test` rather than
            Docker for the Bullshark codebase).
        skip_build: do not rebuild the cargo target between reps.
        runner_script: override for the v1 entrypoint, used by tests.
        runner_overrides: optional dict of additional v1 environment keys to
            inject (e.g., REPETITIONS=1).
        cwd: working directory for the subprocess (default: repo root).
    """

    name = "bullshark"

    def __init__(
        self,
        local_mode: bool = True,
        skip_build: bool = False,
        runner_script: Optional[str] = None,
        runner_overrides: Optional[dict[str, str]] = None,
        cwd: Optional[str] = None,
        use_coordinator: Optional[bool] = None,
        on_coordinator_ready: Optional[
            "Callable[[CoordinatorServer, V2Config, int], Optional[threading.Thread]]"
        ] = None,
    ) -> None:
        self.local_mode = local_mode
        self.skip_build = skip_build
        self.runner_script = runner_script or str(REPO_ROOT / "scripts" / "test_runner.py")
        self.runner_overrides = dict(runner_overrides or {})
        self.cwd = cwd or str(REPO_ROOT)
        # If `None`, we auto-enable the Coordinator iff the config has any
        # adversary.policies (i.e., a non-trivial multi-policy run). Callers
        # can force it on or off explicitly.
        self.use_coordinator = use_coordinator
        # Optional callback invoked *after* the Coordinator is initialised and
        # *before* the Bullshark subprocess starts. Receives (coord, cfg, rep).
        # If the callback returns a Thread, the launcher joins it before
        # tearing the Coordinator down (so concurrent side-channel exercises
        # like the briber lifecycle finish deterministically).
        self.on_coordinator_ready = on_coordinator_ready

    def supports(self, protocol: str) -> bool:
        return protocol == "bullshark"

    # ---- coordinator management -------------------------------------------

    def _should_use_coordinator(self, cfg: V2Config) -> bool:
        if self.use_coordinator is not None:
            return self.use_coordinator
        # Auto: enable when the config materialized any per-node policies.
        return bool(cfg.adversary.policies)

    def _start_coordinator(self, cfg: V2Config) -> CoordinatorServer:
        state = CoordinatorState()
        server = CoordinatorServer(state=state)
        server.start()
        # Init via the HTTP client (so the contract is exercised end-to-end
        # rather than reaching into the state directly).
        client = CoordinatorClient(server.url)
        # Build the victim_profile payload from VictimsSpec.profit; the
        # Coordinator only enables /victim/profit when this is set.
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
        # Build the briber payload from AdversarySpec.bribery; the Coordinator
        # only enables /bribery/* when this is set.
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

    # ---- v2 -> v1 translation ---------------------------------------------

    # Threat models this launcher currently supports.
    #   * TM-Solo     -- always; both env-var path and coord path.
    #   * TM-Compete  -- requires the v2 Coordinator (per-node /policy/lookup).
    #                    Wired since P1a.
    #   * TM-Bribe    -- the Rust path uses /policy/lookup; the bribery
    #                    lifecycle (offers/decide/accept/settle) runs in
    #                    Python alongside the protocol. Full honest-node
    #                    bribery coupling is a P4 task.
    #   * TM-Collude  -- requires Rust to consult /coordinate/decision per
    #                    round; not wired yet (deferred to P3).
    _SUPPORTED_TM_WITH_COORDINATOR: tuple[str, ...] = (
        "TM-Solo", "TM-Compete", "TM-Collude", "TM-Bribe",
    )

    def _validate_threat_model(self, cfg: V2Config) -> None:
        tm = cfg.adversary.threat_model
        if self._should_use_coordinator(cfg):
            if tm not in self._SUPPORTED_TM_WITH_COORDINATOR:
                raise NotImplementedError(
                    f"BullsharkLauncher does not yet support threat_model={tm!r} "
                    f"with the Coordinator. Supported: "
                    f"{self._SUPPORTED_TM_WITH_COORDINATOR}. "
                    "TM-Collude needs the per-round /coordinate/decision path "
                    "to be wired in Rust (P3 task)."
                )
        else:
            # No Coordinator: the v1 env-var path only expresses a single
            # global (family, strategy), so only TM-Solo with at most one
            # materialized policy is valid.
            if tm != "TM-Solo":
                raise NotImplementedError(
                    f"BullsharkLauncher requires the Coordinator for "
                    f"threat_model={tm!r}. Either enable use_coordinator=True "
                    "or set threat_model='TM-Solo'."
                )
            if len(cfg.adversary.policies) > 1:
                raise NotImplementedError(
                    f"BullsharkLauncher without Coordinator supports a "
                    f"single policy; got {len(cfg.adversary.policies)}. "
                    "Enable use_coordinator=True for multi-policy runs."
                )

    def _build_v1_yaml(self, cfg: V2Config) -> dict:
        """Emit a v1-format temp config the existing test_runner already accepts."""
        # Start from the raw config — preserves docker/test/environment keys.
        v1 = json.loads(json.dumps(cfg.raw))  # deep copy via JSON

        # test_runner.py requires an experiment block; synthesize one if absent.
        v1.setdefault(
            "experiment",
            {
                "name": f"v2_bullshark_{cfg.attack_family}_{cfg.dag_strategy}",
                "description": (
                    f"v2 harness regression cell -- TM-Solo, "
                    f"{cfg.attack_family}/{cfg.dag_strategy}, n={cfg.num_nodes}"
                ),
            },
        )

        # Ensure protocol is bullshark.
        v1.setdefault("protocol", {"name": "bullshark", "path": "bullshark"})

        # Set test_name based on dag_strategy.
        v1.setdefault("test", {})
        v1["test"]["test_name"] = _BULLSHARK_TEST_NAMES[cfg.dag_strategy]
        v1["test"].setdefault("REPETITIONS", 1)  # v2 handles rep loop itself

        # Translate to v1 environment keys.
        env = v1.setdefault("environment", {})
        env["ATTACK_MODE"] = cfg.dag_strategy
        env["ATTACK_TYPE"] = cfg.attack_family
        env.setdefault("NUM_NODES", str(cfg.num_nodes))
        # Forward any v2 runtime overrides.
        for k, v in self.runner_overrides.items():
            env[k] = str(v)

        return v1

    # ---- run ---------------------------------------------------------------

    def run(self, request: RunRequest) -> RunResult:
        cfg = request.config
        self._validate_threat_model(cfg)

        v1_yaml = self._build_v1_yaml(cfg)

        # Write temp yaml. Avoid collisions across reps + parallel runs.
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=f"_v2_bullshark_{request.run_id}_rep{request.rep}.yaml",
            delete=False,
            dir=str(REPO_ROOT / "config"),
        ) as fh:
            import yaml as _yaml  # type: ignore
            _yaml.safe_dump(v1_yaml, fh)
            temp_path = fh.name

        cmd: list[str] = [sys.executable, self.runner_script, temp_path]
        if self.local_mode:
            cmd.append("--local")
        if self.skip_build:
            cmd.append("--no-build")

        # Optionally spin up the Coordinator sidecar and export its URL into
        # the subprocess environment. The Bullshark Rust code only consults
        # the coordinator when V2_COORDINATOR_URL is set; with this var
        # absent, the paper-1 env-var path runs unchanged (the P0 regression
        # contract).
        coord: Optional[CoordinatorServer] = None
        side_thread: Optional[threading.Thread] = None
        subprocess_env = os.environ.copy()
        # Always ask test_runner.py to forward the cargo output so the
        # launcher's caller can grep for v2-emitted info!() markers. This
        # is a no-op when v1 paper-1 flow doesn't set the var explicitly.
        subprocess_env["V2_VERBOSE_OUTPUT"] = "1"
        # v3 R-P3.1 / R-P3.2: if any attacker has role_action="amplify",
        # export the full Byzantine-node-id set so the amplifier knows
        # its peers (for preferential parent inclusion).
        all_byz: set[int] = set()
        any_amplify = False
        for p in cfg.adversary.policies:
            if p.params.get("role_action") == "amplify":
                any_amplify = True
            for m in p.members:
                all_byz.add(int(m))
        if any_amplify and all_byz:
            subprocess_env["V2_BYZ_PEERS"] = ",".join(str(x) for x in sorted(all_byz))
        # v3 R-P4.1: if bribery is enabled, export the bribed_honest set so
        # honest nodes know whether to consult /bribery/pending each round.
        if cfg.adversary.bribery.enabled and cfg.adversary.bribery.bribed_honest:
            subprocess_env["V2_BRIBED_HONEST"] = ",".join(
                str(x) for x in cfg.adversary.bribery.bribed_honest
            )
        # v3 R-P2.2: if a canonical victim set is configured, export it so
        # is_victim_block uses the same set across all attackers regardless
        # of each attacker's per-node family.
        if cfg.victims.victim_node_ids:
            subprocess_env["V2_VICTIM_NODE_IDS"] = ",".join(
                str(x) for x in cfg.victims.victim_node_ids
            )
        if self._should_use_coordinator(cfg):
            coord = self._start_coordinator(cfg)
            subprocess_env["V2_COORDINATOR_URL"] = coord.url
            # Per-rep side-channel exercise (e.g. briber lifecycle).
            if self.on_coordinator_ready is not None:
                side_thread = self.on_coordinator_ready(coord, cfg, request.rep)

        start = time.time()
        # Group-killed timeout so a cargo timeout can't orphan the test binary.
        output, exit_code = run_capture(
            cmd, self.cwd, subprocess_env, self._compute_timeout(cfg)
        )
        # Coordinator metrics snapshot (briber ledger + victim_profile config
        # + decisions made) — fetched BEFORE teardown so it lands in
        # RunResult.metrics["coordinator_metrics"]. This is the canonical
        # source for v2-side telemetry in the CSV.
        coord_metrics: Optional[dict] = None
        if coord is not None:
            # Wait for any side-channel exercise to finish before snapshot.
            if side_thread is not None:
                side_thread.join(timeout=30.0)
            try:
                coord_metrics = CoordinatorClient(coord.url).metrics()
            except Exception:
                coord_metrics = None

        try:
            os.unlink(temp_path)
        except OSError:
            pass
        if coord is not None:
            coord.stop()
        duration = time.time() - start

        metrics = self._parse_markers(output, cfg.attack_family)
        if coord_metrics is not None:
            metrics["coordinator_metrics"] = coord_metrics
        # v3 R-P2.1: compute per-policy ASR from the committed-order marker
        # if it was emitted and the cell config supplies a policy vector.
        if metrics.get("committed_order") and cfg.adversary.policies:
            metrics["per_policy_asr"] = _compute_per_policy_asr(
                committed_order=metrics["committed_order"],
                cfg=cfg,
            )
        # All-pairs ASR from the committed order (neutral ~50% baseline). Always
        # stored as a diagnostic; promoted to the headline `asr` ONLY when the
        # cell opts in via env V2_ALL_PAIRS_ASR (the alpha-sweep). Same-round
        # stays the default so the paper-1 contradiction checks on the
        # competition/collusion cells (which reference same-round) are intact.
        ap = _compute_all_pairs_asr(metrics.get("committed_order"), cfg)
        if ap is not None:
            metrics["asr_all_pairs"] = ap
            env = (cfg.raw or {}).get("environment", {}) or {}
            if str(env.get("V2_ALL_PAIRS_ASR", "")).lower() in ("1", "true", "yes"):
                metrics["asr_same_round"] = metrics.get("asr")
                metrics["asr"] = ap
        return RunResult(
            raw_output=output,
            run_id=request.run_id,
            exit_code=exit_code,
            metrics=metrics,
            duration_sec=duration,
            auditor_findings=[],
            runtime_violations=[],
        )

    # ---- helpers -----------------------------------------------------------

    def _compute_timeout(self, cfg: V2Config) -> int:
        """Match v1's timeout heuristic for n=13."""
        if cfg.dag_strategy == "sluggish":
            return 7200  # paper-1 keeps this generous
        return 3600

    @staticmethod
    def _parse_markers(output: str, attack_family: str) -> dict:
        """Extract FINAL_*_RESULT / FINAL_*_STATS / FINAL_COMMITTED_ORDER markers."""
        asr = _grep_last("FINAL_ASR_RESULT:", output)  # same-round (head start)
        if asr is not None:
            asr = asr.rstrip("%").strip()
        all_pairs = _grep_last("FINAL_ALL_PAIRS_ASR:", output)  # neutral ~50% baseline
        if all_pairs is not None:
            all_pairs = all_pairs.rstrip("%").strip()
        backrun = _grep_last_json("FINAL_BACKRUN_STATS:", output)
        sandwich = _grep_last_json("FINAL_SANDWICH_STATS:", output)
        # v3 R-P2.1: committed-order JSON emitted by mev_attack_metrics.rs.
        # Parsed here; per-policy ASR is computed in the launcher's run()
        # method once we also have the cell config in scope.
        committed_order = _grep_last_json_array("FINAL_COMMITTED_ORDER:", output)

        # For sandwich runs paper 1's v1 prefers FINAL_SANDWICH_STATS.sesr as
        # the headline ASR. We preserve that convention.
        if attack_family == "sandwich" and sandwich:
            asr_val = sandwich.get("sesr", asr)
        elif all_pairs is not None:
            # When the test emits all-pairs (the withholding cells), that is the
            # headline: neutral ~50% baseline, so a cross-round lift is visible.
            # Same-round ASR is kept as a diagnostic (asr_same_round).
            asr_val = all_pairs
        else:
            asr_val = asr

        def _f(x):
            try:
                return float(x)
            except (TypeError, ValueError):
                return None

        return {
            "asr": _f(asr_val),
            "asr_same_round": _f(asr),
            "asr_all_pairs": _f(all_pairs),
            "asr_l1": _f(backrun.get("l1_asr")) if backrun else None,
            "asr_l2": _f(backrun.get("l2_asr")) if backrun else None,
            "asr_histogram": json.dumps(backrun.get("histogram"), sort_keys=True)
            if backrun and "histogram" in backrun
            else None,
            "per_policy_asr": None,  # populated by run() below if committed_order present
            "committed_order": committed_order,
            "raw_backrun": backrun or None,
            "raw_sandwich": sandwich or None,
        }


def _grep_last(marker: str, output: str) -> Optional[str]:
    matches = [
        line.split(marker, 1)[1].strip()
        for line in output.splitlines()
        if marker in line
    ]
    return matches[-1] if matches else None


def _grep_last_json(marker: str, output: str) -> Optional[dict]:
    raw = _grep_last(marker, output)
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _grep_last_json_array(marker: str, output: str) -> Optional[list]:
    raw = _grep_last(marker, output)
    if raw is None:
        return None
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, list) else None
    except json.JSONDecodeError:
        return None


def _compute_all_pairs_asr(committed_order, cfg) -> Optional[float]:
    """All-pairs frontrun ASR from the committed order: over every attacker×
    victim pair (any round), the fraction where the attacker is ordered first.
    Neutral ~50% with no attack, so it distinguishes attack impact on Bullshark
    where same-round ASR is saturated by the low-index head start. Attackers =
    first round(n*ATTACKER_RATIO) indices, victims = last round(n*VICTIM_RATIO).
    Returns None on empty order / empty role set (malformed records skipped)."""
    if not committed_order:
        return None
    env = (cfg.raw or {}).get("environment", {}) or {}
    try:
        n = int(env.get("NUM_NODES", cfg.num_nodes))
        ar = float(env.get("ATTACKER_RATIO", 0.308))
        vr = float(env.get("VICTIM_RATIO", 0.231))
    except (TypeError, ValueError):
        return None
    attackers = set(range(round(n * ar)))
    victims = set(range(n - round(n * vr), n))
    att_pos: list[int] = []
    vic_pos: list[int] = []
    for e in committed_order:
        try:
            creator = int(e["creator"])
            position = int(e["position"])
        except (KeyError, TypeError, ValueError):
            continue
        if creator in attackers:
            att_pos.append(position)
        elif creator in victims:
            vic_pos.append(position)
    # Guard degenerate cases: with <2 attacker blocks the ratio is 0/100 noise,
    # not attack impact (e.g. sluggish at low alpha starves the delayed attacker
    # so it barely commits). Report None (n/a) rather than a misleading number.
    if len(att_pos) < 2 or not vic_pos:
        return None
    successes = sum(1 for a in att_pos for v in vic_pos if a < v)
    total = len(att_pos) * len(vic_pos)
    return round(successes / total * 100.0, 2) if total else None


def _compute_per_policy_asr(committed_order: list[dict], cfg) -> dict[str, float]:
    """Compute per-policy ASR from the committed-block order + policy vector.

    Per-policy success predicate by family (v3 R-P2.2):
      frontrun:  attacker.position < victim.position (same round)
      backrun:   attacker.position > victim.position (same round)
      sandwich:  attacker.position != victim.position (loose approximation;
                 doesn't model triplets)

    Victim set:
      1. cfg.victims.victim_node_ids if non-empty (R-P2.2 canonical set);
      2. else the frontrun-layout default (last VICTIM_RATIO*N indices).
    """
    env = (cfg.raw or {}).get("environment", {}) or {}
    try:
        n = int(env.get("NUM_NODES", cfg.num_nodes))
    except (TypeError, ValueError):
        return {}

    if cfg.victims.victim_node_ids:
        victim_set = set(int(x) for x in cfg.victims.victim_node_ids)
    else:
        try:
            victim_ratio = float(env.get("VICTIM_RATIO", 0.231))
        except (TypeError, ValueError):
            return {}
        victim_count = round(n * victim_ratio)
        victim_set = set(range(n - victim_count, n))

    # Defensive: every record we use must have all three fields. Skip
    # malformed entries rather than KeyError.
    def _well_formed(rec: dict) -> bool:
        try:
            int(rec["creator"])
            int(rec["round"])
            int(rec["position"])
            return True
        except (KeyError, TypeError, ValueError):
            return False

    clean_order = [r for r in committed_order if _well_formed(r)]

    # Pre-collect victim records.
    victims_by_round: dict[int, list[dict]] = {}
    for r in clean_order:
        if int(r["creator"]) in victim_set:
            victims_by_round.setdefault(int(r["round"]), []).append(r)

    def _success(family: str, a_pos: int, v_pos: int) -> bool:
        if family == "frontrun":
            return a_pos < v_pos
        if family == "backrun":
            return a_pos > v_pos
        if family == "sandwich":
            return a_pos != v_pos
        return False

    per_policy: dict[str, float] = {}
    for policy in cfg.adversary.policies:
        members = set(int(m) for m in policy.members)
        attackers = [r for r in clean_order if int(r["creator"]) in members]
        successes = 0
        comparable = 0
        for a in attackers:
            round_victims = victims_by_round.get(int(a["round"]), [])
            for v in round_victims:
                comparable += 1
                if _success(policy.family, int(a["position"]), int(v["position"])):
                    successes += 1
        if comparable > 0:
            per_policy[policy.group_id] = round(successes / comparable * 100.0, 2)
        else:
            per_policy[policy.group_id] = None
    return per_policy


# Verify BullsharkLauncher satisfies the Launcher protocol.
_: Launcher = BullsharkLauncher()  # type: ignore[assignment]
