"""v2 YAML schema for multi-policy adversary experiments.

Backward-compat rule: any paper-1 YAML (no `adversary`/`victims` blocks) loads
cleanly and resolves to TM-Solo with a single homogeneous policy.

All validation is pure-Python so the harness has no new runtime dependencies
beyond pyyaml. Exceptions are raised as `SchemaError` with a path-prefix so
config authors get an exact location.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

THREAT_MODELS = ("TM-Solo", "TM-Compete", "TM-Collude", "TM-Bribe")
ATTACK_FAMILIES = ("frontrun", "backrun", "sandwich")
DAG_STRATEGIES = ("fissure", "speculative", "sluggish")
# DS4/DS5 withholding attacks (env-gated proposer hooks). Kept OUT of
# DAG_STRATEGIES so the competition archetypes in policy.py keep rotating only
# the three core strategies; these are valid strategy values but never part of an
# auto-generated split. `ALL_STRATEGIES` is the union used for enum validation.
WITHHOLDING_STRATEGIES = (
    "withhold_baseline",
    "withhold_silent",
    # A3.2 competing attackers (env-gated INDEPENDENT=1 scoring restriction on
    # the same DS4 SILENT_EXCEPT_LEADER hook; see withholding_attack_test.rs).
    "withhold_silent_independent",
    "slw",
)
# A2.7 proposal-timestamp attack (env-gated ATTACK_TIMESTAMP /
# BYZANTINE_TIMESTAMP_OFFSET_MS proposer hook). Kept OUT of DAG_STRATEGIES for
# the same reason as WITHHOLDING_STRATEGIES above.
TIMESTAMP_STRATEGIES = ("timestamp_baseline", "timestamp")
ALL_STRATEGIES = DAG_STRATEGIES + WITHHOLDING_STRATEGIES + TIMESTAMP_STRATEGIES
COORDINATION_POLICIES = ("leader", "role_specialization", "rr_slot")
COORDINATION_INFO = ("own_dag_only", "local_dag_union")
BRIBERY_TYPES = ("guided", "effective")
BRIBERY_SETTLEMENTS = ("simulated", "move")
VICTIM_WORKLOADS = ("single", "single_with_profit", "multi_pareto", "dex_replay")
PROFIT_DISTRIBUTIONS = ("uniform", "pareto", "lognormal")
RESPONSE_POLICIES = ("always_above_X", "prob_p", "reject_all")
ASSIGNMENT_ARCHETYPES = (
    "homogeneous",
    "same_family_split",
    "same_strategy_split",
    "adversarial_best_response",
    "random_latin_square",
)


class SchemaError(ValueError):
    """Raised when a v2 YAML config fails schema validation."""


@dataclass(frozen=True)
class PolicySpec:
    group_id: str
    members: tuple[int, ...]
    family: str
    strategy: str
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CoordinationSpec:
    enabled: bool = False
    channel: str = "grpc"
    policy: str = "role_specialization"
    information: str = "local_dag_union"
    # v3 R-P3.4: when set, the specified Byzantine node ignores coord
    # decisions and falls back to the env-var path (paper-1 behaviour).
    # Used by the P3 H2.5 (defection rationality) test.
    defection_node_id: Optional[int] = None


@dataclass(frozen=True)
class BriberySpec:
    enabled: bool = False
    type: Optional[str] = None
    settlement: str = "simulated"
    budget: float = 0.0
    response_policy: Optional[str] = None
    response_policy_params: dict[str, Any] = field(default_factory=dict)
    bribed_honest: tuple[int, ...] = ()


@dataclass(frozen=True)
class AdversarySpec:
    threat_model: str = "TM-Solo"
    policies: tuple[PolicySpec, ...] = ()
    coordination: CoordinationSpec = field(default_factory=CoordinationSpec)
    bribery: BriberySpec = field(default_factory=BriberySpec)
    archetype: Optional[str] = None  # set when policies are materialized from archetype


@dataclass(frozen=True)
class ProfitSpec:
    distribution: str = "uniform"
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class VictimsSpec:
    workload: str = "single"
    count: int = 1
    profit: ProfitSpec = field(default_factory=ProfitSpec)
    # v3 R-P2.2: optional canonical victim set, shared across all attackers
    # regardless of per-attacker family. When set, the launcher exports
    # V2_VICTIM_NODE_IDS to Bullshark; otherwise (default), each attacker's
    # family-based index range determines its own victim set (paper-1 path).
    victim_node_ids: tuple[int, ...] = ()


@dataclass(frozen=True)
class RuntimeSpec:
    invariant_audit: bool = True
    reps: int = 5  # field convention for distributed systems experiments
    seed: int = 0


@dataclass(frozen=True)
class V2Config:
    """Fully-resolved v2 config. Construct via `parse_config`, not directly."""

    protocol: str
    num_nodes: int
    attack_family: str  # global default; per-policy can override
    dag_strategy: str  # global default; per-policy can override
    adversary: AdversarySpec
    victims: VictimsSpec
    runtime: RuntimeSpec
    raw: dict[str, Any]  # preserved original YAML for forwarding to legacy launchers


def _require(d: dict, key: str, path: str) -> Any:
    if key not in d:
        raise SchemaError(f"{path}: missing required key '{key}'")
    return d[key]


def _check_enum(value: Any, allowed: tuple[str, ...], path: str) -> str:
    if value not in allowed:
        raise SchemaError(f"{path}: {value!r} not in {allowed}")
    return value


def _parse_policy(d: dict, path: str) -> PolicySpec:
    if not isinstance(d, dict):
        raise SchemaError(f"{path}: policy must be a mapping, got {type(d).__name__}")
    members_raw = _require(d, "members", path)
    if not isinstance(members_raw, (list, tuple)) or not all(
        isinstance(m, int) for m in members_raw
    ):
        raise SchemaError(f"{path}.members: must be a list of integer node indices")
    return PolicySpec(
        group_id=str(_require(d, "group_id", path)),
        members=tuple(members_raw),
        family=_check_enum(_require(d, "family", path), ATTACK_FAMILIES, f"{path}.family"),
        strategy=_check_enum(
            _require(d, "strategy", path), ALL_STRATEGIES, f"{path}.strategy"
        ),
        params=dict(d.get("params") or {}),
    )


def _parse_coordination(d: Optional[dict], path: str) -> CoordinationSpec:
    if not d:
        return CoordinationSpec()
    enabled = bool(d.get("enabled", False))
    defection_node_id = d.get("defection_node_id")
    if defection_node_id is not None and not isinstance(defection_node_id, int):
        raise SchemaError(f"{path}.defection_node_id: must be int or null")
    return CoordinationSpec(
        enabled=enabled,
        channel=str(d.get("channel", "grpc")),
        policy=_check_enum(
            d.get("policy", "role_specialization"),
            COORDINATION_POLICIES,
            f"{path}.policy",
        ),
        information=_check_enum(
            d.get("information", "local_dag_union"),
            COORDINATION_INFO,
            f"{path}.information",
        ),
        defection_node_id=defection_node_id,
    )


def _parse_bribery(d: Optional[dict], path: str) -> BriberySpec:
    if not d:
        return BriberySpec()
    enabled = bool(d.get("enabled", False))
    if not enabled:
        return BriberySpec()
    btype = _check_enum(_require(d, "type", path), BRIBERY_TYPES, f"{path}.type")
    settlement = _check_enum(
        d.get("settlement", "simulated"), BRIBERY_SETTLEMENTS, f"{path}.settlement"
    )
    response_policy = d.get("response_policy")
    if response_policy is not None:
        _check_enum(response_policy, RESPONSE_POLICIES, f"{path}.response_policy")
    bribed_honest = tuple(d.get("bribed_honest") or ())
    if not all(isinstance(m, int) for m in bribed_honest):
        raise SchemaError(f"{path}.bribed_honest: must be a list of integer node indices")
    return BriberySpec(
        enabled=True,
        type=btype,
        settlement=settlement,
        budget=float(d.get("budget", 0)),
        response_policy=response_policy,
        response_policy_params=dict(d.get("response_policy_params") or {}),
        bribed_honest=bribed_honest,
    )


def _parse_adversary(d: Optional[dict]) -> AdversarySpec:
    """Parse the optional `adversary` block. Missing block ⇒ TM-Solo defaults."""
    if not d:
        return AdversarySpec()
    tm = _check_enum(d.get("threat_model", "TM-Solo"), THREAT_MODELS, "adversary.threat_model")
    archetype = d.get("archetype")
    if archetype is not None:
        _check_enum(archetype, ASSIGNMENT_ARCHETYPES, "adversary.archetype")
    topology = d.get("topology") or {}
    raw_policies = topology.get("policies") or []
    policies = tuple(
        _parse_policy(p, f"adversary.topology.policies[{i}]")
        for i, p in enumerate(raw_policies)
    )
    coord = _parse_coordination(d.get("coordination"), "adversary.coordination")
    if tm == "TM-Collude" and not coord.enabled:
        raise SchemaError(
            "adversary.coordination.enabled must be true when threat_model is TM-Collude"
        )
    if tm != "TM-Collude" and coord.enabled:
        raise SchemaError(
            f"adversary.coordination.enabled must be false when threat_model is {tm}"
        )
    bribery = _parse_bribery(d.get("bribery"), "adversary.bribery")
    if tm == "TM-Bribe" and not bribery.enabled:
        raise SchemaError(
            "adversary.bribery.enabled must be true when threat_model is TM-Bribe"
        )
    if tm != "TM-Bribe" and bribery.enabled:
        raise SchemaError(
            f"adversary.bribery.enabled must be false when threat_model is {tm}"
        )
    return AdversarySpec(
        threat_model=tm,
        policies=policies,
        coordination=coord,
        bribery=bribery,
        archetype=archetype,
    )


def _parse_victims(d: Optional[dict]) -> VictimsSpec:
    if not d:
        return VictimsSpec()
    workload = _check_enum(d.get("workload", "single"), VICTIM_WORKLOADS, "victims.workload")
    count = int(d.get("count", 1))
    if count < 1:
        raise SchemaError(f"victims.count: must be >= 1, got {count}")
    profit_d = d.get("profit") or {}
    dist = _check_enum(
        profit_d.get("distribution", "uniform"),
        PROFIT_DISTRIBUTIONS,
        "victims.profit.distribution",
    )
    profit = ProfitSpec(distribution=dist, params=dict(profit_d.get("params") or {}))
    if workload == "single" and count != 1:
        raise SchemaError(f"victims.workload=single requires count==1, got {count}")
    victim_ids_raw = d.get("victim_node_ids") or []
    if not isinstance(victim_ids_raw, (list, tuple)):
        raise SchemaError("victims.victim_node_ids: must be a list of ints")
    victim_node_ids = tuple(int(x) for x in victim_ids_raw)
    return VictimsSpec(
        workload=workload, count=count, profit=profit, victim_node_ids=victim_node_ids,
    )


def _parse_runtime(d: Optional[dict]) -> RuntimeSpec:
    if not d:
        return RuntimeSpec()
    reps = int(d.get("reps", 5))
    if reps < 1:
        raise SchemaError(f"runtime.reps: must be >= 1, got {reps}")
    return RuntimeSpec(
        invariant_audit=bool(d.get("invariant_audit", True)),
        reps=reps,
        seed=int(d.get("seed", 0)),
    )


def _infer_family_and_strategy(raw: dict, adversary: AdversarySpec) -> tuple[str, str]:
    """Resolve the global default (family, strategy) for a config.

    Priority:
      1. The first policy in adversary.topology, if any.
      2. raw.environment.ATTACK_MODE / DAG_STRATEGY (paper-1 compat).
      3. raw.environment.ATTACK_MODE alone, with strategy inferred (legacy).
    """
    if adversary.policies:
        first = adversary.policies[0]
        return first.family, first.strategy

    env = raw.get("environment") or {}
    family = env.get("ATTACK_FAMILY") or env.get("ATTACK_TYPE")
    strategy = env.get("DAG_STRATEGY") or env.get("ATTACK_MODE")
    if family is None or strategy is None:
        # paper-1 configs often only specify ATTACK_MODE = the DAG strategy
        # and the family is implied by the runner (default: frontrun)
        strategy = strategy or "fissure"
        family = family or "frontrun"
    _check_enum(family, ATTACK_FAMILIES, "environment.ATTACK_FAMILY")
    _check_enum(strategy, ALL_STRATEGIES, "environment.DAG_STRATEGY")
    return family, strategy


def parse_config(raw: dict) -> V2Config:
    """Validate and resolve a v2-or-v1 YAML mapping into a V2Config.

    A paper-1 YAML (no `adversary` or `victims` block) resolves to TM-Solo
    with no concrete policies — the legacy `environment` keys still drive
    the underlying launcher. New v2 features only activate when the new
    blocks are present.
    """
    if not isinstance(raw, dict):
        raise SchemaError(f"top-level config must be a mapping, got {type(raw).__name__}")

    protocol_d = raw.get("protocol") or {}
    if isinstance(protocol_d, dict):
        protocol = str(_require(protocol_d, "name", "protocol"))
    else:
        protocol = str(protocol_d)

    env = raw.get("environment") or {}
    num_nodes = int(env.get("NUM_NODES", 13))

    adversary = _parse_adversary(raw.get("adversary"))
    victims = _parse_victims(raw.get("victims"))
    runtime = _parse_runtime(raw.get("runtime"))
    family, strategy = _infer_family_and_strategy(raw, adversary)

    return V2Config(
        protocol=protocol,
        num_nodes=num_nodes,
        attack_family=family,
        dag_strategy=strategy,
        adversary=adversary,
        victims=victims,
        runtime=runtime,
        raw=raw,
    )
