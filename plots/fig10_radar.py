"""
Figure 10: Radar Chart — Protocol Family Profiles
====================================================
At-a-glance "security profile" of each protocol family.
"""

import matplotlib.pyplot as plt
import numpy as np

from config import (
    setup_style, save_fig, FULLWIDTH,
    PROTOCOL_ORDER, PROTOCOL_DISPLAY, PROTOCOL_COLORS, FAMILY_COLORS,
    FAMILIES,
)
from data_loader import load_frontrunning_data, load_backrun_sandwich_data, compute_summary


def _normalize_resilience(asr):
    """Convert ASR to a 0-1 resilience score. 50% = 1.0 (fully resilient)."""
    if asr <= 50:
        return 1.0
    elif asr >= 100:
        return 0.0
    else:
        return max(0, 1.0 - (asr - 50) / 50)


def plot_radar():
    setup_style()

    df = load_frontrunning_data()

    offense_map = {
        "fissure":     "offense_fissure",
        "speculative": "offense_speculative",
        "sluggish":    "offense_sluggish",
    }

    # Axes for the radar
    categories = [
        "Fissure\nResilience",
        "Speculative\nResilience",
        "Sluggish\nResilience",
        "Scale\nResilience",
        "Latency\nResilience",
    ]

    # Compute per-family resilience scores
    family_scores = {}

    for family, protocols in FAMILIES.items():
        scores = []

        # Fissure, Speculative, Sluggish resilience
        for attack, exp in offense_map.items():
            asrs = []
            for proto in protocols:
                sub = df[(df["protocol"] == proto) & (df["experiment"] == exp)]
                if len(sub) > 0:
                    asrs.append(sub["asr"].mean())
            if asrs:
                scores.append(_normalize_resilience(np.mean(asrs)))
            else:
                scores.append(0.5)  # Unknown

        # Scale resilience: compare 13-node vs 100-node ASR
        scale_asrs_small, scale_asrs_large = [], []
        for proto in protocols:
            df_s = df[(df["protocol"] == proto) & (df["experiment"] == "scaling")]
            if len(df_s) > 0:
                s13 = df_s[df_s["NUM_NODES"] == 13]["asr"]
                s100 = df_s[df_s["NUM_NODES"] == 100]["asr"]
                if len(s13) > 0:
                    scale_asrs_small.extend(s13.values)
                if len(s100) > 0:
                    scale_asrs_large.extend(s100.values)

        if scale_asrs_large:
            scores.append(_normalize_resilience(np.mean(scale_asrs_large)))
        elif scale_asrs_small:
            scores.append(_normalize_resilience(np.mean(scale_asrs_small)))
        else:
            scores.append(0.5)

        # Latency resilience: ASR under high latency
        lat_asrs = []
        for proto in protocols:
            df_l = df[(df["protocol"] == proto) & (df["experiment"] == "env_latency")]
            if len(df_l) > 0:
                lat_asrs.extend(df_l["asr"].values)
        if lat_asrs:
            scores.append(_normalize_resilience(np.mean(lat_asrs)))
        else:
            scores.append(0.5)

        family_scores[family] = scores

    # ── Plot Radar ──
    N = len(categories)
    angles = np.linspace(0, 2 * np.pi, N, endpoint=False).tolist()
    angles += angles[:1]  # Close the polygon

    fig, ax = plt.subplots(figsize=(FULLWIDTH * 0.7, FULLWIDTH * 0.7),
                           subplot_kw=dict(polar=True))

    ax.set_theta_offset(np.pi / 2)
    ax.set_theta_direction(-1)
    ax.set_rlabel_position(0)

    # Category labels
    ax.set_xticks(angles[:-1])
    ax.set_xticklabels(categories, fontsize=7)

    # Radial labels
    ax.set_yticks([0.25, 0.5, 0.75, 1.0])
    ax.set_yticklabels(["25%", "50%", "75%", "100%"], fontsize=6, color="#666")
    ax.set_ylim(0, 1.05)

    for family, scores in family_scores.items():
        values = scores + scores[:1]  # Close polygon
        color = FAMILY_COLORS.get(family, "#666")
        ax.plot(angles, values, "o-", linewidth=1.5, markersize=4,
                color=color, label=family)
        ax.fill(angles, values, alpha=0.1, color=color)

    ax.legend(
        loc="lower right", bbox_to_anchor=(1.35, -0.05),
        fontsize=7, frameon=True,
    )
    ax.set_title("Protocol Family Security Profiles",
                 fontsize=18, fontweight="bold", y=1.08)

    save_fig(fig, "fig10_radar")
    print("✅ Figure 10: Radar chart generated.")


if __name__ == "__main__":
    plot_radar()
