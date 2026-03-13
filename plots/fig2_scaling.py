"""
Figure 2: ASR vs Network Scale (Scaling Curves)
=================================================
Multi-line chart showing how ASR changes with network size.
One panel per attack mode, lines per protocol.
"""

import matplotlib.pyplot as plt
import numpy as np

from config import (
    setup_style, save_fig, FULLWIDTH, ASPECT,
    PROTOCOL_ORDER, PROTOCOL_DISPLAY, PROTOCOL_COLORS,
    ATTACK_DISPLAY, FAMILY_OF,
)
from data_loader import load_frontrunning_data, get_scaling_data, compute_summary


def plot_scaling():
    setup_style()

    df = load_frontrunning_data()
    df_scale = get_scaling_data(df)

    attacks = ["fissure", "speculative", "sluggish"]

    # Filter to main scaling experiment (not scaling_workers)
    df_scale = df_scale[df_scale["experiment"] == "scaling"]

    fig, axes = plt.subplots(1, 3, figsize=(FULLWIDTH * 1.4, FULLWIDTH * 0.5),
                             sharey=True)

    markers = ["o", "s", "^", "D", "v", "P", "X"]
    linestyles = ["-", "--", "-.", ":", "-", "--", "-."]

    for ax_idx, attack in enumerate(attacks):
        ax = axes[ax_idx]
        df_atk = df_scale[df_scale["attack_mode"] == attack]

        # Cap sluggish at 50 nodes (no 100-node data collected)
        max_nodes = 50 if attack == "sluggish" else 100
        df_atk = df_atk[df_atk["NUM_NODES"] <= max_nodes]

        protocols_present = [p for p in PROTOCOL_ORDER
                             if p in df_atk["protocol"].unique()]

        for pi, proto in enumerate(protocols_present):
            df_p = df_atk[df_atk["protocol"] == proto]
            summary = compute_summary(df_p, ["NUM_NODES"])
            summary = summary.sort_values("NUM_NODES")

            nodes = summary["NUM_NODES"].values
            means = summary["mean_asr"].values
            stds = summary["std_asr"].values

            ax.errorbar(
                nodes, means, yerr=stds,
                marker=markers[pi % len(markers)],
                color=PROTOCOL_COLORS[proto],
                label=PROTOCOL_DISPLAY[proto],
                capsize=3, capthick=1,
                linewidth=2.5, markersize=8,
                linestyle=linestyles[pi % len(linestyles)],
            )

        ax.set_title(ATTACK_DISPLAY[attack], fontweight="bold")
        ax.set_xlabel("Number of Nodes")
        ax.set_xscale("log", base=2)
        if attack == "sluggish":
            ax.set_xticks([13, 25, 50])
        else:
            ax.set_xticks([13, 25, 50, 100])
        ax.get_xaxis().set_major_formatter(plt.ScalarFormatter())

        # 50% baseline reference
        ax.axhline(y=50, color="#999999", linestyle="--", linewidth=0.8,
                   alpha=0.7, zorder=0)
        baseline_x = 55 if attack == "sluggish" else 105
        ax.text(baseline_x, 51, "Fair baseline", fontsize=10, color="#777777",
                va="bottom", fontweight="bold")

        if ax_idx == 0:
            ax.set_ylabel("ASR (%)")

    # Shared legend at the bottom
    handles, labels = axes[0].get_legend_handles_labels()
    # Combine all unique handles
    all_handles, all_labels = [], []
    seen = set()
    for ax in axes:
        for h, l in zip(*ax.get_legend_handles_labels()):
            if l not in seen:
                all_handles.append(h)
                all_labels.append(l)
                seen.add(l)

    fig.legend(
        all_handles, all_labels,
        loc="lower center", ncol=min(4, len(all_labels)),
        bbox_to_anchor=(0.5, -0.12),
        frameon=True, fontsize=12,
    )

    fig.suptitle("Attack Success Rate vs. Network Scale",
                 fontsize=18, fontweight="bold", y=1.05)

    save_fig(fig, "fig2_scaling")
    print("✅ Figure 2: Scaling curves generated.")


if __name__ == "__main__":
    plot_scaling()
