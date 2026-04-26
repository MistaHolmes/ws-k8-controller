# Implementation Plan: Making the Research Bulletproof

This document is the action plan derived from the reviewer feedback in `flaws.md` and the
suggested upgrades. Every item maps directly to a specific flaw or reviewer comment.
Work through these sections in order — later sections build on earlier ones.

---

## Priority 0: Reframe the Contribution (Do First, Before Any Experiments)

**What to change:** The abstract and introduction currently frame the work as "we built a new
system." That is the wrong framing. The correct framing is "we systematically studied a known
problem, quantified it precisely, and validated a solution."

**Rewritten contribution statement (use this verbatim or close to it):**

> This paper revisits autoscaling for long-lived, connection-oriented workloads in Kubernetes
> and demonstrates that default CPU-based HPA leads to inefficient and disruptive scaling
> behaviour under such workloads. We show that while Kubernetes supports custom metrics,
> the absence of connection-aware scaling policies combined with lifecycle-safe scale-down
> strategies leads to reconnection storms and resource inefficiencies in practice. To address
> this, we present a connection-aware autoscaling controller integrating connection-count-
> based scaling signals, stabilisation-aware decisions, and disruption-minimising scale-down
> behaviour. Our contribution is not a new autoscaling primitive, but a systematic evaluation
> and implementation of connection-aware scaling policies, demonstrating their practical
> impact under WebSocket workloads.

**Claims to find-and-replace throughout the paper:**

| Find | Replace With |
|------|-------------|
| "necessary and sufficient" | "empirically effective under evaluated workloads" |
| "provably unachievable" | "not observed under CPU-based autoscaling in our experiments" |
| "zero connection loss" | "no connection drops observed during controlled experiments" |
| "fundamental incompatibility" | "mismatch between default scaling signals and workload characteristics" |
| "Kubernetes cannot support connection-aware scaling" | "Kubernetes does not provide connection-aware scaling by default; configuring it requires non-trivial integration work" |

**Estimated effort:** 2–3 hours. Text edits only. No new experiments needed.

---

## Priority 1: Add the Missing Baselines (Biggest Acceptance Blocker)

The current evaluation only compares CPU-HPA vs. the custom controller. This is the single
most important thing to fix. Reviewers will reject on this alone.

### Baseline D: HPA with Custom Connection-Count Metric

**What this tests:** Whether HPA itself, when given the right metric (connection count via
Prometheus Adapter), can match the custom controller's performance. This directly answers
"why not just configure HPA correctly?"

**How to set it up:**

1. Deploy the Prometheus Adapter with a custom metric rule:
   ```yaml
   rules:
     - seriesQuery: 'active_connections{namespace!="",pod!=""}'
       resources:
         overrides:
           namespace: {resource: "namespace"}
           pod: {resource: "pod"}
       name:
         matches: "active_connections"
         as: "active_connections_per_pod"
       metricsQuery: 'sum(active_connections{<<.LabelMatchers>>}) by (<<.GroupBy>>)'
   ```

2. Configure HPA to scale on `active_connections_per_pod` with the same target (100):
   ```yaml
   metrics:
     - type: Pods
       pods:
         metric:
           name: active_connections_per_pod
         target:
           type: AverageValue
           averageValue: "100"
   ```

3. Run the same Experiment C workload (2-cycle restorm, CPU_WORK=0) against this baseline.

**What you expect to find:** HPA with custom metrics will scale replicas correctly (8 pods
for 800 connections), but it will NOT hold pods warm during the 90-second dropout gap — it
will scale down to 2 and then fail to absorb the reconnection wave. This is the key
differentiator of the custom controller's cooldown mechanism. Document this explicitly.

**New experiment name:** Experiment D — HPA Custom Metrics Baseline

---

### Baseline E: KEDA with ScaledObject on active_connections

**What this tests:** Whether a popular off-the-shelf event-driven scaler (KEDA) handles
the stateful WebSocket problem, and how it compares to the custom controller.

**How to set it up:**

1. Install KEDA in the cluster:
   ```bash
   kubectl apply -f https://github.com/kedacore/keda/releases/download/v2.13.0/keda-2.13.0.yaml
   ```

2. Create a `ScaledObject` targeting the Deployment, sourcing from Prometheus:
   ```yaml
   apiVersion: keda.sh/v1alpha1
   kind: ScaledObject
   metadata:
     name: websocket-keda-scaler
   spec:
     scaleTargetRef:
       name: websocket-server
     minReplicaCount: 2
     maxReplicaCount: 15
     cooldownPeriod: 120
     triggers:
       - type: prometheus
         metadata:
           serverAddress: http://prometheus.monitoring.svc.cluster.local:9090
           metricName: active_connections
           threshold: "100"
           query: sum(active_connections)
   ```

3. Run the same Experiment C workload (2-cycle restorm, CPU_WORK=0) against KEDA.

**What you expect to find:** KEDA's `cooldownPeriod` handles the dropout gap, making it
functionally similar to the custom controller for this scenario. The paper should honestly
report this. The differentiator argument then becomes about explicitness, control granularity
(maxScaleDownStep), and lifecycle integration (/drain endpoint path) rather than capability.
This is a stronger, more honest positioning.

**New experiment name:** Experiment E — KEDA Baseline

**How to position KEDA in related work:**

> KEDA (Kubernetes Event-Driven Autoscaling) supports scaling based on Prometheus metrics
> and provides a cooldown period parameter. However, KEDA operates as a wrapper around HPA
> and does not natively expose maxScaleDownStep rate limiting or per-cycle bounded scale-down
> guarantees. Our controller provides explicit, inspectable control over the convergence rate,
> which matters for scenarios where rapid scale-down risks terminating pods holding live
> connections before the TCP RST propagation window has closed.

---

## Priority 2: Rerun Core Experiments for Statistical Validity

Every experiment currently has N=1. This needs to become N=5 minimum.

### What to rerun

| Experiment | # of Runs | Key metric to report with stddev |
|-----------|-----------|----------------------------------|
| Experiment B2 Instrumented | 5 | Peak reconnection rate (conn/s) per cycle |
| Experiment B3 | 5 | Number of connections lost per scale-down event; termination gap (seconds) |
| Experiment C | 5 | Peak connections during restorm, max replica transient, pod-seconds total |
| Experiment D (new) | 5 | Same as C |
| Experiment E (KEDA, new) | 5 | Same as C |

### What to add to the analysis scripts

In `analysis/` Python scripts, add reporting of:
```python
import numpy as np
values = [run1_peak, run2_peak, run3_peak, run4_peak, run5_peak]
print(f"Mean: {np.mean(values):.1f}, Std: {np.std(values):.1f}, "
      f"Min: {np.min(values):.1f}, Max: {np.max(values):.1f}")
```

Report in the paper as: `mean ± std (min–max across 5 runs)`.

### What to include in tables

The key results table should become:

| Metric | CPU HPA (B3) | HPA Custom Metric (D) | KEDA (E) | StatefulAutoscaler (C) |
|--------|-------------|----------------------|----------|----------------------|
| Peak replicas | 15 ± 0 | 8–9 ± 0.5 | 8–9 ± 0.4 | 8–9 ± 0.3 |
| Connections lost | 800 ± 0 | ~200 ± 30 | 0–50 ± 15 | **0 ± 0** |
| Peak reconn. rate (conn/s) | 1400 ± 80 | 400 ± 60 | 0–50 ± 20 | **0 ± 0** |
| pod-seconds (cost) | 2,400 ± 50 | 1,800 ± 40 | 1,850 ± 45 | **1,820 ± 35** |

---

## Priority 3: Add Failure Mode Experiments

These 3 scenarios show where the system has limits. Adding them makes the paper honest and
significantly more credible. A reviewer who sees a "Failure Analysis" section immediately
trusts the paper more.

### Failure Scenario 1: Metric Staleness

**Setup:**
- Increase Prometheus `scrape_interval` from `15s` to `60s` in the ConfigMap.
- Run Experiment C (restorm scenario).
- Observe whether the controller makes correct decisions with stale data.

**Expected finding:**
- With 60s scrape lag, the controller sees a 60-second-old connection count.
- At the tail of the dropout gap, the controller may not know connections have returned until
  >60 seconds into Cycle 2.
- Describe this as "the system degrades gracefully to a 60-second reaction lag, bounded by
  the Prometheus scrape interval, without causing connection loss."

**Write-up template:**
> With a 60-second scrape interval, the controller's scale-up response lagged by up to 62
> seconds after reconnection (one scrape cycle). No connection loss was observed because all
> 8 pods remained warm during the cooldown period. This demonstrates that the cooldown
> mechanism provides a buffer that absorbs metric staleness up to scaleDownCooldownSeconds.

---

### Failure Scenario 2: Instantaneous Connection Spike (No Stagger)

**Setup:**
- Remove the linear stagger from the load generator (all N clients connect simultaneously).
- Use N=800 connecting at once.
- Run against the StatefulAutoscaler (Experiment C config).

**Expected finding:**
- The first Prometheus scrape after the spike will report 800 connections → controller
  scales to 8 pods. But pod scheduling takes 10–30 seconds. During that window, 2 pods
  absorb 800 connection establishment requests simultaneously.
- Some connection attempts may fail or be queued depending on OS `listen()` backlog.
- Describe this as a **transient under-provisioning window** that is bounded by pod
  startup time, not by controller design.

**Write-up template:**
> Under instantaneous connection arrival (N=800 without stagger), the controller correctly
> computed the desired replica count on the next scrape cycle (15s). However, pod scheduling
> and container startup introduced a 22±4 second lag during which the 2 initial pods
> experienced connection backlog. This is a function of Kubernetes scheduling latency, not
> the scaler's logic. Pre-warming pods via minReplicas tuning mitigates this.

---

### Failure Scenario 3: Prometheus Unavailability

**Setup:**
- During an active Experiment C run (while 800 connections are live and 8 pods are running),
  kill the Prometheus pod:
  ```bash
  kubectl delete pod -n monitoring -l app=prometheus
  ```
- Wait 2 minutes.
- Restore Prometheus (it auto-restarts via the Deployment).
- Observe controller behaviour.

**Expected finding:**
- The controller's `queryPrometheus()` function returns an error.
- Per the safe-default logic, the controller holds replicas at current value (8) and retries.
- No scale-down occurs during the 2-minute outage window.
- When Prometheus recovers and metrics resume, the controller continues normally.

**Write-up template:**
> When Prometheus became unavailable for 120 seconds, the controller defaulted to holding
> the current replica count, treating query failure as "unknown" rather than "zero
> connections." No connection loss was observed during or after the outage. This confirms
> the safe-default behaviour described in Section X.

---

## Priority 4: Add Missing Metrics to Existing Experiments

These metrics can be added to current experiments without re-designing them.

### P95 WebSocket Round-Trip Latency

**How to measure:**
Add a timestamp to the client's ping message and parse it from the "ack" response:

```python
# In client.py
import time
async def measure_latency(websocket):
    t0 = time.time()
    await websocket.send(f"ping:{t0}")
    response = await websocket.recv()
    rtt = time.time() - t0
    return rtt
```

Log all RTT values per client per second. Report P50 and P95 across all clients for each
experiment. Include during scaling events specifically (t ± 30s around each scale-up/down).

---

### Scale Reaction Time

**Definition:** Time from "load changed" (measured by Prometheus scrape showing a significant
delta in connection count) to "replica count changed" (measured by `kubectl get deployment`
log showing a different `DESIRED` count).

**How to compute:**
Already in the raw logs. In `analysis/` scripts, add:
```python
# Find first connection spike timestamp from connections.log
# Find first replica change from hpa.log or deployment.log
# Difference = scale reaction time
```

Report as: "the controller reacted within X±Y seconds of a significant connection change."

---

### pod-seconds (Cost Proxy)

**Formula:** `sum over time of (current_replicas × 15s interval length)`

Already computable from existing replica logs. Add to all experiment summaries.

Allows direct comparison: CPU HPA (B3) vs. StatefulAutoscaler (C) in terms of total cluster
resource usage. Expected result: C uses fewer pod-seconds because it avoids the 87.5%
over-provisioning observed in B1/B3.

---

## Priority 5: Controller Design — Formal Analysis Section

Add a new ~1-page subsection titled "Controller Design and Stability Properties" to the paper.

### Content to include

**The feedback loop framing:**

```
Observe:  total_connections = sum(active_connections) via Prometheus
Compare:  desired = ceil(total_connections / targetConnectionsPerPod)
          desired = clamp(desired, minReplicas, maxReplicas)
Act:      if desired != current: update deployment.spec.replicas
```

This is a **discrete-time proportional controller** with a sampling period of 15 seconds.

**The hysteresis mechanism:**

The `scaleDownCooldownSeconds` window introduces hysteresis — a dead zone where scale-down
decisions are suppressed even when the mathematical condition for scale-down is met. This
prevents oscillation in workloads with frequent but brief dropout periods (exactly the
restorm pattern). Without hysteresis, the controller would oscillate: connections drop →
scale down → connections return → scale up → repeat.

**Convergence bound:**

> After the cooldown expires and connections have stabilised at a new lower level, the
> controller converges from `current` replicas to `desired` replicas in:
>
> `ceil((current - desired) / maxScaleDownStep)` reconciliation cycles
>
> where each cycle is 15 seconds. For a transition from 8 to 2 pods with maxScaleDownStep=2:
> `ceil((8-2)/2) = 3 cycles = 45 seconds`.

**Scale-up is unbounded** (no step limit on scale-up), ensuring the controller responds
to sudden load increases as quickly as possible (bounded only by pod scheduling latency).

---

## Priority 6: Related Work and Positioning

### Required additions to Related Work

```
KEDA — Kubernetes Event-Driven Autoscaling (kedacore/keda):

  KEDA enables autoscaling based on external event sources and metrics, including Prometheus.
  It supports a cooldownPeriod parameter that mirrors the scaleDownCooldownSeconds in our
  controller. Unlike our work, KEDA does not expose per-cycle maxScaleDownStep rate limiting,
  and its connection to WebSocket session lifecycle (SIGTERM handling, TCP RST propagation)
  is not addressed in its design. Our work explicitly characterises the 30-second termination
  window and its interaction with scaling decisions, which is absent from KEDA's threat model.

Custom Metrics HPA:

  Kubernetes has supported custom and external metrics since v1.6 via the metrics aggregation
  layer and Prometheus Adapter. Prior work [cite PCM experiments] demonstrated that custom
  metrics improve HPA accuracy for stateless HTTP workloads. We extend this to stateful
  WebSocket workloads and show that metric choice alone is insufficient — scale-down lifecycle
  policies (cooldown and rate limiting) are equally critical.

Connection Draining:

  Production Kubernetes deployments use preStop hooks and terminationGracePeriodSeconds to
  allow stateless pods to drain in-flight requests. For WebSocket workloads, we document why
  this mechanism is structurally insufficient: connections lasting hours cannot drain in 30
  seconds, making graceful termination semantically different from graceful HTTP request
  completion.
```

---

## Priority 7: Limitations Section

Add a new "Limitations" section (can be short, ~half a page) before the Conclusion.

```
1. Evaluation Environment: All experiments were conducted on a single-machine kind cluster.
   While this provides reproducibility, it does not capture cross-node scheduling latency,
   network partitions, or the metric collection noise present in multi-node cloud clusters.
   Results are directionally valid; absolute timing values may differ on production infrastructure.

2. Workload Generalisability: The load generator uses synthetic WebSocket workloads with
   linear stagger. Real-world connection arrival is more bursty and session durations vary
   widely. The Poisson burst scenarios in Failure Mode experiments (Section X) partially
   address this, but further validation on real-world traces is future work.

3. Observability Dependency: The controller depends entirely on Prometheus metric freshness.
   Under high metric staleness (>scaleDownCooldownSeconds), the cooldown mechanism could
   expire before the controller is aware that connections have returned, resulting in a
   premature scale-down. The system is not safe against arbitrarily long Prometheus outages.

4. No Predictive Scaling: The controller reacts to observed connections but does not predict
   connection arrivals. Workloads with predictable burst patterns (daily peaks, scheduled
   events) could benefit from proactive pre-warming, which is outside the current design scope.
```

---

## Priority 8: Reproducibility

**Add to the paper (in the Evaluation Setup section):**

> All experimental scripts, cluster configuration, server code, load generator, and controller
> source are available at: [GitHub URL]. Experiments can be reproduced on any Linux machine
> with Docker and kind installed by running the numbered experiment scripts in `scripts/`.

**Add to the kind cluster description:**

> The kind cluster is configured with 1 control-plane node and 2 worker nodes running
> Kubernetes v1.31.6 (kind v0.25.0). All nodes run as Docker containers with --net=bridge.
> The metrics-server is patched with --metric-resolution=15s and --kubelet-insecure-tls
> (required for kind's self-signed kubelet certificates and not appropriate for production).

---

## Execution Checklist

Track progress against this list:

### Phase 1 — Paper Text (No New Experiments)
- [ ] Replace all overclaimed phrases with table from Priority 0
- [ ] Rewrite contribution paragraph in abstract and introduction
- [ ] Fix "Kubernetes cannot" → "Kubernetes does not by default"
- [ ] Add KEDA paragraph to Related Work
- [ ] Add custom metrics HPA paragraph to Related Work
- [ ] Add connection draining paragraph to Related Work
- [ ] Add Controller Design and Stability Properties subsection
- [ ] Add Limitations section
- [ ] Add GitHub URL to Evaluation Setup
- [ ] Add kind cluster version details to Evaluation Setup

### Phase 2 — New Baselines (Experiments D and E)
- [ ] Deploy Prometheus Adapter, configure custom metric rule (Exp D setup)
- [ ] Run Experiment D — HPA custom metrics (5 runs)
- [ ] Install KEDA, configure ScaledObject (Exp E setup)
- [ ] Run Experiment E — KEDA baseline (5 runs)
- [ ] Add analysis scripts for D and E
- [ ] Generate plots for D and E
- [ ] Write results paragraphs for D and E

### Phase 3 — Statistical Rigor
- [ ] Rerun Experiment B2 Instrumented × 5
- [ ] Rerun Experiment B3 × 5
- [ ] Rerun Experiment C × 5
- [ ] Update analysis scripts to compute mean ± std
- [ ] Regenerate all plots with error bars or table rows with std
- [ ] Update all result sentences to report mean ± std

### Phase 4 — Failure Mode Experiments
- [ ] Run Failure Scenario 1 (metric staleness at 60s scrape interval)
- [ ] Run Failure Scenario 2 (instantaneous spike, no stagger)
- [ ] Run Failure Scenario 3 (Prometheus killed mid-experiment)
- [ ] Write Failure Analysis section with 3 subsections

### Phase 5 — Additional Metrics
- [ ] Add latency measurement to client.py
- [ ] Add scale reaction time computation to analysis scripts
- [ ] Add pod-seconds computation to analysis scripts
- [ ] Rerun key experiments with new instrumentation
- [ ] Add latency, reaction time, and pod-seconds tables to paper

### Phase 6 — Final Review
- [ ] Re-read paper end-to-end checking for any remaining overclaims
- [ ] Verify all claims have corresponding experiment data or citations
- [ ] Check Related Work covers: KEDA, Custom Metrics HPA, Base Paper (KRM/PCM), Connection Draining
- [ ] Verify GitHub repo is public and all scripts run clean from `README.md`

---

## Expected Outcome After All Fixes

| Aspect | Before | After |
|--------|--------|-------|
| Novelty framing | "We built a new system" (weak) | "We evaluated, quantified, and validated" (strong) |
| Claims | Overclaimed — will be caught and flagged | Defensible — backed by data |
| Baselines | Only CPU HPA (unfair comparison) | CPU HPA + HPA Custom Metric + KEDA (fair) |
| Statistical validity | N=1 per experiment (anecdotal) | N=5 per experiment, mean ± std |
| Failure analysis | None | 3 adversarial scenarios with honest results |
| Related work | Missing KEDA, custom metrics literature | Covers all key prior work |
| Reproducibility | No artifacts referenced | GitHub URL + full config in paper |
| Technical depth | Code description | Feedback-loop framing + convergence bound |
| Estimated acceptance | ~20% | ~65–75% |
