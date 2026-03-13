"""
Figure 8: Protocol-Specific Parameter Analysis
=================================================
Focused mini-figures for each protocol family's unique parameters:
  - AlephBFT: election lookahead, sync speed, hash randomization
  - Mysticeti/MahiMahi: number of leaders, wave length, commit strategy
  - Autobahn: K-parameter, fast path toggle
"""

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from config import (
    setup_style, save_fig, FULLWIDTH,
    PROTOCOL_DISPLAY, PROTOCOL_COLORS, ATTACK_DISPLAY, ATTACK_COLORS,
)
from data_loader import load_frontrunning_data, get_protocol_specific_data, compute_summary


# Experiment → param column mapping
PROTO_PARAMS = {
    "aleph_lookahead":          {"col": "ALEPH_ELECTION_LOOKAHEAD", "label": "Election Lookahead"},
    "aleph_sync_speed":         {"col": "ALEPH_COORD_REQUEST_DELAY_MS", "label": "Coord Request Delay (ms)"},
    "aleph_hash_randomization": {"col": "ALEPH_HASH_SORT_SEED",    "label": "Hash Sort Seed"},
    "mahimahi_leaders":         {"col": "NUMBER_OF_LEADERS",        "label": "Number of Leaders"},
    "mahimahi_wave":            {"col": "WAVE_LENGTH",              "label": "Wave Length"},
    "mahimahi_strategy":        {"col": "SPECULATIVE_STRATEGY",     "label": "Commit Strategy"},
    "mysticeti_strategy":       {"col": "SPECULATIVE_STRATEGY",     "label": "Commit Strategy"},
    "autobahn_k":               {"col": "AUTOBAHN_K",              "label": "K Parameter"},
    "autobahn_fast_path":       {"col": "AUTOBAHN_FAST_PATH_TIMEOUT", "label": "Fast Path Timeout"},
}


def plot_protocol_specific():
    setup_style()

    df = load_frontrunning_data()
    df_spec = get_protocol_specific_data(df)

    # Group by protocol family
    groups = {
        "AlephBFT": ["aleph_lookahead", "aleph_sync_speed", "aleph_hash_randomization"],
        "Mahi Mahi / Mysticeti": ["mahimahi_leaders", "mahimahi_wave", "mahimahi_strategy", "mysticeti_strategy"],
        "Autobahn": ["autobahn_k", "autobahn_fast_path"],
    }

    for group_name, experiments in groups.items():
        available = [e for e in experiments if e in df_spec["experiment"].unique()]
        if not available:
            continue

        n_panels = len(available)
        fig, axes = plt.subplots(1, n_panels, figsize=(FULLWIDTH * 1.2, FULLWIDTH * 0.42),
                                 squeeze=False)
        axes = axes.flatten()

        attack_markers = {"fissure": "o", "speculative": "s", "sluggish": "^"}

        for ax_idx, exp in enumerate(available):
            ax = axes[ax_idx]
            info = PROTO_PARAMS.get(exp)
            if not info:
                continue

            param_col = info["col"]
            param_label = info["label"]

            df_exp = df_spec[df_spec["experiment"] == exp].copy()

            # Check if param is numeric or categorical
            df_exp[param_col] = df_exp[param_col].astype(str).str.strip()
            try:
                df_exp["param_val"] = pd.to_numeric(df_exp[param_col])
                is_numeric = True
            except (ValueError, TypeError):
                df_exp["param_val"] = df_exp[param_col]
                is_numeric = False

            for attack in sorted(df_exp["attack_mode"].unique()):
                df_atk = df_exp[df_exp["attack_mode"] == attack]

                if is_numeric:
                    summary = compute_summary(df_atk, ["param_val"])
                    summary = summary.sort_values("param_val")
                    ax.plot(
                        summary["param_val"], summary["mean_asr"],
                        marker=attack_markers.get(attack, "o"),
                        color=ATTACK_COLORS.get(attack, "#666"),
                        label=ATTACK_DISPLAY.get(attack, attack),
                        linewidth=1.5, markersize=4,
                    )
                else:
                    summary = compute_summary(df_atk, ["param_val"])
                    x = range(len(summary))
                    ax.bar(
                        [xi + 0.2 * list(ATTACK_DISPLAY.keys()).index(attack)
                         for xi in x],
                        summary["mean_asr"],
                        width=0.2,
                        color=ATTACK_COLORS.get(attack, "#666"),
                        label=ATTACK_DISPLAY.get(attack, attack),
                    )
                    ax.set_xticks(range(len(summary)))
                    ax.set_xticklabels(summary["param_val"], rotation=45,
                                       ha="right", fontsize=6)

            ax.axhline(y=50, color="#999", linestyle="--", linewidth=0.8, alpha=0.5)
            ax.set_xlabel(param_label, fontsize=8)
            ax.set_ylabel("ASR (%)" if ax_idx == 0 else "", fontsize=8)
            ax.set_title(exp.replace("_", " ").title(), fontsize=8, fontweight="bold")
            ax.legend(fontsize=6, loc="best")

        fig.suptitle(f"Protocol-Specific Parameters: {group_name}",
                     fontsize=10, fontweight="bold", y=1.02)

        safe_name = group_name.lower().replace(" ", "_").replace("/", "")
        save_fig(fig, f"fig8_{safe_name}")
        print(f"✅ Figure 8 ({group_name}): Protocol-specific params generated.")


if __name__ == "__main__":
    plot_protocol_specific()
