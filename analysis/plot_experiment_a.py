import os
import pandas as pd
import matplotlib.pyplot as plt

PROCESSED_DIR = "results/processed/websocket/experiment-a-hpa"
PLOTS_DIR = f"{PROCESSED_DIR}/plots"

os.makedirs(PLOTS_DIR, exist_ok=True)

# Load data
cpu = pd.read_csv(f"{PROCESSED_DIR}/cpu.csv")
replicas = pd.read_csv(f"{PROCESSED_DIR}/replicas.csv")
connections = pd.read_csv(f"{PROCESSED_DIR}/connections.csv")

# ----------------------------
# Plot CPU
# ----------------------------
plt.figure()
plt.plot(cpu["cpu_millicores"])
plt.title("CPU Usage (millicores)")
plt.xlabel("Sample")
plt.ylabel("CPU (m)")
plt.savefig(f"{PLOTS_DIR}/cpu.png")
plt.close()

# ----------------------------
# Plot Replicas
# ----------------------------
plt.figure()
plt.plot(replicas["replicas"])
plt.title("Replica Count Over Time")
plt.xlabel("Sample")
plt.ylabel("Replicas")
plt.savefig(f"{PLOTS_DIR}/replicas.png")
plt.close()

# ----------------------------
# Plot Connections
# ----------------------------
plt.figure()
plt.plot(connections["active_connections"])
plt.title("Active Connections Over Time")
plt.xlabel("Time")
plt.ylabel("Connections")
plt.savefig(f"{PLOTS_DIR}/connections.png")
plt.close()

print("Plots generated.")