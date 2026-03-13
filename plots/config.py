"""
Publication-Quality Plot Configuration
=======================================
Central style system for all MEV research figures.
Designed for SIGMOD/VLDB camera-ready formatting.
"""

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
from pathlib import Path

# ─── Output ──────────────────────────────────────────────────────────────────
OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)
DPI = 300
FIG_FORMAT = "pdf"  # PDF for LaTeX, also saves PNG

# ─── Data Paths ──────────────────────────────────────────────────────────────
DATA_DIR = Path(__file__).parent.parent
EXPERIMENT_CSV = DATA_DIR / "experiment_results.csv"
AUTOBAHN_CSV = DATA_DIR / "autobahn_results.csv"
NEW_CSV = DATA_DIR / "new.csv"

# ─── Protocol Taxonomy ──────────────────────────────────────────────────────
FAMILIES = {
    "Narwhal-Tusk": ["bullshark", "mevsui", "narwhal"],
    "Mahi Mahi":    ["mahimahi", "mysticeti"],
    "AlephBFT":     ["alephbft"],
    "Autobahn":     ["autobahn"],
}

FAMILY_OF = {}
for family, protocols in FAMILIES.items():
    for p in protocols:
        FAMILY_OF[p] = family

# Display names (pretty-printed for figures)
PROTOCOL_DISPLAY = {
    "bullshark":  "Bullshark",
    "mevsui":     "MEV-SUI",
    "narwhal":    "Narwhal",
    "mahimahi":   "Mahi-Mahi",
    "mysticeti":  "Mysticeti",
    "alephbft":   "AlephBFT",
    "autobahn":   "Autobahn",
}

FAMILY_DISPLAY = {
    "Narwhal-Tusk": "Narwhal-Tusk",
    "Mahi Mahi":    "Mahi Mahi",
    "AlephBFT":     "AlephBFT",
    "Autobahn":     "Autobahn",
}

ATTACK_DISPLAY = {
    "fissure":     "Fissure",
    "speculative": "Speculative",
    "sluggish":    "Sluggish",
}

TYPE_DISPLAY = {
    "backrun":   "Backrun",
    "sandwich":  "Sandwich",
    "frontrun":  "Frontrun",
}

# ─── Color Palette ───────────────────────────────────────────────────────────
# Curated palette — colorblind-safe, print-friendly
FAMILY_COLORS = {
    "Narwhal-Tusk": "#E63946",   # Warm red
    "Mahi Mahi":    "#457B9D",   # Steel blue
    "AlephBFT":     "#2A9D8F",   # Teal
    "Autobahn":     "#E9C46A",   # Gold
}

PROTOCOL_COLORS = {
    "bullshark":  "#E63946",
    "mevsui":     "#F4845F",
    "narwhal":    "#C1121F",
    "mahimahi":   "#457B9D",
    "mysticeti":  "#1D3557",
    "alephbft":   "#2A9D8F",
    "autobahn":   "#E9C46A",
}

ATTACK_COLORS = {
    "fissure":     "#264653",   # Dark teal
    "speculative": "#E76F51",   # Burnt orange
    "sluggish":    "#2A9D8F",   # Teal green
}

TYPE_COLORS = {
    "frontrun":  "#264653",
    "backrun":   "#E76F51",
    "sandwich":  "#E9C46A",
}

# Hatching patterns for B&W printing compatibility
ATTACK_HATCHES = {
    "fissure":     "",
    "speculative": "//",
    "sluggish":    "xx",
}

# ─── Protocol ordering for consistent axis ordering ─────────────────────────
PROTOCOL_ORDER = [
    "bullshark", "mevsui", "narwhal",   # Narwhal-Tusk family
    "mahimahi", "mysticeti",             # Mahi Mahi family
    "alephbft",                          # AlephBFT family
    "autobahn",                          # Autobahn family
]

# Representative protocols for backrun/sandwich (one per family)
REPRESENTATIVE_PROTOCOLS = ["bullshark", "mysticeti", "alephbft", "autobahn"]

# ─── Typography & Global Style ──────────────────────────────────────────────

def setup_style():
    """Apply publication-quality matplotlib style globally."""
    plt.style.use("seaborn-v0_8-whitegrid")

    params = {
        # Font — LARGE for readability
        "font.family":       "serif",
        "font.serif":        ["Times New Roman", "DejaVu Serif", "serif"],
        "font.size":         14,
        "axes.titlesize":    16,
        "axes.labelsize":    14,
        "xtick.labelsize":   12,
        "ytick.labelsize":   12,
        "legend.fontsize":   11,
        "legend.title_fontsize": 13,

        # Lines & markers — THICK for visibility
        "lines.linewidth":   2.5,
        "lines.markersize":  8,

        # Axes
        "axes.linewidth":    1.2,
        "axes.grid":         True,
        "axes.edgecolor":    "#333333",
        "grid.alpha":        0.25,
        "grid.linewidth":    0.6,

        # Ticks
        "xtick.major.width": 1.0,
        "ytick.major.width": 1.0,
        "xtick.direction":   "out",
        "ytick.direction":   "out",
        "xtick.major.pad":   6,
        "ytick.major.pad":   6,

        # Figure
        "figure.dpi":        DPI,
        "savefig.dpi":       DPI,
        "savefig.bbox":      "tight",
        "savefig.pad_inches": 0.15,

        # Legend
        "legend.framealpha":  0.9,
        "legend.edgecolor":   "#cccccc",

        # Layout
        "figure.constrained_layout.use": True,
    }
    mpl.rcParams.update(params)


def save_fig(fig, name, formats=None):
    """Save figure in multiple formats."""
    if formats is None:
        formats = [FIG_FORMAT, "png"]
    for fmt in formats:
        path = OUTPUT_DIR / f"{name}.{fmt}"
        fig.savefig(path, format=fmt)
        print(f"  ✓ Saved: {path}")
    plt.close(fig)


# ─── Helpers ─────────────────────────────────────────────────────────────────

def add_family_spans(ax, protocols, y_offset=-0.18):
    """Add family group labels below x-axis tick labels."""
    family_spans = {}
    for i, p in enumerate(protocols):
        fam = FAMILY_OF.get(p, "Unknown")
        if fam not in family_spans:
            family_spans[fam] = [i, i]
        else:
            family_spans[fam][1] = i

    for fam, (start, end) in family_spans.items():
        mid = (start + end) / 2
        ax.annotate(
            fam, xy=(mid, y_offset), xycoords=("data", "axes fraction"),
            ha="center", va="top", fontsize=11, fontstyle="italic",
            color="#555555",
        )
        if start != end:
            ax.annotate(
                "", xy=(start - 0.3, y_offset + 0.02),
                xytext=(end + 0.3, y_offset + 0.02),
                xycoords=("data", "axes fraction"),
                arrowprops=dict(arrowstyle="-", color="#aaaaaa", lw=0.8),
            )


def asr_color(val):
    """Map ASR value to a color for heatmaps."""
    if val <= 55:
        return "#2A9D8F"  # Green/teal — resilient
    elif val <= 75:
        return "#E9C46A"  # Gold — moderate
    else:
        return "#E63946"  # Red — vulnerable


# ─── Column-width figures for two-column papers ─────────────────────────────
COLWIDTH = 5.0     # inches — single column (generous)
FULLWIDTH = 10.0   # inches — full page width
ASPECT = 0.7       # height = width * aspect

