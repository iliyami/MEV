"""Tests for the realized-profit metric (T4) — benchmark._compute_realized_profit.

Given a committed order + a cell config (attacker/victim sets + profit spec),
weight victim blocks by deterministic per-block profit and mark them attacked
when an attacker shares their round at an earlier position.
"""

from __future__ import annotations

from scripts.v2 import schema, sweeper
from scripts.v2.benchmark import _compute_realized_profit


def _cfg(profit_dist: str = "uniform", params: dict | None = None) -> schema.V2Config:
    raw = {
        "protocol": {"name": "sui", "path": "sui"},
        "environment": {"NUM_NODES": "13", "VICTIM_RATIO": "0.231"},
        "adversary": {
            "threat_model": "TM-Solo",
            "topology": {
                "policies": [
                    {"group_id": "g0", "members": [0, 1, 2, 3], "family": "frontrun",
                     "strategy": "fissure", "params": {}},
                ]
            },
        },
        "victims": {
            "workload": "single", "count": 1,
            "profit": {"distribution": profit_dist, "params": params or {}},
        },
        "runtime": {"reps": 1, "seed": 0},
    }
    return sweeper.expand_policy_vector(schema.parse_config(raw))


# n=13, VICTIM_RATIO=0.231 -> victims {10,11,12}; attackers {0,1,2,3}.
_ORDER = [
    {"creator": 0, "position": 1, "round": 5},    # attacker @ round 5
    {"creator": 10, "position": 3, "round": 5},   # victim, ATTACKED (0 at pos 1 < 3)
    {"creator": 11, "position": 2, "round": 6},   # victim, NOT attacked (no attacker @ 6)
]


def test_none_and_empty_order_return_none():
    assert _compute_realized_profit(None, _cfg(), 0) is None
    assert _compute_realized_profit([], _cfg(), 0) is None


def test_uniform_pwasr_equals_unweighted():
    res = _compute_realized_profit(_ORDER, _cfg("uniform", {"scale": 1.0}), seed=0)
    assert res is not None
    assert res["n_victims"] == 2
    assert abs(res["unweighted_asr"] - 0.5) < 1e-9          # 1 of 2 victims attacked
    assert abs(res["profit_weighted_asr"] - res["unweighted_asr"]) < 1e-9  # uniform special case
    assert abs(res["total_profit"] - 2.0) < 1e-9
    assert abs(res["realized_mev"] - 1.0) < 1e-9


def test_pareto_is_deterministic_and_weighted():
    a = _compute_realized_profit(_ORDER, _cfg("pareto", {"shape": 1.16}), seed=42)
    b = _compute_realized_profit(_ORDER, _cfg("pareto", {"shape": 1.16}), seed=42)
    assert a == b                                # deterministic per seed
    assert a["n_victims"] == 2
    assert a["total_profit"] > 0.0
    assert 0.0 <= a["profit_weighted_asr"] <= 1.0
    assert a["realized_mev"] >= 0.0


def test_no_victim_blocks_returns_none():
    order = [{"creator": 0, "position": 1, "round": 5}]  # only an attacker block
    assert _compute_realized_profit(order, _cfg(), 0) is None


def test_malformed_records_skipped_not_fatal():
    order = [
        {"creator": "x", "position": None, "round": 5},  # malformed -> skipped
        {"creator": 10, "position": 1, "round": 5},       # victim, not attacked
    ]
    res = _compute_realized_profit(order, _cfg("uniform", {"scale": 1.0}), 0)
    assert res is not None
    assert res["n_victims"] == 1
    assert res["unweighted_asr"] == 0.0
