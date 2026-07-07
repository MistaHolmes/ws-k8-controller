import os
import re
import pandas as pd
from datetime import datetime
import shutil

RAW_DIR = os.environ.get("RAW_DIR")
PROCESSED_DIR = os.environ.get("PROCESSED_DIR")

if RAW_DIR is None or PROCESSED_DIR is None:
    raise RuntimeError("RAW_DIR and PROCESSED_DIR must be set as environment variables.")

if os.path.exists(PROCESSED_DIR):
    if os.environ.get("MULTI_RUN", "0") in ("1", "true", "True"):
        print("  MULTI_RUN detected: preserving existing PROCESSED_DIR")
    else:
        shutil.rmtree(PROCESSED_DIR)

os.makedirs(PROCESSED_DIR, exist_ok=True)

# ----------------------------
# Parse CPU log
# ----------------------------
def parse_cpu():
    rows = []
    current_ts = None

    with open(f"{RAW_DIR}/cpu.log") as f:
        for line in f:
            line = line.strip()

            # If line is timestamp
            if line.isdigit():
                current_ts = int(line)
                continue

            parts = line.split()
            if len(parts) >= 3 and current_ts is not None:
                pod = parts[0]
                cpu = parts[1].replace("m", "")

                try:
                    rows.append({
                        "timestamp": current_ts,
                        "pod": pod,
                        "cpu_millicores": int(cpu)
                    })
                except:
                    continue

    df = pd.DataFrame(rows)

    if not df.empty:
        df.to_csv(f"{PROCESSED_DIR}/cpu.csv", index=False)

# ----------------------------
# Parse HPA log
# ----------------------------
def parse_hpa():
    rows = []
    current_ts = None

    with open(f"{RAW_DIR}/hpa.log") as f:
        for line in f:
            line = line.strip()

            # Timestamp line
            if line.isdigit():
                current_ts = int(line)
                continue

            # Skip header lines
            if line.startswith("NAME") or not line:
                continue

            parts = line.split()

            if parts[0] == "websocket-hpa" and current_ts is not None:
                try:
                    # TARGETS column is split: cpu: 52%/60%
                    cpu_percent = parts[3].split("/")[0].replace("%", "")
                    replicas = int(parts[6])

                    rows.append({
                        "timestamp": current_ts,
                        "cpu_percent": float(cpu_percent),
                        "replicas": replicas
                    })
                except:
                    continue

    df = pd.DataFrame(rows)

    if not df.empty:
        df.to_csv(f"{PROCESSED_DIR}/replicas.csv", index=False)

# ----------------------------
# Parse active connections
# ----------------------------
def parse_connections():
    rows = []
    with open(f"{RAW_DIR}/active_connections.log") as f:
        lines = f.readlines()
        for i in range(0, len(lines), 2):
            try:
                ts = int(lines[i].strip())
                conn = int(lines[i+1].split()[-1])
                rows.append({
                    "timestamp": ts,
                    "active_connections": conn
                })
            except:
                continue
    df = pd.DataFrame(rows)
    df.to_csv(f"{PROCESSED_DIR}/connections.csv", index=False)

# ----------------------------
# Compute summary.csv
# ----------------------------
def compute_summary():
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from metrics_utils import compute_pod_seconds, compute_reaction_time, write_summary

    rep_path = f"{PROCESSED_DIR}/replicas.csv"
    conn_path = f"{PROCESSED_DIR}/connections.csv"

    if not os.path.exists(rep_path) or not os.path.exists(conn_path):
        print("  Skipping summary: missing replicas.csv or connections.csv")
        return

    replicas_df = pd.read_csv(rep_path)
    connections_df = pd.read_csv(conn_path)

    pod_s = compute_pod_seconds(replicas_df, replicas_col="replicas")
    reaction = compute_reaction_time(
        connections_df, replicas_df, replicas_col="replicas"
    )

    peak_conn = float(connections_df["active_connections"].max()) if not connections_df.empty else float("nan")
    peak_rep = float(replicas_df["replicas"].max()) if not replicas_df.empty else float("nan")

    write_summary(
        PROCESSED_DIR,
        pod_seconds=pod_s,
        scale_up_reaction_s=reaction["scale_up_s"],
        scale_down_reaction_s=reaction["scale_down_s"],
        peak_connections=peak_conn,
        peak_replicas=peak_rep,
    )
    print(f"  Summary: pod_seconds={pod_s:.1f}  scale_up={reaction['scale_up_s']:.1f}s  peak_replicas={peak_rep}")


if __name__ == "__main__":
    parse_cpu()
    parse_hpa()
    parse_connections()
    compute_summary()
    print("Parsing complete.")