"""Benchmarking framework for the v2 campaigns.

Each campaign is a list of `Cell`s. The framework:

  * runs each cell `reps` times (default 5 — distributed-systems convention),
  * captures full subprocess output + Coordinator metrics per rep,
  * runs an optional per-rep marker extractor (e.g., count V2_VICTIM_PROFIT
    lines, verify multi-policy assignments) and stores the extracted fields
    as additional CSV columns,
  * compares against the paper-1 reference manifest where applicable,
  * writes one CSV row per rep with full config + extracted markers + run
    metadata, and one JSON summary with `mean / median / IQR / min / max`
    per cell, suitable for paper-figure generation.

Cell column schema = standard `V2_FIELDNAMES` from sweeper.py + the
additional v2-marker columns declared per-cell in `Cell.extra_columns`. The
CSV header is the union across all cells of a single run, so later analysis
can read one file.

Invariants (CLAUDE.md):
    * No protocol code is modified here -- benchmark.py is pure
      orchestration on top of the v2 sweeper and launcher.
    * Determinism: each rep's seed is `cfg.runtime.seed + rep`. Mark this
      explicitly in the CSV so the same draws can be reproduced.

Used by:
    scripts/v2/p1_live.py   (P1 mechanism-smoke benchmark)
    scripts/v2/p2_campaign.py (planned for the Competition campaign)
"""

from __future__ import annotations

import csv
import dataclasses
import datetime
import json
import statistics as st
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

from . import baselines as paper1_baselines
from . import schema, sweeper, victim_gen
from .coordinator import CoordinatorServer
from .launchers.bullshark import BullsharkLauncher
from .sweeper import RunRequest, RunResult, V2_FIELDNAMES, make_run_id

# Type aliases (kept loose to avoid a circular import on launcher hook type).
MarkerExtractor = Callable[[str, RunResult], dict[str, Any]]
Paper1Lookup = Callable[[schema.V2Config], Optional[paper1_baselines.ReferenceCell]]
OnCoordinatorReady = Callable[
    [CoordinatorServer, schema.V2Config, int], Optional[threading.Thread]
]


# ---------------------------------------------------------------------------
# Cell + run helpers
# ---------------------------------------------------------------------------


@dataclass
class Cell:
    """One benchmark cell -- a config that gets run `reps` times.

    name              -- stable identifier; rows in the CSV carry it.
    config            -- the materialized V2Config to execute.
    extra_columns     -- ordered list of extra CSV column names this cell
                         contributes via its marker_extractor's output dict.
    marker_extractor  -- (raw_output, RunResult) -> dict of values to embed.
                         Keys should be the subset of extra_columns this cell
                         populates; missing keys become empty cells.
    paper1_lookup     -- (cfg) -> Optional[ReferenceCell]; if returned, the
                         cell's `asr` median will be tolerance-checked.
    on_coord_ready    -- forwarded to BullsharkLauncher to run a side-channel
                         exercise concurrently with each rep.
    """

    name: str
    config: schema.V2Config
    extra_columns: tuple[str, ...] = ()
    marker_extractor: Optional[MarkerExtractor] = None
    paper1_lookup: Optional[Paper1Lookup] = None
    on_coord_ready: Optional[OnCoordinatorReady] = None
    launcher: Optional[Any] = None  # Override: pass a pre-built launcher instance (e.g. SuiLauncher)


@dataclass
class CellRepResult:
    """Per-rep record. One row in the CSV."""

    cell_name: str
    rep: int
    seed: int
    run_id: str
    asr: Optional[float]
    asr_l1: Optional[float]
    asr_l2: Optional[float]
    exit_code: int
    duration_sec: float
    timestamp: str
    extras: dict[str, Any]  # populated by marker_extractor
    run_result: RunResult
    profit: Optional[dict[str, Any]] = None  # realized-profit metric (T4)


@dataclass
class CellSummary:
    """Per-cell summary across all reps. One JSON record."""

    cell_name: str
    threat_model: str
    archetype: Optional[str]
    attack_family: str
    dag_strategy: str
    num_nodes: int
    reps: int
    asrs: list[float]
    asr_mean: Optional[float]
    asr_median: Optional[float]
    asr_min: Optional[float]
    asr_max: Optional[float]
    asr_iqr: Optional[float]
    paper1_ref_median: Optional[float]
    paper1_tolerance_pp: Optional[float]
    paper1_findings: list[str]
    paper1_within_tolerance: Optional[bool]
    coord_metrics_last: Optional[dict[str, Any]]
    extras_aggregated: dict[str, Any]
    all_exit_codes: list[int]
    # Realized-profit metric (T4) — the campaign's primary metric.
    profit_weighted_asr_mean: Optional[float] = None
    profit_weighted_asr_median: Optional[float] = None
    realized_mev_mean: Optional[float] = None


def _iqr(xs: list[float]) -> Optional[float]:
    if len(xs) < 2:
        return None
    quartiles = st.quantiles(xs, n=4)
    return quartiles[2] - quartiles[0]


def _aggregate_extras(rep_extras: list[dict[str, Any]], keys: Sequence[str]) -> dict:
    """For each extra column, collect across reps and compute a sensible summary."""
    out: dict[str, Any] = {}
    for k in keys:
        values = [r.get(k) for r in rep_extras if k in r]
        # Bool: report fraction true
        if values and all(isinstance(v, bool) for v in values):
            out[k] = {"all_true": all(values), "fraction_true": sum(values) / len(values)}
            continue
        # Numeric: aggregate
        numeric = [v for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)]
        if numeric and len(numeric) == len(values):
            out[k] = {
                "mean": st.mean(numeric),
                "median": st.median(numeric),
                "min": min(numeric),
                "max": max(numeric),
                "raw": numeric,
            }
            continue
        # Fallback: keep raw list (preserves order)
        out[k] = {"raw": values}
    return out


def _paper1_lookup_frontrun(cfg: schema.V2Config) -> Optional[paper1_baselines.ReferenceCell]:
    """Convenience: lookup paper-1 frontrun reference cell by dag_strategy."""
    return paper1_baselines.reference_cell(cfg.attack_family, cfg.dag_strategy, metric="asr")


# Exported aliases — campaigns can pick the lookup that matches their cells.
paper1_lookup_frontrun = _paper1_lookup_frontrun


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


# Fixed CSV columns (everything beyond V2_FIELDNAMES is a per-cell extra).
_CSV_FIXED = list(V2_FIELDNAMES) + [
    "cell_name",
    "paper1_ref_median",
    "paper1_tolerance_pp",
    "paper1_within_tolerance",
    "coord_metrics_json",
    # Realized-profit metric (T4) — the campaign's primary metric.
    "realized_mev",
    "profit_weighted_asr",
    "profit_total",
    "profit_n_victims",
]


def _compute_realized_profit(
    committed_order: Optional[list[dict[str, Any]]],
    cfg: schema.V2Config,
    seed: int,
) -> Optional[dict[str, float]]:
    """Realized-profit metric (T4) computed from the committed order.

    Every VICTIM block is weighted by a deterministic per-block profit
    (`victim_gen.VictimProfile`, seeded by the run seed) and marked "attacked"
    when some attacker block shares its round at an earlier position (the
    frontrun predicate). Returns `victim_gen.profit_weighted_asr`'s dict, or
    None when there is no committed order / no victim blocks (defensive: a
    malformed record is skipped, never fatal).
    """
    if not committed_order:
        return None
    attackers: set[int] = set()
    for p in cfg.adversary.policies:
        attackers |= {int(m) for m in p.members}
    n = cfg.num_nodes
    if cfg.victims.victim_node_ids:
        victims = {int(x) for x in cfg.victims.victim_node_ids}
    else:
        env = (cfg.raw or {}).get("environment", {}) or {}
        try:
            vr = float(env.get("VICTIM_RATIO", 0.231))
        except (TypeError, ValueError):
            vr = 0.231
        victims = set(range(n - round(n * vr), n))

    def _rec(e: dict) -> Optional[tuple[int, int, int]]:
        try:
            return int(e["creator"]), int(e["position"]), int(e["round"])
        except (KeyError, TypeError, ValueError):
            return None

    att_pos_by_round: dict[int, list[int]] = {}
    for e in committed_order:
        r = _rec(e)
        if r is not None and r[0] in attackers:
            att_pos_by_round.setdefault(r[2], []).append(r[1])

    blocks: list[dict[str, Any]] = []
    for e in committed_order:
        r = _rec(e)
        if r is not None and r[0] in victims:
            creator, pos, rnd = r
            attacked = any(ap < pos for ap in att_pos_by_round.get(rnd, ()))
            blocks.append({"round": rnd, "author": creator, "attacked": attacked})
    if not blocks:
        return None
    profile = victim_gen.VictimProfile.from_config(
        {
            "distribution": cfg.victims.profit.distribution,
            "params": dict(cfg.victims.profit.params),
        },
        seed=seed,
    )
    return victim_gen.profit_weighted_asr(blocks, profile)


def _row_from_rep(
    cell: Cell, rep_result: CellRepResult, paper1_ref: Optional[paper1_baselines.ReferenceCell]
) -> dict[str, Any]:
    cfg = cell.config
    rr = rep_result.run_result
    coord_metrics = rr.metrics.get("coordinator_metrics") or {}
    within = None
    if paper1_ref is not None and rep_result.asr is not None:
        within = abs(rep_result.asr - paper1_ref.median_pct) <= paper1_ref.tolerance_pp
    row: dict[str, Any] = {
        # V2_FIELDNAMES standard columns:
        "timestamp": rep_result.timestamp,
        "run_id": rep_result.run_id,
        "protocol": cfg.protocol,
        "threat_model": cfg.adversary.threat_model,
        "archetype": cfg.adversary.archetype or "",
        "attack_family": cfg.attack_family,
        "dag_strategy": cfg.dag_strategy,
        "num_nodes": cfg.num_nodes,
        "attacker_fraction": (
            sum(len(p.members) for p in cfg.adversary.policies) / cfg.num_nodes
            if cfg.adversary.policies
            else ""
        ),
        "num_policies": len(cfg.adversary.policies),
        "rep": rep_result.rep,
        "seed": rep_result.seed,
        "exit_code": rep_result.exit_code,
        "duration_sec": rep_result.duration_sec,
        "asr": rep_result.asr if rep_result.asr is not None else "",
        "asr_l1": rep_result.asr_l1 if rep_result.asr_l1 is not None else "",
        "asr_l2": rep_result.asr_l2 if rep_result.asr_l2 is not None else "",
        "asr_histogram": rr.metrics.get("asr_histogram") or "",
        "per_policy_asr_json": json.dumps(rr.metrics.get("per_policy_asr") or {}),
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
        "auditor_findings_count": len(rr.auditor_findings),
        "runtime_violations_count": len(rr.runtime_violations),
        "config_path": f"<benchmark/{cell.name}>",
        # Benchmark-added fixed columns:
        "cell_name": cell.name,
        "paper1_ref_median": paper1_ref.median_pct if paper1_ref is not None else "",
        "paper1_tolerance_pp": paper1_ref.tolerance_pp if paper1_ref is not None else "",
        "paper1_within_tolerance": "" if within is None else within,
        "coord_metrics_json": json.dumps(coord_metrics, default=str),
        # Realized-profit metric (T4). profit_weighted_asr is scaled to a percent
        # here (victim_gen returns a 0..1 fraction) so it lines up with `asr`.
        "realized_mev": (rep_result.profit or {}).get("realized_mev", ""),
        "profit_weighted_asr": (
            round(rep_result.profit["profit_weighted_asr"] * 100.0, 4)
            if rep_result.profit else ""
        ),
        "profit_total": (rep_result.profit or {}).get("total_profit", ""),
        "profit_n_victims": (rep_result.profit or {}).get("n_victims", ""),
    }
    # Cell-specific extras:
    for k in cell.extra_columns:
        v = rep_result.extras.get(k, "")
        # JSON-encode complex types so the CSV stays one row per rep.
        if isinstance(v, (dict, list, tuple)):
            row[k] = json.dumps(v, default=str)
        else:
            row[k] = v
    return row


def _run_one_rep(
    cell: Cell, rep: int, launcher_kwargs: Optional[dict[str, Any]] = None
) -> CellRepResult:
    cfg = cell.config
    seed = cfg.runtime.seed + rep
    run_id = make_run_id(cfg, rep)
    if cell.launcher is not None:
        launcher = cell.launcher
    else:
        launcher = BullsharkLauncher(
            on_coordinator_ready=cell.on_coord_ready,
            **(launcher_kwargs or {}),
        )
    req = RunRequest(config=cfg, rep=rep, seed=seed, run_id=run_id)
    rr = launcher.run(req)

    asr = rr.metrics.get("asr")
    extras: dict[str, Any] = {}
    if cell.marker_extractor is not None:
        try:
            extras = cell.marker_extractor(rr.raw_output, rr) or {}
        except Exception as e:  # extractor bugs shouldn't kill the run
            extras = {"_marker_extractor_error": f"{type(e).__name__}: {e}"}

    profit = _compute_realized_profit(rr.metrics.get("committed_order"), cfg, seed)

    return CellRepResult(
        cell_name=cell.name,
        rep=rep,
        seed=seed,
        run_id=run_id,
        asr=float(asr) if asr is not None else None,
        asr_l1=(float(rr.metrics["asr_l1"]) if rr.metrics.get("asr_l1") is not None else None),
        asr_l2=(float(rr.metrics["asr_l2"]) if rr.metrics.get("asr_l2") is not None else None),
        exit_code=rr.exit_code,
        duration_sec=rr.duration_sec,
        timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        extras=extras,
        run_result=rr,
        profit=profit,
    )


def run_benchmark(
    cells: list[Cell],
    out_csv: str,
    out_summary_json: str,
    reps: Optional[int] = None,
    launcher_kwargs: Optional[dict[str, Any]] = None,
    progress_callback: Optional[Callable[[str], None]] = None,
) -> dict[str, CellSummary]:
    """Run each cell `reps` times. Returns {cell_name: CellSummary}.

    Writes:
      out_csv             -- one row per rep, union of all cells' columns
      out_summary_json    -- one record per cell with stats + paper-1 compare
    """
    out_csv_p = Path(out_csv)
    out_summary_p = Path(out_summary_json)
    out_csv_p.parent.mkdir(parents=True, exist_ok=True)
    out_summary_p.parent.mkdir(parents=True, exist_ok=True)

    # Union of extra_columns across cells, preserving each cell's order.
    extra_cols: list[str] = []
    for c in cells:
        for k in c.extra_columns:
            if k not in extra_cols:
                extra_cols.append(k)
    full_fieldnames = _CSV_FIXED + extra_cols

    summaries: dict[str, CellSummary] = {}
    write_header = not out_csv_p.exists()
    csv_fh = open(out_csv_p, "a", newline="")
    try:
        writer = csv.DictWriter(csv_fh, fieldnames=full_fieldnames)
        if write_header:
            writer.writeheader()

        for cell in cells:
            cell_reps = reps if reps is not None else cell.config.runtime.reps
            if progress_callback:
                progress_callback(
                    f"[{cell.name}] starting {cell_reps} reps "
                    f"(threat_model={cell.config.adversary.threat_model})"
                )
            rep_results: list[CellRepResult] = []
            for r in range(cell_reps):
                if progress_callback:
                    progress_callback(f"[{cell.name}] rep {r + 1}/{cell_reps} ...")
                rep_res = _run_one_rep(cell, r, launcher_kwargs=launcher_kwargs)
                rep_results.append(rep_res)
                paper1_ref = (
                    cell.paper1_lookup(cell.config) if cell.paper1_lookup else None
                )
                writer.writerow(_row_from_rep(cell, rep_res, paper1_ref))
                csv_fh.flush()
                if progress_callback:
                    asr_s = f"{rep_res.asr:.2f}%" if rep_res.asr is not None else "N/A"
                    progress_callback(
                        f"[{cell.name}]   exit={rep_res.exit_code} asr={asr_s} "
                        f"duration={rep_res.duration_sec:.1f}s"
                    )

            # Summary
            asrs = [r.asr for r in rep_results if r.asr is not None]
            paper1_ref = cell.paper1_lookup(cell.config) if cell.paper1_lookup else None
            within_tol: Optional[bool] = None
            findings: list[str] = []
            if paper1_ref is not None and asrs:
                med = st.median(asrs)
                findings = paper1_baselines.check_against_paper1(
                    observed_median_pct=med,
                    family=cell.config.attack_family,
                    strategy=cell.config.dag_strategy,
                    metric="asr",
                )
                within_tol = not findings
            extras_agg = _aggregate_extras(
                [r.extras for r in rep_results], cell.extra_columns
            )
            last_coord = rep_results[-1].run_result.metrics.get("coordinator_metrics") if rep_results else None
            # profit_weighted_asr -> percent, to match `asr`.
            pwasrs = [r.profit["profit_weighted_asr"] * 100.0 for r in rep_results if r.profit]
            realized = [r.profit["realized_mev"] for r in rep_results if r.profit]

            summary = CellSummary(
                cell_name=cell.name,
                threat_model=cell.config.adversary.threat_model,
                archetype=cell.config.adversary.archetype,
                attack_family=cell.config.attack_family,
                dag_strategy=cell.config.dag_strategy,
                num_nodes=cell.config.num_nodes,
                reps=len(rep_results),
                asrs=asrs,
                asr_mean=st.mean(asrs) if asrs else None,
                asr_median=st.median(asrs) if asrs else None,
                asr_min=min(asrs) if asrs else None,
                asr_max=max(asrs) if asrs else None,
                asr_iqr=_iqr(asrs),
                paper1_ref_median=paper1_ref.median_pct if paper1_ref else None,
                paper1_tolerance_pp=paper1_ref.tolerance_pp if paper1_ref else None,
                paper1_findings=findings,
                paper1_within_tolerance=within_tol,
                coord_metrics_last=last_coord,
                extras_aggregated=extras_agg,
                all_exit_codes=[r.exit_code for r in rep_results],
                profit_weighted_asr_mean=st.mean(pwasrs) if pwasrs else None,
                profit_weighted_asr_median=st.median(pwasrs) if pwasrs else None,
                realized_mev_mean=st.mean(realized) if realized else None,
            )
            summaries[cell.name] = summary
            if progress_callback:
                progress_callback(
                    f"[{cell.name}] done: asr_median={summary.asr_median} "
                    f"pwasr_median={summary.profit_weighted_asr_median} "
                    f"realized_mev_mean={summary.realized_mev_mean} "
                    f"(n={summary.reps})"
                )
    finally:
        csv_fh.close()

    # Write summary JSON
    out_summary_p.write_text(
        json.dumps(
            {
                "summaries": {
                    name: dataclasses.asdict(s) for name, s in summaries.items()
                },
                "csv": str(out_csv_p),
                "wrote_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            },
            indent=2,
            default=str,
        )
    )
    return summaries
