# Experiment-A — CPU-Based HPA Baseline (WebSocket Workload)

## 1. Overview

This experiment establishes the baseline behavior of the default Kubernetes Horizontal Pod Autoscaler (HPA) when applied to a persistent WebSocket workload under monotonic load.

The goal is not to demonstrate failure, but to characterize normal scaling behavior under steady-state conditions. This baseline is required before introducing dynamic churn (Experiment-B) and a stateful autoscaler (Experiment-C).



## 2. Objective

To evaluate how CPU-based HPA responds to a persistent WebSocket connection workload with:

- Gradual load increase
- Sustained high load
- Load removal
- Natural scale-down

This experiment answers:

> How does default Kubernetes HPA behave under steady persistent load?



## 3. Hypothesis

Under monotonic connection load:

- CPU usage will increase proportionally to active connections.
- HPA will scale up based on CPU threshold.
- HPA will respect the stabilization window during scale-down.
- No replica oscillation will occur.
- No reconnection storm will occur.



## 4. System Under Test (SUT)

### Workload
- WebSocket server (persistent TCP connections)
- Stateless application logic
- No session draining logic
- No custom termination hooks

### Cluster
- Fresh `kind` cluster per run
- Multi-node configuration
- metrics-server installed
- Prometheus installed

### Autoscaler
- Kubernetes HPA (autoscaling/v2)
- Metric: CPU utilization
- Target: 60%
- Min replicas: 2
- Max replicas: 10
- Default scale-down stabilization window (300s)



## 5. Load Profile

Single-phase monotonic load:

- 800 WebSocket clients
- Duration: 300 seconds
- Abrupt termination at end of load window

No cyclic or burst pattern is used in this experiment.


## 6. Metrics Collected

The following metrics are logged at 5-second intervals:

- CPU usage (millicores per pod)
- Active WebSocket connections
- HPA replica count
- Pod states
- Prometheus time-series export (active_connections)

All logs are stored under:
```
results/raw/websocket/experiment-a-hpa/
```

Processed outputs are stored under:
```
results/processed/websocket/experiment-a-hpa/
```

## 7. Observed Results

### Active Connections
- Rapid ramp-up to ~400 connections.
- Stable plateau during sustained load.
- Gradual drop after load removal.
- Clean return to zero.
- No reconnection spikes observed.

### CPU Usage
- CPU increases proportionally to connection load.
- Peaks during sustained phase.
- Drops to near-zero after load ends.
- No post-scale-down CPU spikes.

### Replica Count
- Initial: 2 replicas.
- Scaled to 4–5 replicas during load.
- Remained elevated during stabilization window.
- Returned cleanly to 2 replicas after stabilization period.
- No oscillation observed.



## 8. Interpretation

Experiment-A demonstrates that:

1. CPU-based HPA behaves correctly under steady persistent load.
2. Scale-up is reactive to CPU increase.
3. Scale-down respects stabilization window.
4. No instability appears under monotonic load.
5. Default HPA is functionally valid in steady-state scenarios.

This confirms that the baseline configuration is stable.



## 9. Limitations of Experiment-A

This experiment does NOT test:

- Abrupt connection churn
- Reconnection storms
- Replica oscillation under bursty load
- Scale-down safety for persistent sessions
- Connection draining behavior

Those aspects are evaluated in Experiment-B.



## 10. Conclusion

Experiment-A establishes a clean and reproducible baseline for CPU-based HPA applied to persistent WebSocket workloads.

The system:

- Scales predictably
- Exhibits no oscillation
- Shows correct stabilization behavior
- Produces stable metrics suitable for comparison

This baseline is required to:

- Demonstrate instability under dynamic churn (Experiment-B)
- Evaluate improvements from a stateful autoscaler (Experiment-C)

Experiment-A is considered successful and complete.