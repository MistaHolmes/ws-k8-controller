# Paper-1: Experiment Commands

All commands should be run from the project root directory:
```bash
cd /home/abhas/node/STAR/future-work
```

---

## Prerequisites

Ensure the following are installed:
```bash
# Core tools
docker --version
kind --version
kubectl version --client
jq --version
curl --version
ansible --version

# Python dependencies
pip3 install pandas numpy matplotlib
```

---

## Task 1: B3 Five-Run Replication

Replicates Experiment B3 five times, computes mean ± std of connection staircase
data, and generates a replication table for Section 4.4.

### Option A: Ansible Playbook (Recommended)

```bash
# Run the playbook
ansible-playbook scripts/ansible/b3-multi-run.yml

# In a separate terminal, monitor progress in real-time
tail -f b3_multi_run.log
```

### Option B: Manual Execution

```bash
# Step 1: Run B3 five times
EXPERIMENT=b3 N=5 CLEAN_MULTI=1 bash scripts/run-multi.sh

# Step 2: Aggregate summary statistics
python3 analysis/multi_run_stats.py \
  --experiment experiment-b3-hpa-idle-connections \
  --multi-proc-dir results/processed/websocket/multi/experiment-b3-hpa-idle-connections

# Step 3: Build B3 replication table
python3 analysis/experiment-b3/b3_multi_run_analysis.py \
  --multi-dir results/processed/websocket/multi/experiment-b3-hpa-idle-connections
```

### Output Files

| File | Description |
|------|-------------|
| `results/processed/websocket/multi/experiment-b3-hpa-idle-connections/run_*/` | Per-run processed data |
| `results/processed/websocket/multi/experiment-b3-hpa-idle-connections/aggregate_stats.csv` | Aggregate stats (mean/std/min/max) |
| `results/processed/websocket/multi/experiment-b3-hpa-idle-connections/b3_replication_table.csv` | Five-run replication table |
| `results/processed/websocket/multi/experiment-b3-hpa-idle-connections/b3_replication_stats.csv` | Machine-readable stats |

---

## Task 2: HPA Stabilization Window Tuning Study

Tests 4 stabilization window values (30s, 60s, 120s, 300s) × 2 gap conditions
(below/above window) = 8 configurations, each run 3 times = 24 total runs.

### Test Matrix

| Window (s) | Gap Below (safe) | Gap Above (fail) |
|-----------|-------------------|-------------------|
| 30        | 15s               | 90s               |
| 60        | 45s               | 120s              |
| 120       | 105s              | 180s              |
| 300       | 285s              | 360s              |

### Option A: Ansible Playbook (Recommended)

```bash
# Run the playbook
ansible-playbook scripts/ansible/b3-tuning-study.yml

# In a separate terminal, monitor progress in real-time
tail -f b3_tuning_run.log
```

### Option B: Manual Execution (single config example)

```bash
# Run a single configuration (e.g., window=60s, gap=45s, run 1)
STABILIZATION_WINDOW=60 GAP_DURATION=45 RUN_ID=1 \
  bash scripts/run-experiment-b3-tuning.sh

# Run all 8 configs × 3 runs manually:
for WINDOW in 30 60 120 300; do
  for GAP in $([ "$WINDOW" = "30" ] && echo "15 90" || \
               [ "$WINDOW" = "60" ] && echo "45 120" || \
               [ "$WINDOW" = "120" ] && echo "105 180" || \
               echo "285 360"); do
    for RUN in 1 2 3; do
      echo "=== Window=${WINDOW}s Gap=${GAP}s Run=${RUN} ==="
      STABILIZATION_WINDOW=$WINDOW GAP_DURATION=$GAP RUN_ID=$RUN \
        bash scripts/run-experiment-b3-tuning.sh
    done
  done
done

# Aggregate results
python3 analysis/experiment-b3/b3_tuning_analysis.py \
  --results-dir results/processed/websocket/experiment-b3-tuning \
  --multi-run
```

### Output Files

| File | Description |
|------|-------------|
| `results/processed/websocket/experiment-b3-tuning/window*_gap*/run_*/` | Per-run data |
| `results/processed/websocket/experiment-b3-tuning/tuning_results.csv` | Aggregated results table |
| `results/processed/websocket/experiment-b3-tuning/tuning_all_runs.csv` | Raw data from all runs |

---

## Task 3: Paper Update (After Results Are Collected)

Once both experiments above have completed successfully:

1. **B3 Replication** — Add a half-page to Section 4.4 with the replication table
   showing mean ± std across 5 runs.

2. **HPA Tuning Study** — Add a new subsection (Section 5.x) presenting the
   stabilization window sensitivity results and the 8-row table.

3. **Mathematical Expressions** — Add two equations to Section 5.1 formalizing:
   - HPA's assumption: `M(t) ∝ D(t)` (CPU tracks demand)
   - WebSocket violation: `M(t) ↛ D(t)` (idle connections break proportionality)

> **Note:** Paper updates will be done after results are generated. Tell the assistant
> to update the paper once you have the results.

---

## Estimated Runtimes

| Task | Estimated Time |
|------|---------------|
| B3 single run | ~10-15 min |
| B3 five-run replication (Task 1) | ~60-90 min |
| B3 tuning single config | ~10-15 min |
| B3 tuning full study (Task 2, 24 runs) | ~4-6 hours |
| **Total** | **~5-8 hours** |
