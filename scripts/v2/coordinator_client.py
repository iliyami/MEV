"""Reference Python client for the Coordinator HTTP service.

Used by tests and the Python-side toy harness. Also serves as the canonical
spec for a Rust client that will live inside the Bullshark fork's attacker
hooks (P1a.3 wiring task).
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Optional


class CoordinatorClientError(RuntimeError):
    def __init__(self, status: int, body: str) -> None:
        super().__init__(f"coordinator HTTP {status}: {body}")
        self.status = status
        self.body = body


@dataclass
class CoordinatorClient:
    url: str
    timeout_sec: float = 5.0

    def _post(self, path: str, body: dict) -> dict:
        data = json.dumps(body).encode()
        req = urllib.request.Request(
            self.url + path,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_sec) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            raise CoordinatorClientError(e.code, e.read().decode("utf-8", "replace"))

    def _get(self, path: str) -> dict:
        req = urllib.request.Request(self.url + path, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_sec) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            raise CoordinatorClientError(e.code, e.read().decode("utf-8", "replace"))

    # ---- public api --------------------------------------------------------

    def init(
        self,
        policies: list[dict],
        coordination_policy: str = "role_specialization",
        information: str = "local_dag_union",
        seed: int = 0,
        leader_node_id: Optional[int] = None,
        victim_profile: Optional[dict] = None,
        briber: Optional[dict] = None,
        defection_node_id: Optional[int] = None,
    ) -> dict:
        body: dict[str, Any] = {
            "policies": policies,
            "coordination_policy": coordination_policy,
            "information": information,
            "seed": seed,
        }
        if leader_node_id is not None:
            body["leader_node_id"] = leader_node_id
        if victim_profile is not None:
            body["victim_profile"] = victim_profile
        if briber is not None:
            body["briber"] = briber
        if defection_node_id is not None:
            body["defection_node_id"] = defection_node_id
        return self._post("/init", body)

    def health(self) -> dict:
        return self._get("/health")

    def metrics(self) -> dict:
        return self._get("/metrics")

    def policy_lookup(self, node_id: int) -> dict:
        return self._post("/policy/lookup", {"node_id": node_id})

    def share_view(self, node_id: int, round_: int, blocks: list[str]) -> dict:
        return self._post(
            "/dag/share", {"node_id": node_id, "round": round_, "blocks": blocks}
        )

    def view_for(self, node_id: int, round_: int) -> dict:
        return self._post("/dag/view", {"node_id": node_id, "round": round_})

    def decision(self, node_id: int, round_: int) -> dict:
        return self._post(
            "/coordinate/decision", {"node_id": node_id, "round": round_}
        )

    def victim_profit(self, round_: int, author: int) -> dict:
        return self._post("/victim/profit", {"round": round_, "author": author})

    # ---- bribery endpoints -------------------------------------------------

    def bribery_offer(
        self,
        recipient_node_id: int,
        infraction: str,
        target: dict,
        payment: float,
        type_: Optional[str] = None,
    ) -> dict:
        body: dict[str, Any] = {
            "recipient_node_id": recipient_node_id,
            "infraction": infraction,
            "target": target,
            "payment": payment,
        }
        if type_ is not None:
            body["type"] = type_
        return self._post("/bribery/offer", body)

    def bribery_decide(self, offer_id: str, node_id: int) -> dict:
        return self._post(
            "/bribery/decide", {"offer_id": offer_id, "node_id": node_id}
        )

    def bribery_accept(
        self, offer_id: str, node_id: int, evidence: Optional[dict] = None
    ) -> dict:
        body: dict[str, Any] = {"offer_id": offer_id, "node_id": node_id}
        if evidence is not None:
            body["evidence"] = evidence
        return self._post("/bribery/accept", body)

    def bribery_settle(self, offer_id: str, attack_succeeded: bool) -> dict:
        return self._post(
            "/bribery/settle",
            {"offer_id": offer_id, "attack_succeeded": attack_succeeded},
        )

    def bribery_ledger(self) -> dict:
        return self._get("/bribery/ledger")

    def bribery_pending(self, node_id: int) -> Optional[dict]:
        """R-P4.1: query a pending offer for `node_id` or None (404)."""
        try:
            return self._post("/bribery/pending", {"node_id": node_id})
        except CoordinatorClientError as e:
            if e.status == 404:
                return None
            raise
