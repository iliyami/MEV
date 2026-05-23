"""Coordinator service tests — in-process state tests + end-to-end HTTP tests."""

from __future__ import annotations

import pytest

from scripts.v2.coordinator import CoordinatorServer, CoordinatorState
from scripts.v2.coordinator_client import CoordinatorClient, CoordinatorClientError
from scripts.v2.schema import PolicySpec


# ---------------------------------------------------------------------------
# In-process state tests (no HTTP)
# ---------------------------------------------------------------------------


def _ps(group_id, members, family, strategy, **params):
    return PolicySpec(
        group_id=group_id,
        members=tuple(members),
        family=family,
        strategy=strategy,
        params=params,
    )


def test_init_populates_byzantine_set_and_leader():
    s = CoordinatorState()
    s.init_from_policies(
        policies=[
            _ps("g1", [3, 5], "frontrun", "fissure"),
            _ps("g2", [7], "backrun", "sluggish"),
        ],
        coordination_policy="leader",
        information="local_dag_union",
    )
    assert s.initialized is True
    assert s.byzantine_node_ids == (3, 5, 7)
    # default leader = smallest Byzantine id
    assert s.leader_node_id == 3


def test_init_explicit_leader_validates_membership():
    s = CoordinatorState()
    with pytest.raises(ValueError, match="not in Byzantine set"):
        s.init_from_policies(
            policies=[_ps("g1", [3, 5], "frontrun", "fissure")],
            coordination_policy="leader",
            information="local_dag_union",
            leader_node_id=11,
        )


def test_policy_lookup_returns_per_node_policy():
    s = CoordinatorState()
    s.init_from_policies(
        policies=[
            _ps("g1", [3, 5], "frontrun", "fissure"),
            _ps("g2", [7], "backrun", "sluggish"),
        ],
        coordination_policy="role_specialization",
        information="local_dag_union",
    )
    p3 = s.lookup_policy(3)
    p7 = s.lookup_policy(7)
    assert p3.family == "frontrun" and p3.strategy == "fissure" and p3.group_id == "g1"
    assert p7.family == "backrun" and p7.strategy == "sluggish" and p7.group_id == "g2"
    assert s.lookup_policy(1) is None  # honest


def test_share_view_rejects_honest_nodes():
    s = CoordinatorState()
    s.init_from_policies(
        policies=[_ps("g1", [3], "frontrun", "fissure")],
        coordination_policy="role_specialization",
        information="local_dag_union",
    )
    with pytest.raises(KeyError):
        s.share_view(node_id=1, round_=5, blocks=["a"])  # honest


def test_view_own_dag_only_returns_only_own_blocks():
    s = CoordinatorState()
    s.init_from_policies(
        policies=[_ps("g1", [3, 5], "frontrun", "fissure")],
        coordination_policy="role_specialization",
        information="own_dag_only",
    )
    s.share_view(3, 5, ["h1", "h2"])
    s.share_view(5, 5, ["h3"])
    assert s.view_for(3, 5) == ["h1", "h2"]
    assert s.view_for(5, 5) == ["h3"]


def test_view_local_dag_union_returns_union_sorted():
    s = CoordinatorState()
    s.init_from_policies(
        policies=[_ps("g1", [3, 5], "frontrun", "fissure")],
        coordination_policy="role_specialization",
        information="local_dag_union",
    )
    s.share_view(3, 5, ["h1", "h2"])
    s.share_view(5, 5, ["h2", "h3"])
    assert s.view_for(3, 5) == ["h1", "h2", "h3"]
    assert s.view_for(5, 5) == ["h1", "h2", "h3"]


def test_decide_leader_makes_leader_active_others_mirror():
    s = CoordinatorState()
    s.init_from_policies(
        policies=[
            _ps("g1", [3], "frontrun", "fissure"),
            _ps("g2", [5], "backrun", "sluggish"),
        ],
        coordination_policy="leader",
        information="local_dag_union",
        leader_node_id=3,
    )
    d3 = s.decide(3, round_=10)
    d5 = s.decide(5, round_=10)
    assert d3["role"] == "leader"
    assert d3["action"] == "propose"
    assert d3["effective_family"] == "frontrun"
    assert d5["role"] == "follower"
    assert d5["action"] == "mirror"
    # Followers adopt the leader's (family, strategy):
    assert d5["effective_family"] == "frontrun"
    assert d5["effective_strategy"] == "fissure"


def test_leader_policy_emits_shared_exclusion_seed():
    """P3 mechanism: shared_exclusion_seed must be identical across
    Byzantine nodes in the same group for the same round."""
    s = CoordinatorState()
    s.init_from_policies(
        policies=[
            _ps("g0", [3, 5, 7], "frontrun", "fissure"),
        ],
        coordination_policy="leader",
        information="local_dag_union",
        seed=42,
        leader_node_id=3,
    )
    s3 = s.decide(3, round_=10)["shared_exclusion_seed"]
    s5 = s.decide(5, round_=10)["shared_exclusion_seed"]
    s7 = s.decide(7, round_=10)["shared_exclusion_seed"]
    assert s3 == s5 == s7
    # Different round → different seed
    s3_r11 = s.decide(3, round_=11)["shared_exclusion_seed"]
    assert s3 != s3_r11


def test_leader_policy_seed_deterministic_given_init_seed():
    a = CoordinatorState()
    a.init_from_policies(
        policies=[_ps("g0", [3], "frontrun", "fissure")],
        coordination_policy="leader",
        information="local_dag_union",
        seed=42,
        leader_node_id=3,
    )
    b = CoordinatorState()
    b.init_from_policies(
        policies=[_ps("g0", [3], "frontrun", "fissure")],
        coordination_policy="leader",
        information="local_dag_union",
        seed=42,
        leader_node_id=3,
    )
    assert a.decide(3, round_=5)["shared_exclusion_seed"] == b.decide(3, round_=5)["shared_exclusion_seed"]


def test_non_leader_policies_no_shared_exclusion_seed():
    """role_specialization and rr_slot decisions don't carry a shared seed (P3 mechanism is leader-only for v1)."""
    s = CoordinatorState()
    s.init_from_policies(
        policies=[_ps("g0", [3, 5], "frontrun", "fissure")],
        coordination_policy="role_specialization",
        information="local_dag_union",
    )
    d = s.decide(3, round_=10)
    assert "shared_exclusion_seed" not in d


def test_defection_returns_no_shared_seed():
    """v3 R-P3.4: when defection_node_id is set, that node gets a
    'defected' decision without shared_exclusion_seed."""
    s = CoordinatorState()
    s.init_from_policies(
        policies=[
            _ps("g0", [3, 5, 7], "frontrun", "fissure"),
        ],
        coordination_policy="leader",
        information="local_dag_union",
        seed=42,
        leader_node_id=3,
        defection_node_id=7,
    )
    # Leader and non-defector follower get shared_exclusion_seed.
    assert "shared_exclusion_seed" in s.decide(3, round_=10)
    assert "shared_exclusion_seed" in s.decide(5, round_=10)
    # Defector does NOT get a shared seed.
    d7 = s.decide(7, round_=10)
    assert "shared_exclusion_seed" not in d7
    assert d7["role"] == "defector"
    assert d7["policy"] == "defected"


def test_defection_rejects_non_byzantine_node():
    s = CoordinatorState()
    with pytest.raises(ValueError, match="not in Byzantine set"):
        s.init_from_policies(
            policies=[_ps("g0", [3, 5], "frontrun", "fissure")],
            coordination_policy="leader",
            information="local_dag_union",
            leader_node_id=3,
            defection_node_id=11,  # honest, not in Byzantine set
        )


def test_defection_node_uses_own_policy():
    """The defector's decision carries its own family/strategy, not the leader's."""
    s = CoordinatorState()
    s.init_from_policies(
        policies=[
            _ps("g_lead", [3], "frontrun", "fissure"),
            _ps("g_defect", [5], "backrun", "sluggish"),
        ],
        coordination_policy="leader",
        information="local_dag_union",
        leader_node_id=3,
        defection_node_id=5,
    )
    d5 = s.decide(5, round_=10)
    # Defector uses its OWN policy, not the leader's.
    assert d5["effective_family"] == "backrun"
    assert d5["effective_strategy"] == "sluggish"


def test_no_defection_means_all_get_shared_seed():
    s = CoordinatorState()
    s.init_from_policies(
        policies=[_ps("g0", [3, 5], "frontrun", "fissure")],
        coordination_policy="leader",
        information="local_dag_union",
        seed=42,
        leader_node_id=3,
        # defection_node_id omitted → default None
    )
    assert "shared_exclusion_seed" in s.decide(3, round_=10)
    assert "shared_exclusion_seed" in s.decide(5, round_=10)


def test_decide_role_specialization_preserves_per_node_policy():
    s = CoordinatorState()
    s.init_from_policies(
        policies=[
            _ps("g1", [3], "frontrun", "fissure"),
            _ps("g2", [5], "backrun", "sluggish"),
        ],
        coordination_policy="role_specialization",
        information="local_dag_union",
    )
    d3 = s.decide(3, round_=10)
    d5 = s.decide(5, round_=10)
    assert d3["effective_family"] == "frontrun"
    assert d5["effective_strategy"] == "sluggish"
    assert d3["role"] == "g1"
    assert d5["role"] == "g2"


def test_decide_rr_slot_rotates_active_node_round_by_round():
    s = CoordinatorState()
    s.init_from_policies(
        policies=[_ps("g1", [3, 5, 7], "frontrun", "fissure")],
        coordination_policy="rr_slot",
        information="local_dag_union",
        seed=0,
    )
    active_by_round = []
    for r in range(6):
        # decision is per-node; the "active" node is the one whose role==active
        active = [n for n in (3, 5, 7) if s.decide(n, r)["role"] == "active"]
        assert len(active) == 1  # exactly one active per round
        active_by_round.append(active[0])
    # Round-robin order: 3, 5, 7, 3, 5, 7
    assert active_by_round == [3, 5, 7, 3, 5, 7]


def test_decide_rr_slot_inactive_nodes_have_no_effective_strategy():
    s = CoordinatorState()
    s.init_from_policies(
        policies=[_ps("g1", [3, 5], "frontrun", "fissure")],
        coordination_policy="rr_slot",
        information="local_dag_union",
    )
    # round 0 active = 3, inactive = 5
    d5 = s.decide(5, 0)
    assert d5["role"] == "passive"
    assert d5["effective_family"] is None
    assert d5["effective_strategy"] is None


def test_decide_is_cached_per_round_per_node():
    s = CoordinatorState()
    s.init_from_policies(
        policies=[_ps("g1", [3], "frontrun", "fissure")],
        coordination_policy="role_specialization",
        information="local_dag_union",
    )
    d1 = s.decide(3, 10)
    d2 = s.decide(3, 10)
    assert d1 == d2
    # Different round = different cache key
    d3 = s.decide(3, 11)
    assert d3 == d1  # value-equal but separately cached
    assert len(s.decisions) == 2


# ---------------------------------------------------------------------------
# End-to-end HTTP tests
# ---------------------------------------------------------------------------


@pytest.fixture
def running_server():
    state = CoordinatorState()
    server = CoordinatorServer(state=state)
    server.start()
    try:
        yield server, state
    finally:
        server.stop()


def test_http_health_before_init(running_server):
    server, _state = running_server
    client = CoordinatorClient(server.url)
    r = client.health()
    assert r["ok"] is True
    assert r["initialized"] is False


def test_http_init_then_lookup(running_server):
    server, _state = running_server
    client = CoordinatorClient(server.url)
    client.init(
        policies=[
            {"group_id": "g1", "members": [3, 5], "family": "frontrun", "strategy": "fissure", "params": {}},
            {"group_id": "g2", "members": [7], "family": "backrun", "strategy": "sluggish", "params": {}},
        ],
        coordination_policy="role_specialization",
        information="local_dag_union",
    )
    p = client.policy_lookup(node_id=3)
    assert p["group_id"] == "g1"
    assert p["family"] == "frontrun"
    assert p["strategy"] == "fissure"


def test_http_honest_lookup_returns_404(running_server):
    server, _ = running_server
    client = CoordinatorClient(server.url)
    client.init(
        policies=[{"group_id": "g1", "members": [3], "family": "frontrun", "strategy": "fissure", "params": {}}],
        coordination_policy="role_specialization",
        information="local_dag_union",
    )
    with pytest.raises(CoordinatorClientError) as ei:
        client.policy_lookup(node_id=1)  # honest
    assert ei.value.status == 404


def test_http_requests_before_init_get_409(running_server):
    server, _ = running_server
    client = CoordinatorClient(server.url)
    with pytest.raises(CoordinatorClientError) as ei:
        client.policy_lookup(node_id=3)
    assert ei.value.status == 409


def test_http_share_and_view_with_union_information(running_server):
    server, _state = running_server
    client = CoordinatorClient(server.url)
    client.init(
        policies=[{"group_id": "g1", "members": [3, 5], "family": "frontrun", "strategy": "fissure", "params": {}}],
        coordination_policy="role_specialization",
        information="local_dag_union",
    )
    client.share_view(node_id=3, round_=5, blocks=["h1", "h2"])
    client.share_view(node_id=5, round_=5, blocks=["h2", "h3"])
    view = client.view_for(node_id=3, round_=5)
    assert view["blocks"] == ["h1", "h2", "h3"]
    assert view["information"] == "local_dag_union"


def test_http_decision_rr_slot(running_server):
    server, _ = running_server
    client = CoordinatorClient(server.url)
    client.init(
        policies=[{"group_id": "g1", "members": [3, 5, 7], "family": "frontrun", "strategy": "fissure", "params": {}}],
        coordination_policy="rr_slot",
        information="local_dag_union",
    )
    # round 0 active = 3
    d3 = client.decision(node_id=3, round_=0)
    d5 = client.decision(node_id=5, round_=0)
    assert d3["role"] == "active"
    assert d5["role"] == "passive"


def test_http_metrics_snapshot(running_server):
    server, _ = running_server
    client = CoordinatorClient(server.url)
    client.init(
        policies=[{"group_id": "g1", "members": [3, 5], "family": "frontrun", "strategy": "fissure", "params": {}}],
        coordination_policy="leader",
        information="own_dag_only",
    )
    client.decision(node_id=3, round_=0)
    client.decision(node_id=5, round_=0)
    m = client.metrics()
    assert m["initialized"] is True
    assert m["coordination_policy"] == "leader"
    assert m["information"] == "own_dag_only"
    assert m["byzantine_node_ids"] == [3, 5]
    assert m["decisions_made"] == 2


def test_http_defection_no_shared_seed_for_defector(running_server):
    """v3 R-P3.4 HTTP integration: defector gets no shared_exclusion_seed."""
    server, _ = running_server
    client = CoordinatorClient(server.url)
    client.init(
        policies=[
            {"group_id": "g0", "members": [3, 5, 7], "family": "frontrun", "strategy": "fissure", "params": {}}
        ],
        coordination_policy="leader",
        information="local_dag_union",
        seed=42,
        leader_node_id=3,
        defection_node_id=7,
    )
    d3 = client.decision(node_id=3, round_=10)
    d5 = client.decision(node_id=5, round_=10)
    d7 = client.decision(node_id=7, round_=10)
    assert "shared_exclusion_seed" in d3
    assert "shared_exclusion_seed" in d5
    assert "shared_exclusion_seed" not in d7  # defector
    assert d7["role"] == "defector"
