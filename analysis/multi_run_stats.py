#!/usr/bin/env python3
"""
multi_run_stats.py — Aggregate summary.csv files across N replicate runs.

Usage:
    python3 analysis/multi_run_stats.py \
        --experiment experiment-c-stateful \
        --multi-proc-dir results/processed/websocket/experiment-c-stateful/multi

For each metric column found in summary.csv, computes mean ± std, min, max
across all run_* subdirectories and writes aggregate_stats.csv.

Also prints a human-readable table to stdout.
"""

from __future__ import annotations

import argparse
import os
import sys

import numpy as np
import pandas as pd

# Allow importing metrics_utils from parent dir when run directly
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from metrics_utils import compute_stats


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Aggregate multi-run summary CSVs")
    p.add_argument("--experiment", required=True, help="Experiment name (for display)")
    p.add_argument(
        "--multi-proc-dir",
        required=True,
        help="Path to <experiment>/multi/ containing run_1, run_2, … subdirs",
    )
    p.add_argument(
        "--out",
        default=None,
        help="Output CSV path (default: <multi-proc-dir>/aggregate_stats.csv)",
    )
    return p.parse_args()


def collect_summaries(multi_proc_dir: str) -> pd.DataFrame:
    """Read summary.csv from every run_* subdir and stack them."""
    rows = []
    for entry in sorted(os.listdir(multi_proc_dir)):
        if not entry.startswith("run_"):
            continue
        run_dir = os.path.join(multi_proc_dir, entry)
        summary_path = os.path.join(run_dir, "summary.csv")
        if not os.path.exists(summary_path):
            print(f"  WARNING: {summary_path} not found, skipping.")
            continue
        df = pd.read_csv(summary_path)
        df["run"] = entry
        rows.append(df)

    if not rows:
        print("ERROR: No summary.csv files found under", multi_proc_dir)
        sys.exit(1)

    return pd.concat(rows, ignore_index=True)


def aggregate(combined: pd.DataFrame) -> pd.DataFrame:
    """For every metric column, compute mean/std/min/max/n."""
    skip_cols = {"run", "metric", "value"}  # pivot-style summary has metric+value cols

    # Detect format: wide (one column per metric) or long (metric, value)
    if "metric" in combined.columns and "value" in combined.columns:
        # Long format — pivot to wide first
        wide = combined.pivot_table(
            index="run", columns="metric", values="value", aggfunc="first"
        )
    else:
        wide = combined.drop(columns=[c for c in skip_cols if c in combined.columns], errors="ignore")
        # Drop non-numeric columns
        wide = wide.select_dtypes(include=[np.number])

    agg_rows = []
    for col in wide.columns:
        vals = wide[col].dropna().tolist()
        if not vals:
            continue
        stats = compute_stats(vals)
        agg_rows.append({
            "metric": col,
            "mean": stats["mean"],
            "std": stats["std"],
            "min": stats["min"],
            "max": stats["max"],
            "n": stats["n"],
        })

    return pd.DataFrame(agg_rows)


def print_table(agg: pd.DataFrame, experiment: str, n_runs: int) -> None:
    print()
    print(f"=== Aggregate Statistics: {experiment}  ({n_runs} runs) ===")
    print(f"{'Metric':<30} {'Mean':>12} {'Std':>10} {'Min':>10} {'Max':>10} {'N':>4}")
    print("-" * 78)
    for _, row in agg.iterrows():
        print(
            f"{row['metric']:<30} "
            f"{row['mean']:>12.3f} "
            f"{row['std']:>10.3f} "
            f"{row['min']:>10.3f} "
            f"{row['max']:>10.3f} "
            f"{int(row['n']):>4}"
        )
    print()


def plot_multi_runs(multi_proc_dir: str, experiment: str, n_runs: int) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    runs = sorted([d for d in os.listdir(multi_proc_dir) if d.startswith("run_")])
    if not runs:
        return

    # Check which metrics are available
    has_conn = os.path.exists(os.path.join(multi_proc_dir, runs[0], "connections.csv"))
    has_rep = os.path.exists(os.path.join(multi_proc_dir, runs[0], "replicas.csv"))
    has_cpu = os.path.exists(os.path.join(multi_proc_dir, runs[0], "cpu.csv"))
    has_reconnect = False
    if has_conn:
        try:
            _tmp = pd.read_csv(os.path.join(multi_proc_dir, runs[0], "connections.csv"), nrows=0)
            has_reconnect = "reconnect_rate" in _tmp.columns
        except:
            pass

    panels = sum([has_conn, has_rep, has_cpu, has_reconnect])
    if panels == 0:
        return

    fig, axes = plt.subplots(panels, 1, figsize=(8, 3 * panels), sharex=True)
    if panels == 1:
        axes = [axes]
    
    colors = ["#2c3e50", "#2980b9", "#27ae60", "#e67e22", "#8e44ad", "#c0392b"]

    for i, r in enumerate(runs):
        run_dir = os.path.join(multi_proc_dir, r)
        col = colors[i % len(colors)]
        label = f"Run {i+1}"
        
        ax_idx = 0
        
        if has_conn:
            df = pd.read_csv(os.path.join(run_dir, "connections.csv"))
            if not df.empty:
                t0 = df["timestamp"].min()
                axes[ax_idx].plot(df["timestamp"] - t0, df["active_connections"],
                                  color=col, alpha=0.8, linewidth=1.5, label=label)
            axes[ax_idx].set_ylabel("Active Connections")
            axes[ax_idx].set_title(f"{experiment} - Connections")
            ax_idx += 1
            
        if has_reconnect:
            df = pd.read_csv(os.path.join(run_dir, "connections.csv"))
            if not df.empty and "reconnect_rate" in df.columns:
                t0 = df["timestamp"].min()
                axes[ax_idx].plot(df["timestamp"] - t0, df["reconnect_rate"],
                                  color=col, alpha=0.8, linewidth=1.5, label=label)
            axes[ax_idx].set_ylabel("Reconnect Rate")
            axes[ax_idx].set_title(f"{experiment} - Reconnections")
            ax_idx += 1
            
        if has_rep:
            df = pd.read_csv(os.path.join(run_dir, "replicas.csv"))
            if not df.empty:
                t0 = df["timestamp"].min()
                rep_col = "spec_replicas" if "spec_replicas" in df.columns else df.columns[1]
                axes[ax_idx].step(df["timestamp"] - t0, df[rep_col],
                                  where="post", color=col, alpha=0.8, linewidth=1.5, label=label)
            axes[ax_idx].set_ylabel("Replicas")
            axes[ax_idx].set_title(f"{experiment} - Replicas")
            ax_idx += 1
            
        if has_cpu:
            df = pd.read_csv(os.path.join(run_dir, "cpu.csv"))
            if not df.empty:
                t0 = df["timestamp"].min()
                if "cpu_millicores" in df.columns:
                    axes[ax_idx].plot(df["timestamp"] - t0, df["cpu_millicores"],
                                      color=col, alpha=0.8, linewidth=1.5, label=label)
                    axes[ax_idx].set_ylabel("CPU (m)")
            axes[ax_idx].set_title(f"{experiment} - CPU")

    for ax in axes:
        ax.grid(True, linestyle=":", alpha=0.5)
        ax.legend(loc="upper right", ncol=min(3, len(runs)), fontsize=8)

    axes[-1].set_xlabel("Elapsed Time (s)")
    fig.tight_layout()
    
    out_path = os.path.join(multi_proc_dir, "multi_timeseries.png")
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  Multi-run overlay plot written → {out_path}")


def plot_averaged_runs(multi_proc_dir: str, experiment: str, n_runs: int) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    import pandas as pd

    runs = sorted([d for d in os.listdir(multi_proc_dir) if d.startswith("run_")])
    if not runs:
        return

    has_conn = os.path.exists(os.path.join(multi_proc_dir, runs[0], "connections.csv"))
    has_rep = os.path.exists(os.path.join(multi_proc_dir, runs[0], "replicas.csv"))
    has_cpu = os.path.exists(os.path.join(multi_proc_dir, runs[0], "cpu.csv"))
    has_reconnect = False
    if has_conn:
        try:
            _tmp = pd.read_csv(os.path.join(multi_proc_dir, runs[0], "connections.csv"), nrows=0)
            has_reconnect = "reconnect_rate" in _tmp.columns
        except:
            pass

    panels = sum([has_conn, has_rep, has_cpu, has_reconnect])
    if panels == 0:
        return

    fig, axes = plt.subplots(panels, 1, figsize=(8, 3 * panels), sharex=True)
    if panels == 1:
        axes = [axes]
    
    colors = ["#2c3e50", "#2980b9", "#c0392b"]

    def _get_aligned_data(filename: str, val_col: str):
        all_series = []
        max_t = 0
        for r in runs:
            p = os.path.join(multi_proc_dir, r, filename)
            if not os.path.exists(p):
                continue
            df = pd.read_csv(p)
            if df.empty:
                continue
            t0 = df["timestamp"].min()
            df["t"] = ((df["timestamp"] - t0) // 5) * 5  # bin to nearest 5s
            # average within the same bin just in case
            df = df.groupby("t", as_index=False)[val_col].mean()
            all_series.append(df.set_index("t")[val_col])
            max_t = max(max_t, df["t"].max())
        
        if not all_series:
            return None, None, None
            
        # Reindex all to a common grid
        common_idx = np.arange(0, max_t + 5, 5)
        aligned = pd.concat([s.reindex(common_idx).ffill() for s in all_series], axis=1)
        return common_idx, aligned.mean(axis=1), aligned.std(axis=1).fillna(0)

    def _save_individual_plot(t_grid, mean_val, std_val, ylabel, title, color, out_name, is_step=False):
        f, ax = plt.subplots(figsize=(6, 2.5))
        if is_step:
            ax.step(t_grid, mean_val, where="post", color=color, linewidth=2, label="Mean")
            ax.fill_between(t_grid, mean_val - std_val, mean_val + std_val, step="post", color=color, alpha=0.2, label="±1 Std Dev")
        else:
            ax.plot(t_grid, mean_val, color=color, linewidth=2, label="Mean")
            ax.fill_between(t_grid, mean_val - std_val, mean_val + std_val, color=color, alpha=0.2, label="±1 Std Dev")
        ax.set_ylabel(ylabel)
        ax.set_xlabel("Elapsed Time (s)")
        ax.set_title(title)
        ax.grid(True, linestyle=":", alpha=0.5)
        ax.legend(loc="upper right")
        f.tight_layout()
        f.savefig(os.path.join(multi_proc_dir, out_name), dpi=150, bbox_inches="tight")
        plt.close(f)

    ax_idx = 0
    if has_conn:
        t_grid, mean_val, std_val = _get_aligned_data("connections.csv", "active_connections")
        if t_grid is not None:
            axes[ax_idx].plot(t_grid, mean_val, color=colors[0], linewidth=2, label="Mean")
            axes[ax_idx].fill_between(t_grid, mean_val - std_val, mean_val + std_val, color=colors[0], alpha=0.2, label="±1 Std Dev")
            _save_individual_plot(t_grid, mean_val, std_val, "Active Connections", f"{experiment} - Connections", colors[0], "multi_averaged_connections.png")
        axes[ax_idx].set_ylabel("Active Connections")
        axes[ax_idx].set_title(f"{experiment} - Connections (Averaged over {n_runs} runs)")
        axes[ax_idx].legend(loc="upper right")
        ax_idx += 1

    if has_reconnect:
        t_grid, mean_val, std_val = _get_aligned_data("connections.csv", "reconnect_rate")
        if t_grid is not None:
            c = colors[3 % len(colors)] if len(colors) > 3 else "#e67e22"
            axes[ax_idx].plot(t_grid, mean_val, color=c, linewidth=2, label="Mean")
            axes[ax_idx].fill_between(t_grid, mean_val - std_val, mean_val + std_val, color=c, alpha=0.2, label="±1 Std Dev")
            _save_individual_plot(t_grid, mean_val, std_val, "Reconnect Rate", f"{experiment} - Reconnections", c, "multi_averaged_reconnections.png")
        axes[ax_idx].set_ylabel("Reconnect Rate")
        axes[ax_idx].set_title(f"{experiment} - Reconnections (Averaged over {n_runs} runs)")
        axes[ax_idx].legend(loc="upper right")
        ax_idx += 1

    if has_rep:
        # Determine replica column
        rep_col = "spec_replicas"
        p = os.path.join(multi_proc_dir, runs[0], "replicas.csv")
        if os.path.exists(p):
            cols = pd.read_csv(p, nrows=0).columns
            if "replicas" in cols:
                rep_col = "replicas"

        t_grid, mean_val, std_val = _get_aligned_data("replicas.csv", rep_col)
        if t_grid is not None:
            axes[ax_idx].step(t_grid, mean_val, where="post", color=colors[1], linewidth=2, label="Mean")
            axes[ax_idx].fill_between(t_grid, mean_val - std_val, mean_val + std_val, step="post", color=colors[1], alpha=0.2, label="±1 Std Dev")
            _save_individual_plot(t_grid, mean_val, std_val, "Replicas", f"{experiment} - Replicas", colors[1], "multi_averaged_replicas.png", is_step=True)
        axes[ax_idx].set_ylabel("Replicas")
        axes[ax_idx].set_title(f"{experiment} - Replicas (Averaged over {n_runs} runs)")
        axes[ax_idx].legend(loc="upper right")
        ax_idx += 1

    if has_cpu:
        t_grid, mean_val, std_val = _get_aligned_data("cpu.csv", "cpu_millicores")
        if t_grid is not None:
            axes[ax_idx].plot(t_grid, mean_val, color=colors[2], linewidth=2, label="Mean")
            axes[ax_idx].fill_between(t_grid, mean_val - std_val, mean_val + std_val, color=colors[2], alpha=0.2, label="±1 Std Dev")
            _save_individual_plot(t_grid, mean_val, std_val, "CPU (m)", f"{experiment} - CPU", colors[2], "multi_averaged_cpu.png")
        axes[ax_idx].set_ylabel("CPU (m)")
        axes[ax_idx].set_title(f"{experiment} - CPU (Averaged over {n_runs} runs)")
        axes[ax_idx].legend(loc="upper right")

    for ax in axes:
        ax.grid(True, linestyle=":", alpha=0.5)

    axes[-1].set_xlabel("Elapsed Time (s)")
    fig.tight_layout()
    
    out_path = os.path.join(multi_proc_dir, "multi_averaged.png")
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  Multi-run averaged plot written → {out_path}")


def main() -> None:
    args = parse_args()

    if not os.path.isdir(args.multi_proc_dir):
        print(f"ERROR: --multi-proc-dir '{args.multi_proc_dir}' does not exist.")
        sys.exit(1)

    combined = collect_summaries(args.multi_proc_dir)
    n_runs = combined["run"].nunique() if "run" in combined.columns else len(combined)

    agg = aggregate(combined)

    out_path = args.out or os.path.join(args.multi_proc_dir, "aggregate_stats.csv")
    agg.to_csv(out_path, index=False)
    print(f"  Aggregate stats written → {out_path}")

    print_table(agg, args.experiment, n_runs)
    
    # Generate multi-run overlaid plots
    plot_multi_runs(args.multi_proc_dir, args.experiment, n_runs)
    plot_averaged_runs(args.multi_proc_dir, args.experiment, n_runs)


if __name__ == "__main__":
    main()
