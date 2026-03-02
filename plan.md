# Stateful Autoscaling Research Plan

## Research Goal

Design and evaluate a Kubernetes-native autoscaling mechanism for persistent-connection workloads (WebSocket, MQTT) that:

- Prevents connection drops during scale-down
- Avoids reconnection storms
- Eliminates replica oscillation
- Provides stable, connection-aware scaling

We compare default HPA behavior against a stateful autoscaler.


# Experiment-A — CPU-Based HPA Baseline

## Objective

Establish baseline behavior of Kubernetes Horizontal Pod Autoscaler (HPA) when applied to a persistent WebSocket workload.

## Configuration

- HPA metric: CPU utilization
- Target CPU: 60%
- Min replicas: 2
- Max replicas: 10
- Load duration: 300 seconds
- Scale-down stabilization: default (300s)

## Metrics Collected

- CPU usage (millicores)
- Active WebSocket connections
- Replica count
- Prometheus time-series export

## Expected Behavior

- Scale-up triggered by CPU rise.
- Overshoot possible during spike.
- Scale-down delayed due to stabilization window.
- No awareness of connection state.

## What It Proves

- Default HPA works for CPU-bound scaling.
- HPA is reactive (not predictive).
- Stabilization window delays scale-down.
- HPA has no semantic awareness of persistent connections.

This experiment establishes the baseline.

---

# Experiment-B — Dynamic Load Instability Demonstration

## Objective

Demonstrate instability of default CPU-based HPA under dynamic connection churn.

## Load Pattern

- Phase 1: High load (300s)
- Phase 2: Sudden drop to 0
- Phase 3: Immediate spike back to high load
- Repeat cycles

## Expected Observations

- Scale-down terminates pods with active connections.
- Clients reconnect aggressively.
- CPU spikes due to reconnection storm.
- HPA scales up again.
- Replica oscillation occurs.

## What It Proves

- Default HPA is unaware of connection draining.
- Abrupt scale-down induces instability.
- Persistent workloads behave differently than stateless HTTP.
- CPU-based metrics are insufficient for stateful safety.

This experiment justifies architectural change.

---

# Experiment-B2 (Optional but Strong) — HPA Using Connection Metric

## Objective

Evaluate whether changing the metric (CPU → active_connections) solves instability.

## Configuration

- HPA metric: Prometheus custom metric `active_connections`
- Same replica bounds.

## Expected Observations

- Scale-up aligns better with load.
- Scale-down still drops active connections.
- No draining logic.
- Reconnection spikes remain.

## What It Proves

Metric selection alone does not solve the statefulness problem.
The issue is architectural, not merely metric choice.

---

# Experiment-C — Stateful Autoscaler (Proposed Controller)

## Objective

Implement and evaluate a Kubernetes-native stateful autoscaler.

## Design Principles

- Scale based on connection count.
- Drain connections before pod termination.
- Delay termination until connection count = 0.
- Avoid scaling if redistribution incomplete.
- Optionally rebalance sessions.

## Implementation Strategy

- Custom controller (replaces HPA)
- Poll Prometheus directly
- Patch Deployment replica count
- Monitor per-pod connection metrics
- Graceful termination hook

## Expected Improvements

- No abrupt connection drops.
- No reconnection storm.
- Smooth replica transitions.
- Reduced oscillation.
- Improved stability during dynamic load.

## Comparison Metrics

- Replica oscillation amplitude
- Connection drop events
- CPU spike magnitude
- Scale-up latency
- Scale-down safety

---

# Final Evaluation Criteria

The stateful autoscaler is considered successful if it:

- Maintains connection continuity during scale-down.
- Prevents reconnection storms.
- Reduces replica oscillation compared to default HPA.
- Preserves scale-up responsiveness.
- Demonstrates measurable stability improvement.

---

# Research Narrative Flow

1. Show baseline (Experiment-A).
2. Show instability under churn (Experiment-B).
3. Show metric-only tuning insufficient (Experiment-B2).
4. Introduce architectural solution (Experiment-C).
5. Quantitatively compare all approaches.

---

# End Goal

"We built a Kubernetes-native autoscaler for persistent-connection workloads that prevents connection drops during scale-down and eliminates reconnection storms."
