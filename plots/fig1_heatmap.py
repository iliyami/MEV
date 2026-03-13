"""
Figure 1: Cross-Protocol ASR Heatmap
=====================================
The "hero figure" — one glance shows which protocols are vulnerable to what.
Rows = protocols (grouped by family), Columns = attack modes.
"""

import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import numpy as np
import pandas as pd

from config import (
    setup_style, save_fig, FULLWIDTH, ASPECT,
    PROTOCOL_ORDER, PROTOCOL_DISPLAY, ATTACK_DISPLAY,
    FAMILY_OF, FAMILY_COLORS,
)
from data_loader import load_frontrunning_data, compute_summary, get_simple_frontrunning


def plot_heatmap():
    setup_style()

    df_full = load_frontrunning_data()
    df = get_simple_frontrunning(df_full)

    # Use offense experiments with default params for the base ASR
    attacks = ["fissure", "speculative", "sluggish"]
    offense_map = {
        "fissure":     "offense_fissure",
        "speculative": "offense_speculative",
        "sluggish":    "offense_sluggish",
    }

    # Build the matrix: rows = protocols, cols = attacks
    protocols = PROTOCOL_ORDER
    matrix = np.full((len(protocols), len(attacks)), np.nan)

    for i, proto in enumerate(protocols):
        for j, attack in enumerate(attacks):
            exp_name = offense_map[attack]
            mask = (df["protocol"] == proto) & (df["experiment"] == exp_name)
            subset = df[mask]
            if len(subset) > 0:
                matrix[i, j] = subset["asr"].mean()

    # ── Baseline column ──
    # Known baseline values from FINAL_RESULTS_REPORT.md
    baselines = {
        "bullshark": 50, "mevsui": 50, "narwhal": 50,
        "mahimahi": 49.97, "mysticeti": 50.05,
        "alephbft": 31, "autobahn": 50,
    }
    baseline_col = np.array([baselines.get(p, np.nan) for p in protocols])

    # Prepend baseline column
    full_matrix = np.column_stack([baseline_col, matrix])
    col_labels = ["Baseline"] + [ATTACK_DISPLAY[a] for a in attacks]
    row_labels = [PROTOCOL_DISPLAY[p] for p in protocols]

    # ── Create figure ──
    fig, ax = plt.subplots(figsize=(FULLWIDTH * 0.8, FULLWIDTH * 0.7))

    # Custom colormap: green → yellow → red
    cmap = mcolors.LinearSegmentedColormap.from_list(
        "asr_cmap",
        [(0.0, "#2A9D8F"), (0.4, "#E9C46A"), (0.7, "#E76F51"), (1.0, "#E63946")],
    )

    im = ax.imshow(full_matrix, cmap=cmap, aspect="auto", vmin=0, vmax=100)

    # Labels
    ax.set_xticks(range(len(col_labels)))
    ax.set_xticklabels(col_labels, fontweight="bold")
    ax.set_yticks(range(len(row_labels)))
    ax.set_yticklabels(row_labels)

    # Move x-axis labels to top
    ax.xaxis.set_ticks_position("top")
    ax.xaxis.set_label_position("top")

    # Annotate cells with values
    for i in range(len(protocols)):
        for j in range(len(col_labels)):
            val = full_matrix[i, j]
            if np.isnan(val):
                text = "—"
                color = "#999999"
            else:
                text = f"{val:.1f}%"
                # White text on dark cells, black on light
                color = "white" if val > 65 else "black"
            ax.text(j, i, text, ha="center", va="center",
                    fontsize=13, fontweight="bold", color=color)

    # Family separator lines
    family_boundaries = []
    prev_family = None
    for i, p in enumerate(protocols):
        fam = FAMILY_OF[p]
        if prev_family and fam != prev_family:
            family_boundaries.append(i - 0.5)
        prev_family = fam

    for y in family_boundaries:
        ax.axhline(y=y, color="white", linewidth=2)

    # Family labels on the right
    family_spans = {}
    for i, p in enumerate(protocols):
        fam = FAMILY_OF[p]
        if fam not in family_spans:
            family_spans[fam] = [i, i]
        else:
            family_spans[fam][1] = i

    for fam, (start, end) in family_spans.items():
        mid = (start + end) / 2
        ax.text(
            len(col_labels) + 0.3, mid, fam,
            ha="left", va="center", fontsize=12, fontstyle="italic",
            color=FAMILY_COLORS.get(fam, "#666"),
            fontweight="bold",
        )

    # Colorbar
    cbar = fig.colorbar(im, ax=ax, shrink=0.8, pad=0.15)
    cbar.set_label("ASR (%)", fontsize=14)

    # Title
    ax.set_title("Frontrunning Attack Success Rate by Protocol",
                 fontsize=18, fontweight="bold", pad=25)

    save_fig(fig, "fig1_heatmap")
    print("✅ Figure 1: Heatmap generated.")


if __name__ == "__main__":
    plot_heatmap()
