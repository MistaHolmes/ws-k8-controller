# Experiment-B — CPU-Based HPA Under Dynamic Churn

## 1. Overview

This experiment evaluates the behavior of Kubernetes CPU-based Horizontal Pod Autoscaler (HPA) under cyclic persistent connection load.

Unlike Experiment-A (monotonic load), this experiment introduces dynamic churn to expose instability characteristics.

The workload and autoscaler configuration remain identical to Experiment-A.
Only the load pattern changes.

---

## 2. Objective

To determine how default CPU-based HPA behaves under rapid load cycling in a persistent WebSocket workload.

Specifically, this experiment evaluates:

- Replica oscillation
- Reconnection storms
- CPU spikes during scale transitions
- Reactive scaling instability

---

## 3. Hypothesis

Under cyclic load:

- HPA will scale up during high-load phases.
- HPA will attempt scale-down during low-load phases.
- Abrupt termination of pods with active sessions will induce reconnection bursts.
- CPU spikes will occur during reconnection.
- Replica oscillation will become visible.

---

## 4. Load Pattern

Cyclic load pattern:

- 60 seconds — High load (800 clients)
- 30 seconds — Zero load
- Repeat for 5 cycles

Total duration ≈ 7.5–8 minutes.

This intentionally stresses:

- Scale-up responsiveness
- Scale-down stability
- Control-loop lag

---

## 5. Autoscaler Configuration

Identical to Experiment-A:

- Metric: CPU utilization
- Target: 60%
- Min replicas: 2
- Max replicas: 10
- Scale-down stabilization: 300 seconds

No parameter tuning is performed to preserve fairness.

---

## 6. Metrics Collected

- CPU usage (millicores)
- Active WebSocket connections
- Replica count
- Phase transitions (high/low markers)
- Prometheus time-series export

Raw logs stored under:

results/raw/websocket/experiment-b-hpa-churn/

Processed results stored under:

results/processed/websocket/experiment-b-hpa-churn/

---

## 7. Expected Observations

Compared to Experiment-A:

- Sawtooth pattern in active connections
- Visible replica oscillation
- CPU spikes during reconnection bursts
- HPA chasing load rather than stabilizing

This experiment demonstrates that:

Default HPA is stable under steady load (Experiment-A)
but unstable under dynamic persistent connection churn.

---

## 8. Conclusion Target

This experiment provides justification for implementing a stateful autoscaler in Experiment-C.