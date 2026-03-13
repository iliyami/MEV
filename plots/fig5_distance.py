"""
Figure 5: Backrun Distance Histogram
======================================
Shows WHERE the attacker's block lands relative to the victim.
Separate panels per protocol family.
"""

import matplotlib.pyplot as plt
import numpy as np
import seaborn as sns

from config import (
    setup_style, save_fig, FULLWIDTH,
    REPRESENTATIVE_PROTOCOLS, PROTOCOL_DISPLAY, PROTOCOL_COLORS,
    ATTACK_COLORS, ATTACK_DISPLAY,
)
from data_loader import load_backrun_sandwich_data, parse_histogram


def plot_distance_histogram():
    setup_style()

    df = load_backrun_sandwich_data()
    # In some places protocol might not be in REPRESENTATIVE_PROTOCOLS, or missing
    df_br = df[df["attack_type"] == "backrun"].copy()

    # Only include protocols that actually have histogram data
    protocols_with_data = []
    for proto in REPRESENTATIVE_PROTOCOLS:
        df_p = df_br[df_br["protocol"] == proto]
        if "asr_histogram" in df_p.columns and df_p["asr_histogram"].notna().any():
            protocols_with_data.append(proto)

    n = len(protocols_with_data)
    if n == 0:
        print("⚠️  Figure 5: No histogram data available for any protocol.")
        return

    fig, axes = plt.subplots(1, n, figsize=(FULLWIDTH * 0.55 * n, FULLWIDTH * 0.45))
    if n == 1:
        axes = [axes]

    attacks = ["fissure", "speculative", "sluggish"]

    for ax_idx, proto in enumerate(protocols_with_data):
        ax = axes[ax_idx]
        df_p = df_br[df_br["protocol"] == proto]

        for attack in attacks:
            df_atk = df_p[df_p["attack_mode"] == attack]

            all_hists = []
            for _, row in df_atk.iterrows():
                h = parse_histogram(row.get("asr_histogram"))
                if h is not None:
                    all_hists.append(h)

            if not all_hists:
                continue

            # Flatten all actual distance values across reps
            distances = np.concatenate(all_hists)
            if len(distances) == 0:
                continue

            # Compute Cumulative ASR
            # 1. We need the overall base ASR for this specific experiment/rep to scale the CDF properly.
            # However, since we aggregated all reps into `distances`, the easiest mathematical equivalent
            # is to treat the total number of victims as the denominator. 
            # ASR = (total successful backruns) / (total victims)
            # The length of `distances` IS the total number of successful backruns across all reps.
            
            # Since we only have the successful `distances`, we need to recover the true denominator 
            # (total victims). We can approximate the average ASR from the dataframe:
            mean_asr = df_atk["asr"].mean() / 100.0  # e.g., 0.45 for 45%
            
            # Sort distances to build the CDF
            sorted_gaps = np.sort(distances)
            
            # For each unique gap, what cumulative fraction of our successes are <= this gap?
            x_vals = np.unique(sorted_gaps)
            # Find the cumulative count of elements <= each unique x
            counts = np.searchsorted(sorted_gaps, x_vals, side='right')
            
            # The internal CDF (from 0.0 to 1.0) of *just the successful conditional distribution*
            success_cdf = counts / len(sorted_gaps)
            
            # The True Cumulative ASR is the internal CDF scaled by the overall ASR
            cumulative_asr = success_cdf * mean_asr * 100.0  # Scale back to percentage

            # Optimization for readability: cap the x-axis plotting so we don't draw 600-block flatlines
            # We'll plot up to the 99th percentile of gaps to keep the charts focused
            max_x = np.percentile(sorted_gaps, 99)
            if max_x < 50:
                max_x = 50 # ensure at least 50 is shown if the tail is short (e.g. Bullshark)
            
            valid_idx = x_vals <= max_x
            plot_x = x_vals[valid_idx]
            plot_y = cumulative_asr[valid_idx]

            # Prepend (0, 0) if the lowest gap is > 0, just to anchor the line
            if len(plot_x) > 0 and plot_x[0] > 0:
                plot_x = np.insert(plot_x, 0, 0)
                plot_y = np.insert(plot_y, 0, 0)

            ax.plot(
                plot_x, plot_y,
                color=ATTACK_COLORS[attack],
                label=ATTACK_DISPLAY[attack],
                linewidth=2.5,
                alpha=0.8,
                linestyle='-' if attack == 'fissure' else ('--' if attack == 'speculative' else '-.')
            )

        ax.set_title(PROTOCOL_DISPLAY[proto], fontweight="bold")
        ax.set_xlabel("Allowed Gap (blocks)")
        ax.set_ylabel("Cumulative ASR (%)")
        
        # Add a grid for readability
        ax.grid(True, linestyle="--", linewidth=0.5, alpha=0.5)
        ax.legend(fontsize=10, loc="lower right")

    fig.suptitle("Cumulative Backrun ASR by Allowed Gap",
                 fontsize=18, fontweight="bold", y=1.05)

    save_fig(fig, "fig5_distance_histogram")
    print("✅ Figure 5: Distance histogram generated.")


if __name__ == "__main__":
    plot_distance_histogram()
