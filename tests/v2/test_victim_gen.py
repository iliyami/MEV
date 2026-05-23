"""VictimGen tests — determinism, distribution shape, HTTP endpoint."""

from __future__ import annotations

import statistics as st

import pytest

from scripts.v2.coordinator import CoordinatorServer, CoordinatorState
from scripts.v2.coordinator_client import CoordinatorClient, CoordinatorClientError
from scripts.v2.victim_gen import (
    VictimProfile,
    profit_weighted_asr,
)


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_uniform_is_constant():
    vp = VictimProfile(distribution="uniform", params={"scale": 1.0}, seed=0)
    # Different (round, author) tuples must all return the configured scalar.
    assert vp.profit_for_block(0, 0) == 1.0
    assert vp.profit_for_block(7, 11) == 1.0
    assert vp.profit_for_block(99, 100) == 1.0


def test_pareto_deterministic_same_seed():
    a = VictimProfile(distribution="pareto", params={"shape": 1.16, "scale": 1.0}, seed=42)
    b = VictimProfile(distribution="pareto", params={"shape": 1.16, "scale": 1.0}, seed=42)
    for r in range(20):
        for n in range(13):
            assert a.profit_for_block(r, n) == b.profit_for_block(r, n)


def test_pareto_different_seed_changes_stream():
    a = VictimProfile(distribution="pareto", params={"shape": 1.16}, seed=1)
    b = VictimProfile(distribution="pareto", params={"shape": 1.16}, seed=2)
    differences = sum(1 for r in range(50) for n in range(13)
                      if a.profit_for_block(r, n) != b.profit_for_block(r, n))
    # Hash-based draws ⇒ overwhelmingly likely to differ on most positions.
    assert differences > 50 * 13 - 5


def test_pareto_different_block_ids_have_different_profits():
    vp = VictimProfile(distribution="pareto", params={"shape": 1.16}, seed=0)
    seen: set[float] = set()
    for r in range(100):
        for n in range(13):
            seen.add(vp.profit_for_block(r, n))
    # We expect near-unique values; allow some collisions in floating point.
    assert len(seen) > 100 * 13 - 5


# ---------------------------------------------------------------------------
# Distribution shape
# ---------------------------------------------------------------------------


def test_uniform_mean_equals_scale():
    vp = VictimProfile(distribution="uniform", params={"scale": 2.5}, seed=0)
    draws = [vp.profit_for_block(r, n) for r in range(50) for n in range(13)]
    assert st.mean(draws) == 2.5
    assert max(draws) == 2.5
    assert min(draws) == 2.5


def test_pareto_mean_approaches_theoretical():
    """For shape>1, the Pareto mean is scale*shape/(shape-1).

    With shape=2.0 + scale=1.0 → theoretical mean = 2.0. Use a moderate-shape
    parameter so the empirical mean converges within a reasonable sample.
    """
    vp = VictimProfile(distribution="pareto", params={"shape": 2.0, "scale": 1.0}, seed=0)
    draws = [vp.profit_for_block(r, n) for r in range(400) for n in range(13)]
    theoretical = 2.0 * 1.0 / (2.0 - 1.0)
    # Heavy-tailed distributions converge slowly; allow ±30% on n=5200.
    assert 0.7 * theoretical < st.mean(draws) < 1.3 * theoretical


def test_pareto_is_heavier_tailed_than_uniform():
    """Sanity: Pareto produces large outliers; uniform doesn't."""
    vp_u = VictimProfile(distribution="uniform", params={"scale": 1.0}, seed=0)
    vp_p = VictimProfile(distribution="pareto", params={"shape": 1.16}, seed=0)
    u_max = max(vp_u.profit_for_block(r, n) for r in range(200) for n in range(13))
    p_max = max(vp_p.profit_for_block(r, n) for r in range(200) for n in range(13))
    assert u_max == 1.0
    # Heavy-tailed shape=1.16 should generate at least one >> 1 sample over 2600 draws.
    assert p_max > 10.0


# ---------------------------------------------------------------------------
# Profit-weighted ASR (the metric)
# ---------------------------------------------------------------------------


def test_profit_weighted_asr_equals_unweighted_under_uniform():
    """Paper 1 metric must be the special case of v2's metric."""
    vp = VictimProfile(distribution="uniform", params={"scale": 1.0}, seed=0)
    blocks = [
        {"round": 5, "author": 11, "attacked": True},
        {"round": 6, "author": 12, "attacked": False},
        {"round": 7, "author": 11, "attacked": True},
        {"round": 8, "author": 12, "attacked": True},
    ]
    res = profit_weighted_asr(blocks, vp)
    assert res["unweighted_asr"] == res["profit_weighted_asr"]
    assert res["unweighted_asr"] == 0.75


def test_profit_weighted_asr_diverges_under_pareto():
    """When profit is heterogeneous, profit-weighted ASR can differ materially
    from unweighted ASR. We construct an example where the attacker hits only
    a high-profit victim and misses many low-profit ones."""
    vp = VictimProfile(distribution="pareto", params={"shape": 1.16}, seed=0)
    blocks = [
        {"round": r, "author": 11, "attacked": False} for r in range(20)
    ] + [
        {"round": 100, "author": 11, "attacked": True}
    ]
    res = profit_weighted_asr(blocks, vp)
    # 1/21 of victims attacked unweighted
    assert abs(res["unweighted_asr"] - 1 / 21) < 1e-6
    # Profit-weighted will be much higher iff that one block draws a heavy
    # outlier; check the realized_mev / total_profit ratio is at least
    # something meaningfully different from 1/21.
    # We don't assert a specific direction (the random one block might be
    # low-draw too) — we assert non-equality to unweighted in expectation.
    assert res["profit_weighted_asr"] != res["unweighted_asr"]


def test_profit_weighted_asr_empty_blocks():
    vp = VictimProfile(distribution="uniform", seed=0)
    res = profit_weighted_asr([], vp)
    assert res == {
        "unweighted_asr": 0.0,
        "profit_weighted_asr": 0.0,
        "total_profit": 0.0,
        "realized_mev": 0.0,
        "n_victims": 0,
    }


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_unknown_distribution_rejected():
    with pytest.raises(ValueError, match="unknown distribution"):
        VictimProfile(distribution="lognormal", seed=0)


def test_negative_scale_rejected():
    vp = VictimProfile(distribution="uniform", params={"scale": -1.0}, seed=0)
    with pytest.raises(ValueError):
        vp.profit_for_block(0, 0)


def test_negative_pareto_shape_rejected():
    vp = VictimProfile(distribution="pareto", params={"shape": -1.0}, seed=0)
    with pytest.raises(ValueError):
        vp.profit_for_block(0, 0)


# ---------------------------------------------------------------------------
# Coordinator HTTP endpoint
# ---------------------------------------------------------------------------


@pytest.fixture
def server_with_pareto():
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
            seed=42,
            victim_profile={
                "distribution": "pareto",
                "params": {"shape": 1.16, "scale": 1.0},
                "seed": 42,
            },
        )
        yield server, client
    finally:
        server.stop()


def test_http_victim_profit_returns_deterministic_value(server_with_pareto):
    _, client = server_with_pareto
    r1 = client.victim_profit(round_=5, author=11)
    r2 = client.victim_profit(round_=5, author=11)
    assert r1["profit"] == r2["profit"]
    assert r1["distribution"] == "pareto"


def test_http_victim_profit_disabled_without_profile():
    state = CoordinatorState()
    server = CoordinatorServer(state=state)
    server.start()
    try:
        client = CoordinatorClient(server.url)
        client.init(
            policies=[{"group_id": "g0", "members": [3], "family": "frontrun", "strategy": "fissure", "params": {}}],
            coordination_policy="role_specialization",
            information="local_dag_union",
        )  # no victim_profile
        with pytest.raises(CoordinatorClientError) as ei:
            client.victim_profit(round_=0, author=0)
        assert ei.value.status == 409
    finally:
        server.stop()


def test_http_victim_profit_metrics_snapshot_includes_profile(server_with_pareto):
    _, client = server_with_pareto
    m = client.metrics()
    assert m["victim_profile"] is not None
    assert m["victim_profile"]["distribution"] == "pareto"
    assert m["victim_profile"]["seed"] == 42
