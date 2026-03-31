from __future__ import annotations

import csv
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from statistics import median
from typing import Dict, Iterable, List, Sequence, Tuple

from .config import (
    ATTACK_LABELS,
    ATTACK_MARKS,
    ATTACK_ORDER,
    ATTACK_STYLES,
    ATTACK_TIKZ_COLORS,
    EXPERIMENT_LABELS,
    FIGURE_DIR,
    GENERATED_DIR,
    LATENCY_LABELS,
    LATENCY_ORDER,
    PROTOCOL_LABELS,
    PROTOCOL_MARKS,
    PROTOCOL_ORDER,
    PROTOCOL_TIKZ_COLORS,
    REPORT_DIR,
    TIKZ_STYLE_PREAMBLE,
)
from .data_loader import (
    BASELINE_PATH,
    DISPLAY_KEYS,
    RESULT_PATHS,
    Row,
    box_stats,
    completeness,
    experiment_matrix,
    find_structural_anomalies,
    fixed_values,
    infer_attacker_count,
    infer_victim_setup,
    load_baselines,
    load_rows,
    sort_key,
    varying_keys,
)


ALL_PROTOCOLS = set(PROTOCOL_ORDER)

EXPECTED_PROTOCOLS = {
    "scaling": ALL_PROTOCOLS,
    "offense_fissure": ALL_PROTOCOLS,
    "offense_sluggish": ALL_PROTOCOLS,
    "offense_speculative": ALL_PROTOCOLS,
    "env_latency": ALL_PROTOCOLS,
    "defense_memory": {"bullshark", "narwhal", "mevsui"},
    "defense_gc": {"bullshark", "narwhal", "mevsui"},
    "defense_network": {"bullshark", "narwhal", "mevsui"},
    "defense_header": {"narwhal"},
    "defense_batching": {"narwhal"},
    "scaling_workers": {"narwhal"},
    "offense_exclusion": {"alephbft", "mysticeti", "autobahn"},
    "mahimahi_leaders": {"mahimahi", "mysticeti"},
    "mahimahi_wave": {"mahimahi", "mysticeti"},
    "mahimahi_strategy": {"mahimahi"},
    "mysticeti_strategy": {"mysticeti"},
    "aleph_lookahead": {"alephbft"},
    "aleph_sync_speed": {"alephbft"},
    "aleph_hash_randomization": {"alephbft"},
    "autobahn_k": {"autobahn"},
    "autobahn_fast_path": {"autobahn"},
}

COLUMN_TO_FIGURES = {
    "asr": ["fig01_peak_attack_lift", "all sensitivity and scaling figures"],
    "rep": ["fig03-fig05 scaling boxplots", "distribution checks in reports"],
    "NUM_NODES": ["fig01_peak_attack_lift", "fig02_scaling_trends", "fig03-fig05 scaling boxplots"],
    "ATTACKER_RATIO": ["fig06_offense_sweeps"],
    "SPECULATIVE_P_MAX": ["fig06_offense_sweeps"],
    "SLUGGISH_TIMEOUT_MULTIPLIER": ["fig06_offense_sweeps"],
    "DAG_STATE_CACHED_ROUNDS": ["fig08_core_defenses"],
    "SYNC_TIMEOUT_MS": ["fig08_core_defenses"],
    "GC_DEPTH": ["fig08_core_defenses"],
    "LATENCY_JITTER": ["fig07_latency_sensitivity"],
    "HEADER_SIZE": ["fig10_narwhal_header_heatmaps"],
    "MAX_HEADER_DELAY": ["fig10_narwhal_header_heatmaps"],
    "BATCH_SIZE": ["fig11_narwhal_batching_heatmaps"],
    "MAX_BATCH_DELAY": ["fig11_narwhal_batching_heatmaps"],
    "NUM_WORKERS": ["fig09_narwhal_workers"],
    "WAVE_LENGTH": ["fig12_wave_leaders"],
    "NUMBER_OF_LEADERS": ["fig12_wave_leaders"],
    "SPECULATIVE_STRATEGY": ["fig13_strategy_sweeps"],
    "EXCLUSION_PROBABILITY": ["fig06_offense_sweeps"],
    "HYBRID_EXCLUSION": ["inventory report only"],
    "SIMPLE_EXCLUSION_PROB": ["inventory report only"],
    "VICTIM_RATIO": ["inventory report only"],
    "VICTIM_COUNT": ["inventory report only"],
    "ALEPH_ELECTION_LOOKAHEAD": ["fig14_aleph_knobs"],
    "ALEPH_COORD_REQUEST_DELAY_MS": ["fig14_aleph_knobs"],
    "ALEPH_HASH_SORT_SEED": ["fig14_aleph_knobs"],
    "AUTOBAHN_K": ["fig15_autobahn_knobs"],
    "AUTOBAHN_FAST_PATH_TIMEOUT": ["fig15_autobahn_knobs"],
    "AUTOBAHN_USE_FAST_PATH": ["inventory report only"],
    "duration": ["experiment inventory report"],
    "exit_code": ["experiment inventory report"],
    "timestamp": ["provenance only"],
    "protocol": ["all figures"],
    "experiment": ["all figures"],
    "attack_mode": ["all figures"],
}

STRATEGY_ORDER = {
    "simple": 0,
    "smart": 1,
    "aggressive": 2,
    "sophisticated": 3,
    "traversal": 4,
    "hybrid": 5,
}

VIRIDIS_STOPS = [
    (0.0, (68, 1, 84)),
    (0.25, (59, 82, 139)),
    (0.5, (33, 145, 140)),
    (0.75, (94, 201, 97)),
    (1.0, (253, 231, 37)),
]


@dataclass
class FigureInfo:
    name: str
    title: str
    path: Path
    columns: List[str]
    purpose: str
    setup: str
    baseline_use: str


def ensure_dirs() -> None:
    FIGURE_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n")


def report_stamp() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z")


def fmt(value: float, digits: int = 2) -> str:
    return f"{value:.{digits}f}"


def tex_escape(text: str) -> str:
    replacements = {
        "_": r"\_",
        "%": r"\%",
        "&": r"\&",
        "#": r"\#",
    }
    out = text
    for old, new in replacements.items():
        out = out.replace(old, new)
    return out


def param_value_label(key: str, value: str) -> str:
    if key == "LATENCY_JITTER":
        return LATENCY_LABELS.get(value, value)
    return str(value)


def sorted_unique_values(rows: Iterable[Row], key: str, *, custom_order: Dict[str, int] | None = None) -> List[str]:
    values = {row.get(key, "") for row in rows}
    if custom_order is not None:
        return sorted(values, key=lambda value: (custom_order.get(value, 999), str(value)))
    return sorted(values, key=sort_key)


def filter_expected(rows: Iterable[Row]) -> List[Row]:
    filtered: List[Row] = []
    for row in rows:
        expected = EXPECTED_PROTOCOLS.get(row.experiment)
        if expected is not None and row.protocol not in expected:
            continue
        filtered.append(row)
    return filtered


def filter_rows(
    rows: Iterable[Row],
    *,
    protocol: str | None = None,
    experiment: str | None = None,
    attack_mode: str | None = None,
) -> List[Row]:
    filtered: List[Row] = []
    for row in rows:
        if protocol is not None and row.protocol != protocol:
            continue
        if experiment is not None and row.experiment != experiment:
            continue
        if attack_mode is not None and row.attack_mode != attack_mode:
            continue
        filtered.append(row)
    return filtered


def group_cell_medians(rows: Iterable[Row], x_key: str) -> Dict[str, float]:
    buckets: Dict[str, List[float]] = defaultdict(list)
    for row in rows:
        buckets[row.get(x_key, "")].append(row.asr)
    return {x: median(values) for x, values in buckets.items()}


def x_coord(value: str, symbolic: bool) -> str:
    if symbolic:
        return "{" + str(value) + "}"
    numeric = float(value)
    return fmt(numeric, 0 if numeric.is_integer() else 2)


def protocol_line_plot(
    rows: Sequence[Row],
    *,
    x_key: str,
    x_values: Sequence[str],
    symbolic: bool = False,
    y_ref: float | None = 50.0,
) -> Tuple[str, List[str]]:
    lines: List[str] = []
    legend_entries: List[str] = []
    if y_ref is not None:
        ref_coords = " ".join(f"({x_coord(value, symbolic)},{fmt(y_ref)})" for value in x_values)
        lines.append(rf"\addplot+[black!40, densely dashed, mark=none] coordinates {{{ref_coords}}};")
        legend_entries.append("50\\% fair-order reference")
    for protocol in PROTOCOL_ORDER:
        bucket = [row for row in rows if row.protocol == protocol]
        if not bucket:
            continue
        medians = group_cell_medians(bucket, x_key)
        coords = []
        for value in x_values:
            if value not in medians:
                continue
            coords.append(f"({x_coord(value, symbolic)},{fmt(medians[value])})")
        if not coords:
            continue
        color = PROTOCOL_TIKZ_COLORS[protocol]
        mark = PROTOCOL_MARKS[protocol]
        lines.append(
            rf"\addplot+[color={color}, mark={mark}, mark options={{fill={color}}}] coordinates {{{' '.join(coords)}}};"
        )
        legend_entries.append(PROTOCOL_LABELS[protocol])
    return "\n".join(lines), legend_entries


def attack_line_plot(
    rows: Sequence[Row],
    *,
    x_key: str,
    x_values: Sequence[str],
    symbolic: bool = False,
    y_ref: float | None = 50.0,
) -> Tuple[str, List[str]]:
    lines: List[str] = []
    legend_entries: List[str] = []
    if y_ref is not None:
        ref_coords = " ".join(f"({x_coord(value, symbolic)},{fmt(y_ref)})" for value in x_values)
        lines.append(rf"\addplot+[black!40, densely dashed, mark=none] coordinates {{{ref_coords}}};")
        legend_entries.append("50\\% fair-order reference")
    for attack in ATTACK_ORDER:
        bucket = [row for row in rows if row.attack_mode == attack]
        if not bucket:
            continue
        medians = group_cell_medians(bucket, x_key)
        coords = []
        for value in x_values:
            if value not in medians:
                continue
            coords.append(f"({x_coord(value, symbolic)},{fmt(medians[value])})")
        if not coords:
            continue
        color = ATTACK_TIKZ_COLORS[attack]
        mark = ATTACK_MARKS[attack]
        style = ATTACK_STYLES[attack]
        lines.append(
            rf"\addplot+[color={color}, {style}, mark={mark}, mark options={{fill={color}}}] coordinates {{{' '.join(coords)}}};"
        )
        legend_entries.append(ATTACK_LABELS[attack])
    return "\n".join(lines), legend_entries


def emit_legend(entries: Sequence[str]) -> str:
    return "\n".join(rf"\addlegendentry{{{entry}}}" for entry in entries)


def axis_symbolic_setup(values: Sequence[str], labels: Sequence[str]) -> str:
    coords = ",".join(values)
    ticks = ",".join(values)
    ticklabels = ",".join(tex_escape(label) for label in labels)
    return rf"symbolic x coords={{{coords}}}, xtick={{{ticks}}}, xticklabels={{{ticklabels}}}"


def make_figure_header(name: str, title: str) -> str:
    return f"% Auto-generated by plots/generate_all.py\n% {name}: {title}\n"


def panel_row_col(index: int, cols: int) -> Tuple[int, int]:
    return index // cols, index % cols


def outer_axis_labels(index: int, cols: int, total: int, xlabel: str, ylabel: str) -> Tuple[str, str]:
    row, col = panel_row_col(index, cols)
    rows = (total + cols - 1) // cols
    return (xlabel if row == rows - 1 else "", ylabel if col == 0 else "")


def axis_y_bounds(
    values: Sequence[float],
    *,
    include: Sequence[float] = (),
    min_span: float = 8.0,
    margin: float = 0.08,
) -> Tuple[float, float]:
    data = list(values) + list(include)
    if not data:
        return 0.0, 100.0
    low = min(data)
    high = max(data)
    span = max(high - low, min_span)
    pad = span * margin
    ymin = max(0.0, low - pad)
    ymax = min(100.0, high + pad)
    if ymax - ymin < min_span:
        center = (ymin + ymax) / 2.0
        ymin = max(0.0, center - min_span / 2.0)
        ymax = min(100.0, center + min_span / 2.0)
    return ymin, ymax


def jitter_offsets(count: int) -> List[float]:
    presets = {
        1: [0.0],
        2: [-0.06, 0.06],
        3: [-0.09, 0.0, 0.09],
        4: [-0.12, -0.04, 0.04, 0.12],
        5: [-0.14, -0.07, 0.0, 0.07, 0.14],
    }
    if count in presets:
        return presets[count]
    step = 0.28 / max(count - 1, 1)
    start = -0.14
    return [start + idx * step for idx in range(count)]


def interpolate_rgb(value: float, *, low: float = 0.0, high: float = 100.0) -> Tuple[int, int, int]:
    if high <= low:
        return VIRIDIS_STOPS[-1][1]
    norm = max(0.0, min(1.0, (value - low) / (high - low)))
    for idx in range(1, len(VIRIDIS_STOPS)):
        stop, color = VIRIDIS_STOPS[idx]
        prev_stop, prev_color = VIRIDIS_STOPS[idx - 1]
        if norm <= stop:
            ratio = 0.0 if stop == prev_stop else (norm - prev_stop) / (stop - prev_stop)
            return tuple(
                round(prev_channel + ratio * (channel - prev_channel))
                for prev_channel, channel in zip(prev_color, color)
            )
    return VIRIDIS_STOPS[-1][1]


def tikz_rgb(value: float) -> str:
    r, g, b = interpolate_rgb(value)
    return f"{{rgb,255:red,{r};green,{g};blue,{b}}}"


def text_color_for_fill(value: float) -> str:
    r, g, b = interpolate_rgb(value)
    luminance = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255.0
    return "white" if luminance < 0.46 else "black"


def flatten(rows: Iterable[Row]) -> List[Row]:
    return list(rows)


def effective_num_nodes(row: Row) -> int | None:
    return row.get_int("NUM_NODES")


def compute_peak_lifts(rows: Sequence[Row], baselines: Dict[str, float]) -> Dict[Tuple[str, str], Dict[str, object]]:
    candidates: Dict[Tuple[str, str], List[Tuple[float, Row]]] = defaultdict(list)
    for row in rows:
        if effective_num_nodes(row) != 13:
            continue
        key = (row.protocol, row.attack_mode, row.experiment, row.param_signature())
        candidates[key].append((row.asr, row))

    best: Dict[Tuple[str, str], Dict[str, object]] = {}
    for (protocol, attack_mode, experiment, signature), values in candidates.items():
        rows_here = [row for _, row in values]
        median_value = median(row.asr for row in rows_here)
        baseline = baselines[protocol]
        lift = median_value - baseline
        current = best.get((protocol, attack_mode))
        if current is None or lift > current["lift"]:
            best[(protocol, attack_mode)] = {
                "lift": lift,
                "median_asr": median_value,
                "baseline": baseline,
                "experiment": experiment,
                "signature": dict(signature),
            }
    return best


def raw_extra_field_count(path: Path) -> int:
    count = 0
    with path.open() as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if row.get(None):
                count += 1
    return count


def suspicious_variance_cells(rows: Sequence[Row]) -> List[Tuple[str, str, str, str, float, float, float]]:
    flagged: List[Tuple[str, str, str, str, float, float, float]] = []
    for (protocol, experiment, attack), bucket in experiment_matrix(rows).items():
        varying = varying_keys(bucket)
        if not varying:
            continue
        rep_cells = completeness(bucket, varying)
        for signature, reps in rep_cells.items():
            cell_rows = [
                row for row in bucket
                if tuple(row.get(key, "") for key in varying) == signature
            ]
            values = [row.asr for row in cell_rows]
            if len(values) < 3:
                continue
            span = max(values) - min(values)
            if span >= 35.0:
                flagged.append(
                    (
                        protocol,
                        experiment,
                        attack,
                        ", ".join(f"{key}={value}" for key, value in zip(varying, signature)),
                        min(values),
                        median(values),
                        max(values),
                    )
                )
    return sorted(flagged, key=lambda item: (-(item[6] - item[4]), item[0], item[1], item[2]))


def generate_preamble() -> None:
    write_text(FIGURE_DIR / "preamble.tex", TIKZ_STYLE_PREAMBLE)


def generate_baseline_sanity(baselines: Dict[str, float]) -> FigureInfo:
    name = "fig00_baseline_sanity"
    path = FIGURE_DIR / f"{name}.tex"
    bars = []
    ref_coords = []
    x_values = []
    labels = []
    for protocol in PROTOCOL_ORDER:
        x = protocol
        x_values.append(x)
        labels.append(PROTOCOL_LABELS[protocol])
        ref_coords.append(f"({x},50.00)")
        color = PROTOCOL_TIKZ_COLORS[protocol]
        value = baselines[protocol]
        bars.append(
            rf"\addplot+[ybar, draw=none, fill={color}, nodes near coords, every node near coord/.append style={{font=\scriptsize, rotate=90, anchor=west}}] coordinates {{({x},{fmt(value)})}};"
        )
    content = make_figure_header(name, "Pure 13-node baseline sanity check") + rf"""
\begin{{tikzpicture}}
\begin{{axis}}[
  mevBarAxis,
  ymin=49,
  ymax=53.5,
  ylabel={{Baseline ASR (\%)}},
  {axis_symbolic_setup(x_values, labels)},
  x tick label style={{rotate=30, anchor=east}},
]
\addplot+[black!45, densely dashed, mark=none] coordinates {{{' '.join(ref_coords)}}};
{chr(10).join(bars)}
\end{{axis}}
\end{{tikzpicture}}
"""
    write_text(path, content)
    return FigureInfo(
        name=name,
        title="Pure baseline sanity check",
        path=path,
        columns=["protocol", "asr"],
        purpose="Shows that the harmonized 13-node baselines cluster around fair-order behavior instead of protocol-specific placeholders.",
        setup="All baselines are pure 13-node runs with no attack and node 0 versus node 1 measurement.",
        baseline_use="This is the baseline figure itself.",
    )


def generate_peak_attack_lift(rows: Sequence[Row], baselines: Dict[str, float]) -> FigureInfo:
    name = "fig01_peak_attack_lift"
    path = FIGURE_DIR / f"{name}.tex"
    best = compute_peak_lifts(rows, baselines)
    x_values = PROTOCOL_ORDER
    labels = [PROTOCOL_LABELS[p] for p in PROTOCOL_ORDER]
    bar_plots = []
    baseline_coords = []
    for attack in ATTACK_ORDER:
        coords = []
        for protocol in PROTOCOL_ORDER:
            cell = best.get((protocol, attack))
            if cell is None:
                continue
            coords.append(f"({protocol},{fmt(cell['median_asr'])})")
        color = ATTACK_TIKZ_COLORS[attack]
        bar_plots.append(
            rf"\addplot+[fill={color}, draw=none, nodes near coords, every node near coord/.append style={{font=\scriptsize, rotate=90, anchor=west}}] coordinates {{{' '.join(coords)}}};"
        )
    for protocol in PROTOCOL_ORDER:
        baseline_coords.append(f"({protocol},{fmt(baselines[protocol])})")
    baseline_plot = rf"\addplot+[black, densely dashed, mark=none, line width=1.2pt, nodes near coords, every node near coord/.append style={{font=\scriptsize, rotate=90, anchor=west, text=black}}] coordinates {{{' '.join(baseline_coords)}}};"
    first_protocol = PROTOCOL_ORDER[0]
    last_protocol = PROTOCOL_ORDER[-1]
    first_baseline = baselines[first_protocol]
    last_baseline = baselines[last_protocol]
    legend_entries = [
        ("legf", ATTACK_TIKZ_COLORS["fissure"], "Fissure", -5.3),
        ("legs", ATTACK_TIKZ_COLORS["speculative"], "Speculative", -1.9),
        ("legl", ATTACK_TIKZ_COLORS["sluggish"], "Sluggish", 1.7),
        ("legb", "black", "Pure baseline", 4.8),
    ]
    manual_legend_lines = [r"\begin{scope}[shift={($(current bounding box.north)+(0,0.42cm)$)}]"]
    for name_id, fill, label, xshift in legend_entries:
        draw = "black" if name_id == "legb" else "black!20"
        manual_legend_lines.append(
            rf"\node[draw={draw}, fill={fill}, minimum width=6mm, minimum height=3mm, inner sep=0pt] ({name_id}) at ({xshift}cm,0) {{}};"
        )
        manual_legend_lines.append(
            rf"\node[anchor=west, font=\scriptsize] at ([xshift=2pt]{name_id}.east) {{{label}}};"
        )
    manual_legend_lines.append(r"\end{scope}")
    manual_legend = "\n".join(manual_legend_lines)
    content = make_figure_header(name, "Best 13-node attack ASR with protocol baselines") + rf"""
\begin{{tikzpicture}}
\begin{{axis}}[
  mevBarAxis,
  name=peakbars,
  ybar=4pt,
  ymin=40,
  ymax=100,
  ylabel={{Best observed median ASR (\%)}},
  {axis_symbolic_setup(x_values, labels)},
  x tick label style={{rotate=30, anchor=east}},
]
{chr(10).join(bar_plots)}
\end{{axis}}
\begin{{axis}}[
  width=\linewidth,
  height=0.33\linewidth,
  at={{(peakbars.south west)}},
  anchor=south west,
  ymin=40,
  ymax=100,
  symbolic x coords={{{','.join(x_values)}}},
  xtick=\empty,
  ytick=\empty,
  axis lines=none,
  clip=false,
]
{baseline_plot}
\coordinate (baselinefirst) at (axis cs:{first_protocol},{fmt(first_baseline)});
\coordinate (baselinelast) at (axis cs:{last_protocol},{fmt(last_baseline)});
\end{{axis}}
\draw[black, densely dashed, line width=1.2pt] ($(peakbars.west |- baselinefirst)$) -- (baselinefirst);
\draw[black, densely dashed, line width=1.2pt] (baselinelast) -- ($(peakbars.east |- baselinelast)$);
{manual_legend}
\end{{tikzpicture}}
"""
    write_text(path, content)
    return FigureInfo(
        name=name,
        title="Best 13-node attack ASR with protocol baselines",
        path=path,
        columns=["protocol", "attack_mode", "experiment", "rep", "asr", "NUM_NODES"],
        purpose="Shows the strongest 13-node exploitability signal for each protocol and attack while keeping the pure baseline visible in the same chart.",
        setup="Only configurations with effective NUM_NODES=13 are considered; each bar is the best median over repeated cells for that protocol-attack pair.",
        baseline_use="A dashed black line plots the protocol's pure 13-node baseline from baseline.csv.",
    )


def generate_scaling_trends(rows: Sequence[Row]) -> FigureInfo:
    name = "fig02_scaling_trends"
    path = FIGURE_DIR / f"{name}.tex"
    panels = []
    for idx, attack in enumerate(ATTACK_ORDER):
        node_values = ["13", "25", "50"] if attack == "sluggish" else ["13", "25", "50", "100"]
        bucket = filter_rows(rows, experiment="scaling", attack_mode=attack)
        lines, legend_entries = protocol_line_plot(bucket, x_key="NUM_NODES", x_values=node_values)
        legend = emit_legend(legend_entries) if idx == 0 else ""
        axis_max = 53 if attack == "sluggish" else 103
        ticks = "13,25,50" if attack == "sluggish" else "13,25,50,100"
        panel = rf"""
\nextgroupplot[
  mevAxis,
  title={{{ATTACK_LABELS[attack]}}},
  xlabel={{Node count}},
  ylabel={{Median ASR (\%)}},
  xmin=10,
  xmax={axis_max},
  xtick={{{ticks}}},
  legend columns=4,
  legend style={{at={{(1.58,1.18)}}, anchor=south}},
]
{lines}
{legend}
"""
        panels.append(panel)
    content = make_figure_header(name, "Scaling medians across node counts") + rf"""
\begin{{tikzpicture}}
\begin{{groupplot}}[
  group style={{group size=3 by 1, horizontal sep=1.5cm}},
]
{''.join(panels)}
\end{{groupplot}}
\end{{tikzpicture}}
"""
    write_text(path, content)
    return FigureInfo(
        name=name,
        title="Scaling median trends",
        path=path,
        columns=["protocol", "attack_mode", "NUM_NODES", "asr"],
        purpose="Shows how each attack scales with committee size without cluttering the trend lines with variance bars.",
        setup="Uses the scaling experiment from both CSVs; x-axis is NUM_NODES and curves show per-cell medians.",
        baseline_use="Includes a dashed 50% fair-order reference rather than per-protocol baselines because node counts vary.",
    )


def generate_scaling_boxplots(rows: Sequence[Row], attack_mode: str, figure_index: int) -> FigureInfo:
    name = f"fig{figure_index:02d}_scaling_boxplot_{attack_mode}"
    path = FIGURE_DIR / f"{name}.tex"
    bucket = filter_rows(rows, experiment="scaling", attack_mode=attack_mode)
    protocols = [protocol for protocol in PROTOCOL_ORDER if any(row.protocol == protocol for row in bucket)]
    drawings: List[str] = []
    for pos, protocol in enumerate(protocols, start=1):
        values = sorted(row.asr for row in bucket if row.protocol == protocol)
        if not values:
            continue
        stats = box_stats(values)
        color = PROTOCOL_TIKZ_COLORS[protocol]
        left = pos - 0.28
        right = pos + 0.28
        drawings.extend(
            [
                rf"\draw[{color}!80!black, line width=1.0pt] (axis cs:{fmt(pos)},{fmt(stats['lower_whisker'])}) -- (axis cs:{fmt(pos)},{fmt(stats['lower_quartile'])});",
                rf"\draw[{color}!80!black, line width=1.0pt] (axis cs:{fmt(pos)},{fmt(stats['upper_quartile'])}) -- (axis cs:{fmt(pos)},{fmt(stats['upper_whisker'])});",
                rf"\draw[{color}!80!black, line width=1.0pt] (axis cs:{fmt(left)},{fmt(stats['lower_whisker'])}) -- (axis cs:{fmt(right)},{fmt(stats['lower_whisker'])});",
                rf"\draw[{color}!80!black, line width=1.0pt] (axis cs:{fmt(left)},{fmt(stats['upper_whisker'])}) -- (axis cs:{fmt(right)},{fmt(stats['upper_whisker'])});",
                rf"\path[fill={color}!65, fill opacity=0.72, draw={color}!85!black, line width=1.1pt] (axis cs:{fmt(left)},{fmt(stats['lower_quartile'])}) rectangle (axis cs:{fmt(right)},{fmt(stats['upper_quartile'])});",
                rf"\draw[black, line width=1.2pt] (axis cs:{fmt(left)},{fmt(stats['median'])}) -- (axis cs:{fmt(right)},{fmt(stats['median'])});",
            ]
        )
        if stats["outliers"]:
            outlier_coords = " ".join(
                f"({fmt(pos + offset, 2)},{fmt(value)})"
                for offset, value in zip(jitter_offsets(len(stats['outliers'])), stats["outliers"])
            )
            drawings.append(
                rf"\addplot+[only marks, color={color}!75!black, mark=*, mark options={{fill=white}}, mark size=1.8pt] coordinates {{{outlier_coords}}};"
            )
    ref_coords = " ".join(f"({idx},50.00)" for idx in range(1, len(protocols) + 1))
    x_values = ",".join(str(idx) for idx in range(1, len(protocols) + 1))
    x_labels = ",".join(PROTOCOL_LABELS[protocol] for protocol in protocols)
    content = make_figure_header(name, f"Scaling variability for {ATTACK_LABELS[attack_mode]}") + rf"""
\begin{{tikzpicture}}
\begin{{axis}}[
  mevAxis,
  width=0.96\linewidth,
  height=0.42\linewidth,
  title={{{ATTACK_LABELS[attack_mode]}}},
  xlabel={{Protocol}},
  ylabel={{ASR (\%)}},
  xmin=0.4,
  xmax={len(protocols) + 0.6},
  ymin=0,
  ymax=105,
  xtick={{{x_values}}},
  xticklabels={{{x_labels}}},
  x tick label style={{rotate=30, anchor=east}},
]
\addplot+[black!40, densely dashed, mark=none] coordinates {{{ref_coords}}};
{chr(10).join(drawings)}
\node[anchor=south west, font=\scriptsize, text=black!55] at (rel axis cs:0.01,0.505) {{50\% fair-order reference}};
\end{{axis}}
\end{{tikzpicture}}
"""
    write_text(path, content)
    return FigureInfo(
        name=name,
        title=f"Scaling distributions for {ATTACK_LABELS[attack_mode]}",
        path=path,
        columns=["protocol", "attack_mode", "NUM_NODES", "rep", "asr"],
        purpose=f"Shows the pooled ASR distribution for each protocol across the repeated scaling runs under the {ATTACK_LABELS[attack_mode].lower()} attack.",
        setup="Each box pools all valid scaling-run ASRs for one protocol under one attack mode, across the node-count cells present in the scaling sweep.",
        baseline_use="Includes a dashed 50% fair-order reference to anchor the overall distribution view.",
    )


def generate_offense_sweeps(rows: Sequence[Row]) -> FigureInfo:
    name = "fig06_offense_sweeps"
    path = FIGURE_DIR / f"{name}.tex"
    specs = [
        ("offense_fissure", "ATTACKER_RATIO", "Attacker fraction"),
        ("offense_sluggish", "SLUGGISH_TIMEOUT_MULTIPLIER", "Delay multiplier"),
        ("offense_speculative", "SPECULATIVE_P_MAX", "Speculative grind depth"),
        ("offense_exclusion", "EXCLUSION_PROBABILITY", "Exclusion probability"),
    ]
    panels = []
    for idx, (experiment, x_key, x_label) in enumerate(specs):
        bucket = filter_rows(rows, experiment=experiment)
        x_values = sorted_unique_values(bucket, x_key)
        lines, legend_entries = protocol_line_plot(bucket, x_key=x_key, x_values=x_values)
        symbolic = any(not value.replace(".", "", 1).isdigit() for value in x_values)
        option_lines = [
            "mevAxis",
            f"title={{{x_label}}}",
            f"xlabel={{{x_label}}}",
            r"ylabel={Median ASR (\%)}",
        ]
        if symbolic:
            option_lines.append(axis_symbolic_setup(x_values, [param_value_label(x_key, value) for value in x_values]))
        else:
            option_lines.append(f"xmin={float(x_values[0]) - 0.05}, xmax={float(x_values[-1]) + 0.05}, xtick={{{','.join(x_values)}}}")
        option_lines.extend([
            "legend columns=4",
            r"legend style={at={(1.58,1.20)}, anchor=south}",
        ])
        legend = emit_legend(legend_entries) if idx == 0 else ""
        panels.append(
            rf"""
\nextgroupplot[
  {',\n  '.join(option_lines)}
]
{lines}
{legend}
"""
        )
    content = make_figure_header(name, "Attack-power sensitivity sweeps") + rf"""
\begin{{tikzpicture}}
\begin{{groupplot}}[
  group style={{group size=2 by 2, horizontal sep=1.5cm, vertical sep=1.25cm}},
]
{''.join(panels)}
\end{{groupplot}}
\end{{tikzpicture}}
"""
    write_text(path, content)
    return FigureInfo(
        name=name,
        title="Attack-power sensitivity sweeps",
        path=path,
        columns=["ATTACKER_RATIO", "SLUGGISH_TIMEOUT_MULTIPLIER", "SPECULATIVE_P_MAX", "EXCLUSION_PROBABILITY", "protocol", "asr"],
        purpose="Compares how each protocol's ASR responds when attack strength is increased along the main attack-specific knobs.",
        setup="Uses 13-node offense sweeps; each curve is a median across repetitions for one protocol.",
        baseline_use="Adds a dashed 50% fair-order reference; the exact baselines remain within a narrow band around 50%.",
    )


def generate_latency_sensitivity(rows: Sequence[Row]) -> FigureInfo:
    name = "fig07_latency_sensitivity"
    path = FIGURE_DIR / f"{name}.tex"
    panels = []
    for idx, attack in enumerate(ATTACK_ORDER):
        bucket = filter_rows(rows, experiment="env_latency", attack_mode=attack)
        lines, legend_entries = protocol_line_plot(bucket, x_key="LATENCY_JITTER", x_values=LATENCY_ORDER, symbolic=True)
        legend = emit_legend(legend_entries) if idx == 0 else ""
        panels.append(
            rf"""
\nextgroupplot[
  mevAxis,
  title={{{ATTACK_LABELS[attack]}}},
  xlabel={{Injected latency profile (ms)}},
  ylabel={{Median ASR (\%)}},
  {axis_symbolic_setup(LATENCY_ORDER, [LATENCY_LABELS[v] for v in LATENCY_ORDER])},
  legend columns=4,
  legend style={{at={{(1.58,1.20)}}, anchor=south}},
]
{lines}
{legend}
"""
        )
    content = make_figure_header(name, "Latency sensitivity across attacks") + rf"""
\begin{{tikzpicture}}
\begin{{groupplot}}[
  group style={{group size=3 by 1, horizontal sep=1.5cm}},
]
{''.join(panels)}
\end{{groupplot}}
\end{{tikzpicture}}
"""
    write_text(path, content)
    return FigureInfo(
        name=name,
        title="Latency / geo-distribution proxy sensitivity",
        path=path,
        columns=["LATENCY_JITTER", "attack_mode", "protocol", "asr"],
        purpose="Shows whether injected latency and jitter, used here as a geo-distribution proxy, amplify or suppress each attack across protocols.",
        setup="Uses the env_latency sweep with an added `0ms 0ms` no-added-latency slice derived from matching 13-node scaling rows, plus the collected `50±10`, `150±30`, and `300±50` profiles.",
        baseline_use="Adds a 50% fair-order reference; these runs are predominantly 13-node configurations.",
    )


def generate_core_defenses(rows: Sequence[Row]) -> FigureInfo:
    name = "fig08_core_defenses"
    path = FIGURE_DIR / f"{name}.tex"
    protocols = ["bullshark", "narwhal", "mevsui"]
    experiments = [
        ("defense_memory", "DAG_STATE_CACHED_ROUNDS", "Cache depth"),
        ("defense_gc", "GC_DEPTH", "GC depth"),
        ("defense_network", "SYNC_TIMEOUT_MS", "Sync timeout (ms)"),
    ]
    panels = []
    legend_name = f"{name}legend"
    for p_idx, protocol in enumerate(protocols):
        for e_idx, (experiment, x_key, x_label) in enumerate(experiments):
            bucket = filter_rows(rows, protocol=protocol, experiment=experiment)
            x_values = sorted_unique_values(bucket, x_key)
            lines, legend_entries = attack_line_plot(bucket, x_key=x_key, x_values=x_values, y_ref=None)
            legend = emit_legend(legend_entries) if p_idx == 0 and e_idx == 0 else ""
            ymin, ymax = axis_y_bounds([row.asr for row in bucket], min_span=12.0, margin=0.12)
            title = x_label if p_idx == 0 else ""
            xlabel = x_label if p_idx == len(protocols) - 1 else ""
            ylabel = "Median ASR (\\%)" if e_idx == 0 else ""
            extra_options = [f"ymin={fmt(ymin)}", f"ymax={fmt(ymax)}"]
            if p_idx == 0 and e_idx == 0:
                extra_options.append(f"legend to name={legend_name}")
            panel_label = rf"\node[anchor=north west, font=\scriptsize\bfseries, fill=white, fill opacity=0.92, text opacity=1, inner sep=1.2pt] at (rel axis cs:0.02,0.98) {{{PROTOCOL_LABELS[protocol]}}};"
            panels.append(
                rf"""
\nextgroupplot[
  mevSmallAxis,
  width=0.27\linewidth,
  height=0.19\linewidth,
  title={{{title}}},
  xlabel={{{xlabel}}},
  ylabel={{{ylabel}}},
  xmin={float(x_values[0]) - 0.2 if x_values else 0},
  xmax={float(x_values[-1]) + 0.2 if x_values else 1},
  xtick={{{','.join(x_values)}}},
  {', '.join(extra_options)},
]
{lines}
{panel_label}
{legend}
"""
            )
    content = make_figure_header(name, "Core defense sensitivities") + rf"""
\begin{{tikzpicture}}
\begin{{groupplot}}[
  group style={{group size=3 by 3, horizontal sep=1.2cm, vertical sep=1.45cm}},
]
{''.join(panels)}
\end{{groupplot}}
\node[anchor=north] at ($(group c1r3.south west)!0.5!(group c3r3.south east)+(0,-0.85cm)$) {{\pgfplotslegendfromname{{{legend_name}}}}};
\end{{tikzpicture}}
"""
    write_text(path, content)
    return FigureInfo(
        name=name,
        title="Core defense sensitivities",
        path=path,
        columns=["DAG_STATE_CACHED_ROUNDS", "GC_DEPTH", "SYNC_TIMEOUT_MS", "attack_mode", "protocol", "asr"],
        purpose="Compares the effect of memory retention, garbage collection, and sync patience on the three DAG-based protocols that expose these knobs.",
        setup="Rows are Bullshark, Narwhal-Tusk, and MEVSUI; lines show attack modes over the corresponding defense sweep.",
        baseline_use="Uses a dashed 50% fair-order reference because all cells are near the same base scale but not all are baseline runs.",
    )


def generate_narwhal_workers(rows: Sequence[Row]) -> FigureInfo:
    name = "fig09_narwhal_workers"
    path = FIGURE_DIR / f"{name}.tex"
    bucket = filter_rows(rows, protocol="narwhal", experiment="scaling_workers")
    x_values = sorted_unique_values(bucket, "NUM_WORKERS")
    lines, legend_entries = attack_line_plot(bucket, x_key="NUM_WORKERS", x_values=x_values)
    content = make_figure_header(name, "Narwhal worker scaling") + rf"""
\begin{{tikzpicture}}
\begin{{axis}}[
  mevAxis,
  width=0.62\linewidth,
  height=0.30\linewidth,
  title={{Narwhal worker scaling}},
  xlabel={{Workers per node}},
  ylabel={{Median ASR (\%)}},
  xmin={float(x_values[0]) - 0.2},
  xmax={float(x_values[-1]) + 0.2},
  xtick={{{','.join(x_values)}}},
  legend columns=4,
  legend style={{at={{(0.5,1.18)}}, anchor=south}},
]
{lines}
{emit_legend(legend_entries)}
\end{{axis}}
\end{{tikzpicture}}
"""
    write_text(path, content)
    return FigureInfo(
        name=name,
        title="Narwhal worker scaling",
        path=path,
        columns=["NUM_WORKERS", "attack_mode", "asr"],
        purpose="Shows whether Narwhal's per-node worker fanout amplifies or stabilizes attack success across attack modes.",
        setup="Narwhal-specific scaling_workers sweep with one median curve per attack mode.",
        baseline_use="Uses the 50% fair-order reference, not the protocol baseline, because the workers sweep changes internal throughput rather than attack definition.",
    )


def emit_heatmap_panel(
    rows: Sequence[Row],
    *,
    x_key: str,
    y_key: str,
    title: str,
    last_panel: bool,
) -> str:
    x_values = sorted_unique_values(rows, x_key)
    y_values = sorted_unique_values(rows, y_key)
    if not x_values or not y_values:
        return rf"""
\nextgroupplot[
  mevHeatAxis,
  title={{{title}}},
]
\node[font=\scriptsize, text=black!55] at (rel axis cs:0.5,0.5) {{No valid data}};
"""
    x_positions = {value: idx for idx, value in enumerate(x_values, start=1)}
    y_positions = {value: idx for idx, value in enumerate(y_values, start=1)}
    cells: Dict[Tuple[str, str], List[float]] = defaultdict(list)
    for row in rows:
        cells[(row.get(x_key, ""), row.get(y_key, ""))].append(row.asr)
    background_cells = []
    colored_cells = []
    for y_value in y_values:
        for x_value in x_values:
            xpos = x_positions[x_value]
            ypos = y_positions[y_value]
            background_cells.append(
                rf"\path[draw=black!12, fill=black!02] (axis cs:{fmt(xpos - 0.46, 2)},{fmt(ypos - 0.46, 2)}) rectangle (axis cs:{fmt(xpos + 0.46, 2)},{fmt(ypos + 0.46, 2)});"
            )
            values = cells.get((x_value, y_value))
            if not values:
                continue
            med = median(values)
            colored_cells.append(
                rf"\path[draw=black!18, fill={tikz_rgb(med)}] (axis cs:{fmt(xpos - 0.46, 2)},{fmt(ypos - 0.46, 2)}) rectangle (axis cs:{fmt(xpos + 0.46, 2)},{fmt(ypos + 0.46, 2)});"
            )
            colored_cells.append(
                rf"\node[font=\scriptsize\bfseries, text={text_color_for_fill(med)}] at (axis cs:{fmt(xpos)},{fmt(ypos)}) {{{fmt(med, 1)}}};"
            )
    xticklabels = ",".join(tex_escape(param_value_label(x_key, value)) for value in x_values)
    yticklabels = ",".join(tex_escape(param_value_label(y_key, value)) for value in y_values)
    option_lines = [
        "mevHeatAxis",
        f"title={{{title}}}",
        rf"xlabel={{{tex_escape(x_key.replace('_', ' ').title())}}}",
        rf"ylabel={{{tex_escape(y_key.replace('_', ' ').title())}}}",
        "xmin=0.5",
        f"xmax={len(x_values) + 0.5}",
        "ymin=0.5",
        f"ymax={len(y_values) + 0.5}",
        f"xtick={{1,...,{len(x_values)}}}",
        f"ytick={{1,...,{len(y_values)}}}",
        f"xticklabels={{{xticklabels}}}",
        f"yticklabels={{{yticklabels}}}",
    ]
    return rf"""
\nextgroupplot[
  {',\n  '.join(option_lines)}
]
{chr(10).join(background_cells)}
{chr(10).join(colored_cells)}
"""


def generate_narwhal_heatmaps(rows: Sequence[Row], experiment: str, figure_index: int, x_key: str, y_key: str, title: str) -> FigureInfo:
    name = f"fig{figure_index:02d}_narwhal_{experiment}"
    path = FIGURE_DIR / f"{name}.tex"
    panels = []
    for idx, attack in enumerate(ATTACK_ORDER):
        bucket = filter_rows(rows, protocol="narwhal", experiment=experiment, attack_mode=attack)
        panels.append(
            emit_heatmap_panel(
                bucket,
                x_key=x_key,
                y_key=y_key,
                title=ATTACK_LABELS[attack],
                last_panel=idx == len(ATTACK_ORDER) - 1,
            )
        )
    colorbar_steps = []
    for idx, value in enumerate(range(0, 101, 10)):
        y0 = idx * 0.24
        y1 = y0 + 0.24
        colorbar_steps.append(
            rf"\path[draw=none, fill={tikz_rgb(float(value))}] (0,{fmt(y0, 2)}) rectangle (0.28,{fmt(y1, 2)});"
        )
    content = make_figure_header(name, title) + rf"""
\begin{{tikzpicture}}
\begin{{groupplot}}[
  group style={{group size=3 by 1, horizontal sep=1.5cm}},
]
{''.join(panels)}
\end{{groupplot}}
\begin{{scope}}[shift={{($(group c3r1.east)+(1.25cm,-1.25cm)$)}}]
{chr(10).join(colorbar_steps)}
\draw[black!20] (0,0) rectangle (0.28,2.64);
\node[anchor=west, font=\scriptsize] at (0.36,0.00) {{0}};
\node[anchor=west, font=\scriptsize] at (0.36,1.32) {{50}};
\node[anchor=west, font=\scriptsize] at (0.36,2.64) {{100}};
\node[anchor=west, font=\scriptsize\bfseries, align=left] at (0.36,2.94) {{Median\\ASR (\%)}};
\end{{scope}}
\end{{tikzpicture}}
"""
    write_text(path, content)
    return FigureInfo(
        name=name,
        title=title,
        path=path,
        columns=[x_key, y_key, "attack_mode", "asr"],
        purpose=f"Maps the Narwhal {EXPERIMENT_LABELS[experiment].lower()} surface so the paper can show interaction effects instead of only one-dimensional slices.",
        setup=f"Narwhal-only {experiment} sweep; one heatmap per attack mode.",
        baseline_use="No direct baseline normalization because the goal is to expose the parameter-response surface.",
    )


def generate_wave_leaders(rows: Sequence[Row]) -> FigureInfo:
    name = "fig12_wave_leaders"
    path = FIGURE_DIR / f"{name}.tex"
    panel_specs = [
        ("mysticeti", "mahimahi_leaders", "NUMBER_OF_LEADERS", "Leaders per wave"),
        ("mysticeti", "mahimahi_wave", "WAVE_LENGTH", "Wave length"),
        ("mahimahi", "mahimahi_leaders", "NUMBER_OF_LEADERS", "Leaders per wave"),
        ("mahimahi", "mahimahi_wave", "WAVE_LENGTH", "Wave length"),
    ]
    panels = []
    for idx, (protocol, experiment, x_key, x_label) in enumerate(panel_specs):
        bucket = filter_rows(rows, protocol=protocol, experiment=experiment)
        x_values = sorted_unique_values(bucket, x_key)
        lines, legend_entries = attack_line_plot(bucket, x_key=x_key, x_values=x_values)
        legend = emit_legend(legend_entries) if idx == 0 else ""
        panels.append(
            rf"""
\nextgroupplot[
  mevAxis,
  title={{{PROTOCOL_LABELS[protocol]}: {x_label}}},
  xlabel={{{x_label}}},
  ylabel={{Median ASR (\%)}},
  xmin={float(x_values[0]) - 0.2 if x_values else 0},
  xmax={float(x_values[-1]) + 0.2 if x_values else 1},
  xtick={{{','.join(x_values)}}},
  legend columns=4,
  legend style={{at={{(1.58,1.20)}}, anchor=south}},
]
{lines}
{legend}
"""
        )
    content = make_figure_header(name, "Wave and leader sensitivity") + rf"""
\begin{{tikzpicture}}
\begin{{groupplot}}[
  group style={{group size=2 by 2, horizontal sep=1.5cm, vertical sep=1.25cm}},
]
{''.join(panels)}
\end{{groupplot}}
\end{{tikzpicture}}
"""
    write_text(path, content)
    return FigureInfo(
        name=name,
        title="Wave and leader sensitivity",
        path=path,
        columns=["NUMBER_OF_LEADERS", "WAVE_LENGTH", "attack_mode", "asr"],
        purpose="Highlights how leader parallelism and wave length reshape attackability in the Mysticeti-family protocols.",
        setup="Uses the populated Mysticeti and Mahi-Mahi leader and wave sweeps; Aleph's stray single-rep rows are intentionally excluded.",
        baseline_use="Uses the 50% fair-order reference because these are parameter sweeps around the default setup, not baseline runs.",
    )


def generate_strategy_sweeps(rows: Sequence[Row]) -> FigureInfo:
    name = "fig13_strategy_sweeps"
    path = FIGURE_DIR / f"{name}.tex"
    panel_specs = [
        ("mahimahi", "mahimahi_strategy", "Mahi-Mahi speculative strategy"),
        ("mysticeti", "mysticeti_strategy", "Mysticeti speculative strategy"),
    ]
    panels = []
    for idx, (protocol, experiment, title) in enumerate(panel_specs):
        bucket = filter_rows(rows, protocol=protocol, experiment=experiment)
        x_values = sorted_unique_values(bucket, "SPECULATIVE_STRATEGY", custom_order=STRATEGY_ORDER)
        lines, legend_entries = attack_line_plot(bucket, x_key="SPECULATIVE_STRATEGY", x_values=x_values, symbolic=True)
        legend = emit_legend(legend_entries) if idx == 0 else ""
        panels.append(
            rf"""
\nextgroupplot[
  mevAxis,
  width=0.46\linewidth,
  title={{{title}}},
  xlabel={{Strategy}},
  ylabel={{Median ASR (\%)}},
  {axis_symbolic_setup(x_values, x_values)},
  x tick label style={{rotate=20, anchor=east}},
  legend columns=4,
  legend style={{at={{(1.08,1.20)}}, anchor=south}},
]
{lines}
{legend}
"""
        )
    content = make_figure_header(name, "Speculative strategy comparison") + rf"""
\begin{{tikzpicture}}
\begin{{groupplot}}[
  group style={{group size=2 by 1, horizontal sep=1.5cm}},
]
{''.join(panels)}
\end{{groupplot}}
\end{{tikzpicture}}
"""
    write_text(path, content)
    return FigureInfo(
        name=name,
        title="Speculative strategy comparison",
        path=path,
        columns=["SPECULATIVE_STRATEGY", "attack_mode", "asr"],
        purpose="Shows whether smarter speculative heuristics actually buy attack success in the two protocols that expose strategy variants.",
        setup="Uses the Mahi-Mahi and Mysticeti strategy sweeps with attack modes as the line dimension.",
        baseline_use="Uses the 50% fair-order reference since the figure compares strategy variants within each protocol.",
    )


def generate_aleph_knobs(rows: Sequence[Row]) -> FigureInfo:
    name = "fig14_aleph_knobs"
    path = FIGURE_DIR / f"{name}.tex"
    specs = [
        ("aleph_lookahead", "ALEPH_ELECTION_LOOKAHEAD", "Election lookahead"),
        ("aleph_sync_speed", "ALEPH_COORD_REQUEST_DELAY_MS", "Coordination delay (ms)"),
        ("aleph_hash_randomization", "ALEPH_HASH_SORT_SEED", "Hash seed"),
    ]
    panels = []
    for idx, (experiment, x_key, x_label) in enumerate(specs):
        bucket = filter_rows(rows, protocol="alephbft", experiment=experiment)
        x_values = sorted_unique_values(bucket, x_key)
        lines, legend_entries = attack_line_plot(bucket, x_key=x_key, x_values=x_values)
        legend = emit_legend(legend_entries) if idx == 0 else ""
        panels.append(
            rf"""
\nextgroupplot[
  mevAxis,
  title={{{x_label}}},
  xlabel={{{x_label}}},
  ylabel={{Median ASR (\%)}},
  xmin={float(x_values[0]) - 0.2 if x_values else 0},
  xmax={float(x_values[-1]) + 0.2 if x_values else 1},
  xtick={{{','.join(x_values)}}},
  legend columns=4,
  legend style={{at={{(1.58,1.20)}}, anchor=south}},
]
{lines}
{legend}
"""
        )
    content = make_figure_header(name, "AlephBFT-specific sensitivity") + rf"""
\begin{{tikzpicture}}
\begin{{groupplot}}[
  group style={{group size=3 by 1, horizontal sep=1.5cm}},
]
{''.join(panels)}
\end{{groupplot}}
\end{{tikzpicture}}
"""
    write_text(path, content)
    return FigureInfo(
        name=name,
        title="AlephBFT-specific sensitivity",
        path=path,
        columns=["ALEPH_ELECTION_LOOKAHEAD", "ALEPH_COORD_REQUEST_DELAY_MS", "ALEPH_HASH_SORT_SEED", "attack_mode", "asr"],
        purpose="Captures the protocol-specific levers unique to AlephBFT and how they move ASR across attacks.",
        setup="Aleph-only sweep with attack modes as the line dimension.",
        baseline_use="Uses the 50% fair-order reference to contextualize the protocol-specific knob sweeps.",
    )


def generate_autobahn_knobs(rows: Sequence[Row]) -> FigureInfo:
    name = "fig15_autobahn_knobs"
    path = FIGURE_DIR / f"{name}.tex"
    specs = [
        ("autobahn_k", "AUTOBAHN_K", "Autobahn K"),
        ("autobahn_fast_path", "AUTOBAHN_FAST_PATH_TIMEOUT", "Fast-path timeout (ms)"),
    ]
    panels = []
    legend_name = f"{name}legend"
    for idx, (experiment, x_key, x_label) in enumerate(specs):
        bucket = filter_rows(rows, protocol="autobahn", experiment=experiment)
        x_values = sorted_unique_values(bucket, x_key)
        lines, legend_entries = attack_line_plot(bucket, x_key=x_key, x_values=x_values)
        legend = emit_legend(legend_entries) if idx == 0 else ""
        plotted_values = [50.0]
        for attack in ATTACK_ORDER:
            medians = group_cell_medians([row for row in bucket if row.attack_mode == attack], x_key)
            plotted_values.extend(medians.values())
        ymin, ymax = axis_y_bounds(plotted_values, min_span=1.0, margin=0.2)
        extra_options = [f"ymin={fmt(ymin)}", f"ymax={fmt(ymax)}"]
        if idx == 0:
            extra_options.append(f"legend to name={legend_name}")
            extra_options.append("xmode=log")
            extra_options.append("log basis x=2")
        panels.append(
            rf"""
\nextgroupplot[
  mevAxis,
  width=0.44\linewidth,
  height=0.28\linewidth,
  title={{{x_label}}},
  xlabel={{{x_label}}},
  ylabel={{Median ASR (\%)}},
  xmin={float(x_values[0]) - 0.2 if x_values else 0},
  xmax={float(x_values[-1]) + 0.2 if x_values else 1},
  xtick={{{','.join(x_values)}}},
  {', '.join(extra_options)},
]
{lines}
{legend}
"""
        )
    content = make_figure_header(name, "Autobahn-specific sensitivity") + rf"""
\begin{{tikzpicture}}
\begin{{groupplot}}[
  group style={{group size=2 by 1, horizontal sep=1.8cm}},
]
{''.join(panels)}
\end{{groupplot}}
\node[anchor=north] at ($(group c1r1.south west)!0.5!(group c2r1.south east)+(0,-0.72cm)$) {{\pgfplotslegendfromname{{{legend_name}}}}};
\end{{tikzpicture}}
"""
    write_text(path, content)
    return FigureInfo(
        name=name,
        title="Autobahn-specific sensitivity",
        path=path,
        columns=["AUTOBAHN_K", "AUTOBAHN_FAST_PATH_TIMEOUT", "attack_mode", "asr"],
        purpose="Shows whether Autobahn's concurrency and fast-path timeout settings materially move attack success or mostly leave it near baseline.",
        setup="Autobahn-only sweep with attack modes as the line dimension.",
        baseline_use="Uses the 50% fair-order reference because Autobahn stays close to baseline in most cells.",
    )


def generate_column_audit(rows: Sequence[Row], figures: Sequence[FigureInfo]) -> None:
    figure_map = {figure.name: figure for figure in figures}
    column_counts: Dict[str, int] = Counter()
    column_experiments: Dict[str, set[str]] = defaultdict(set)
    for row in rows:
        for key, value in row.raw.items():
            if key is None or value in ("", None):
                continue
            column_counts[key] += 1
            column_experiments[key].add(row.experiment)
    lines = ["# Column Audit", ""]
    lines.append(f"Last regenerated: `{report_stamp()}`")
    lines.append("")
    lines.append("This file maps every populated results column to the figures or reports that use it.")
    lines.append("")
    for key in sorted(column_counts):
        figure_refs = COLUMN_TO_FIGURES.get(key, ["inventory report only"])
        experiments = ", ".join(sorted(column_experiments[key]))
        lines.append(f"## `{key}`")
        lines.append(f"- Non-empty rows: `{column_counts[key]}`")
        lines.append(f"- Experiments: {experiments}")
        lines.append(f"- Used by: {', '.join(figure_refs)}")
        lines.append("")
    write_text(REPORT_DIR / "column_audit.md", "\n".join(lines))


def generate_experiment_inventory(rows: Sequence[Row]) -> None:
    lines = ["# Experiment Inventory", ""]
    lines.append(f"Last regenerated: `{report_stamp()}`")
    lines.append("")
    lines.append("This inventory groups results by protocol, experiment, and attack mode after filtering out unexpected protocol-experiment combinations.")
    lines.append("")
    grouped = experiment_matrix(rows)
    for protocol in PROTOCOL_ORDER:
        protocol_keys = sorted(key for key in grouped if key[0] == protocol)
        if not protocol_keys:
            continue
        lines.append(f"## {PROTOCOL_LABELS[protocol]}")
        lines.append("")
        for _, experiment, attack in protocol_keys:
            bucket = grouped[(protocol, experiment, attack)]
            varying = varying_keys(bucket)
            fixed = fixed_values(bucket)
            rep_map = completeness(bucket, varying) if varying else {}
            sample_row = bucket[0]
            lines.append(f"### `{experiment}` / `{attack}`")
            lines.append(f"- Rows: `{len(bucket)}`")
            lines.append(f"- Source: `{sample_row.source}`")
            lines.append(f"- Varying columns: `{', '.join(varying) if varying else 'none'}`")
            if fixed:
                fixed_text = ", ".join(f"`{key}={value}`" for key, value in fixed.items())
                lines.append(f"- Fixed setup: {fixed_text}")
            attacker_setup = infer_attacker_count(sample_row)
            if attacker_setup:
                lines.append(f"- Implied attacker setup: {attacker_setup}")
            victim_setup = infer_victim_setup(sample_row)
            if victim_setup:
                lines.append(f"- Victim setup: {victim_setup}")
            lines.append(f"- Median ASR: `{fmt(median(row.asr for row in bucket))}%`")
            lines.append(f"- ASR range: `{fmt(min(row.asr for row in bucket))}%` to `{fmt(max(row.asr for row in bucket))}%`")
            if rep_map:
                for signature, reps in sorted(rep_map.items()):
                    label = ", ".join(f"{key}={value}" for key, value in zip(varying, signature))
                    lines.append(f"- Repetitions for `{label}`: `{reps}`")
            lines.append("")
    write_text(REPORT_DIR / "experiment_inventory.md", "\n".join(lines))


def generate_data_anomalies(rows: Sequence[Row], baselines: Dict[str, float]) -> None:
    anomalies = find_structural_anomalies(rows)
    suspicious = suspicious_variance_cells(rows)
    unexpected = []
    for row in rows:
        expected = EXPECTED_PROTOCOLS.get(row.experiment)
        if expected is not None and row.protocol not in expected:
            unexpected.append((row.protocol, row.experiment, row.attack_mode, row.rep))

    lines = ["# Data Anomalies and Consistency Checks", ""]
    lines.append(f"Last regenerated: `{report_stamp()}`")
    lines.append("")
    lines.append("These are the main places where the collected data needs explicit caveats in the paper.")
    lines.append("")
    lines.append("## Structural checks")
    lines.append(f"- Rows after cleaning and filtering: `{anomalies['row_count']}`")
    lines.append(
        f"- Extra unnamed trailing CSV fields: `experiment_results.csv={raw_extra_field_count(RESULT_PATHS[0])}`, `autobahn_results.csv={raw_extra_field_count(RESULT_PATHS[1])}`"
    )
    lines.append(f"- High-ASR rows (`>=99.9%`): `{anomalies['high_asr_count']}`")
    lines.append(f"- Incomplete parameter cells: `{len(anomalies['incomplete_cells'])}`")
    lines.append("")

    lines.append("## Baseline comparability")
    lines.append("- The harmonized baselines cluster between roughly 49.9% and 52.9%, which makes a 50% fair-order reference defensible in non-baseline sweep figures.")
    lines.append("- MEVSUI is the one protocol whose non-scaling sweeps default to 16 nodes in the config, while the harmonized baseline is 13 nodes. Any direct baseline-normalized claim for MEVSUI therefore uses only its 13-node cells.")
    lines.append("")

    if unexpected:
        lines.append("## Unexpected protocol-experiment combinations")
        for protocol, experiment, attack, rep in unexpected[:10]:
            lines.append(f"- `{protocol}` appears in `{experiment}` / `{attack}` / rep `{rep}` even though that experiment belongs to another protocol family.")
        lines.append("")

    lines.append("## Incomplete cells")
    for cell in anomalies["incomplete_cells"][:25]:
        signature = ", ".join(f"{key}={value}" for key, value in zip(cell["varying"], cell["signature"]))
        lines.append(
            f"- `{cell['protocol']}` / `{cell['experiment']}` / `{cell['attack_mode']}` / `{signature}` only has reps `{cell['reps']}` out of expected `{cell['expected']}`."
        )
    lines.append("")

    lines.append("## High-variance cells")
    for protocol, experiment, attack, signature, low, med, high in suspicious[:25]:
        lines.append(
            f"- `{protocol}` / `{experiment}` / `{attack}` / `{signature}` spans `{fmt(low)}%` to `{fmt(high)}%` with median `{fmt(med)}%`."
        )
    lines.append("")

    lines.append("## Notes worth carrying into captions")
    lines.append("- Narwhal contributes many near-100% cells; the figures should present them, but the text should avoid implying that all Narwhal regimes are saturated across every scale.")
    lines.append("- Autobahn stays near baseline in median for most sweeps, but several cells show very large run-to-run spread. That makes the boxplots and median-only trend lines important.")
    lines.append("- The Aleph rows that appear under `mahimahi_wave`, `mahimahi_leaders`, and `mysticeti_strategy` look like exploratory misrouted runs and are excluded from the protocol-specific figures.")
    lines.append("")

    write_text(REPORT_DIR / "data_anomalies.md", "\n".join(lines))


def generate_category_summary(rows: Sequence[Row], figures: Sequence[FigureInfo]) -> None:
    category_map = {
        "Overview": {
            "figures": ["fig01_peak_attack_lift"],
            "experiments": ["baseline", "13-node peak attack cells"],
        },
        "Scaling": {
            "figures": ["fig02_scaling_trends", "fig03_scaling_boxplot_fissure", "fig04_scaling_boxplot_speculative", "fig05_scaling_boxplot_sluggish"],
            "experiments": ["scaling"],
        },
        "Attack Power": {
            "figures": ["fig06_offense_sweeps"],
            "experiments": ["offense_fissure", "offense_sluggish", "offense_speculative", "offense_exclusion"],
        },
        "Environment": {
            "figures": ["fig07_latency_sensitivity"],
            "experiments": ["env_latency"],
        },
        "Core Defenses": {
            "figures": ["fig08_core_defenses"],
            "experiments": ["defense_memory", "defense_gc", "defense_network"],
        },
        "Narwhal-Specific": {
            "figures": ["fig09_narwhal_workers", "fig10_narwhal_defense_header", "fig11_narwhal_defense_batching"],
            "experiments": ["scaling_workers", "defense_header", "defense_batching"],
        },
        "Mysticeti-Family": {
            "figures": ["fig12_wave_leaders", "fig13_strategy_sweeps"],
            "experiments": ["mahimahi_leaders", "mahimahi_wave", "mahimahi_strategy", "mysticeti_strategy"],
        },
        "AlephBFT-Specific": {
            "figures": ["fig14_aleph_knobs"],
            "experiments": ["aleph_lookahead", "aleph_sync_speed", "aleph_hash_randomization"],
        },
        "Autobahn-Specific": {
            "figures": ["fig15_autobahn_knobs"],
            "experiments": ["autobahn_k", "autobahn_fast_path"],
        },
    }
    figure_lookup = {figure.name: figure for figure in figures}
    grouped = experiment_matrix(rows)
    lines = ["# Category Summary", ""]
    lines.append(f"Last regenerated: `{report_stamp()}`")
    lines.append("")
    lines.append("This is the condensed paper-facing map from experiment categories to generated figures and the setups they summarize.")
    lines.append("")
    for category, meta in category_map.items():
        lines.append(f"## {category}")
        lines.append("")
        for fig_name in meta["figures"]:
            figure = figure_lookup[fig_name]
            lines.append(f"- Figure: `{figure.name}` -> `{figure.path.relative_to(GENERATED_DIR.parent.parent)}`")
            lines.append(f"  Purpose: {figure.purpose}")
        lines.append("")
        for experiment in meta["experiments"]:
            if experiment == "baseline":
                lines.append("- Experiment: pure protocol baselines from `baseline.csv`")
                lines.append("  Setup: all protocols on 13 nodes, no attack, node 0 versus node 1 measurement.")
                continue
            if experiment == "13-node peak attack cells":
                lines.append("- Experiment: best observed 13-node cells shown as full ASR bars with protocol baselines overlaid.")
                lines.append("  Setup: derived from whatever 13-node sweep cell produced the highest per-attack median.")
                continue
            keys = sorted(key for key in grouped if key[1] == experiment)
            if not keys:
                continue
            protocols = ", ".join(PROTOCOL_LABELS[protocol] for protocol in sorted({key[0] for key in keys}, key=PROTOCOL_ORDER.index))
            attacks = ", ".join(sorted({ATTACK_LABELS[key[2]] for key in keys}))
            lines.append(f"- Experiment: `{experiment}` ({EXPERIMENT_LABELS.get(experiment, experiment)})")
            lines.append(f"  Protocols: {protocols}")
            lines.append(f"  Attacks: {attacks}")
            sample = grouped[keys[0]][0]
            fixed = fixed_values(grouped[keys[0]], keys=DISPLAY_KEYS)
            if fixed:
                fixed_text = ", ".join(f"`{k}={v}`" for k, v in fixed.items())
                lines.append(f"  Representative fixed setup: {fixed_text}")
        lines.append("")
    write_text(REPORT_DIR / "category_summary.md", "\n".join(lines))


def generate_criteria_coverage(rows: Sequence[Row]) -> None:
    experiment_names = {row.experiment for row in rows}
    has_env_geodist = "env_geodist" in experiment_names
    has_latency_distance = any(
        row.get("LATENCY_MS", "") not in ("", None) or row.get("JITTER_MS", "") not in ("", None)
        for row in rows
    )
    present_latency_profiles = {
        row.get("LATENCY_JITTER", "")
        for row in rows
        if row.experiment == "env_latency" and row.get("LATENCY_JITTER", "") not in ("", None)
    }
    latency_profiles = [value for value in LATENCY_ORDER if value in present_latency_profiles]
    latency_profile_labels = ", ".join(f"`{LATENCY_LABELS.get(value, value)}`" for value in latency_profiles)
    lines = ["# Figure Criteria Coverage", ""]
    lines.append(f"Last regenerated: `{report_stamp()}`")
    lines.append("")
    lines.append("This file maps the requested paper criteria to the generated figures and states where the data is incomplete.")
    lines.append("")
    lines.append("## Covered")
    lines.append("- `(b) scalability`: covered by `fig02_scaling_trends`, `fig03_scaling_boxplot_fissure`, `fig04_scaling_boxplot_speculative`, and `fig05_scaling_boxplot_sluggish`.")
    lines.append("- `(c) attack ratio`: covered by `fig06_offense_sweeps` via the `offense_fissure` / `ATTACKER_RATIO` panel.")
    lines.append("- `(f) ASR across runs`: covered by the scaling boxplots. These replace error bars because the five-run distribution is more informative and was explicitly requested earlier.")
    lines.append("- `(g) attack-specific parameters`: covered by `fig06_offense_sweeps` via `SPECULATIVE_P_MAX` and `SLUGGISH_TIMEOUT_MULTIPLIER`.")
    lines.append("")
    lines.append("## Partially Covered")
    if "env_latency" in experiment_names:
        lines.append(f"- `(d) geo-distributed`: approximated by `fig07_latency_sensitivity`, which uses the available added-latency profiles ({latency_profile_labels}) as a geo-distribution proxy.")
    else:
        lines.append("- `(d) geo-distributed`: not present in the collected CSVs.")
    lines.append("")
    lines.append("## Not Covered By Current Data")
    if not has_env_geodist:
        lines.append("- No `env_geodist` experiment rows were recorded, even though the sweeper supports that experiment.")
    if not has_latency_distance:
        lines.append("- `(e) victim-attacker distance` is not separately plottable from the current CSVs. There are no populated `LATENCY_MS/JITTER_MS` rows and no explicit victim-distance field in the recorded results.")
    lines.append("")
    lines.append("## Recommendation")
    lines.append("- If the paper must include a true victim-attacker-distance figure, new data collection is required. The current figure suite can only support a latency-profile proxy, not a true distance sweep.")
    lines.append("")
    write_text(REPORT_DIR / "criteria_coverage.md", "\n".join(lines))


def generate_figure_manifest(figures: Sequence[FigureInfo], peak_lifts: Dict[Tuple[str, str], Dict[str, object]]) -> None:
    lines = ["# Figure Manifest", ""]
    lines.append(f"Last regenerated: `{report_stamp()}`")
    lines.append(f"Current figure count: `{len(figures)}`")
    lines.append("")
    lines.append("This manifest maps each generated TikZ figure to its analytical purpose and the setups it summarizes.")
    lines.append("Important: identifiers such as `fig07_latency_sensitivity` are generator file IDs, not the final LaTeX `Figure 7` numbering in the paper.")
    lines.append("The manuscript figure numbers depend on the order and placement of floats in Overleaf, so they can diverge from the generated file IDs.")
    lines.append("")
    for figure in figures:
        lines.append(f"## `{figure.name}`")
        lines.append(f"- File: `{figure.path.relative_to(GENERATED_DIR.parent.parent)}`")
        lines.append(f"- Title: {figure.title}")
        lines.append(f"- Purpose: {figure.purpose}")
        lines.append(f"- Columns: {', '.join(f'`{column}`' for column in figure.columns)}")
        lines.append(f"- Setup: {figure.setup}")
        lines.append(f"- Baseline handling: {figure.baseline_use}")
        lines.append("")

    lines.append("## Peak 13-node ASR cells behind `fig01_peak_attack_lift`")
    for protocol in PROTOCOL_ORDER:
        for attack in ATTACK_ORDER:
            cell = peak_lifts.get((protocol, attack))
            if cell is None:
                continue
            signature = ", ".join(
                f"`{key}={value}`" for key, value in cell["signature"].items() if value not in ("", None)
            )
            lines.append(
                f"- `{PROTOCOL_LABELS[protocol]}` / `{ATTACK_LABELS[attack]}`: median `{fmt(cell['median_asr'])}%`, baseline `{fmt(cell['baseline'])}%`, lift `{fmt(cell['lift'])}` from `{cell['experiment']}` ({signature or 'default cell'})."
            )
    lines.append("")
    write_text(REPORT_DIR / "figure_manifest.md", "\n".join(lines))


def generate_preview_document(figures: Sequence[FigureInfo]) -> None:
    inputs = "\n".join(
        rf"\begin{{figure}}[p]\centering\input{{figures/{figure.name}.tex}}\caption{{{tex_escape(figure.title)}}}\end{{figure}}"
        for figure in figures
    )
    content = r"""\documentclass{article}
\usepackage[margin=0.7in]{geometry}
\usepackage{pgfplots}
\usepackage{tikz}
\usepackage{caption}
\input{figures/preamble.tex}
\begin{document}
""" + inputs + r"""
\end{document}
"""
    write_text(GENERATED_DIR / "preview.tex", content)


def main() -> None:
    ensure_dirs()
    generate_preamble()

    raw_rows = load_rows()
    rows = filter_expected(raw_rows)
    baselines = load_baselines()

    figures: List[FigureInfo] = []
    peak_lifts = compute_peak_lifts(rows, baselines)
    figures.append(generate_peak_attack_lift(rows, baselines))
    figures.append(generate_scaling_trends(rows))
    figures.append(generate_scaling_boxplots(rows, "fissure", 3))
    figures.append(generate_scaling_boxplots(rows, "speculative", 4))
    figures.append(generate_scaling_boxplots(rows, "sluggish", 5))
    figures.append(generate_offense_sweeps(rows))
    figures.append(generate_latency_sensitivity(rows))
    figures.append(generate_core_defenses(rows))
    figures.append(generate_narwhal_workers(rows))
    figures.append(generate_narwhal_heatmaps(rows, "defense_header", 10, "HEADER_SIZE", "MAX_HEADER_DELAY", "Narwhal header parameter surface"))
    figures.append(generate_narwhal_heatmaps(rows, "defense_batching", 11, "BATCH_SIZE", "MAX_BATCH_DELAY", "Narwhal batching parameter surface"))
    figures.append(generate_wave_leaders(rows))
    figures.append(generate_strategy_sweeps(rows))
    figures.append(generate_aleph_knobs(rows))
    figures.append(generate_autobahn_knobs(rows))

    generate_column_audit(rows, figures)
    generate_experiment_inventory(rows)
    generate_data_anomalies(rows, baselines)
    generate_category_summary(rows, figures)
    generate_criteria_coverage(rows)
    generate_figure_manifest(figures, peak_lifts)
    generate_preview_document(figures)

    summary_lines = [
        f"Last regenerated: {report_stamp()}",
        "",
        "Generated figures:",
        *[f"- {figure.name}: {figure.path}" for figure in figures],
        "",
        "Generated reports:",
        f"- {REPORT_DIR / 'column_audit.md'}",
        f"- {REPORT_DIR / 'experiment_inventory.md'}",
        f"- {REPORT_DIR / 'data_anomalies.md'}",
        f"- {REPORT_DIR / 'category_summary.md'}",
        f"- {REPORT_DIR / 'criteria_coverage.md'}",
        f"- {REPORT_DIR / 'figure_manifest.md'}",
        "",
        f"Rows used after filtering unexpected protocol-experiment combos: {len(rows)}",
        f"Baselines loaded: {len(baselines)}",
    ]
    write_text(REPORT_DIR / "generation_summary.txt", "\n".join(summary_lines))
    print("\n".join(summary_lines))


if __name__ == "__main__":
    main()
