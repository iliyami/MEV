"""PolicyEngine — materialize per-slot policy vectors from named archetypes.

A "policy vector" is the assignment, per Byzantine node slot, of (family,
strategy, group_id). The five named archetypes (homogeneous, same_family_split,
same_strategy_split, adversarial_best_response, random_latin_square) cover the
principled subset of the 9^f Cartesian product the plan calls for.

This module never modifies protocol code. It only computes assignments that
the per-protocol attacker hooks will later consume (see CLAUDE.md invariant).
"""

from __future__ import annotations

import itertools
import random
from dataclasses import dataclass
from typing import Optional

from .schema import (
    ASSIGNMENT_ARCHETYPES,
    ATTACK_FAMILIES,
    DAG_STRATEGIES,
    PolicySpec,
)


@dataclass(frozen=True)
class PolicyVectorRequest:
    """Inputs to PolicyEngine.materialize.

    archetype: one of ASSIGNMENT_ARCHETYPES.
    n: total network size.
    f: number of Byzantine slots to fill.
    k: number of attacker groups (TM-Compete only; ignored for solo/collude).
    base_family / base_strategy: the (family, strategy) for archetypes that
        hold one axis fixed. Required for homogeneous, same_family_split,
        same_strategy_split.
    seed: deterministic seed for archetypes that draw randomly.
    byzantine_node_ids: optional explicit node assignment. If None, slots
        0..f-1 are used (matches paper-1's ATTACKER_ID convention).
    best_response_table: dict[(family, strategy) -> score] used only for
        adversarial_best_response. Pre-computed from a paper-1-style sweep.
    """

    archetype: str
    n: int
    f: int
    k: int = 1
    base_family: Optional[str] = None
    base_strategy: Optional[str] = None
    seed: int = 0
    byzantine_node_ids: Optional[tuple[int, ...]] = None
    best_response_table: Optional[dict[tuple[str, str], float]] = None


def _resolve_node_ids(req: PolicyVectorRequest) -> tuple[int, ...]:
    if req.byzantine_node_ids is not None:
        if len(req.byzantine_node_ids) != req.f:
            raise ValueError(
                f"byzantine_node_ids length {len(req.byzantine_node_ids)} != f={req.f}"
            )
        return req.byzantine_node_ids
    return tuple(range(req.f))


def _split_groups(node_ids: tuple[int, ...], k: int) -> list[tuple[int, ...]]:
    """Partition node_ids into k contiguous groups as balanced as possible."""
    if k < 1 or k > len(node_ids):
        raise ValueError(f"invalid k={k} for f={len(node_ids)}")
    base, extra = divmod(len(node_ids), k)
    groups: list[tuple[int, ...]] = []
    cursor = 0
    for i in range(k):
        size = base + (1 if i < extra else 0)
        groups.append(tuple(node_ids[cursor : cursor + size]))
        cursor += size
    return groups


def _homogeneous(req: PolicyVectorRequest) -> list[PolicySpec]:
    if req.base_family is None or req.base_strategy is None:
        raise ValueError("homogeneous archetype requires base_family + base_strategy")
    node_ids = _resolve_node_ids(req)
    # One group, one policy, all members.
    return [
        PolicySpec(
            group_id="g0",
            members=node_ids,
            family=req.base_family,
            strategy=req.base_strategy,
            params={},
        )
    ]


def _same_family_split(req: PolicyVectorRequest) -> list[PolicySpec]:
    if req.base_family is None:
        raise ValueError("same_family_split requires base_family")
    node_ids = _resolve_node_ids(req)
    groups = _split_groups(node_ids, min(req.k, len(DAG_STRATEGIES)))
    strategies = list(DAG_STRATEGIES)
    return [
        PolicySpec(
            group_id=f"g{i}",
            members=members,
            family=req.base_family,
            strategy=strategies[i % len(strategies)],
            params={},
        )
        for i, members in enumerate(groups)
    ]


def _same_strategy_split(req: PolicyVectorRequest) -> list[PolicySpec]:
    if req.base_strategy is None:
        raise ValueError("same_strategy_split requires base_strategy")
    node_ids = _resolve_node_ids(req)
    groups = _split_groups(node_ids, min(req.k, len(ATTACK_FAMILIES)))
    families = list(ATTACK_FAMILIES)
    return [
        PolicySpec(
            group_id=f"g{i}",
            members=members,
            family=families[i % len(families)],
            strategy=req.base_strategy,
            params={},
        )
        for i, members in enumerate(groups)
    ]


def _adversarial_best_response(req: PolicyVectorRequest) -> list[PolicySpec]:
    if req.best_response_table is None or not req.best_response_table:
        raise ValueError("adversarial_best_response requires a non-empty best_response_table")
    node_ids = _resolve_node_ids(req)
    # Rank (family, strategy) cells by score descending; assign top-k cells to k groups.
    ranked = sorted(req.best_response_table.items(), key=lambda kv: kv[1], reverse=True)
    k = min(req.k, len(ranked))
    groups = _split_groups(node_ids, k)
    return [
        PolicySpec(
            group_id=f"g{i}",
            members=members,
            family=ranked[i][0][0],
            strategy=ranked[i][0][1],
            params={"score": ranked[i][1]},
        )
        for i, members in enumerate(groups)
    ]


def _random_latin_square(req: PolicyVectorRequest) -> list[PolicySpec]:
    """Random balanced (family, strategy) draw.

    Property: every family appears at least once and every strategy appears at
    least once across all groups (when k >= 3). For k < 3 we just sample
    uniformly and accept the imbalance — the archetype is a falsification
    test, not a guarantee.
    """
    rng = random.Random(req.seed)
    node_ids = _resolve_node_ids(req)
    groups = _split_groups(node_ids, req.k)
    cells = list(itertools.product(ATTACK_FAMILIES, DAG_STRATEGIES))
    if req.k >= 3:
        # Force coverage: draw one from each family and one from each strategy first.
        forced_families = list(ATTACK_FAMILIES)
        forced_strategies = list(DAG_STRATEGIES)
        rng.shuffle(forced_families)
        rng.shuffle(forced_strategies)
        # Pair the first three groups with (forced_family[i], random strategy) and
        # (random family, forced_strategy[i]) alternately.
        chosen: list[tuple[str, str]] = []
        for i in range(req.k):
            if i < 3:
                fam = forced_families[i]
                strat = rng.choice(DAG_STRATEGIES)
            elif i < 6:
                fam = rng.choice(ATTACK_FAMILIES)
                strat = forced_strategies[i - 3]
            else:
                fam, strat = rng.choice(cells)
            chosen.append((fam, strat))
    else:
        chosen = [rng.choice(cells) for _ in range(req.k)]
    return [
        PolicySpec(
            group_id=f"g{i}",
            members=members,
            family=family,
            strategy=strategy,
            params={},
        )
        for i, (members, (family, strategy)) in enumerate(zip(groups, chosen))
    ]


_ARCHETYPE_FNS = {
    "homogeneous": _homogeneous,
    "same_family_split": _same_family_split,
    "same_strategy_split": _same_strategy_split,
    "adversarial_best_response": _adversarial_best_response,
    "random_latin_square": _random_latin_square,
}


def materialize(req: PolicyVectorRequest) -> list[PolicySpec]:
    """Materialize a policy vector for the given request.

    Returns a list of PolicySpec — one per group. Deterministic given (req, seed).
    Never modifies protocol code: this is pure assignment logic.
    """
    if req.archetype not in ASSIGNMENT_ARCHETYPES:
        raise ValueError(f"unknown archetype {req.archetype!r}; expected {ASSIGNMENT_ARCHETYPES}")
    if req.archetype == "homogeneous" and req.k != 1:
        raise ValueError("homogeneous archetype requires k==1")
    if req.archetype == "adversarial_best_response" and req.k < 1:
        raise ValueError("adversarial_best_response requires k>=1")
    return _ARCHETYPE_FNS[req.archetype](req)
