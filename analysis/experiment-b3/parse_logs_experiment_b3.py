import os
import pandas as pd
import shutil

RAW_DIR = os.environ.get("RAW_DIR")
PROCESSED_DIR = os.environ.get("PROCESSED_DIR")

if RAW_DIR is None or PROCESSED_DIR is None:
    raise RuntimeError("RAW_DIR and PROCESSED_DIR must be set.")

if os.path.exists(PROCESSED_DIR):
    shutil.rmtree(PROCESSED_DIR)

os.makedirs(PROCESSED_DIR, exist_ok=True)


# --------------------------------------------------
# Parse CPU logs -> cpu.csv
# --------------------------------------------------
def parse_cpu():
    cpu_file = f"{RAW_DIR}/cpu.log"
    if not os.path.exists(cpu_file):
        print("No cpu.log found, skipping.")
        return

    rows = []
    current_ts = None

    with open(cpu_file) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue

            if line.isdigit():
                current_ts = int(line)
                continue

            parts = line.split()
            if len(parts) >= 3 and current_ts is not None:
                try:
                    rows.append({
                        "timestamp": current_ts,
                        "pod": parts[0],
                        "cpu_millicores": int(parts[1].replace("m", ""))
                    })
                except (ValueError, IndexError):
                    continue

    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.groupby("timestamp", as_index=False)["cpu_millicores"].sum()
        df.to_csv(f"{PROCESSED_DIR}/cpu.csv", index=False)
        print(f"  Parsed cpu.csv: {len(df)} rows")
    else:
        print("  WARNING: No CPU data parsed.")


# --------------------------------------------------
# Parse HPA logs -> replicas.csv
# --------------------------------------------------
def parse_hpa():
    hpa_file = f"{RAW_DIR}/hpa.log"
    if not os.path.exists(hpa_file):
        print("No hpa.log found, skipping.")
        return

    rows = []
    current_ts = None

    with open(hpa_file) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue

            if line.isdigit():
                current_ts = int(line)
                continue

            if line.startswith("NAME") or not line:
                continue

            parts = line.split()
            # kubectl get hpa (autoscaling/v2) columns:
            #   NAME  REFERENCE  [cpu:]  TARGETS  MINPODS  MAXPODS  REPLICAS  AGE
            # REFERENCE contains "/" but is NOT the metric target.
            # Metric target looks like "45%/60%" or "<unknown>/60%".
            # Match only parts that contain "/" AND end with "%" (the x/y% pattern).
            if parts[0] == "websocket-hpa" and current_ts is not None:
                try:
                    replicas = int(parts[-2])

                    # Extract CPU% — only the token that matches "N%/M%" or "<unknown>/M%"
                    cpu_str = "0"
                    for p in parts:
                        if "/" in p and p.endswith("%"):
                            raw = p.split("/")[0].replace("%", "").strip()
                            if raw not in ["<unknown>", "unknown", ""]:
                                cpu_str = raw
                            break

                    try:
                        cpu_val = float(cpu_str)
                    except ValueError:
                        cpu_val = 0.0

                    rows.append({
                        "timestamp": current_ts,
                        "cpu_percent": cpu_val,
                        "replicas": replicas
                    })
                except (ValueError, IndexError):
                    continue


    df = pd.DataFrame(rows)
    if not df.empty:
        df.to_csv(f"{PROCESSED_DIR}/replicas.csv", index=False)
        print(f"  Parsed replicas.csv: {len(df)} rows")
    else:
        print("  WARNING: No HPA data parsed.")


# --------------------------------------------------
# Parse Prometheus CSV dump -> connections.csv
# --------------------------------------------------
def parse_prometheus():
    dump_file = f"{RAW_DIR}/prometheus_dump.csv"
    if not os.path.exists(dump_file):
        print("No prometheus_dump.csv found, skipping.")
        return

    try:
        with open(dump_file) as f:
            first_line = f.readline().strip()

        if first_line and first_line[0].isdigit():
            df = pd.read_csv(dump_file, header=None,
                             names=["timestamp", "active_connections"])
        else:
            df = pd.read_csv(dump_file)

        if df.empty:
            print("  WARNING: Prometheus dump CSV is empty.")
            return

        df["timestamp"] = df["timestamp"].astype(int)
        df["active_connections"] = df["active_connections"].astype(float)

        df.to_csv(f"{PROCESSED_DIR}/connections.csv", index=False)
        print(f"  Parsed connections.csv: {len(df)} rows")

    except Exception as e:
        print(f"  ERROR parsing Prometheus CSV: {e}")


if __name__ == "__main__":
    print("Parsing experiment-b3 logs...")
    parse_cpu()
    parse_hpa()
    parse_prometheus()
    print("Experiment-B3 log parsing complete.")
