"""Paper-1 baseline reference loader + contradiction detector.

Loads the curated JSON manifest of paper-1 Bullshark medians and provides a
single entry point `check_against_paper1(observed, family, strategy, metric)`
that returns a list of human-readable findings. Empty list ⇒ consistent.

Used by the sweeper after every Bullshark TM-Solo regression cell to catch
harness drift before the data is admitted.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

_MANIFEST_PATH = Path(__file__).resolve().parent / "refs" / "paper1_bullshark_baselines.json"


@dataclass(frozen=True)
class ReferenceCell:
    median_pct: float
    tolerance_pp: float
    source: str
    paper_ref: Optional[str] = None
    n: Optional[int] = None


def _load_manifest() -> dict:
    with open(_MANIFEST_PATH, "r") as fh:
        return json.load(fh)


_MANIFEST = _load_manifest()


def _get_tolerance(cell: dict, default: float) -> float:
    return float(cell.get("tolerance_pp", default))


def _default_tol() -> float:
    return float(_MANIFEST["_meta"]["tolerance_default_pct"])


def reference_cell(family: str, strategy: str, metric: str) -> Optional[ReferenceCell]:
    """Look up the paper-1 reference cell for (family, strategy, metric).

    family in {"frontrun", "backrun", "sandwich"}.
    strategy in {"fissure", "speculative", "sluggish"}.
    metric in {"asr", "asr_l1", "asr_l2", "cum_asr"}.

    Returns None when no reference exists (e.g., metric not applicable).
    """
    if family == "frontrun":
        cells = _MANIFEST.get("frontrun_default_config_n13", {})
        cell = cells.get(strategy)
        if cell is None or metric != "asr":
            return None
        return ReferenceCell(
            median_pct=float(cell["median_pct"]),
            tolerance_pp=_get_tolerance(cell, _default_tol()),
            source=cell["source"],
            paper_ref=cell.get("paper_ref"),
            n=cell.get("n"),
        )
    if family == "backrun":
        cells = _MANIFEST.get("backrun_cumulative_n13", {})
        cell = cells.get(strategy)
        if cell is None:
            return None
        if metric == "cum_asr":
            return ReferenceCell(
                median_pct=float(cell["cum_median_pct"]),
                tolerance_pp=_get_tolerance(cell, _default_tol()),
                source=cell["source"],
                n=cell.get("n"),
            )
        if metric == "asr_l1":
            return ReferenceCell(
                median_pct=float(cell["l1_median_pct"]),
                tolerance_pp=_get_tolerance(cell, _default_tol()),
                source=cell["source"],
                n=cell.get("n"),
            )
        if metric == "asr_l2":
            return ReferenceCell(
                median_pct=float(cell["l2_median_pct"]),
                tolerance_pp=_get_tolerance(cell, _default_tol()),
                source=cell["source"],
                n=cell.get("n"),
            )
        return None
    if family == "sandwich":
        cells = _MANIFEST.get("sandwich_triplet_n13", {})
        cell = cells.get(strategy)
        if cell is None or metric != "asr":
            return None
        return ReferenceCell(
            median_pct=float(cell["median_pct"]),
            tolerance_pp=_get_tolerance(cell, _default_tol()),
            source=cell["source"],
            n=cell.get("n"),
        )
    return None


def pure_baseline() -> ReferenceCell:
    cell = _MANIFEST["pure_baseline"]
    return ReferenceCell(
        median_pct=float(cell["value_pct"]),
        tolerance_pp=_get_tolerance(cell, 5.0),
        source=cell["source"],
        paper_ref=cell.get("paper_ref"),
    )


def check_against_paper1(
    observed_median_pct: float,
    family: str,
    strategy: str,
    metric: str = "asr",
) -> list[str]:
    """Return a list of contradiction findings. Empty list ⇒ within tolerance."""
    ref = reference_cell(family, strategy, metric)
    if ref is None:
        return [
            f"no paper-1 reference for ({family}, {strategy}, {metric}); "
            f"comparison skipped"
        ]
    delta = observed_median_pct - ref.median_pct
    if abs(delta) > ref.tolerance_pp:
        return [
            f"CONTRADICTION: {family}/{strategy}/{metric}: "
            f"observed {observed_median_pct:.2f}%, paper-1 reference "
            f"{ref.median_pct:.2f}% (tol +/- {ref.tolerance_pp:.1f}pp); "
            f"delta {delta:+.2f}pp. Source: {ref.source}"
        ]
    return []


def check_pure_baseline(observed_pct: float) -> list[str]:
    ref = pure_baseline()
    delta = observed_pct - ref.median_pct
    if abs(delta) > ref.tolerance_pp:
        return [
            f"CONTRADICTION: pure baseline observed {observed_pct:.2f}%, "
            f"paper-1 reference {ref.median_pct:.2f}% "
            f"(tol +/- {ref.tolerance_pp:.1f}pp). Source: {ref.source}"
        ]
    return []
