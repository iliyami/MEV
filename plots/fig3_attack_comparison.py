"""
Figure 3: Attack Mode Comparison
==================================
Three separate sub-figures:
  3a — Frontrunning ASR (strict, gap≤1-2)  for all 7 protocols
  3b — Backrunning ASR (cumulative)        for 4 representative protocols
  3c — Sandwich Success Rate               for 4 representative protocols
"""

import matplotlib.pyplot as plt
import numpy as np

from config import (
    setup_style, save_fig, FULLWIDTH, COLWIDTH, ASPECT,
    PROTOCOL_ORDER, REPRESENTATIVE_PROTOCOLS,
    PROTOCOL_DISPLAY, PROTOCOL_COLORS,
    ATTACK_DISPLAY, ATTACK_COLORS, ATTACK_HATCHES,
    FAMILY_OF, add_family_spans,
)
from data_loader import (
    load_frontrunning_data, load_backrun_sandwich_data,
    compute_summary,
)


def _grouped_bar(ax, summary_df, protocols, attacks, title, ylabel="ASR (%)"):
    """
    Draw grouped bar chart on the given axes.

    Parameters
    ----------
    summary_df : DataFrame with columns [protocol, attack_mode, mean_asr, std_asr]
    protocols  : list of protocol keys to include (in order)
    attacks    : list of attack_mode keys
    """
    n_protocols = len(protocols)
    n_attacks = len(attacks)
    bar_width = 0.22
    x = np.arange(n_protocols)

    for j, attack in enumerate(attacks):
        means, stds = [], []
        for proto in protocols:
            row = summary_df[
                (summary_df["protocol"] == proto) &
                (summary_df["attack_mode"] == attack)
            ]
            if len(row) > 0:
                means.append(row["mean_asr"].values[0])
                stds.append(row["std_asr"].values[0])
            else:
                means.append(0)
                stds.append(0)

        offset = (j - n_attacks / 2 + 0.5) * bar_width
        bars = ax.bar(
            x + offset, means, bar_width,
            yerr=stds, capsize=3,
            color=ATTACK_COLORS[attack],
            hatch=ATTACK_HATCHES[attack],
            edgecolor="white", linewidth=0.5,
            label=ATTACK_DISPLAY[attack],
            zorder=3,
        )

        # Value labels on top of bars
        for bar, val in zip(bars, means):
            if val > 0:
                ax.text(
                    bar.get_x() + bar.get_width() / 2,
                    bar.get_height() + 1.5,
                    f"{val:.0f}",
                    ha="center", va="bottom", fontsize=10,
                    fontweight="bold", color="#333",
                )

    # 50% baseline reference
    ax.axhline(y=50, color="#999", linestyle="--", linewidth=0.8,
               alpha=0.6, zorder=1)

    ax.set_xticks(x)
    ax.set_xticklabels(
        [PROTOCOL_DISPLAY[p] for p in protocols],
        rotation=30, ha="right", fontsize=12,
    )
    ax.set_ylabel(ylabel, fontsize=14)
    ax.set_title(title, fontsize=16, fontweight="bold")
    ax.set_ylim(0, 115)
    ax.legend(fontsize=11, loc="upper right")

    # Family spans below x-axis
    add_family_spans(ax, protocols, y_offset=-0.25)


def plot_fig3a_frontrunning():
    """Fig 3a: Frontrunning ASR for all 7 protocols."""
    setup_style()

    df = load_frontrunning_data()
    attacks = ["fissure", "speculative", "sluggish"]

    # Get offense experiments
    offense_map = {
        "fissure": "offense_fissure",
        "speculative": "offense_speculative",
        "sluggish": "offense_sluggish",
    }

    rows = []
    for attack, exp in offense_map.items():
        mask = df["experiment"] == exp
        sub = df[mask].copy()
        sub["attack_mode"] = attack
        rows.append(sub)
    df_off = pd.concat(rows, ignore_index=True)

    summary = compute_summary(df_off, ["protocol", "attack_mode"])

    fig, ax = plt.subplots(figsize=(FULLWIDTH * 1.0, FULLWIDTH * 0.55))
    _grouped_bar(ax, summary, PROTOCOL_ORDER, attacks,
                 "Frontrunning ASR by Protocol")

    save_fig(fig, "fig3a_frontrunning")
    print("✅ Figure 3a: Frontrunning comparison generated.")




def plot_fig3c_sandwich():
    """Fig 3c: Sandwich Success Rate for 4 representative protocols."""
    setup_style()

    df = load_backrun_sandwich_data()
    df_sw = df[df["attack_type"] == "sandwich"]
    attacks = ["fissure", "speculative", "sluggish"]

    summary = compute_summary(df_sw, ["protocol", "attack_mode"])

    fig, ax = plt.subplots(figsize=(COLWIDTH * 1.6, COLWIDTH * 1.1))
    _grouped_bar(ax, summary, REPRESENTATIVE_PROTOCOLS, attacks,
                 "Sandwich Success Rate by Protocol (SeSR)")

    save_fig(fig, "fig3c_sandwich")
    print("✅ Figure 3c: Sandwich comparison generated.")


# Need pandas import at module level for fig3a
import pandas as pd


if __name__ == "__main__":
    plot_fig3a_frontrunning()
    plot_fig3c_sandwich()
