"""
Parse raw logs from Experiment-D (HPA + Custom Metric) into CSVs.

Log formats written by run-experiment-d.sh:
  replicas.log  : timestamp,spec_replicas,hpa_current,hpa_desired,metric_value
  prometheus.log: timestamp,active_connections,reconnection_rate

Usage (env vars):
  RAW_DIR       - path to results/raw/websocket/experiment-d-hpa-custom-metric
  PROCESSED_DIR - path to write CSVs (created/overwritten on each run)
"""

import os
import shutil
import pandas as pd

RAW_DIR = os.environ.get("RAW_DIR")
PROCESSED_DIR = os.environ.get("PROCESSED_DIR")

if RAW_DIR is None or PROCESSED_DIR is None:
    # Sensible defaults so the script can be run from the workspace root
    _base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    RAW_DIR = RAW_DIR or os.path.join(
        _base, "results", "raw", "websocket", "experiment-d-hpa-custom-metric"
    )
    PROCESSED_DIR = PROCESSED_DIR or os.path.join(
        _base, "results", "processed", "websocket", "experiment-d-hpa-custom-metric"
    )

if os.path.exists(PROCESSED_DIR):
    shutil.rmtree(PROCESSED_DIR)
os.makedirs(PROCESSED_DIR, exist_ok=True)

print(f"RAW_DIR:       {RAW_DIR}")
print(f"PROCESSED_DIR: {PROCESSED_DIR}")


# --------------------------------------------------
# Parse replicas.log -> replicas.csv
# Columns: timestamp, spec_replicas, hpa_current, hpa_desired, metric_value
# --------------------------------------------------
def parse_replicas():
    path = os.path.join(RAW_DIR, "replicas.log")
    if not os.path.exists(path):
        print("  No replicas.log found, skipping.")
        return

    rows = []
    with open(path) as f:
        for line in f:
            line = line.strip().rstrip(",")
            if not line:
                continue
            parts = line.split(",")
            try:
                ts = int(parts[0])
                spec = int(parts[1]) if parts[1] else None
                hpa_current = int(parts[2]) if len(parts) > 2 and parts[2] else None
                hpa_desired = int(parts[3]) if len(parts) > 3 and parts[3] else None
                metric_val = float(parts[4]) if len(parts) > 4 and parts[4] else None
                rows.append({
                    "timestamp": ts,
                    "spec_replicas": spec,
                    "hpa_current": hpa_current,
                    "hpa_desired": hpa_desired,
                    "metric_value": metric_val,
                })
            except (ValueError, IndexError):
                continue

    df = pd.DataFrame(rows)
    if not df.empty:
        df.to_csv(os.path.join(PROCESSED_DIR, "replicas.csv"), index=False)
        print(f"  Parsed replicas.csv: {len(df)} rows")
    else:
        print("  WARNING: No replica data parsed.")


# --------------------------------------------------
# Parse prometheus.log -> connections.csv
# Columns: timestamp, active_connections, reconnection_rate
# --------------------------------------------------
def parse_prometheus():
    path = os.path.join(RAW_DIR, "prometheus.log")
    if not os.path.exists(path):
        print("  No prometheus.log found, skipping.")
        return

    rows = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split(",")
            try:
                rows.append({
                    "timestamp": int(parts[0]),
                    "active_connections": float(parts[1]),
                    "reconnection_rate": float(parts[2]) if len(parts) > 2 else 0.0,
                })
            except (ValueError, IndexError):
                continue

    df = pd.DataFrame(rows)
    if not df.empty:
        df.to_csv(os.path.join(PROCESSED_DIR, "connections.csv"), index=False)
        print(f"  Parsed connections.csv: {len(df)} rows")
    else:
        print("  WARNING: No connections data parsed.")


parse_replicas()
parse_prometheus()
print("Done.")
