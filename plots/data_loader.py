"""
Unified Data Loader
====================
Loads and preprocesses all experimental CSVs into clean DataFrames.
"""

import ast
import pandas as pd
import numpy as np
from pathlib import Path

from config import (
    EXPERIMENT_CSV, AUTOBAHN_CSV, NEW_CSV,
    PROTOCOL_DISPLAY, ATTACK_DISPLAY, FAMILY_OF, PROTOCOL_ORDER,
)


def load_frontrunning_data():
    """
    Load frontrunning experiment data from experiment_results.csv
    and autobahn_results.csv. Combines both into a single DataFrame.

    Returns
    -------
    pd.DataFrame with columns:
        protocol, experiment, attack_mode, rep, asr, duration,
        exit_code, + all parameter columns
    """
    dfs = []

    if EXPERIMENT_CSV.exists():
        df = pd.read_csv(EXPERIMENT_CSV)
        dfs.append(df)

    if AUTOBAHN_CSV.exists():
        df_aut = pd.read_csv(AUTOBAHN_CSV)
        # Align columns — autobahn_results may have extra columns
        dfs.append(df_aut)

    if not dfs:
        raise FileNotFoundError("No frontrunning CSV files found.")

    df = pd.concat(dfs, ignore_index=True, sort=False)

    # Clean up
    df["protocol"] = df["protocol"].str.strip().str.lower()
    df["attack_mode"] = df["attack_mode"].str.strip().str.lower()
    df["experiment"] = df["experiment"].str.strip().str.lower()
    df["asr"] = pd.to_numeric(df["asr"], errors="coerce")
    df = df.dropna(subset=["asr"])

    # Add display names
    df["protocol_name"] = df["protocol"].map(PROTOCOL_DISPLAY).fillna(df["protocol"])
    df["attack_name"] = df["attack_mode"].map(ATTACK_DISPLAY).fillna(df["attack_mode"])
    df["family"] = df["protocol"].map(FAMILY_OF).fillna("Unknown")

    return df


def load_backrun_sandwich_data():
    """
    Load backrunning and sandwich data from new.csv.

    Returns
    -------
    pd.DataFrame with columns:
        protocol, experiment, attack_mode, attack_type, rep, asr,
        asr_l1, asr_l2, asr_histogram, duration, + parameters
    """
    if not NEW_CSV.exists():
        raise FileNotFoundError(f"new.csv not found at {NEW_CSV}")

    df = pd.read_csv(NEW_CSV)
    df["protocol"] = df["protocol"].str.strip().str.lower()
    df["attack_mode"] = df["attack_mode"].str.strip().str.lower()
    df["attack_type"] = df["attack_type"].str.strip().str.lower()
    df["asr"] = pd.to_numeric(df["asr"], errors="coerce")
    df = df.dropna(subset=["asr"])

    # Add display names
    df["protocol_name"] = df["protocol"].map(PROTOCOL_DISPLAY).fillna(df["protocol"])
    df["attack_name"] = df["attack_mode"].map(ATTACK_DISPLAY).fillna(df["attack_mode"])
    df["family"] = df["protocol"].map(FAMILY_OF).fillna("Unknown")

    return df


def get_scaling_data(df_front):
    """Extract scaling experiments (ASR vs NUM_NODES)."""
    mask = df_front["experiment"].str.contains("scaling", na=False)
    df = df_front[mask].copy()
    df["NUM_NODES"] = pd.to_numeric(df["NUM_NODES"], errors="coerce")
    return df.dropna(subset=["NUM_NODES"])


def get_offense_data(df_front):
    """Extract offense parameter sweep experiments."""
    mask = df_front["experiment"].str.startswith("offense_", na=False)
    return df_front[mask].copy()


def get_defense_data(df_front):
    """Extract defense parameter sweep experiments."""
    mask = df_front["experiment"].str.startswith("defense_", na=False)
    return df_front[mask].copy()


def get_env_latency_data(df_front):
    """Extract environment/latency sensitivity experiments."""
    mask = df_front["experiment"] == "env_latency"
    df = df_front[mask].copy()

    # Latency is stored as combined string in LATENCY_JITTER, e.g. "50ms 10ms"
    # Parse out the first number (latency) from the string
    if "LATENCY_JITTER" in df.columns:
        def _parse_latency(val):
            if pd.isna(val):
                return np.nan
            s = str(val).strip()
            # Extract first number from strings like "50ms 10ms"
            parts = s.replace("ms", "").split()
            try:
                return float(parts[0])
            except (ValueError, IndexError):
                return np.nan

        df["LATENCY_MS"] = df["LATENCY_JITTER"].apply(_parse_latency)
    else:
        df["LATENCY_MS"] = pd.to_numeric(df.get("LATENCY_MS"), errors="coerce")

    return df.dropna(subset=["LATENCY_MS"])


def get_protocol_specific_data(df_front):
    """Extract protocol-specific parameter experiments."""
    specific_exps = [
        "aleph_lookahead", "aleph_sync_speed", "aleph_hash_randomization",
        "mahimahi_leaders", "mahimahi_wave", "mahimahi_strategy",
        "mysticeti_strategy",
        "autobahn_k", "autobahn_fast_path",
    ]
    mask = df_front["experiment"].isin(specific_exps)
    return df_front[mask].copy()


def get_simple_frontrunning(df_front):
    """
    Get the 'simple' / 'offense_*' experiments with default params (13 nodes).
    These are the base-case frontrunning ASR per protocol per attack.
    """
    # offense_fissure, offense_speculative, offense_sluggish with default params
    mask = (
        df_front["experiment"].str.startswith("offense_", na=False)
        & (df_front["NUM_NODES"].isna() | (df_front["NUM_NODES"] == 13))
    )
    return df_front[mask].copy()


def parse_histogram(hist_str):
    """Parse the histogram string from CSV into a numpy array."""
    if pd.isna(hist_str) or hist_str == "":
        return None
    try:
        # The core engines report raw index differences (att_pos - vic_pos).
        # We subtract 1 to match the user definition of 'blocks in between' (offset 0 for adjacent).
        arr = np.array(ast.literal_eval(hist_str))
        # Ensure gap never goes below 0 
        arr = np.maximum(0, arr - 1)
        return arr
    except (ValueError, SyntaxError):
        return None


def compute_summary(df, group_cols):
    """
    Compute mean, std, min, max ASR grouped by given columns.

    Returns
    -------
    pd.DataFrame with columns: [group_cols] + mean_asr, std_asr, min_asr, max_asr, n
    """
    agg = df.groupby(group_cols)["asr"].agg(
        mean_asr="mean",
        std_asr="std",
        min_asr="min",
        max_asr="max",
        n="count",
    ).reset_index()
    agg["std_asr"] = agg["std_asr"].fillna(0)
    return agg


# ─── Quick test ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("Loading frontrunning data...")
    df_f = load_frontrunning_data()
    print(f"  → {len(df_f)} rows, protocols: {sorted(df_f['protocol'].unique())}")
    print(f"  → experiments: {sorted(df_f['experiment'].unique())}")

    print("\nLoading backrun/sandwich data...")
    df_b = load_backrun_sandwich_data()
    print(f"  → {len(df_b)} rows, protocols: {sorted(df_b['protocol'].unique())}")
    print(f"  → attack types: {sorted(df_b['attack_type'].unique())}")

    print("\nScaling data:")
    df_s = get_scaling_data(df_f)
    print(f"  → {len(df_s)} rows, nodes: {sorted(df_s['NUM_NODES'].unique())}")

    print("\n✅ All data loaded successfully.")
