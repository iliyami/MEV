"""
Figure 6: Defense Parameter Sensitivity
=========================================
Line charts for Narwhal-Tusk family protocols showing how
defensive tuning affects ASR.
"""

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from config import (
    setup_style, save_fig, FULLWIDTH,
    PROTOCOL_DISPLAY, PROTOCOL_COLORS, ATTACK_DISPLAY,
)
from data_loader import load_frontrunning_data, get_defense_data, compute_summary


# Map defense experiments to their parameter columns and labels
DEFENSE_PARAMS = {
    "defense_memory":   {"col": "DAG_STATE_CACHED_ROUNDS", "label": "DAG Cached Rounds"},
    "defense_network":  {"col": "SYNC_TIMEOUT_MS",         "label": "Sync Timeout (ms)"},
    "defense_gc":       {"col": "GC_DEPTH",                "label": "GC Depth"},
    "defense_batching": {"col": "BATCH_SIZE",              "label": "Batch Size"},
    "defense_header":   {"col": "HEADER_SIZE",             "label": "Header Size"},
}


def plot_defense_sensitivity():
    setup_style()

    df = load_frontrunning_data()
    df_def = get_defense_data(df)

    # Find which defense experiments exist and have data
    available_exps = sorted(df_def["experiment"].unique())
    available_exps = [e for e in available_exps if e in DEFENSE_PARAMS]

    if not available_exps:
        print("⚠️  No defense experiments found.")
        return

    n_panels = len(available_exps)
    ncols = min(3, n_panels)
    nrows = (n_panels + ncols - 1) // ncols

    fig, axes = plt.subplots(nrows, ncols, figsize=(FULLWIDTH * 1.2, FULLWIDTH * 0.5 * nrows),
                             squeeze=False)
    axes = axes.flatten()

    markers = ["o", "s", "^", "D", "v"]
    attack_markers = {"fissure": "o", "speculative": "s", "sluggish": "^"}

    for ax_idx, exp in enumerate(available_exps):
        ax = axes[ax_idx]
        info = DEFENSE_PARAMS[exp]
        param_col = info["col"]
        param_label = info["label"]

        df_exp = df_def[df_def["experiment"] == exp].copy()
        df_exp[param_col] = pd.to_numeric(df_exp[param_col], errors="coerce")
        df_exp = df_exp.dropna(subset=[param_col])

        # Plot per protocol × attack_mode
        for proto in sorted(df_exp["protocol"].unique()):
            for attack in sorted(df_exp["attack_mode"].unique()):
                df_sub = df_exp[(df_exp["protocol"] == proto) &
                                (df_exp["attack_mode"] == attack)]
                if len(df_sub) == 0:
                    continue

                summary = compute_summary(df_sub, [param_col])
                summary = summary.sort_values(param_col)

                label = f"{PROTOCOL_DISPLAY.get(proto, proto)} ({ATTACK_DISPLAY.get(attack, attack)})"
                ax.plot(
                    summary[param_col], summary["mean_asr"],
                    marker=attack_markers.get(attack, "o"),
                    color=PROTOCOL_COLORS.get(proto, "#666"),
                    label=label,
                    linewidth=1.2, markersize=4,
                    alpha=0.85,
                )

        ax.axhline(y=50, color="#999", linestyle="--", linewidth=0.8, alpha=0.5)
        ax.set_xlabel(param_label, fontsize=8)
        ax.set_ylabel("ASR (%)" if ax_idx % ncols == 0 else "", fontsize=8)
        ax.set_title(exp.replace("defense_", "").replace("_", " ").title(),
                     fontweight="bold", fontsize=9)
        ax.legend(fontsize=5, loc="best", ncol=1)

    # Hide unused axes
    for i in range(len(available_exps), len(axes)):
        axes[i].set_visible(False)

    fig.suptitle("Defense Parameter Sensitivity (Narwhal-Tusk Family)",
                 fontsize=18, fontweight="bold", y=1.05)

    save_fig(fig, "fig6_defense_sensitivity")
    print("✅ Figure 6: Defense sensitivity generated.")


if __name__ == "__main__":
    plot_defense_sensitivity()
