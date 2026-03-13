#!/usr/bin/env python3
"""
Generate All Figures
=====================
Master script to generate all publication-quality figures.

Usage:
    cd plots/
    python generate_all.py          # Generate all figures
    python generate_all.py --fig 1  # Generate only Figure 1
    python generate_all.py --tier 1 # Generate only Tier 1 figures
"""

import argparse
import sys
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Generate publication figures")
    parser.add_argument("--fig", type=str, help="Generate specific figure (e.g., '1', '3a')")
    parser.add_argument("--tier", type=int, choices=[1, 2, 3],
                        help="Generate all figures in a tier")
    args = parser.parse_args()

    # All figure generators
    figures = {
        # Tier 1 — Core Results
        "1":  ("fig1_heatmap",           "plot_heatmap",             "Cross-Protocol ASR Heatmap"),
        "2":  ("fig2_scaling",           "plot_scaling",             "ASR vs. Network Scale"),
        "3a": ("fig3_attack_comparison", "plot_fig3a_frontrunning",  "Frontrunning ASR Comparison"),
        "3c": ("fig3_attack_comparison", "plot_fig3c_sandwich",      "Sandwich Success Rate"),
        "4":  ("fig4_offense",           "plot_offense_sensitivity", "Offense Parameter Sensitivity"),
        "5":  ("fig5_distance",          "plot_distance_histogram",  "Backrun Distance Histogram"),

        # Tier 2 — Deep Insights
        "6":  ("fig6_defense",           "plot_defense_sensitivity",  "Defense Parameter Sensitivity"),
        "7":  ("fig7_latency",           "plot_latency_sensitivity",  "Latency Sensitivity"),
        "8":  ("fig8_protocol_specific", "plot_protocol_specific",    "Protocol-Specific Parameters"),

        # Tier 3 — Supplementary
        "9":  ("fig9_boxplots",          "plot_boxplots",             "ASR Distribution Box Plots"),
        "10": ("fig10_radar",            "plot_radar",                "Protocol Family Radar"),
    }

    tiers = {
        1: ["1", "2", "3a", "3c", "4", "5"],
        2: ["6", "7", "8"],
        3: ["9", "10"],
    }

    # Determine which figures to generate
    if args.fig:
        targets = [args.fig]
    elif args.tier:
        targets = tiers[args.tier]
    else:
        targets = list(figures.keys())

    print("=" * 60)
    print("  MEV Research — Publication Figure Generator")
    print("=" * 60)
    print(f"  Generating {len(targets)} figure(s)...")
    print()

    success, failed = 0, 0
    total_start = time.time()

    for fig_id in targets:
        if fig_id not in figures:
            print(f"  ⚠️  Unknown figure: {fig_id}")
            failed += 1
            continue

        module_name, func_name, title = figures[fig_id]

        print(f"  📊 Fig {fig_id}: {title}")
        start = time.time()

        try:
            module = __import__(module_name)
            func = getattr(module, func_name)
            func()
            elapsed = time.time() - start
            print(f"     Done in {elapsed:.1f}s\n")
            success += 1
        except Exception as e:
            elapsed = time.time() - start
            print(f"     ❌ FAILED ({elapsed:.1f}s): {e}\n")
            failed += 1

    total_elapsed = time.time() - total_start
    print("=" * 60)
    print(f"  ✅ {success} succeeded, ❌ {failed} failed")
    print(f"  Total time: {total_elapsed:.1f}s")
    print(f"  Output: {Path('output').resolve()}")
    print("=" * 60)


if __name__ == "__main__":
    main()
