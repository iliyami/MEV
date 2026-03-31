from __future__ import annotations

import csv
import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from typing import Dict, Iterable, List, Sequence, Tuple

import yaml

from .config import ROOT


RESULT_PATHS = [
    ROOT / "experiment_results.csv",
    ROOT / "autobahn_results.csv",
    ROOT / "back_sand_results.csv",
]

BASELINE_PATH = ROOT / "baseline.csv"

PROTOCOL_CONFIGS = {
    "mevsui": ROOT / "config" / "grand_experiment.yaml",
    "narwhal": ROOT / "config" / "grand_experiment_narwhal.yaml",
    "mysticeti": ROOT / "config" / "grand_experiment_mysticeti.yaml",
    "alephbft": ROOT / "config" / "grand_experiment_alephbft.yaml",
    "mahimahi": ROOT / "config" / "grand_experiment_mahimahi.yaml",
    "autobahn": ROOT / "config" / "grand_experiment_autobahn.yaml",
    "bullshark": ROOT / "config" / "local_verify_unified.yaml",
}

META_KEYS = {
    "timestamp",
    "protocol",
    "experiment",
    "attack_type",
    "attack_mode",
    "rep",
    "asr",
    "asr_l1",
    "asr_l2",
    "asr_histogram",
    "duration",
    "exit_code",
}

DISPLAY_KEYS = [
    "NUM_NODES",
    "ATTACKER_RATIO",
    "VICTIM_RATIO",
    "VICTIM_COUNT",
    "NUM_WORKERS",
    "SPECULATIVE_P_MAX",
    "SLUGGISH_TIMEOUT_MULTIPLIER",
    "SLUGGISH_MULTIPLIER",
    "EXCLUSION_PROBABILITY",
    "LATENCY_JITTER",
    "LATENCY_MS",
    "JITTER_MS",
    "DAG_STATE_CACHED_ROUNDS",
    "SYNC_TIMEOUT_MS",
    "GC_DEPTH",
    "HEADER_SIZE",
    "MAX_HEADER_DELAY",
    "BATCH_SIZE",
    "MAX_BATCH_DELAY",
    "WAVE_LENGTH",
    "NUMBER_OF_LEADERS",
    "SPECULATIVE_STRATEGY",
    "ALEPH_ELECTION_LOOKAHEAD",
    "ALEPH_COORD_REQUEST_DELAY_MS",
    "ALEPH_HASH_SORT_SEED",
    "AUTOBAHN_K",
    "AUTOBAHN_FAST_PATH_TIMEOUT",
    "AUTOBAHN_USE_FAST_PATH",
]


@dataclass(frozen=True)
class Row:
    source: str
    raw: Dict[str, str]
    defaults: Dict[str, str]

    @property
    def protocol(self) -> str:
        return self.raw["protocol"]

    @property
    def experiment(self) -> str:
        return self.raw["experiment"]

    @property
    def attack_mode(self) -> str:
        return self.raw["attack_mode"]

    @property
    def attack_type(self) -> str:
        return self.raw.get("attack_type", "") or self.raw.get("ATTACK_TYPE", "") or "frontrun"

    @property
    def rep(self) -> int:
        return int(self.raw["rep"])

    @property
    def asr(self) -> float:
        return float(self.raw["asr"])

    def get(self, key: str, default: str = "") -> str:
        value = self.raw.get(key, "")
        if value not in ("", None):
            return value
        return self.defaults.get(key, default)

    def get_float(self, key: str) -> float | None:
        value = self.get(key, "")
        if value in ("", None):
            return None
        try:
            return float(value)
        except ValueError:
            return None

    def get_int(self, key: str) -> int | None:
        value = self.get(key, "")
        if value in ("", None):
            return None
        try:
            return int(float(value))
        except ValueError:
            return None

    def param_signature(self) -> Tuple[Tuple[str, str], ...]:
        keys = sorted(k for k in self.raw.keys() if k not in META_KEYS)
        return tuple((key, self.get(key, "")) for key in keys)


def load_protocol_defaults() -> Dict[str, Dict[str, str]]:
    defaults: Dict[str, Dict[str, str]] = {}
    for protocol, path in PROTOCOL_CONFIGS.items():
        with path.open() as handle:
            config = yaml.safe_load(handle)
        env = config.get("environment", {})
        defaults[protocol] = {key: str(value) for key, value in env.items()}
    return defaults


def clean_csv_row(row: Dict[str, str]) -> Dict[str, str]:
    return {
        key: (value.strip() if isinstance(value, str) else value)
        for key, value in row.items()
        if key is not None
    }


def load_rows() -> List[Row]:
    defaults = load_protocol_defaults()
    rows: List[Row] = []
    for path in RESULT_PATHS:
        if not path.exists():
            continue
        with path.open() as handle:
            reader = csv.DictReader(handle)
            for raw_row in reader:
                row = clean_csv_row(raw_row)
                protocol = row["protocol"]
                asr = row.get("asr", "")
                if asr in ("", "N/A"):
                    continue
                try:
                    float(asr)
                except ValueError:
                    continue
                rows.append(Row(source=path.name, raw=row, defaults=defaults[protocol]))
    return rows


def load_baselines() -> Dict[str, float]:
    latest: Dict[str, float] = {}
    with BASELINE_PATH.open() as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if row.get("status") != "success":
                continue
            latest[row["protocol"]] = float(row["asr"])
    return latest


def group_rows(rows: Iterable[Row], keys: Sequence[str]) -> Dict[Tuple[str, ...], List[Row]]:
    grouped: Dict[Tuple[str, ...], List[Row]] = defaultdict(list)
    for row in rows:
        grouped[tuple(getattr(row, key) for key in keys)].append(row)
    return grouped


def median_asr(rows: Sequence[Row]) -> float:
    return median(row.asr for row in rows)


def percentile(sorted_values: Sequence[float], p: float) -> float:
    if not sorted_values:
        raise ValueError("percentile requires non-empty input")
    if len(sorted_values) == 1:
        return sorted_values[0]
    pos = (len(sorted_values) - 1) * p
    lower = math.floor(pos)
    upper = math.ceil(pos)
    if lower == upper:
        return sorted_values[lower]
    weight = pos - lower
    return sorted_values[lower] * (1.0 - weight) + sorted_values[upper] * weight


def box_stats(values: Sequence[float]) -> Dict[str, float]:
    ordered = sorted(values)
    q1 = percentile(ordered, 0.25)
    med = percentile(ordered, 0.50)
    q3 = percentile(ordered, 0.75)
    iqr = q3 - q1
    low_fence = q1 - 1.5 * iqr
    high_fence = q3 + 1.5 * iqr
    inliers = [value for value in ordered if low_fence <= value <= high_fence]
    whisker_low = min(inliers) if inliers else ordered[0]
    whisker_high = max(inliers) if inliers else ordered[-1]
    outliers = [value for value in ordered if value < low_fence or value > high_fence]
    return {
        "lower_whisker": whisker_low,
        "lower_quartile": q1,
        "median": med,
        "upper_quartile": q3,
        "upper_whisker": whisker_high,
        "min": ordered[0],
        "max": ordered[-1],
        "n": len(ordered),
        "outliers": outliers,
    }


def sort_key(value: str) -> Tuple[int, float | str]:
    if value is None:
        return (2, "")
    text = str(value).strip()
    if text == "":
        return (2, "")
    if text.endswith("ms") and " " not in text:
        try:
            return (0, float(text[:-2]))
        except ValueError:
            return (1, text)
    if text in {"true", "false"}:
        return (0, 1.0 if text == "true" else 0.0)
    try:
        return (0, float(text))
    except ValueError:
        return (1, text)


def unique_effective_values(rows: Iterable[Row], key: str) -> List[str]:
    values = {row.get(key, "") for row in rows}
    return sorted(values, key=sort_key)


def experiment_matrix(rows: Iterable[Row]) -> Dict[Tuple[str, str, str, str], List[Row]]:
    grouped: Dict[Tuple[str, str, str, str], List[Row]] = defaultdict(list)
    for row in rows:
        grouped[(row.protocol, row.experiment, row.attack_type, row.attack_mode)].append(row)
    return grouped


def varying_keys(rows: Sequence[Row]) -> List[str]:
    keys = sorted(k for k in rows[0].raw.keys() if k not in META_KEYS and k is not None)
    varying = []
    for key in keys:
        values = {row.get(key, "") for row in rows}
        if len(values) > 1:
            varying.append(key)
    return varying


def fixed_values(rows: Sequence[Row], keys: Sequence[str] = DISPLAY_KEYS) -> Dict[str, str]:
    fixed: Dict[str, str] = {}
    for key in keys:
        values = {row.get(key, "") for row in rows}
        if len(values) == 1:
            value = next(iter(values))
            if value != "":
                fixed[key] = value
    return fixed


def completeness(rows: Sequence[Row], varying: Sequence[str]) -> Dict[Tuple[str, ...], List[int]]:
    buckets: Dict[Tuple[str, ...], List[int]] = defaultdict(list)
    for row in rows:
        signature = tuple(row.get(key, "") for key in varying)
        buckets[signature].append(row.rep)
    for reps in buckets.values():
        reps.sort()
    return dict(buckets)


def infer_attacker_count(row: Row) -> str:
    num_nodes = row.get_int("NUM_NODES")
    ratio = row.get_float("ATTACKER_RATIO")
    if num_nodes is None or ratio is None:
        attacker_id = row.get("ATTACKER_ID", "")
        if attacker_id != "":
            return "1 explicit attacker"
        return ""
    return f"~{round(num_nodes * ratio)} attackers ({ratio:.3f})"


def infer_victim_setup(row: Row) -> str:
    victim_count = row.get("VICTIM_COUNT", "")
    if victim_count:
        return f"{victim_count} victims"
    victim_ratio = row.get_float("VICTIM_RATIO")
    num_nodes = row.get_int("NUM_NODES")
    if num_nodes is None or victim_ratio is None:
        victim_id = row.get("VICTIM_ID", "")
        if victim_id != "":
            return "1 explicit victim"
        return ""
    return f"~{round(num_nodes * victim_ratio)} victims ({victim_ratio:.3f})"


def summarize_protocol_baselines(baselines: Dict[str, float]) -> List[Tuple[str, float]]:
    return sorted(baselines.items(), key=lambda item: item[0])


def find_structural_anomalies(rows: Sequence[Row]) -> Dict[str, object]:
    high_asr = [
        row for row in rows
        if row.asr >= 99.9
    ]
    by_file: Dict[str, int] = Counter(row.source for row in rows)
    incomplete_cells: List[Dict[str, object]] = []
    for (protocol, experiment, attack_type, attack), bucket in sorted(experiment_matrix(rows).items()):
        varying = varying_keys(bucket)
        if not varying:
            continue
        cell_reps = completeness(bucket, varying)
        expected = max(len(reps) for reps in cell_reps.values())
        for signature, reps in sorted(cell_reps.items()):
            if len(reps) < expected:
                incomplete_cells.append({
                    "protocol": protocol,
                    "experiment": experiment,
                    "attack_type": attack_type,
                    "attack_mode": attack,
                    "varying": list(varying),
                    "signature": list(signature),
                    "reps": reps,
                    "expected": expected,
                })
    return {
        "row_count": len(rows),
        "rows_by_file": dict(by_file),
        "high_asr_count": len(high_asr),
        "high_asr_examples": high_asr[:12],
        "incomplete_cells": incomplete_cells,
    }
