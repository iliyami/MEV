"""
Figure 7: Environment / Latency Sensitivity
=============================================
Line chart showing how network latency affects ASR across protocols.
"""

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from config import (
    setup_style, save_fig, FULLWIDTH,
    PROTOCOL_DISPLAY, PROTOCOL_COLORS, ATTACK_DISPLAY,
    PROTOCOL_ORDER,
)
from data_loader import load_frontrunning_data, get_env_latency_data, compute_summary


def plot_latency_sensitivity():
    setup_style()

    df = load_frontrunning_data()
    df_lat = get_env_latency_data(df)

    attacks = ["fissure", "speculative", "sluggish"]

    fig, axes = plt.subplots(1, 3, figsize=(FULLWIDTH * 1.4, FULLWIDTH * 0.5),
                             sharey=True)
    markers = ["o", "s", "^", "D", "v", "P", "X"]

    for ax_idx, attack in enumerate(attacks):
        ax = axes[ax_idx]
        df_atk = df_lat[df_lat["attack_mode"] == attack]

        protocols_present = [p for p in PROTOCOL_ORDER
                             if p in df_atk["protocol"].unique()]

        for pi, proto in enumerate(protocols_present):
            df_p = df_atk[df_atk["protocol"] == proto]
            summary = compute_summary(df_p, ["LATENCY_MS"])
            summary = summary.sort_values("LATENCY_MS")

            ax.plot(
                summary["LATENCY_MS"], summary["mean_asr"],
                marker=markers[pi % len(markers)],
                color=PROTOCOL_COLORS[proto],
                label=PROTOCOL_DISPLAY[proto],
                linewidth=1.5, markersize=4,
            )

        ax.axhline(y=50, color="#999", linestyle="--", linewidth=0.8,
                   alpha=0.6, zorder=0)
        ax.set_title(ATTACK_DISPLAY[attack], fontweight="bold")
        ax.set_xlabel("Network Latency (ms)")
        if ax_idx == 0:
            ax.set_ylabel("ASR (%)")

    # Shared legend
    all_handles, all_labels = [], []
    seen = set()
    for ax in axes:
        for h, l in zip(*ax.get_legend_handles_labels()):
            if l not in seen:
                all_handles.append(h)
                all_labels.append(l)
                seen.add(l)

    if all_handles:
        fig.legend(
            all_handles, all_labels,
            loc="lower center", ncol=min(4, len(all_labels)),
            bbox_to_anchor=(0.5, -0.12),
            frameon=True, fontsize=12,
        )

    fig.suptitle("ASR Sensitivity to Network Latency",
                 fontsize=18, fontweight="bold", y=1.05)

    save_fig(fig, "fig7_latency_sensitivity")
    print("✅ Figure 7: Latency sensitivity generated.")


if __name__ == "__main__":
    plot_latency_sensitivity()
