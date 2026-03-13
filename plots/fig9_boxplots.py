"""
Figure 9: Box Plots of ASR Distribution
=========================================
Shows variance and outliers across 5 reps — demonstrates statistical rigor.
"""

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from config import (
    setup_style, save_fig, FULLWIDTH,
    PROTOCOL_ORDER, PROTOCOL_DISPLAY, PROTOCOL_COLORS,
    ATTACK_DISPLAY, ATTACK_COLORS, FAMILY_OF,
    add_family_spans,
)
from data_loader import load_frontrunning_data


def plot_boxplots():
    setup_style()

    df = load_frontrunning_data()
    attacks = ["fissure", "speculative", "sluggish"]
    offense_map = {
        "fissure":     "offense_fissure",
        "speculative": "offense_speculative",
        "sluggish":    "offense_sluggish",
    }

    fig, axes = plt.subplots(1, 3, figsize=(FULLWIDTH * 1.4, FULLWIDTH * 0.5),
                             sharey=True)

    for ax_idx, attack in enumerate(attacks):
        ax = axes[ax_idx]
        exp = offense_map[attack]
        df_atk = df[df["experiment"] == exp]

        box_data = []
        labels = []
        colors = []
        for proto in PROTOCOL_ORDER:
            sub = df_atk[df_atk["protocol"] == proto]["asr"]
            if len(sub) > 0:
                box_data.append(sub.values)
                labels.append(PROTOCOL_DISPLAY[proto])
                colors.append(PROTOCOL_COLORS[proto])
            else:
                box_data.append([])
                labels.append(PROTOCOL_DISPLAY[proto])
                colors.append("#cccccc")

        bp = ax.boxplot(
            box_data, patch_artist=True, widths=0.6,
            medianprops=dict(color="black", linewidth=1.5),
            whiskerprops=dict(linewidth=0.8),
            capprops=dict(linewidth=0.8),
            flierprops=dict(marker="o", markersize=3, alpha=0.5),
        )

        for patch, color in zip(bp["boxes"], colors):
            patch.set_facecolor(color)
            patch.set_alpha(0.7)
            patch.set_edgecolor("#333")

        # 50% baseline
        ax.axhline(y=50, color="#999", linestyle="--", linewidth=0.8, alpha=0.6)

        ax.set_xticklabels(labels, rotation=35, ha="right", fontsize=10)
        ax.set_title(ATTACK_DISPLAY[attack], fontweight="bold")
        if ax_idx == 0:
            ax.set_ylabel("ASR (%)")

    fig.suptitle("ASR Distribution Across Repetitions",
                 fontsize=18, fontweight="bold", y=1.05)

    save_fig(fig, "fig9_boxplots")
    print("✅ Figure 9: Box plots generated.")


if __name__ == "__main__":
    plot_boxplots()
