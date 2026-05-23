"""PolicyEngine archetype materialization tests."""

import pytest

from scripts.v2 import policy
from scripts.v2.schema import ATTACK_FAMILIES, DAG_STRATEGIES


def _req(**kw):
    return policy.PolicyVectorRequest(**kw)


def test_homogeneous_single_group_all_byz():
    req = _req(
        archetype="homogeneous",
        n=13,
        f=4,
        k=1,
        base_family="frontrun",
        base_strategy="fissure",
    )
    out = policy.materialize(req)
    assert len(out) == 1
    p = out[0]
    assert p.members == (0, 1, 2, 3)
    assert p.family == "frontrun"
    assert p.strategy == "fissure"


def test_homogeneous_rejects_k_gt_one():
    with pytest.raises(ValueError, match="homogeneous"):
        policy.materialize(
            _req(
                archetype="homogeneous",
                n=13,
                f=4,
                k=2,
                base_family="frontrun",
                base_strategy="fissure",
            )
        )


def test_same_family_split_assigns_distinct_strategies():
    req = _req(
        archetype="same_family_split",
        n=13,
        f=4,
        k=3,
        base_family="frontrun",
    )
    out = policy.materialize(req)
    assert len(out) == 3
    assert {p.family for p in out} == {"frontrun"}
    assert {p.strategy for p in out} == set(DAG_STRATEGIES)
    # Members partition Byzantine slots exactly:
    flat = [m for p in out for m in p.members]
    assert sorted(flat) == [0, 1, 2, 3]


def test_same_strategy_split_assigns_distinct_families():
    req = _req(
        archetype="same_strategy_split",
        n=13,
        f=4,
        k=3,
        base_strategy="sluggish",
    )
    out = policy.materialize(req)
    assert {p.strategy for p in out} == {"sluggish"}
    assert {p.family for p in out} == set(ATTACK_FAMILIES)


def test_adversarial_best_response_picks_top_cells():
    table = {
        ("frontrun", "fissure"): 0.95,
        ("frontrun", "speculative"): 0.93,
        ("backrun", "sluggish"): 0.99,
        ("sandwich", "fissure"): 0.81,
    }
    req = _req(
        archetype="adversarial_best_response",
        n=13,
        f=4,
        k=2,
        base_family="frontrun",  # ignored for this archetype
        base_strategy="fissure",
        best_response_table=table,
    )
    out = policy.materialize(req)
    assert len(out) == 2
    # Highest-scoring cell first
    assert (out[0].family, out[0].strategy) == ("backrun", "sluggish")
    assert (out[1].family, out[1].strategy) == ("frontrun", "fissure")


def test_random_latin_square_is_deterministic_under_seed():
    base = dict(
        archetype="random_latin_square",
        n=13,
        f=4,
        k=3,
    )
    out1 = policy.materialize(_req(**base, seed=42))
    out2 = policy.materialize(_req(**base, seed=42))
    out3 = policy.materialize(_req(**base, seed=43))
    assert [(p.family, p.strategy) for p in out1] == [(p.family, p.strategy) for p in out2]
    # Different seed should usually produce different draw; we don't assert
    # inequality (could collide), but at minimum the call is callable.
    assert len(out3) == 3


def test_random_latin_square_k3_covers_all_families_or_strategies():
    """For k>=3 the archetype must cover at least all three families OR all three strategies."""
    req = _req(archetype="random_latin_square", n=13, f=4, k=3, seed=7)
    out = policy.materialize(req)
    families = {p.family for p in out}
    strategies = {p.strategy for p in out}
    # By construction we force coverage along one axis:
    assert families == set(ATTACK_FAMILIES) or strategies == set(DAG_STRATEGIES)


def test_byzantine_node_ids_override():
    req = _req(
        archetype="homogeneous",
        n=13,
        f=4,
        k=1,
        base_family="frontrun",
        base_strategy="fissure",
        byzantine_node_ids=(3, 5, 7, 9),
    )
    out = policy.materialize(req)
    assert out[0].members == (3, 5, 7, 9)


def test_byzantine_node_ids_length_mismatch_rejected():
    with pytest.raises(ValueError):
        policy.materialize(
            _req(
                archetype="homogeneous",
                n=13,
                f=4,
                k=1,
                base_family="frontrun",
                base_strategy="fissure",
                byzantine_node_ids=(3, 5),  # only 2, f=4
            )
        )
