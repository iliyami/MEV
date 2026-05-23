"""Briber subsystem — simulated bribery settlement for the Bullshark phase.

Threat model (see CLAUDE.md + paper_workspace/plan_v2.md §0):

  * Bribery in this paper *never* induces an honest node to sign an invalid
    message or violate protocol rules. The bribed honest node, when it
    accepts an offer, performs a choice from its already-legitimate action
    set (e.g., which subset of valid parent references to include) that
    happens to favor the briber.
  * The Briber subsystem here only models the **economic** half of bribery:
    publishing offers, deciding acceptance, escrowing/paying out the budget.
    The actual choice-of-legitimate-action is enforced by the protocol's
    own validity rules at the point the bribed node acts.

Two bribery types per Karakostas et al. 2024 §guided vs effective:

  * **guided**: payment is owed when the bribed node performs the named
    infraction (we settle at /bribery/accept).
  * **effective**: payment is owed only if the targeted attack succeeds
    (settled by an explicit /bribery/settle call from the run harness).

Three response policies the bribed honest node uses to decide on offers:

  * `always_above_X`: accept iff `offer.payment > params["threshold"]`.
  * `prob_p`: accept with probability `params["p"]`, deterministic via
    `hash(seed, offer_id, node_id)`.
  * `reject_all`: control. Lets us A/B-test "bribery on vs bribery effectively
    off" within the same run.

Bullshark phase: settlement is a Python-side in-memory ledger.
Sui phase (deferred per plan_v2.md §8 P7+): the same offer/decide/accept/settle
contract is implemented by a Move escrow contract on Sui testnet, swapped in
behind the same coordinator endpoints.
"""

from __future__ import annotations

import dataclasses
import hashlib
import struct
import threading
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional


BRIBERY_TYPES = ("guided", "effective")
RESPONSE_POLICIES = ("always_above_X", "prob_p", "reject_all")
SETTLEMENT_MODES = ("simulated", "move")  # "move" reserved for the Sui phase
INFRACTIONS = (
    "omit_reference",
    "delay_broadcast",
    "select_candidate",
    # v3 R-P4.1: behavioural no-op (accounting only). Used in P4 v3 cells
    # to study budget/ledger dynamics without altering honest behaviour;
    # the Rust hook treats this as a no-op (preserves invariant).
    "gas_style_incentive",
)


class BriberyError(RuntimeError):
    """Raised on invalid state transitions or budget violations."""


# ---------------------------------------------------------------------------
# Data records
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BriberyOffer:
    offer_id: str
    recipient_node_id: int
    infraction: str
    target: dict[str, Any]
    payment: float
    type: str  # "guided" | "effective"


@dataclass(frozen=True)
class AcceptanceRecord:
    offer_id: str
    node_id: int
    evidence: dict[str, Any]
    tick: int


@dataclass(frozen=True)
class SettlementRecord:
    offer_id: str
    outcome: str  # "paid" | "released"
    amount: float


# ---------------------------------------------------------------------------
# Honest response policy
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HonestResponsePolicy:
    name: str
    params: dict[str, Any] = field(default_factory=dict)
    seed: int = 0

    def __post_init__(self) -> None:
        if self.name not in RESPONSE_POLICIES:
            raise ValueError(
                f"unknown response policy {self.name!r}; expected {RESPONSE_POLICIES}"
            )

    def decide(self, offer: BriberyOffer, node_id: int) -> bool:
        if self.name == "reject_all":
            return False
        if self.name == "always_above_X":
            threshold = float(self.params.get("threshold", 0.0))
            return offer.payment > threshold
        if self.name == "prob_p":
            p = float(self.params.get("p", 0.0))
            if p <= 0.0:
                return False
            if p >= 1.0:
                return True
            # Deterministic accept-or-not based on (seed, offer_id, node_id).
            # Hash → u in [0, 1); accept iff u < p.
            h = hashlib.sha256()
            h.update(struct.pack(">q", int(self.seed)))
            h.update(offer.offer_id.encode("utf-8"))
            h.update(struct.pack(">q", int(node_id)))
            u = int.from_bytes(h.digest()[:8], "big") / float(1 << 64)
            return u < p
        raise RuntimeError(f"unhandled response policy {self.name!r}")


# ---------------------------------------------------------------------------
# Briber state (the in-memory ledger)
# ---------------------------------------------------------------------------


@dataclass
class BriberState:
    type: str  # default bribery type for offers that don't specify
    settlement: str  # "simulated" for the Bullshark phase
    budget_total: float
    response_policy: HonestResponsePolicy
    bribed_honest: frozenset[int] = frozenset()

    offers: dict[str, BriberyOffer] = field(default_factory=dict)
    acceptances: dict[str, AcceptanceRecord] = field(default_factory=dict)
    settlements: dict[str, SettlementRecord] = field(default_factory=dict)
    budget_escrowed: float = 0.0
    budget_paid: float = 0.0
    _tick: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def __post_init__(self) -> None:
        if self.type not in BRIBERY_TYPES:
            raise ValueError(f"unknown bribery type {self.type!r}; expected {BRIBERY_TYPES}")
        if self.settlement not in SETTLEMENT_MODES:
            raise ValueError(
                f"unknown settlement {self.settlement!r}; expected {SETTLEMENT_MODES}"
            )
        if self.settlement == "move":
            raise NotImplementedError(
                "Move-based settlement is reserved for the Sui phase (P7+)."
            )
        if self.budget_total < 0:
            raise ValueError(f"budget_total must be >= 0, got {self.budget_total}")

    @property
    def budget_remaining(self) -> float:
        return self.budget_total - self.budget_escrowed - self.budget_paid

    # ---- offer lifecycle ---------------------------------------------------

    def publish_offer(
        self,
        recipient_node_id: int,
        infraction: str,
        target: dict[str, Any],
        payment: float,
        type_: Optional[str] = None,
    ) -> BriberyOffer:
        if infraction not in INFRACTIONS:
            raise BriberyError(
                f"unknown infraction {infraction!r}; expected {INFRACTIONS}"
            )
        if payment <= 0:
            raise BriberyError(f"payment must be > 0, got {payment}")
        chosen_type = type_ or self.type
        if chosen_type not in BRIBERY_TYPES:
            raise BriberyError(f"unknown type {chosen_type!r}")
        with self._lock:
            if int(recipient_node_id) not in self.bribed_honest:
                raise BriberyError(
                    f"node {recipient_node_id} not in bribed_honest set "
                    f"({sorted(self.bribed_honest)})"
                )
            if payment > self.budget_remaining + 1e-9:
                raise BriberyError(
                    f"payment {payment} exceeds budget_remaining "
                    f"{self.budget_remaining:.4f}"
                )
            offer = BriberyOffer(
                offer_id=uuid.uuid4().hex[:16],
                recipient_node_id=int(recipient_node_id),
                infraction=infraction,
                target=dict(target),
                payment=float(payment),
                type=chosen_type,
            )
            self.offers[offer.offer_id] = offer
            self.budget_escrowed += offer.payment
            return offer

    def decide(self, offer_id: str, node_id: int) -> bool:
        """Apply the response policy to an offer. Pure read; no state change."""
        with self._lock:
            offer = self._get_offer(offer_id)
            if int(node_id) != offer.recipient_node_id:
                raise BriberyError(
                    f"node {node_id} cannot decide an offer addressed to "
                    f"{offer.recipient_node_id}"
                )
        # Decision is outside the lock: the response policy is pure.
        return self.response_policy.decide(offer, int(node_id))

    def accept(
        self, offer_id: str, node_id: int, evidence: Optional[dict] = None
    ) -> AcceptanceRecord:
        """Record acceptance. For guided: also settles immediately."""
        with self._lock:
            offer = self._get_offer(offer_id)
            if int(node_id) != offer.recipient_node_id:
                raise BriberyError(
                    f"node {node_id} cannot accept an offer addressed to "
                    f"{offer.recipient_node_id}"
                )
            if offer_id in self.acceptances:
                raise BriberyError(f"offer {offer_id} already accepted")
            if offer_id in self.settlements:
                raise BriberyError(f"offer {offer_id} already settled")
            self._tick += 1
            record = AcceptanceRecord(
                offer_id=offer_id,
                node_id=int(node_id),
                evidence=dict(evidence or {}),
                tick=self._tick,
            )
            self.acceptances[offer_id] = record
            if offer.type == "guided":
                # Pay out at acceptance.
                self._settle_locked(offer_id, "paid", offer.payment)
            return record

    def settle(self, offer_id: str, attack_succeeded: bool) -> SettlementRecord:
        """Effective bribery settlement.

        For type=guided: this is a no-op when already settled (acceptance
        already paid); attempts to re-settle a guided offer raise.
        For type=effective: attack_succeeded=True → paid; False → released
        (the escrow is returned to the budget).
        """
        with self._lock:
            offer = self._get_offer(offer_id)
            if offer.type == "guided":
                if offer_id in self.settlements:
                    return self.settlements[offer_id]
                raise BriberyError(
                    f"guided offer {offer_id} cannot be effective-settled "
                    "(payment fires at acceptance)"
                )
            if offer_id not in self.acceptances:
                raise BriberyError(
                    f"offer {offer_id} cannot be settled before acceptance"
                )
            if offer_id in self.settlements:
                raise BriberyError(f"offer {offer_id} already settled")
            outcome = "paid" if attack_succeeded else "released"
            amount = offer.payment if attack_succeeded else 0.0
            return self._settle_locked(offer_id, outcome, amount)

    # ---- helpers -----------------------------------------------------------

    def _get_offer(self, offer_id: str) -> BriberyOffer:
        offer = self.offers.get(offer_id)
        if offer is None:
            raise BriberyError(f"unknown offer_id {offer_id!r}")
        return offer

    def _settle_locked(
        self, offer_id: str, outcome: str, amount: float
    ) -> SettlementRecord:
        # Caller holds the lock.
        offer = self.offers[offer_id]
        self.budget_escrowed -= offer.payment
        if outcome == "paid":
            self.budget_paid += amount
        # "released" case: escrow is returned to the budget; nothing else.
        record = SettlementRecord(offer_id=offer_id, outcome=outcome, amount=amount)
        self.settlements[offer_id] = record
        return record

    # ---- pending-offer lookup (R-P4.1) ------------------------------------

    def pending_offer_for(self, node_id: int) -> Optional[BriberyOffer]:
        """Return the first published-but-not-yet-accepted offer addressed to
        `node_id`, or None. Used by the Rust honest-side hook to discover
        offers without polling the global offer list."""
        with self._lock:
            for offer in self.offers.values():
                if offer.recipient_node_id == int(node_id) and offer.offer_id not in self.acceptances:
                    return offer
            return None

    # ---- read-only views ---------------------------------------------------

    def ledger_snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "type": self.type,
                "settlement": self.settlement,
                "budget_total": self.budget_total,
                "budget_escrowed": self.budget_escrowed,
                "budget_paid": self.budget_paid,
                "budget_remaining": self.budget_remaining,
                "n_offers": len(self.offers),
                "n_acceptances": len(self.acceptances),
                "n_settlements": len(self.settlements),
                "n_paid": sum(1 for s in self.settlements.values() if s.outcome == "paid"),
                "n_released": sum(
                    1 for s in self.settlements.values() if s.outcome == "released"
                ),
                "response_policy": {
                    "name": self.response_policy.name,
                    "params": dict(self.response_policy.params),
                    "seed": self.response_policy.seed,
                },
                "bribed_honest": sorted(self.bribed_honest),
            }
