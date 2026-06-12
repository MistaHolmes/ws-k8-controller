#!/usr/bin/env python3
"""
b3_multi_run_analysis.py — Analyze N replicate runs of Experiment B3.

Extracts per-run staircase connection metrics and builds a replication table
with mean ± std across all runs.

Usage:
    python3 analysis/experiment-b3/b3_multi_run_analysis.py \
        --multi-dir results/processed/websocket/multi/experiment-b3-hpa-idle-connections

Output:
    <multi-dir>/b3_replication_table.csv
"""

from __future__ import annotations

import argparse
import os
import sys

import numpy as np
import pandas as pd

# Allow importing metrics_utils from parent dir
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from metrics_utils import compute_stats


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Analyze B3 multi-run replication results"
    )
    p.add_argument(
        "--multi-dir",
        required=True,
        help="Path to multi/<experiment> dir containing run_1, run_2, … subdirs",
    )
    p.add_argument(
        "--out",
        default=None,
        help="Output CSV path (default: <multi-dir>/b3_replication_table.csv)",
    )
    return p.parse_args()


def extract_run_metrics(run_dir: str) -> dict | None:
    """Extract key B3 metrics from a single run directory."""
    conn_path = os.path.join(run_dir, "connections.csv")
    rep_path = os.path.join(run_dir, "replicas.csv")

    if not os.path.exists(conn_path) or not os.path.exists(rep_path):
        print(f"  WARNING: Missing connections.csv or replicas.csv in {run_dir}")
        return None

    connections = pd.read_csv(conn_path)
    replicas = pd.read_csv(rep_path)

    if connections.empty or replicas.empty:
        print(f"  WARNING: Empty data in {run_dir}")
        return None

    # Determine the active_connections column name
    conn_col = "active_connections"
    if conn_col not in connections.columns:
        # Try to find it
        candidates = [c for c in connections.columns if "connection" in c.lower()]
        if candidates:
            conn_col = candidates[0]
        else:
            print(f"  WARNING: No connection column found in {run_dir}")
            return None

    # Peak connections (should be ~800 at the start)
    peak_connections = float(connections[conn_col].max())

    # Final connections (last recorded value — the bottom of the staircase)
    final_connections = float(connections[conn_col].iloc[-1])

    # Total connections lost
    connections_lost = peak_connections - final_connections

    # Percentage lost
    pct_lost = (connections_lost / peak_connections * 100) if peak_connections > 0 else 0.0

    # Number of scale-down events
    rep_col = "replicas"
    if rep_col not in replicas.columns:
        candidates = [c for c in replicas.columns if "replica" in c.lower()]
        rep_col = candidates[0] if candidates else replicas.columns[-1]

    replicas_sorted = replicas.sort_values("timestamp")
    scale_down_events = int((replicas_sorted[rep_col].diff() < 0).sum())

    # Peak replicas
    peak_replicas = int(replicas_sorted[rep_col].max())

    # Final replicas
    final_replicas = int(replicas_sorted[rep_col].iloc[-1])

    return {
        "peak_connections": peak_connections,
        "final_connections": final_connections,
        "connections_lost": connections_lost,
        "pct_lost": round(pct_lost, 1),
        "scale_down_events": scale_down_events,
        "peak_replicas": peak_replicas,
        "final_replicas": final_replicas,
    }


def main() -> None:
    args = parse_args()

    if not os.path.isdir(args.multi_dir):
        print(f"ERROR: '{args.multi_dir}' does not exist.")
        sys.exit(1)

    # Collect run directories
    run_dirs = sorted(
        [d for d in os.listdir(args.multi_dir) if d.startswith("run_")]
    )

    if not run_dirs:
        print(f"ERROR: No run_* directories found in {args.multi_dir}")
        sys.exit(1)

    print(f"\n=== B3 Multi-Run Analysis ({len(run_dirs)} runs) ===\n")

    rows = []
    for run_name in run_dirs:
        run_path = os.path.join(args.multi_dir, run_name)
        metrics = extract_run_metrics(run_path)
        if metrics is not None:
            metrics["run"] = run_name
            rows.append(metrics)
            print(
                f"  {run_name}: peak={metrics['peak_connections']:.0f} "
                f"final={metrics['final_connections']:.0f} "
                f"lost={metrics['connections_lost']:.0f} ({metrics['pct_lost']}%) "
                f"scale_downs={metrics['scale_down_events']}"
            )

    if not rows:
        print("ERROR: No valid run data found.")
        sys.exit(1)

    df = pd.DataFrame(rows)

    # Compute aggregate statistics
    metrics_to_aggregate = [
        "peak_connections",
        "final_connections",
        "connections_lost",
        "pct_lost",
        "scale_down_events",
        "peak_replicas",
        "final_replicas",
    ]

    agg_row = {"run": "mean ± std"}
    for col in metrics_to_aggregate:
        vals = df[col].dropna().tolist()
        stats = compute_stats(vals)
        agg_row[col] = f"{stats['mean']:.1f} ± {stats['std']:.1f}"

    # Build final table
    # Convert numeric rows to formatted strings for the combined table
    display_rows = []
    for _, row in df.iterrows():
        display_row = {"run": row["run"]}
        for col in metrics_to_aggregate:
            display_row[col] = f"{row[col]:.1f}" if isinstance(row[col], float) else str(row[col])
        display_rows.append(display_row)
    display_rows.append(agg_row)

    result_df = pd.DataFrame(display_rows)

    # Save
    out_path = args.out or os.path.join(args.multi_dir, "b3_replication_table.csv")
    result_df.to_csv(out_path, index=False)
    print(f"\n  Replication table written → {out_path}")

    # Also save a machine-readable stats CSV
    stats_rows = []
    for col in metrics_to_aggregate:
        vals = df[col].dropna().tolist()
        stats = compute_stats(vals)
        stats["metric"] = col
        stats_rows.append(stats)

    stats_df = pd.DataFrame(stats_rows)
    stats_path = os.path.join(os.path.dirname(out_path), "b3_replication_stats.csv")
    stats_df.to_csv(stats_path, index=False)
    print(f"  Replication stats written → {stats_path}")

    # Print summary table
    print(f"\n{'='*80}")
    print(f"  B3 Replication Summary ({len(df)} runs)")
    print(f"{'='*80}")
    print(f"  {'Metric':<25} {'Mean':>10} {'Std':>10} {'Min':>10} {'Max':>10}")
    print(f"  {'-'*65}")
    for _, row in stats_df.iterrows():
        print(
            f"  {row['metric']:<25} "
            f"{row['mean']:>10.1f} "
            f"{row['std']:>10.1f} "
            f"{row['min']:>10.1f} "
            f"{row['max']:>10.1f}"
        )
    print()


if __name__ == "__main__":
    main()
