"""Byzantine-only Coordinator sidecar.

P3 extension: under `coordination_policy == "leader"` the
`/coordinate/decision` endpoint also returns a `shared_exclusion_seed`
derived deterministically from `(coordinator.seed, round, leader_id)`.
All Byzantine nodes in the same group receive the *same* seed value
for the same round, enabling synchronized exclusion-coin decisions in
the Rust-side fissure attack hook (see `p3_preregistration.md` §3).


A small HTTP/JSON service that runs alongside an experiment and lets the
attacker-controlled (Byzantine) nodes share local DAG views and look up
coordination decisions. Honest nodes never connect; the existence of this
service is invisible to the protocol code paths.

Invariants (see CLAUDE.md):
    * No request handled here writes into a protocol's state or messages.
    * Only Byzantine-set node IDs are recognized; honest IDs get 404.
    * Decisions returned are *suggestions* the attacker hooks may use when
      picking among their already-legitimate action set; they never instruct
      an honest node to do anything.

Transport choice: stdlib `http.server`, JSON bodies. Zero new dependencies,
trivial to curl from a debug shell, easy to call from the Bullshark fork
later using a 30-line reqwest client. gRPC would be overkill for our scale
(a handful of nodes, low req/s).

Three coordination policies (see paper plan §4):
    leader              -- a designated Byzantine node decides; others mirror
    role_specialization -- each member keeps its configured (family, strategy)
                           and the coordinator just records / confirms the role
    rr_slot             -- only one Byzantine node is "active" per round, in
                           round-robin order; studies attack-density effects

Two information modes:
    own_dag_only      -- /dag/view returns only the requester's own published
                         blocks (lower bound on collusion power: no sharing)
    local_dag_union   -- returns union across all Byzantine nodes (upper bound)
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import logging
import struct
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Optional

from .briber import BriberState, HonestResponsePolicy
from .schema import (
    COORDINATION_INFO,
    COORDINATION_POLICIES,
    PolicySpec,
)
from .victim_gen import VictimProfile

logger = logging.getLogger("v2.coordinator")


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------


@dataclass
class CoordinatorState:
    """In-memory state. One instance per experiment run."""

    coordination_policy: str = "role_specialization"
    information: str = "local_dag_union"
    seed: int = 0
    leader_node_id: Optional[int] = None
    # node_id -> PolicySpec
    policies: dict[int, PolicySpec] = field(default_factory=dict)
    # round -> node_id -> list[block_hash]
    dag_views: dict[int, dict[int, list[str]]] = field(default_factory=dict)
    # (round, node_id) -> decision dict (cached)
    decisions: dict[tuple[int, int], dict[str, Any]] = field(default_factory=dict)
    # round -> set of node_ids that have shared this round (for activity tracking)
    shared_this_round: dict[int, set[int]] = field(default_factory=dict)
    # immutable Byzantine node-id list, in stable order
    byzantine_node_ids: tuple[int, ...] = ()
    # Optional per-run victim-profit configuration. None ⇒ /victim/profit 409s.
    victim_profile: Optional[VictimProfile] = None
    # Optional per-run briber state. None ⇒ /bribery/* 409s.
    briber: Optional[BriberState] = None
    # v3 R-P3.4: a defecting Byzantine node ignores coord decisions.
    # The coordinator emits no shared_exclusion_seed for this node.
    defection_node_id: Optional[int] = None
    initialized: bool = False
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def init_from_policies(
        self,
        policies: list[PolicySpec],
        coordination_policy: str,
        information: str,
        seed: int = 0,
        leader_node_id: Optional[int] = None,
        victim_profile: Optional[VictimProfile] = None,
        briber: Optional[BriberState] = None,
        defection_node_id: Optional[int] = None,
    ) -> None:
        if coordination_policy not in COORDINATION_POLICIES:
            raise ValueError(f"unknown coordination_policy {coordination_policy!r}")
        if information not in COORDINATION_INFO:
            raise ValueError(f"unknown information mode {information!r}")
        with self._lock:
            self.coordination_policy = coordination_policy
            self.information = information
            self.seed = seed
            self.policies = {}
            for p in policies:
                for member in p.members:
                    self.policies[int(member)] = p
            self.byzantine_node_ids = tuple(sorted(self.policies.keys()))
            if leader_node_id is not None:
                if leader_node_id not in self.policies:
                    raise ValueError(
                        f"leader_node_id {leader_node_id} not in Byzantine set"
                    )
                self.leader_node_id = leader_node_id
            else:
                self.leader_node_id = (
                    self.byzantine_node_ids[0] if self.byzantine_node_ids else None
                )
            self.dag_views.clear()
            self.decisions.clear()
            self.shared_this_round.clear()
            self.victim_profile = victim_profile
            self.briber = briber
            # v3 R-P3.4: validate defector is Byzantine if specified.
            if defection_node_id is not None and defection_node_id not in self.policies:
                raise ValueError(
                    f"defection_node_id {defection_node_id} not in Byzantine set"
                )
            self.defection_node_id = defection_node_id
            self.initialized = True

    # --- queries -------------------------------------------------------------

    def lookup_policy(self, node_id: int) -> Optional[PolicySpec]:
        with self._lock:
            return self.policies.get(int(node_id))

    def share_view(self, node_id: int, round_: int, blocks: list[str]) -> None:
        with self._lock:
            if int(node_id) not in self.policies:
                raise KeyError(f"node_id {node_id} is not Byzantine")
            self.dag_views.setdefault(int(round_), {})[int(node_id)] = list(blocks)
            self.shared_this_round.setdefault(int(round_), set()).add(int(node_id))

    def view_for(self, node_id: int, round_: int) -> list[str]:
        with self._lock:
            if int(node_id) not in self.policies:
                raise KeyError(f"node_id {node_id} is not Byzantine")
            round_views = self.dag_views.get(int(round_), {})
            if self.information == "own_dag_only":
                return list(round_views.get(int(node_id), []))
            # local_dag_union: union, stable order = sorted by hash
            seen: set[str] = set()
            for view in round_views.values():
                seen.update(view)
            return sorted(seen)

    def decide(self, node_id: int, round_: int) -> dict[str, Any]:
        """Return the coordination decision for (node_id, round). Cached."""
        with self._lock:
            if int(node_id) not in self.policies:
                raise KeyError(f"node_id {node_id} is not Byzantine")
            key = (int(round_), int(node_id))
            if key in self.decisions:
                return dict(self.decisions[key])
            decision = self._compute_decision(int(node_id), int(round_))
            self.decisions[key] = dict(decision)
            return dict(decision)

    def _compute_decision(self, node_id: int, round_: int) -> dict[str, Any]:
        own_policy = self.policies[node_id]
        # v3 R-P3.4: defection — the defector ignores coord and uses
        # its own policy directly (no shared seed, no role override).
        if self.defection_node_id is not None and node_id == self.defection_node_id:
            return {
                "policy": "defected",
                "role": "defector",
                "leader_id": self.leader_node_id,
                "effective_family": own_policy.family,
                "effective_strategy": own_policy.strategy,
                "effective_params": dict(own_policy.params),
                # NOTE: deliberately no shared_exclusion_seed -> Rust falls back to block-derived.
            }
        if self.coordination_policy == "leader":
            leader_policy = self.policies[self.leader_node_id] if self.leader_node_id is not None else own_policy
            is_leader = node_id == self.leader_node_id
            # P3 mechanism: synchronized exclusion-coin seed.
            #
            # We hash `(self.seed, round, leader_id)` to produce a 64-bit
            # seed that is identical for every Byzantine node in the same
            # group (since all share the same leader_id) but varies per
            # round. The Rust fissure hook uses this seed to drive the
            # exclusion-probability coin flip when present, so every
            # Byzantine node either-all-excludes or none-excludes a given
            # victim block on a given round.
            h = hashlib.sha256()
            h.update(struct.pack(">qqq", int(self.seed), int(round_), int(self.leader_node_id or 0)))
            shared_seed = int.from_bytes(h.digest()[:8], "big")
            return {
                "policy": "leader",
                "role": "leader" if is_leader else "follower",
                "leader_id": self.leader_node_id,
                "action": "propose" if is_leader else "mirror",
                # Followers adopt the leader's (family, strategy):
                "effective_family": leader_policy.family,
                "effective_strategy": leader_policy.strategy,
                "effective_params": dict(leader_policy.params),
                # P3: synchronized exclusion-coin seed.
                "shared_exclusion_seed": shared_seed,
            }
        if self.coordination_policy == "role_specialization":
            # Each Byzantine node keeps its assigned policy; the coordinator
            # exists to *confirm* the role and (optionally) order group actions.
            # For now we just echo the per-node policy plus its group id.
            return {
                "policy": "role_specialization",
                "role": own_policy.group_id,
                "effective_family": own_policy.family,
                "effective_strategy": own_policy.strategy,
                "effective_params": dict(own_policy.params),
            }
        if self.coordination_policy == "rr_slot":
            order = self.byzantine_node_ids
            if not order:
                raise RuntimeError("no Byzantine nodes registered")
            active_idx = (round_ + self.seed) % len(order)
            active_id = order[active_idx]
            is_active = node_id == active_id
            return {
                "policy": "rr_slot",
                "role": "active" if is_active else "passive",
                "active_id": active_id,
                "effective_family": own_policy.family if is_active else None,
                "effective_strategy": own_policy.strategy if is_active else None,
                "effective_params": dict(own_policy.params) if is_active else {},
            }
        raise RuntimeError(f"unhandled coordination_policy {self.coordination_policy!r}")

    def victim_profit(self, round_: int, author: int) -> float:
        with self._lock:
            if self.victim_profile is None:
                raise RuntimeError("no victim_profile configured for this run")
            return self.victim_profile.profit_for_block(int(round_), int(author))

    def metrics_snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "initialized": self.initialized,
                "coordination_policy": self.coordination_policy,
                "information": self.information,
                "byzantine_node_ids": list(self.byzantine_node_ids),
                "leader_node_id": self.leader_node_id,
                "rounds_with_shares": sorted(self.dag_views.keys()),
                "decisions_made": len(self.decisions),
                "victim_profile": (
                    {
                        "distribution": self.victim_profile.distribution,
                        "params": dict(self.victim_profile.params),
                        "seed": self.victim_profile.seed,
                    }
                    if self.victim_profile
                    else None
                ),
                "briber_ledger": (
                    self.briber.ledger_snapshot() if self.briber else None
                ),
            }


# ---------------------------------------------------------------------------
# HTTP server
# ---------------------------------------------------------------------------


def _make_handler(state: CoordinatorState):
    class Handler(BaseHTTPRequestHandler):
        # Quiet the default access log; the sweeper does its own logging.
        def log_message(self, fmt, *args):  # noqa: N802
            logger.debug("coord %s - " + fmt, self.address_string(), *args)

        def _read_json(self) -> dict:
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length) if length else b""
            if not body:
                return {}
            try:
                return json.loads(body.decode())
            except json.JSONDecodeError as e:
                raise ValueError(f"invalid JSON: {e}") from e

        def _send(self, code: int, payload: dict) -> None:
            body = json.dumps(payload).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):  # noqa: N802
            if self.path == "/health":
                return self._send(200, {"ok": True, "initialized": state.initialized})
            if self.path == "/metrics":
                return self._send(200, state.metrics_snapshot())
            if self.path == "/bribery/ledger":
                if state.briber is None:
                    return self._send(409, {"error": "no briber configured for this run"})
                return self._send(200, state.briber.ledger_snapshot())
            return self._send(404, {"error": f"unknown path {self.path}"})

        def do_POST(self):  # noqa: N802
            try:
                body = self._read_json()
            except ValueError as e:
                return self._send(400, {"error": str(e)})
            try:
                if self.path == "/init":
                    return self._handle_init(body)
                if not state.initialized:
                    return self._send(409, {"error": "coordinator not initialized"})
                if self.path == "/policy/lookup":
                    return self._handle_policy_lookup(body)
                if self.path == "/dag/share":
                    return self._handle_dag_share(body)
                if self.path == "/dag/view":
                    return self._handle_dag_view(body)
                if self.path == "/coordinate/decision":
                    return self._handle_decision(body)
                if self.path == "/victim/profit":
                    return self._handle_victim_profit(body)
                if self.path == "/bribery/offer":
                    return self._handle_bribery_offer(body)
                if self.path == "/bribery/decide":
                    return self._handle_bribery_decide(body)
                if self.path == "/bribery/accept":
                    return self._handle_bribery_accept(body)
                if self.path == "/bribery/settle":
                    return self._handle_bribery_settle(body)
                if self.path == "/bribery/pending":
                    return self._handle_bribery_pending(body)
                return self._send(404, {"error": f"unknown path {self.path}"})
            except KeyError as e:
                return self._send(404, {"error": str(e)})
            except ValueError as e:
                return self._send(400, {"error": str(e)})
            except Exception as e:  # noqa: BLE001
                logger.exception("coordinator internal error")
                return self._send(500, {"error": f"internal: {e}"})

        def _handle_init(self, body: dict) -> None:
            policies_raw = body.get("policies") or []
            policies = [
                PolicySpec(
                    group_id=str(p["group_id"]),
                    members=tuple(int(m) for m in p["members"]),
                    family=str(p["family"]),
                    strategy=str(p["strategy"]),
                    params=dict(p.get("params") or {}),
                )
                for p in policies_raw
            ]
            seed = int(body.get("seed", 0))
            victim_profile = None
            vp_raw = body.get("victim_profile")
            if vp_raw:
                victim_profile = VictimProfile(
                    distribution=str(vp_raw.get("distribution", "uniform")),
                    params=dict(vp_raw.get("params") or {}),
                    seed=int(vp_raw.get("seed", seed)),
                )
            briber = None
            br_raw = body.get("briber")
            if br_raw:
                response_policy = HonestResponsePolicy(
                    name=str(br_raw.get("response_policy", "reject_all")),
                    params=dict(br_raw.get("response_policy_params") or {}),
                    seed=int(br_raw.get("seed", seed)),
                )
                briber = BriberState(
                    type=str(br_raw.get("type", "guided")),
                    settlement=str(br_raw.get("settlement", "simulated")),
                    budget_total=float(br_raw.get("budget", 0.0)),
                    response_policy=response_policy,
                    bribed_honest=frozenset(
                        int(n) for n in (br_raw.get("bribed_honest") or [])
                    ),
                )
            state.init_from_policies(
                policies=policies,
                coordination_policy=str(body.get("coordination_policy", "role_specialization")),
                information=str(body.get("information", "local_dag_union")),
                seed=seed,
                leader_node_id=body.get("leader_node_id"),
                victim_profile=victim_profile,
                briber=briber,
                defection_node_id=body.get("defection_node_id"),
            )
            self._send(200, {"ok": True})

        def _handle_policy_lookup(self, body: dict) -> None:
            node_id = int(body["node_id"])
            policy = state.lookup_policy(node_id)
            if policy is None:
                return self._send(404, {"error": f"node {node_id} is not Byzantine"})
            self._send(
                200,
                {
                    "node_id": node_id,
                    "group_id": policy.group_id,
                    "family": policy.family,
                    "strategy": policy.strategy,
                    "params": dict(policy.params),
                },
            )

        def _handle_dag_share(self, body: dict) -> None:
            state.share_view(
                node_id=int(body["node_id"]),
                round_=int(body["round"]),
                blocks=list(body.get("blocks") or []),
            )
            self._send(200, {"ok": True})

        def _handle_dag_view(self, body: dict) -> None:
            blocks = state.view_for(
                node_id=int(body["node_id"]), round_=int(body["round"])
            )
            self._send(
                200,
                {
                    "node_id": int(body["node_id"]),
                    "round": int(body["round"]),
                    "information": state.information,
                    "blocks": blocks,
                },
            )

        def _handle_decision(self, body: dict) -> None:
            decision = state.decide(
                node_id=int(body["node_id"]), round_=int(body["round"])
            )
            self._send(200, decision)

        def _handle_victim_profit(self, body: dict) -> None:
            if state.victim_profile is None:
                return self._send(
                    409, {"error": "no victim_profile configured for this run"}
                )
            profit = state.victim_profit(
                round_=int(body["round"]), author=int(body["author"])
            )
            self._send(
                200,
                {
                    "round": int(body["round"]),
                    "author": int(body["author"]),
                    "profit": profit,
                    "distribution": state.victim_profile.distribution,
                },
            )

        # ---- bribery endpoints --------------------------------------------

        def _require_briber(self) -> Optional[bool]:
            """Send 409 and return False when no briber is configured."""
            if state.briber is None:
                self._send(409, {"error": "no briber configured for this run"})
                return False
            return True

        def _handle_bribery_offer(self, body: dict) -> None:
            if not self._require_briber():
                return
            try:
                offer = state.briber.publish_offer(
                    recipient_node_id=int(body["recipient_node_id"]),
                    infraction=str(body["infraction"]),
                    target=dict(body.get("target") or {}),
                    payment=float(body["payment"]),
                    type_=body.get("type"),
                )
            except Exception as e:  # BriberyError, ValueError
                return self._send(400, {"error": str(e)})
            self._send(
                200,
                {
                    "offer_id": offer.offer_id,
                    "recipient_node_id": offer.recipient_node_id,
                    "infraction": offer.infraction,
                    "target": dict(offer.target),
                    "payment": offer.payment,
                    "type": offer.type,
                },
            )

        def _handle_bribery_decide(self, body: dict) -> None:
            if not self._require_briber():
                return
            try:
                accept = state.briber.decide(
                    offer_id=str(body["offer_id"]),
                    node_id=int(body["node_id"]),
                )
            except Exception as e:
                return self._send(400, {"error": str(e)})
            self._send(200, {"accept": bool(accept)})

        def _handle_bribery_accept(self, body: dict) -> None:
            if not self._require_briber():
                return
            try:
                record = state.briber.accept(
                    offer_id=str(body["offer_id"]),
                    node_id=int(body["node_id"]),
                    evidence=body.get("evidence") or {},
                )
            except Exception as e:
                return self._send(400, {"error": str(e)})
            self._send(
                200,
                {
                    "offer_id": record.offer_id,
                    "node_id": record.node_id,
                    "tick": record.tick,
                    "evidence": dict(record.evidence),
                },
            )

        def _handle_bribery_settle(self, body: dict) -> None:
            if not self._require_briber():
                return
            try:
                record = state.briber.settle(
                    offer_id=str(body["offer_id"]),
                    attack_succeeded=bool(body.get("attack_succeeded", False)),
                )
            except Exception as e:
                return self._send(400, {"error": str(e)})
            self._send(
                200,
                {
                    "offer_id": record.offer_id,
                    "outcome": record.outcome,
                    "amount": record.amount,
                },
            )

        def _handle_bribery_pending(self, body: dict) -> None:
            """R-P4.1: honest-side discovery of pending offers."""
            if state.briber is None:
                # Honest nodes should not see 409 here; just return 404 so
                # the fast-path "no bribery configured" is silent.
                return self._send(404, {"error": "no pending offer"})
            try:
                node_id = int(body["node_id"])
            except (KeyError, ValueError):
                return self._send(400, {"error": "node_id required"})
            offer = state.briber.pending_offer_for(node_id)
            if offer is None:
                return self._send(404, {"error": "no pending offer"})
            self._send(
                200,
                {
                    "offer_id": offer.offer_id,
                    "recipient_node_id": offer.recipient_node_id,
                    "infraction": offer.infraction,
                    "target": dict(offer.target),
                    "payment": offer.payment,
                    "type": offer.type,
                },
            )

    return Handler


@dataclasses.dataclass
class CoordinatorServer:
    """Wraps a ThreadingHTTPServer + worker thread for clean start/stop."""

    state: CoordinatorState
    host: str = "127.0.0.1"
    port: int = 0  # 0 = pick free port; actual_port populated after start
    _server: Optional[ThreadingHTTPServer] = None
    _thread: Optional[threading.Thread] = None
    actual_port: int = 0

    def start(self) -> None:
        if self._server is not None:
            raise RuntimeError("CoordinatorServer already running")
        handler = _make_handler(self.state)
        self._server = ThreadingHTTPServer((self.host, self.port), handler)
        self.actual_port = self._server.server_address[1]
        self._thread = threading.Thread(
            target=self._server.serve_forever, name="v2-coordinator", daemon=True
        )
        self._thread.start()
        logger.info("coordinator listening on http://%s:%d", self.host, self.actual_port)

    def stop(self, timeout: float = 5.0) -> None:
        if self._server is None:
            return
        self._server.shutdown()
        self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
        self._server = None
        self._thread = None

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.actual_port}"

    def __enter__(self) -> "CoordinatorServer":
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.stop()
