"""Briber unit + HTTP tests.

Covers:
    * Response policies (always_above_X, prob_p determinism, reject_all)
    * Budget escrow + payout invariants
    * Guided vs effective settlement semantics
    * Ledger consistency
    * HTTP lifecycle: /init briber → /bribery/offer → /bribery/decide → accept → settle
"""

from __future__ import annotations

import pytest

from scripts.v2.briber import (
    BriberState,
    BriberyError,
    BriberyOffer,
    HonestResponsePolicy,
)
from scripts.v2.coordinator import CoordinatorServer, CoordinatorState
from scripts.v2.coordinator_client import CoordinatorClient, CoordinatorClientError


# ---------------------------------------------------------------------------
# Response policies
# ---------------------------------------------------------------------------


def _offer(payment: float = 10.0, recipient: int = 5, type_: str = "guided") -> BriberyOffer:
    return BriberyOffer(
        offer_id="o1",
        recipient_node_id=recipient,
        infraction="omit_reference",
        target={"victim_node_id": 11},
        payment=payment,
        type=type_,
    )


def test_reject_all_never_accepts():
    rp = HonestResponsePolicy(name="reject_all")
    assert rp.decide(_offer(payment=1_000_000), node_id=5) is False


def test_always_above_X_uses_threshold():
    rp = HonestResponsePolicy(name="always_above_X", params={"threshold": 5.0})
    assert rp.decide(_offer(payment=4.0), node_id=5) is False
    assert rp.decide(_offer(payment=5.0), node_id=5) is False  # strict >
    assert rp.decide(_offer(payment=5.01), node_id=5) is True


def test_always_above_X_default_threshold_is_zero():
    rp = HonestResponsePolicy(name="always_above_X")
    assert rp.decide(_offer(payment=0.01), node_id=5) is True


def test_prob_p_deterministic_under_same_seed():
    a = HonestResponsePolicy(name="prob_p", params={"p": 0.5}, seed=42)
    b = HonestResponsePolicy(name="prob_p", params={"p": 0.5}, seed=42)
    for nid in range(13):
        # use distinct offer_ids by re-constructing offers per node to vary the hash input
        offer = BriberyOffer(
            offer_id=f"o_{nid}",
            recipient_node_id=nid,
            infraction="omit_reference",
            target={},
            payment=10.0,
            type="guided",
        )
        assert a.decide(offer, nid) == b.decide(offer, nid)


def test_prob_p_extremes():
    rp_zero = HonestResponsePolicy(name="prob_p", params={"p": 0.0}, seed=0)
    rp_one = HonestResponsePolicy(name="prob_p", params={"p": 1.0}, seed=0)
    assert rp_zero.decide(_offer(), node_id=5) is False
    assert rp_one.decide(_offer(), node_id=5) is True


def test_prob_p_acceptance_rate_close_to_p():
    """100 trials at p=0.5 should land between 30 and 70 acceptances."""
    rp = HonestResponsePolicy(name="prob_p", params={"p": 0.5}, seed=0)
    accepts = 0
    for i in range(100):
        o = BriberyOffer(
            offer_id=f"o_{i}",
            recipient_node_id=5,
            infraction="omit_reference",
            target={},
            payment=10.0,
            type="guided",
        )
        if rp.decide(o, node_id=5):
            accepts += 1
    assert 30 <= accepts <= 70


def test_unknown_response_policy_rejected():
    with pytest.raises(ValueError, match="unknown response policy"):
        HonestResponsePolicy(name="bayesian_optimal")


# ---------------------------------------------------------------------------
# BriberState lifecycle
# ---------------------------------------------------------------------------


def _state(
    type_: str = "guided",
    budget: float = 100.0,
    policy_name: str = "always_above_X",
    policy_params: dict | None = None,
    bribed_honest: tuple[int, ...] = (5, 7),
) -> BriberState:
    return BriberState(
        type=type_,
        settlement="simulated",
        budget_total=budget,
        response_policy=HonestResponsePolicy(
            name=policy_name, params=policy_params or {}
        ),
        bribed_honest=frozenset(bribed_honest),
    )


def test_publish_offer_escrows_budget():
    s = _state()
    o = s.publish_offer(
        recipient_node_id=5,
        infraction="omit_reference",
        target={"victim_node_id": 11},
        payment=10.0,
    )
    assert s.budget_escrowed == 10.0
    assert s.budget_paid == 0.0
    assert s.budget_remaining == 90.0
    assert o.recipient_node_id == 5


def test_publish_offer_rejects_unknown_infraction():
    s = _state()
    with pytest.raises(BriberyError, match="unknown infraction"):
        s.publish_offer(
            recipient_node_id=5,
            infraction="invalidate_signature",  # not a legitimate-action choice
            target={},
            payment=10.0,
        )


def test_publish_offer_rejects_non_eligible_recipient():
    s = _state(bribed_honest=(5,))
    with pytest.raises(BriberyError, match="not in bribed_honest set"):
        s.publish_offer(
            recipient_node_id=7,
            infraction="omit_reference",
            target={},
            payment=10.0,
        )


def test_publish_offer_rejects_over_budget():
    s = _state(budget=10.0)
    s.publish_offer(
        recipient_node_id=5, infraction="omit_reference", target={}, payment=8.0
    )
    with pytest.raises(BriberyError, match="exceeds budget_remaining"):
        s.publish_offer(
            recipient_node_id=5, infraction="omit_reference", target={}, payment=5.0
        )


def test_publish_offer_rejects_zero_or_negative_payment():
    s = _state()
    with pytest.raises(BriberyError, match="payment must be"):
        s.publish_offer(
            recipient_node_id=5, infraction="omit_reference", target={}, payment=0.0
        )


def test_guided_acceptance_settles_immediately():
    s = _state(type_="guided")
    o = s.publish_offer(
        recipient_node_id=5, infraction="omit_reference", target={}, payment=10.0
    )
    s.accept(offer_id=o.offer_id, node_id=5)
    assert s.budget_escrowed == 0.0
    assert s.budget_paid == 10.0
    assert s.budget_remaining == 90.0
    settled = s.settlements[o.offer_id]
    assert settled.outcome == "paid"
    assert settled.amount == 10.0


def test_effective_acceptance_does_not_settle():
    s = _state(type_="effective")
    o = s.publish_offer(
        recipient_node_id=5, infraction="omit_reference", target={}, payment=10.0
    )
    s.accept(offer_id=o.offer_id, node_id=5)
    # Budget still escrowed; not yet paid.
    assert s.budget_escrowed == 10.0
    assert s.budget_paid == 0.0


def test_effective_settle_paid_on_success():
    s = _state(type_="effective")
    o = s.publish_offer(
        recipient_node_id=5, infraction="omit_reference", target={}, payment=10.0
    )
    s.accept(offer_id=o.offer_id, node_id=5)
    s.settle(offer_id=o.offer_id, attack_succeeded=True)
    assert s.budget_escrowed == 0.0
    assert s.budget_paid == 10.0


def test_effective_settle_released_on_failure():
    s = _state(type_="effective")
    o = s.publish_offer(
        recipient_node_id=5, infraction="omit_reference", target={}, payment=10.0
    )
    s.accept(offer_id=o.offer_id, node_id=5)
    s.settle(offer_id=o.offer_id, attack_succeeded=False)
    assert s.budget_escrowed == 0.0
    assert s.budget_paid == 0.0
    # Budget is fully recovered:
    assert s.budget_remaining == s.budget_total


def test_double_accept_rejected():
    s = _state(type_="effective")
    o = s.publish_offer(
        recipient_node_id=5, infraction="omit_reference", target={}, payment=10.0
    )
    s.accept(offer_id=o.offer_id, node_id=5)
    with pytest.raises(BriberyError, match="already accepted"):
        s.accept(offer_id=o.offer_id, node_id=5)


def test_settle_before_accept_rejected():
    s = _state(type_="effective")
    o = s.publish_offer(
        recipient_node_id=5, infraction="omit_reference", target={}, payment=10.0
    )
    with pytest.raises(BriberyError, match="before acceptance"):
        s.settle(offer_id=o.offer_id, attack_succeeded=True)


def test_settle_guided_is_noop_after_acceptance():
    s = _state(type_="guided")
    o = s.publish_offer(
        recipient_node_id=5, infraction="omit_reference", target={}, payment=10.0
    )
    s.accept(offer_id=o.offer_id, node_id=5)
    # idempotent: returns the existing record
    r = s.settle(offer_id=o.offer_id, attack_succeeded=True)
    assert r.outcome == "paid"


def test_accept_by_wrong_node_rejected():
    s = _state(bribed_honest=(5, 7))
    o = s.publish_offer(
        recipient_node_id=5, infraction="omit_reference", target={}, payment=10.0
    )
    with pytest.raises(BriberyError, match="cannot accept"):
        s.accept(offer_id=o.offer_id, node_id=7)


def test_decide_uses_configured_policy():
    s = _state(
        policy_name="always_above_X", policy_params={"threshold": 5.0}
    )
    o = s.publish_offer(
        recipient_node_id=5, infraction="omit_reference", target={}, payment=4.0
    )
    assert s.decide(offer_id=o.offer_id, node_id=5) is False


def test_move_settlement_rejected_during_bullshark_phase():
    with pytest.raises(NotImplementedError):
        BriberState(
            type="effective",
            settlement="move",
            budget_total=10.0,
            response_policy=HonestResponsePolicy(name="reject_all"),
        )


def test_ledger_snapshot_counts():
    s = _state(type_="effective", budget=100.0)
    o1 = s.publish_offer(
        recipient_node_id=5, infraction="omit_reference", target={}, payment=10.0
    )
    o2 = s.publish_offer(
        recipient_node_id=7, infraction="delay_broadcast", target={}, payment=20.0
    )
    s.accept(o1.offer_id, 5)
    s.accept(o2.offer_id, 7)
    s.settle(o1.offer_id, attack_succeeded=True)
    s.settle(o2.offer_id, attack_succeeded=False)
    snap = s.ledger_snapshot()
    assert snap["n_offers"] == 2
    assert snap["n_acceptances"] == 2
    assert snap["n_settlements"] == 2
    assert snap["n_paid"] == 1
    assert snap["n_released"] == 1
    assert snap["budget_paid"] == 10.0


# ---------------------------------------------------------------------------
# Coordinator HTTP integration
# ---------------------------------------------------------------------------


def _start_server_with_briber(
    type_: str = "guided",
    response_policy: str = "always_above_X",
    response_params: dict | None = None,
    bribed_honest: list[int] | None = None,
) -> tuple[CoordinatorServer, CoordinatorClient]:
    state = CoordinatorState()
    server = CoordinatorServer(state=state)
    server.start()
    client = CoordinatorClient(server.url)
    client.init(
        policies=[
            {
                "group_id": "g0",
                "members": [3],
                "family": "frontrun",
                "strategy": "fissure",
                "params": {},
            }
        ],
        coordination_policy="role_specialization",
        information="local_dag_union",
        seed=42,
        briber={
            "type": type_,
            "settlement": "simulated",
            "budget": 100.0,
            "response_policy": response_policy,
            "response_policy_params": response_params or {},
            "bribed_honest": bribed_honest or [5, 7],
        },
    )
    return server, client


def test_http_bribery_disabled_returns_409():
    state = CoordinatorState()
    server = CoordinatorServer(state=state)
    server.start()
    try:
        client = CoordinatorClient(server.url)
        client.init(
            policies=[
                {"group_id": "g0", "members": [3], "family": "frontrun", "strategy": "fissure", "params": {}}
            ],
            coordination_policy="role_specialization",
            information="local_dag_union",
        )
        with pytest.raises(CoordinatorClientError) as ei:
            client.bribery_offer(
                recipient_node_id=5,
                infraction="omit_reference",
                target={},
                payment=10.0,
            )
        assert ei.value.status == 409
    finally:
        server.stop()


def test_http_guided_lifecycle():
    server, client = _start_server_with_briber(
        type_="guided",
        response_policy="always_above_X",
        response_params={"threshold": 0.0},
    )
    try:
        r = client.bribery_offer(
            recipient_node_id=5,
            infraction="omit_reference",
            target={"victim_node_id": 11},
            payment=10.0,
        )
        offer_id = r["offer_id"]
        assert client.bribery_decide(offer_id=offer_id, node_id=5)["accept"] is True
        client.bribery_accept(offer_id=offer_id, node_id=5, evidence={"omitted_round": 5})
        ledger = client.bribery_ledger()
        assert ledger["n_paid"] == 1
        assert ledger["budget_paid"] == 10.0
    finally:
        server.stop()


def test_http_effective_lifecycle_paid_on_success():
    server, client = _start_server_with_briber(
        type_="effective",
        response_policy="always_above_X",
        response_params={"threshold": 0.0},
    )
    try:
        r = client.bribery_offer(
            recipient_node_id=5,
            infraction="omit_reference",
            target={},
            payment=10.0,
        )
        client.bribery_accept(offer_id=r["offer_id"], node_id=5)
        settled = client.bribery_settle(
            offer_id=r["offer_id"], attack_succeeded=True
        )
        assert settled["outcome"] == "paid"
        ledger = client.bribery_ledger()
        assert ledger["budget_paid"] == 10.0
    finally:
        server.stop()


def test_http_effective_lifecycle_released_on_failure():
    server, client = _start_server_with_briber(
        type_="effective",
        response_policy="always_above_X",
        response_params={"threshold": 0.0},
    )
    try:
        r = client.bribery_offer(
            recipient_node_id=5,
            infraction="omit_reference",
            target={},
            payment=10.0,
        )
        client.bribery_accept(offer_id=r["offer_id"], node_id=5)
        settled = client.bribery_settle(
            offer_id=r["offer_id"], attack_succeeded=False
        )
        assert settled["outcome"] == "released"
        ledger = client.bribery_ledger()
        assert ledger["budget_paid"] == 0.0
        assert ledger["budget_remaining"] == ledger["budget_total"]
    finally:
        server.stop()


def test_http_decide_rejects_under_reject_all_policy():
    server, client = _start_server_with_briber(
        type_="guided", response_policy="reject_all"
    )
    try:
        r = client.bribery_offer(
            recipient_node_id=5, infraction="omit_reference", target={}, payment=10.0
        )
        decision = client.bribery_decide(offer_id=r["offer_id"], node_id=5)
        assert decision["accept"] is False
        # Briber still tracks the offer, but node never accepts.
        ledger = client.bribery_ledger()
        assert ledger["n_acceptances"] == 0
        assert ledger["budget_escrowed"] == 10.0
    finally:
        server.stop()


def test_http_metrics_snapshot_includes_briber_ledger():
    server, client = _start_server_with_briber()
    try:
        m = client.metrics()
        assert m["briber_ledger"] is not None
        assert m["briber_ledger"]["budget_total"] == 100.0
    finally:
        server.stop()


def test_pending_offer_for_returns_unaccepted():
    """R-P4.1: pending_offer_for returns the first unaccepted offer for the node."""
    s = _state()
    o1 = s.publish_offer(
        recipient_node_id=5, infraction="omit_reference", target={}, payment=10.0
    )
    pending = s.pending_offer_for(5)
    assert pending is not None
    assert pending.offer_id == o1.offer_id
    # Accept it; pending should now be None
    s.accept(offer_id=o1.offer_id, node_id=5)
    assert s.pending_offer_for(5) is None


def test_pending_offer_for_returns_none_for_no_offers():
    s = _state()
    assert s.pending_offer_for(5) is None


def test_pending_offer_for_filters_by_recipient():
    s = _state(bribed_honest=(5, 7))
    s.publish_offer(
        recipient_node_id=5, infraction="omit_reference", target={}, payment=10.0
    )
    o7 = s.publish_offer(
        recipient_node_id=7, infraction="delay_broadcast", target={}, payment=15.0
    )
    pending_7 = s.pending_offer_for(7)
    assert pending_7 is not None
    assert pending_7.offer_id == o7.offer_id


def test_http_bribery_pending_returns_offer():
    """R-P4.1 HTTP integration: /bribery/pending returns the pending offer."""
    server, client = _start_server_with_briber()
    try:
        offer_resp = client.bribery_offer(
            recipient_node_id=5,
            infraction="omit_reference",
            target={"target_victim_id": 11},
            payment=10.0,
        )
        pending = client.bribery_pending(node_id=5)
        assert pending is not None
        assert pending["offer_id"] == offer_resp["offer_id"]
        assert pending["infraction"] == "omit_reference"
    finally:
        server.stop()


def test_http_bribery_pending_returns_none_for_node_without_offer():
    server, client = _start_server_with_briber()
    try:
        client.bribery_offer(
            recipient_node_id=5, infraction="omit_reference", target={}, payment=10.0
        )
        # node 7 is bribed_honest but has no pending offer
        assert client.bribery_pending(node_id=7) is None
    finally:
        server.stop()


def test_http_bribery_pending_returns_none_without_briber_configured():
    """When no briber is configured, /bribery/pending returns 404 silently."""
    state = CoordinatorState()
    server = CoordinatorServer(state=state)
    server.start()
    try:
        client = CoordinatorClient(server.url)
        client.init(
            policies=[
                {"group_id": "g0", "members": [3], "family": "frontrun", "strategy": "fissure", "params": {}}
            ],
            coordination_policy="role_specialization",
            information="local_dag_union",
        )
        # No briber configured → 404
        assert client.bribery_pending(node_id=5) is None
    finally:
        server.stop()
