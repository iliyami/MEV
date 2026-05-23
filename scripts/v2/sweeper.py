"""experiment_sweeper_v2 — orchestration skeleton for multi-policy adversary runs.

Reads a v2 YAML, validates it, materializes the per-slot policy vector if the
config specifies an archetype rather than concrete policies, dispatches to the
per-protocol launcher, and aggregates results into the per-row CSV schema.

The launcher dispatch is a strategy-pattern hook (`Launcher`). P0 ships a stub
launcher (`StubLauncher`) so the harness end-to-end can be smoke-tested
without touching any protocol fork. P1 plugs in the real Bullshark launcher.
"""

from __future__ import annotations

import argparse
import csv
import dataclasses
import datetime
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Iterable, Optional, Protocol

# Local imports — supports both `python -m scripts.v2.sweeper` and direct exec.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
    from scripts.v2 import auditor as auditor_mod  # noqa: E402
    from scripts.v2 import policy as policy_mod  # noqa: E402
    from scripts.v2 import schema as schema_mod  # noqa: E402
else:
    from . import auditor as auditor_mod
    from . import policy as policy_mod
    from . import schema as schema_mod


# ---------------------------------------------------------------------------
# YAML loading (robust against the local-yaml-folder shadow in this repo)
# ---------------------------------------------------------------------------


def _load_yaml(path: str) -> dict:
    # Mirror the working-yaml import in scripts/experiment_sweeper.py to avoid
    # the local ./yaml/ directory shadowing the pyyaml package.
    root_dir = os.getcwd()
    if os.path.isdir(os.path.join(root_dir, "yaml")) and root_dir not in sys.path:
        sys.path.insert(0, root_dir)
    if "yaml" in sys.modules and not hasattr(sys.modules["yaml"], "safe_load"):
        del sys.modules["yaml"]
    import yaml  # noqa: WPS433

    with open(path, "r") as fh:
        return yaml.safe_load(fh)


# ---------------------------------------------------------------------------
# Launcher interface
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class RunRequest:
    config: schema_mod.V2Config
    rep: int
    seed: int
    run_id: str


@dataclasses.dataclass
class RunResult:
    run_id: str
    exit_code: int
    metrics: dict[str, Any]
    duration_sec: float
    auditor_findings: list[str]
    runtime_violations: list[auditor_mod.RuntimeViolation]
    raw_output: str = ""  # raw stdout+stderr; populated by launchers that capture it


class Launcher(Protocol):
    """Per-protocol launcher contract.

    Implementations live in scripts/v2/launchers/<protocol>.py and are wired
    in P1+. They must never modify the protocol's core code — they only
    invoke an existing binary or `cargo test` entrypoint that the protocol
    already exposes, plus the attacker hooks added in the protocol's own fork.
    """

    name: str

    def supports(self, protocol: str) -> bool: ...

    def run(self, request: RunRequest) -> RunResult: ...


class StubLauncher:
    """P0 launcher. Produces deterministic synthetic metrics and exit codes.

    Used to smoke-test the orchestration. Returns ASR=51.86 ± 0.5 for TM-Solo
    Bullshark frontrun/fissure cells to align with paper-1's pure baseline,
    and synthetic non-zero ASRs for other cells. This is *not* a result —
    it is a placeholder that proves the orchestration end-to-end.
    """

    name = "stub"

    def supports(self, protocol: str) -> bool:
        return True

    def run(self, request: RunRequest) -> RunResult:
        cfg = request.config
        # Deterministic seed-driven jitter.
        h = hashlib.sha256(
            f"{request.run_id}|{request.rep}|{cfg.protocol}|{cfg.attack_family}|{cfg.dag_strategy}".encode()
        ).digest()
        jitter = (h[0] / 255.0) - 0.5  # in [-0.5, 0.5]
        if cfg.adversary.threat_model == "TM-Solo" and cfg.attack_family == "frontrun":
            base = 95.0 if cfg.protocol == "bullshark" else 50.0
        else:
            base = 50.0 + (h[1] / 255.0) * 30.0
        asr = round(base + jitter, 4)
        return RunResult(
            run_id=request.run_id,
            exit_code=0,
            metrics={
                "asr": asr,
                "asr_l1": None,
                "asr_l2": None,
                "asr_histogram": None,
                "per_policy_asr": {
                    p.group_id: round(asr + (h[2] / 255.0 - 0.5) * 5.0, 4)
                    for p in cfg.adversary.policies
                }
                or None,
            },
            duration_sec=0.0,
            auditor_findings=[],
            runtime_violations=[],
        )


# ---------------------------------------------------------------------------
# CSV schema (extends paper-1; strict superset)
# ---------------------------------------------------------------------------

V2_FIELDNAMES = [
    "timestamp",
    "run_id",
    "protocol",
    "threat_model",
    "archetype",
    "attack_family",
    "dag_strategy",
    "num_nodes",
    "attacker_fraction",
    "num_policies",
    "rep",
    "seed",
    "exit_code",
    "duration_sec",
    "asr",
    "asr_l1",
    "asr_l2",
    "asr_histogram",
    "per_policy_asr_json",
    "victim_workload",
    "victim_count",
    "victim_profit_distribution",
    "coordination_enabled",
    "coordination_policy",
    "coordination_information",
    "bribery_enabled",
    "bribery_type",
    "bribery_settlement",
    "bribery_budget",
    "auditor_findings_count",
    "runtime_violations_count",
    "config_path",
]


def _row_from_result(
    result: RunResult, cfg: schema_mod.V2Config, config_path: str
) -> dict[str, Any]:
    return {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "run_id": result.run_id,
        "protocol": cfg.protocol,
        "threat_model": cfg.adversary.threat_model,
        "archetype": cfg.adversary.archetype or "",
        "attack_family": cfg.attack_family,
        "dag_strategy": cfg.dag_strategy,
        "num_nodes": cfg.num_nodes,
        "attacker_fraction": sum(len(p.members) for p in cfg.adversary.policies)
        / cfg.num_nodes
        if cfg.adversary.policies
        else "",
        "num_policies": len(cfg.adversary.policies),
        "rep": "",  # filled in by caller
        "seed": "",  # filled in by caller
        "exit_code": result.exit_code,
        "duration_sec": result.duration_sec,
        "asr": result.metrics.get("asr", ""),
        "asr_l1": result.metrics.get("asr_l1", "") or "",
        "asr_l2": result.metrics.get("asr_l2", "") or "",
        "asr_histogram": result.metrics.get("asr_histogram", "") or "",
        "per_policy_asr_json": json.dumps(result.metrics.get("per_policy_asr") or {}),
        "victim_workload": cfg.victims.workload,
        "victim_count": cfg.victims.count,
        "victim_profit_distribution": cfg.victims.profit.distribution,
        "coordination_enabled": cfg.adversary.coordination.enabled,
        "coordination_policy": cfg.adversary.coordination.policy,
        "coordination_information": cfg.adversary.coordination.information,
        "bribery_enabled": cfg.adversary.bribery.enabled,
        "bribery_type": cfg.adversary.bribery.type or "",
        "bribery_settlement": cfg.adversary.bribery.settlement,
        "bribery_budget": cfg.adversary.bribery.budget,
        "auditor_findings_count": len(result.auditor_findings),
        "runtime_violations_count": len(result.runtime_violations),
        "config_path": config_path,
    }


# ---------------------------------------------------------------------------
# Matrix expansion
# ---------------------------------------------------------------------------


def expand_policy_vector(cfg: schema_mod.V2Config) -> schema_mod.V2Config:
    """If the config specifies an archetype + no concrete policies, materialize."""
    adv = cfg.adversary
    if adv.policies or adv.archetype is None:
        return cfg
    # Derive f from existing environment knobs (paper-1 convention).
    env = cfg.raw.get("environment") or {}
    f = int(env.get("BYZANTINE_F") or env.get("F") or max(1, (cfg.num_nodes - 1) // 3))
    k_default = 1 if adv.threat_model in ("TM-Solo", "TM-Collude") else f
    k = int(env.get("ATTACKER_GROUPS_K") or k_default)
    req = policy_mod.PolicyVectorRequest(
        archetype=adv.archetype,
        n=cfg.num_nodes,
        f=f,
        k=k,
        base_family=cfg.attack_family,
        base_strategy=cfg.dag_strategy,
        seed=cfg.runtime.seed,
    )
    materialized = tuple(policy_mod.materialize(req))
    new_adv = dataclasses.replace(adv, policies=materialized)
    return dataclasses.replace(cfg, adversary=new_adv)


# ---------------------------------------------------------------------------
# Orchestration entry points
# ---------------------------------------------------------------------------


def make_run_id(cfg: schema_mod.V2Config, rep: int) -> str:
    h = hashlib.sha256()
    h.update(cfg.protocol.encode())
    h.update(cfg.adversary.threat_model.encode())
    h.update((cfg.adversary.archetype or "").encode())
    h.update(cfg.attack_family.encode())
    h.update(cfg.dag_strategy.encode())
    h.update(str(cfg.num_nodes).encode())
    h.update(str(rep).encode())
    h.update(str(cfg.runtime.seed).encode())
    return h.hexdigest()[:16]


def run_one(
    cfg: schema_mod.V2Config, launcher: Launcher, rep: int, seed: int
) -> RunResult:
    if not launcher.supports(cfg.protocol):
        raise RuntimeError(
            f"launcher {launcher.name!r} does not support protocol {cfg.protocol!r}"
        )
    return launcher.run(
        RunRequest(config=cfg, rep=rep, seed=seed, run_id=make_run_id(cfg, rep))
    )


def run_config(
    config_path: str,
    out_csv: str,
    launcher: Launcher,
    static_auditor: Optional[auditor_mod.StaticAuditor] = None,
    dry_run: bool = False,
) -> list[RunResult]:
    raw = _load_yaml(config_path)
    cfg = schema_mod.parse_config(raw)
    cfg = expand_policy_vector(cfg)

    if static_auditor is not None and cfg.runtime.invariant_audit:
        static_auditor.assert_clean()

    results: list[RunResult] = []
    write_header = not os.path.exists(out_csv)
    rows: list[dict[str, Any]] = []

    for rep in range(cfg.runtime.reps):
        if dry_run:
            print(
                f"[dry-run] cfg={config_path} rep={rep + 1}/{cfg.runtime.reps} "
                f"tm={cfg.adversary.threat_model} archetype={cfg.adversary.archetype} "
                f"family={cfg.attack_family} strategy={cfg.dag_strategy} "
                f"policies={len(cfg.adversary.policies)}"
            )
            continue
        result = run_one(cfg, launcher, rep, cfg.runtime.seed + rep)
        results.append(result)
        row = _row_from_result(result, cfg, config_path)
        row["rep"] = rep
        row["seed"] = cfg.runtime.seed + rep
        rows.append(row)

    if rows:
        with open(out_csv, "a", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=V2_FIELDNAMES)
            if write_header:
                writer.writeheader()
            for row in rows:
                writer.writerow(row)

    return results


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="experiment_sweeper_v2")
    parser.add_argument("--config", required=True, help="path to v2 YAML config")
    parser.add_argument("--out", required=True, help="path to output CSV")
    parser.add_argument(
        "--launcher",
        default="stub",
        choices=["stub", "bullshark"],
        help="protocol launcher to use",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.launcher == "bullshark":
        from scripts.v2.launchers import BullsharkLauncher
        launcher = BullsharkLauncher()
    else:
        launcher = StubLauncher()
    static_auditor = auditor_mod.make_default_auditor()
    results = run_config(
        config_path=args.config,
        out_csv=args.out,
        launcher=launcher,
        static_auditor=static_auditor,
        dry_run=args.dry_run,
    )
    print(
        f"ok: {len(results)} run(s); "
        f"out={args.out if not args.dry_run else '<dry-run>'}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
