#!/usr/bin/env python3
"""
b3_tuning_analysis.py — Aggregate HPA stabilization window tuning study results.

Reads tuning_result.csv from each sub-experiment directory and builds
a consolidated results table.

Usage:
    python3 analysis/experiment-b3/b3_tuning_analysis.py \
        --results-dir results/processed/websocket/experiment-b3-tuning

    # With multi-run (3 runs per config):
    python3 analysis/experiment-b3/b3_tuning_analysis.py \
        --results-dir results/processed/websocket/experiment-b3-tuning \
        --multi-run
"""

from __future__ import annotations

import argparse
import os
import sys

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from metrics_utils import compute_stats


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Aggregate B3 tuning study results")
    p.add_argument(
        "--results-dir",
        required=True,
        help="Path to experiment-b3-tuning processed results directory",
    )
    p.add_argument(
        "--multi-run",
        action="store_true",
        help="If set, expect run_1/run_2/run_3 subdirs within each config dir",
    )
    p.add_argument(
        "--out",
        default=None,
        help="Output CSV path (default: <results-dir>/tuning_results.csv)",
    )
    return p.parse_args()


def collect_single_run(results_dir: str) -> pd.DataFrame:
    """Collect tuning_result.csv from each window*_gap* subdir (single-run mode)."""
    rows = []
    for entry in sorted(os.listdir(results_dir)):
        if not entry.startswith("window"):
            continue
        subdir = os.path.join(results_dir, entry)
        if not os.path.isdir(subdir):
            continue
        csv_path = os.path.join(subdir, "tuning_result.csv")
        if not os.path.exists(csv_path):
            print(f"  WARNING: {csv_path} not found, skipping.")
            continue
        df = pd.read_csv(csv_path)
        df["config"] = entry
        rows.append(df)
        plot_individual_run(subdir)

    if not rows:
        return pd.DataFrame()
    return pd.concat(rows, ignore_index=True)


def collect_multi_run(results_dir: str) -> pd.DataFrame:
    """Collect tuning_result.csv from each window*_gap*/run_* subdir."""
    rows = []
    for entry in sorted(os.listdir(results_dir)):
        if not entry.startswith("window"):
            continue
        config_dir = os.path.join(results_dir, entry)
        if not os.path.isdir(config_dir):
            continue

        # Look for run_* subdirs
        run_dirs = sorted(
            [d for d in os.listdir(config_dir) if d.startswith("run_")]
        )
        if not run_dirs:
            # Fall back to single-run mode for this config
            csv_path = os.path.join(config_dir, "tuning_result.csv")
            if os.path.exists(csv_path):
                df = pd.read_csv(csv_path)
                df["config"] = entry
                df["run"] = "run_1"
                rows.append(df)
                plot_individual_run(config_dir)
            continue

        for run_name in run_dirs:
            csv_path = os.path.join(config_dir, run_name, "tuning_result.csv")
            if not os.path.exists(csv_path):
                print(f"  WARNING: {csv_path} not found, skipping.")
                continue
            df = pd.read_csv(csv_path)
            df["config"] = entry
            df["run"] = run_name
            rows.append(df)
            plot_individual_run(os.path.join(config_dir, run_name))

    if not rows:
        return pd.DataFrame()
    return pd.concat(rows, ignore_index=True)


def aggregate_multi_run(combined: pd.DataFrame) -> pd.DataFrame:
    """Aggregate multi-run results per configuration."""
    agg_rows = []
    for config, group in combined.groupby("config"):
        row = {
            "config": config,
            "stabilization_window_s": group["stabilization_window_s"].iloc[0],
            "gap_duration_s": group["gap_duration_s"].iloc[0],
            "gap_relation": group["gap_relation"].iloc[0],
            "n_runs": len(group),
        }

        for col in ["connections_before", "connections_after", "pct_lost"]:
            if col in group.columns:
                vals = group[col].dropna().tolist()
                stats = compute_stats(vals)
                row[f"{col}_mean"] = round(stats["mean"], 1)
                row[f"{col}_std"] = round(stats["std"], 1)

        # survived: majority vote
        if "connections_survived" in group.columns:
            survived_count = group["connections_survived"].sum()
            row["survived_ratio"] = f"{survived_count}/{len(group)}"
            row["connections_survived"] = survived_count == len(group)

        agg_rows.append(row)

    return pd.DataFrame(agg_rows)


def plot_individual_run(run_dir: str):
    """Generate a combined connection/CPU/replica plot for a single run."""
    conn_path = os.path.join(run_dir, "connections.csv")
    cpu_path = os.path.join(run_dir, "cpu.csv")
    rep_path = os.path.join(run_dir, "replicas.csv")
    if not (os.path.exists(conn_path) and os.path.exists(cpu_path) and os.path.exists(rep_path)):
        return
    
    conn_df = pd.read_csv(conn_path)
    cpu_df = pd.read_csv(cpu_path)
    rep_df = pd.read_csv(rep_path)
    
    if conn_df.empty or cpu_df.empty or rep_df.empty:
        return
        
    t0 = min(conn_df["timestamp"].min(), cpu_df["timestamp"].min(), rep_df["timestamp"].min())
    conn_df["time_sec"] = conn_df["timestamp"] - t0
    cpu_df["time_sec"] = cpu_df["timestamp"] - t0
    rep_df["time_sec"] = rep_df["timestamp"] - t0
    
    fig, ax1 = plt.subplots(figsize=(10, 4))
    
    color_conn = "#1E88E5"
    ax1.set_xlabel("Time (s)")
    ax1.set_ylabel("Active Connections", color=color_conn)
    ax1.plot(conn_df["time_sec"], conn_df["active_connections"], color=color_conn, linewidth=1.5, label="Connections")
    ax1.tick_params(axis="y", labelcolor=color_conn)
    
    ax2 = ax1.twinx()
    color_cpu = "#E53935"
    ax2.set_ylabel("CPU (m)", color=color_cpu)
    ax2.plot(cpu_df["time_sec"], cpu_df["cpu_millicores"], color=color_cpu, linewidth=1.0, alpha=0.5, label="CPU")
    ax2.tick_params(axis="y", labelcolor=color_cpu)
    
    ax3 = ax1.twinx()
    ax3.spines["right"].set_position(("outward", 60))
    color_rep = "#43A047"
    ax3.set_ylabel("Replicas", color=color_rep)
    ax3.step(rep_df["time_sec"], rep_df["replicas"], where="post", color=color_rep, linewidth=2.0, alpha=0.8, label="Replicas")
    ax3.tick_params(axis="y", labelcolor=color_rep)
    ax3.set_ylim(bottom=0)
    
    fig.tight_layout()
    fig.savefig(os.path.join(run_dir, "combined.png"), dpi=120)
    plt.close(fig)


def plot_aggregated_results(combined: pd.DataFrame, out_dir: str):
    """Generate aggregated bar plot for connection loss across window sizes."""
    if "pct_lost" not in combined.columns:
        return
        
    fig, ax = plt.subplots(figsize=(8, 5))
    
    # Calculate means and stds for each group
    grouped = combined.groupby(["stabilization_window_s", "gap_relation"])["pct_lost"].agg(["mean", "std"]).reset_index()
    
    windows = sorted(grouped["stabilization_window_s"].unique())
    x = np.arange(len(windows))
    width = 0.35
    
    below_means = []
    below_stds = []
    above_means = []
    above_stds = []
    
    for w in windows:
        b_val = grouped[(grouped["stabilization_window_s"] == w) & (grouped["gap_relation"] == "below")]
        a_val = grouped[(grouped["stabilization_window_s"] == w) & (grouped["gap_relation"] == "above")]
        
        below_means.append(b_val["mean"].values[0] if not b_val.empty else 0)
        below_stds.append(b_val["std"].values[0] if not b_val.empty and pd.notna(b_val["std"].values[0]) else 0)
        
        above_means.append(a_val["mean"].values[0] if not a_val.empty else 0)
        above_stds.append(a_val["std"].values[0] if not a_val.empty and pd.notna(a_val["std"].values[0]) else 0)
        
    rects1 = ax.bar(x - width/2, below_means, width, yerr=below_stds, label='below', color="#4CAF50", capsize=5)
    rects2 = ax.bar(x + width/2, above_means, width, yerr=above_stds, label='above', color="#F44336", capsize=5)
    
    ax.set_title("Connection Loss vs. HPA Stabilization Window")
    ax.set_xlabel("Stabilization Window (seconds)")
    ax.set_ylabel("Connection Loss (%)")
    ax.set_xticks(x)
    ax.set_xticklabels([f"{w}s" for w in windows])
    ax.legend(title="Gap Relation (to Window)")
    
    fig.tight_layout()
    out_path = os.path.join(out_dir, "tuning_results_loss.png")
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    print(f"  Aggregated plot saved → {out_path}")


def main() -> None:
    args = parse_args()

    if not os.path.isdir(args.results_dir):
        print(f"ERROR: '{args.results_dir}' does not exist.")
        sys.exit(1)

    if args.multi_run:
        combined = collect_multi_run(args.results_dir)
    else:
        combined = collect_single_run(args.results_dir)

    if combined.empty:
        print("ERROR: No tuning results found.")
        sys.exit(1)

    print(f"\n=== B3 Tuning Study Results ({len(combined)} total runs) ===\n")

    # If multi-run, aggregate
    if args.multi_run and "run" in combined.columns:
        result = aggregate_multi_run(combined)
        # Also save raw combined data
        raw_path = os.path.join(args.results_dir, "tuning_all_runs.csv")
        combined.to_csv(raw_path, index=False)
        print(f"  All runs saved → {raw_path}")
    else:
        result = combined

    out_path = args.out or os.path.join(args.results_dir, "tuning_results.csv")
    result.to_csv(out_path, index=False)
    print(f"  Results table saved → {out_path}")
    
    # Generate aggregated plot
    plot_aggregated_results(combined, args.results_dir)

    # Print table
    print(f"\n{'='*90}")
    print(f"  HPA Stabilization Window Tuning Study")
    print(f"{'='*90}")
    for _, row in result.iterrows():
        w = row.get("stabilization_window_s", "?")
        g = row.get("gap_duration_s", "?")
        rel = row.get("gap_relation", "?")
        surv = row.get("connections_survived", "?")
        if "pct_lost_mean" in row:
            loss = f"{row['pct_lost_mean']:.1f}% ± {row['pct_lost_std']:.1f}%"
        elif "pct_lost" in row:
            loss = f"{row['pct_lost']:.1f}%"
        else:
            loss = "?"
        n = row.get("n_runs", 1)
        print(f"  Window={w}s  Gap={g}s ({rel:>5})  Survived={surv}  Loss={loss}  N={n}")
    print()


if __name__ == "__main__":
    main()
