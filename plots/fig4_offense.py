"""
Figure 4: Offense Parameter Sensitivity
=========================================
Line charts showing how ASR changes as attacker power increases.
One panel per parameter type, lines per protocol.
"""

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from config import (
    setup_style, save_fig, FULLWIDTH,
    PROTOCOL_DISPLAY, PROTOCOL_COLORS, ATTACK_DISPLAY,
)
from data_loader import load_frontrunning_data, get_offense_data, compute_summary


# Map experiment names to the parameter column they sweep
OFFENSE_PARAMS = {
    "offense_fissure": {
        "param_col": "ATTACKER_RATIO",
        "label": "Attacker Ratio (fraction of nodes)",
    },
    "offense_speculative": {
        "param_col": "SPECULATIVE_P_MAX",
        "label": "Speculative P_max (# blocks)",
    },
    "offense_sluggish": {
        "param_col": "SLUGGISH_TIMEOUT_MULTIPLIER",
        "label": "Timeout Multiplier (×)",
    },
    "offense_exclusion": {
        "param_col": "EXCLUSION_PROBABILITY",
        "label": "Exclusion Probability",
    },
}


def plot_offense_sensitivity():
    setup_style()

    df = load_frontrunning_data()
    df_off = get_offense_data(df)

    # We'll create panels for fissure, speculative, sluggish
    experiments = ["offense_fissure", "offense_speculative", "offense_sluggish"]

    fig, axes = plt.subplots(1, 3, figsize=(FULLWIDTH * 1.4, FULLWIDTH * 0.5))
    markers = ["o", "s", "^", "D", "v", "P", "X"]
    linestyles = ["-", "--", "-.", ":", "-", "--", "-."]

    for ax_idx, exp in enumerate(experiments):
        ax = axes[ax_idx]
        info = OFFENSE_PARAMS[exp]
        param_col = info["param_col"]
        param_label = info["label"]

        df_exp = df_off[df_off["experiment"] == exp].copy()
        df_exp[param_col] = pd.to_numeric(df_exp[param_col], errors="coerce")
        df_exp = df_exp.dropna(subset=[param_col])

        protocols_present = sorted(df_exp["protocol"].unique(),
                                   key=lambda x: list(PROTOCOL_DISPLAY.keys()).index(x)
                                   if x in PROTOCOL_DISPLAY else 99)

        for pi, proto in enumerate(protocols_present):
            df_p = df_exp[df_exp["protocol"] == proto]
            summary = compute_summary(df_p, [param_col])
            summary = summary.sort_values(param_col)

            ax.errorbar(
                summary[param_col], summary["mean_asr"],
                yerr=summary["std_asr"],
                marker=markers[pi % len(markers)],
                color=PROTOCOL_COLORS.get(proto, "#666"),
                label=PROTOCOL_DISPLAY.get(proto, proto),
                capsize=3, capthick=1,
                linewidth=2.5, markersize=8,
                linestyle=linestyles[pi % len(linestyles)],
            )

        ax.axhline(y=50, color="#999", linestyle="--", linewidth=0.8,
                   alpha=0.6, zorder=0)

        attack_name = exp.replace("offense_", "")
        ax.set_title(ATTACK_DISPLAY.get(attack_name, attack_name),
                     fontweight="bold")
        ax.set_xlabel(param_label)
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

    fig.legend(
        all_handles, all_labels,
        loc="lower center", ncol=min(4, len(all_labels)),
        bbox_to_anchor=(0.5, -0.12),
        frameon=True, fontsize=12,
    )

    fig.suptitle("Offense Parameter Sensitivity",
                 fontsize=18, fontweight="bold", y=1.05)

    save_fig(fig, "fig4_offense_sensitivity")
    print("✅ Figure 4: Offense sensitivity generated.")


if __name__ == "__main__":
    plot_offense_sensitivity()
