"""
Parse raw logs from Experiment-E (KEDA Baseline) into CSVs.

Log formats written by run-experiment-e.sh:
  replicas.log         : timestamp,spec_replicas,keda_hpa_status
  prometheus.log       : timestamp,active_connections,reconnection_rate
  keda-scaledobject.log: timestamp,scaledobject_status_json

Usage (env vars):
  RAW_DIR       - path to results/raw/websocket/experiment-e-keda
  PROCESSED_DIR - path to write CSVs (created/overwritten on each run)
  or just run with no env vars for sensible defaults.
"""

import os
import shutil
import pandas as pd

_base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RAW_DIR = os.environ.get(
    "RAW_DIR",
    os.path.join(_base, "results", "raw", "websocket", "experiment-e-keda"),
)
PROCESSED_DIR = os.environ.get(
    "PROCESSED_DIR",
    os.path.join(_base, "results", "processed", "websocket", "experiment-e-keda"),
)

if os.path.exists(PROCESSED_DIR):
    shutil.rmtree(PROCESSED_DIR)
os.makedirs(PROCESSED_DIR, exist_ok=True)

print(f"RAW_DIR:       {RAW_DIR}")
print(f"PROCESSED_DIR: {PROCESSED_DIR}")


# --------------------------------------------------
# Parse replicas.log -> replicas.csv
# Columns: timestamp, spec_replicas, keda_hpa (raw string)
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
            parts = line.split(",", 2)  # max 3 fields; keda_hpa may contain commas
            try:
                ts = int(parts[0])
                spec = int(parts[1]) if len(parts) > 1 and parts[1] else None
                keda_hpa = parts[2] if len(parts) > 2 else ""
                rows.append({
                    "timestamp": ts,
                    "spec_replicas": spec,
                    "keda_hpa": keda_hpa,
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


# --------------------------------------------------
# Parse keda-scaledobject.log -> keda.csv
# Columns: timestamp, status_raw
# --------------------------------------------------
def parse_keda():
    path = os.path.join(RAW_DIR, "keda-scaledobject.log")
    if not os.path.exists(path):
        print("  No keda-scaledobject.log found, skipping.")
        return

    rows = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            idx = line.find(",")
            if idx == -1:
                continue
            try:
                rows.append({
                    "timestamp": int(line[:idx]),
                    "status_raw": line[idx + 1:],
                })
            except ValueError:
                continue

    df = pd.DataFrame(rows)
    if not df.empty:
        df.to_csv(os.path.join(PROCESSED_DIR, "keda.csv"), index=False)
        print(f"  Parsed keda.csv: {len(df)} rows")
    else:
        print("  WARNING: No KEDA status data parsed.")


parse_replicas()
parse_prometheus()
parse_keda()
print("Done.")
