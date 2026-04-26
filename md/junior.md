# STAR Project — End-to-End Developer Guide

> **Audience**: SDE-1 with general software engineering knowledge but minimal Kubernetes experience.
> **Purpose**: Understand this research project from scratch — what problem it solves, how every experiment works, what was found, and where it is going next.

---

## Table of Contents

1. [Background: What is Kubernetes and Why Does Scaling Matter?](#1-background-what-is-kubernetes-and-why-does-scaling-matter)
2. [The Core Problem this Project Solves](#2-the-core-problem-this-project-solves)
3. [Project Structure at a Glance](#3-project-structure-at-a-glance)
4. [Phase 0 — Base Paper Implementation (The Foundation)](#4-phase-0--base-paper-implementation-the-foundation)
   - [4.1 KRM Experiment — CPU-based HPA](#41-krm-experiment--cpu-based-hpa)
   - [4.2 PCM Experiment — Prometheus Custom Metrics HPA](#42-pcm-experiment--prometheus-custom-metrics-hpa)
   - [4.3 Lessons from the Base Paper](#43-lessons-from-the-base-paper)
5. [Phase 1 — WebSocket Experiments (The Main Research)](#5-phase-1--websocket-experiments-the-main-research)
   - [5.1 Shared Infrastructure for All Experiments](#51-shared-infrastructure-for-all-experiments)
   - [5.2 Experiment A — Baseline: Does HPA Even Work for WebSockets?](#52-experiment-a--baseline-does-hpa-even-work-for-websockets)
   - [5.3 Experiment B1 — Cyclic Churn: Over-Provisioning Trap](#53-experiment-b1--cyclic-churn-over-provisioning-trap)
   - [5.4 Experiment B2 (Extended LOW) — The Experimental Wander *(not in the paper)*](#54-experiment-b2-extended-low--the-experimental-wander-not-in-the-paper)
   - [5.5 Experiment B2 (Instrumented) — Quantifying the Reconnection Storm](#55-experiment-b2-instrumented--quantifying-the-reconnection-storm)
   - [5.6 Experiment B3 — The Fatal Flaw (Control Baseline)](#56-experiment-b3--the-fatal-flaw-control-baseline)
   - [5.7 Experiment C — The Custom StatefulAutoscaler (The Solution)](#57-experiment-c--the-custom-statefulautoscaler-the-solution)
6. [The Custom Controller — Architecture Deep Dive](#6-the-custom-controller--architecture-deep-dive)
7. [Phase 2 — MQTT Experiments (Future Work)](#7-phase-2--mqtt-experiments-future-work)
8. [Edge Cases and Caveats](#8-edge-cases-and-caveats)
9. [Summary Evidence Chain](#9-summary-evidence-chain)
10. [Key Numbers Across All Experiments](#10-key-numbers-across-all-experiments)
11. [Glossary](#11-glossary)

---

## 1. Background: What is Kubernetes and Why Does Scaling Matter?

### What is Kubernetes?

Imagine you have a web application — a chat server. Thousands of users connect to it. One server (one machine, one process) can only handle so many users at once. When load spikes, you need more servers. When load drops, you want to shut down extra servers to save money.

**Kubernetes** (K8s) is a system that manages running applications across a fleet of machines. Key concepts you need to know:

| Term | Plain English Explanation |
|------|--------------------------|
| **Cluster** | The whole fleet of machines Kubernetes manages. Has one "boss" machine (control-plane) and several "worker" machines (nodes). |
| **Node** | A single machine (physical or virtual) inside the cluster. Think of it as a single server. |
| **Pod** | The smallest deployable unit in Kubernetes. A pod wraps one (or more) running containers. Think of it as one running instance of your application. |
| **Deployment** | A Kubernetes object that says "I want N copies of this pod running at all times." It manages creating, destroying and updating pods. |
| **Service** | A stable network address that routes traffic to whichever pods are healthy. Clients connect to the Service, not directly to a pod. |
| **Container** | A lightweight package of your app + its runtime (like Docker). Pods contain containers. |
| **kubectl** | The command-line tool to talk to a Kubernetes cluster. Like `git` for Kubernetes. |
| **kind** | "Kubernetes IN Docker." Creates a fake multi-node Kubernetes cluster entirely inside Docker containers on your local laptop. Used for local testing. |
| **HPA (Horizontal Pod Autoscaler)** | A built-in Kubernetes controller that automatically increases or decreases the number of pod replicas based on metrics like CPU usage. |
| **Prometheus** | An open-source monitoring system that scrapes (collects) metrics from your services on a regular interval and stores them as time-series data. |
| **Metrics Server** | A lightweight Kubernetes add-on that collects CPU and memory stats from each node and pod, making them available to HPA. |
| **CRD (Custom Resource Definition)** | A way to extend Kubernetes with your own object types. Like adding a new table to a database schema. |
| **Operator / Controller** | A program running inside the cluster that watches Kubernetes objects and takes actions (e.g., creates/deletes pods) in response. The "brains" of automation. |
| **RBAC** | Role-Based Access Control. Controls what a service account (like a controller) is allowed to do inside the cluster. |
| **SIGTERM / SIGKILL** | Unix signals. `SIGTERM` politely asks a process to shut down (it can clean up). `SIGKILL` forcefully murders the process instantly, no cleanup. |
| **terminationGracePeriodSeconds** | How long Kubernetes waits after sending `SIGTERM` before escalating to `SIGKILL`. Default = 30 seconds. |

### How Does HPA Work?

```
Every 15 seconds:
  HPA asks metrics-server: "What is the average CPU % across all pods?"

  If average CPU > target (e.g., 60%):
    desired_replicas = ceil(current_replicas * (current_cpu / target_cpu))
    scale UP deployment

  If average CPU < target AND CPU has been low for > stabilizationWindow:
    scale DOWN deployment
```

HPA is reactive — it only responds to what already happened. It does not predict future load.

### What is a WebSocket?

HTTP (normal web requests) works like a phone call you hang up after each sentence. You ask, server answers, connection closes.

A **WebSocket** is like an open phone line — once established, the connection stays open indefinitely. Both sides can send messages at any time without re-dialing. This is used in:

- Real-time chat apps (Slack, Discord)
- Multiplayer games
- Live dashboards / stock tickers
- IoT device fleets (devices report sensor data continuously)
- Collaborative editing (Google Docs)

WebSocket connections are called **stateful** because the server must remember the state (the open connection, the associated user session) for the entire duration — which might be hours or days.

### What is MQTT?

MQTT (Message Queuing Telemetry Transport) is a publish-subscribe protocol designed for IoT devices. A device (e.g., a temperature sensor) connects to an **MQTT broker** and either publishes data to a "topic" or subscribes to receive messages on a topic. Like WebSockets, MQTT connections are persistent and long-lived.

---

## 2. The Core Problem this Project Solves

### The Mismatch

HPA was designed for **stateless** workloads. A stateless app (like a REST API) handles each request independently — any pod can handle any request, and terminating a pod mid-flight at worst drops one in-flight request, which the client retries transparently.

WebSocket and MQTT workloads are **stateful**. Each active connection lives on a specific pod. If you kill that pod:

1. **Every connection on that pod is immediately severed.** 100 connected users suddenly get a disconnect error.
2. **All 100 users reconnect at the same time.** This is a **reconnection storm** — a massive simultaneous surge of TCP handshakes hitting the remaining pods.
3. **The reconnection storm drives CPU through the roof.** HPA sees the CPU spike and scales UP, just as it was trying to scale DOWN.
4. **Oscillation begins.** Scale down → storm → scale up → calm → scale down → storm → repeat. The cluster never stabilizes.

### What HPA Does Wrong

```
Scenario: 500 users are connected. They all go idle (stop sending messages).
CPU drops to near 0%. HPA sees: "CPU is below target, time to remove pods."
HPA kills 3 pods. Those 3 pods happen to hold 300 live connections.
300 users get a disconnect. 300 users immediately reconnect.
CPU spikes hard. HPA scales back up.
→ The problem was never solved. It just repeats.
```

CPU is a **lagging, indirect indicator** of connection-based load. A user can hold a WebSocket connection for hours while generating zero CPU. HPA is blind to this.

### The Project's Solution

Build a **custom Kubernetes controller** (the `StatefulAutoscaler`) that:

1. Scales based on **connection count**, not CPU.
2. Never terminates a pod that still holds active connections.
3. Uses a **cooldown window** to avoid panic scale-downs during brief network blips.
4. Proves the problem empirically across a series of controlled experiments.

---

## 3. Project Structure at a Glance

```
future-work/
├── base-paper-implementation/   ← Phase 0: original stateless HPA experiments
│   ├── krm-experiment/          ← CPU-based HPA baseline (stateless HTTP app)
│   └── pcm-exp/                 ← Prometheus custom metrics HPA (stateless HTTP app)
│
├── workloads/
│   ├── websocket/               ← The WebSocket server (Python asyncio + websockets library)
│   │   └── app/server.py        ← Core server: handles connections, exposes /metrics
│   └── mqtt/                    ← (Future) MQTT broker
│
├── load-generator/
│   └── websocket-client/        ← Python async client: opens N WebSocket connections
│       └── client.py
│
├── experiments/
│   └── websocket/
│       ├── experiment-a-hpa-baseline/
│       ├── experiment-b1-hpa-churn/
│       ├── experiment-b2-hpa-churn-instrumented/
│       ├── experiment-b3-hpa-idle-connections/
│       └── experiment-c-stateful/
│
├── controller/                  ← The custom StatefulAutoscaler (Go / Kubebuilder)
│   ├── internal/controller/     ← Core reconciliation loop
│   └── api/v1alpha1/            ← CRD type definitions
│
├── scripts/                     ← Shell scripts that orchestrate each experiment end-to-end
│   ├── run-experiment-a.sh
│   ├── run-experiment-b1.sh
│   ├── run-experiment-b2.sh
│   ├── run-experiment-b3.sh
│   └── run-experiment-c.sh
│
├── analysis/                    ← Python scripts to parse logs and generate plots
│
└── results/
    ├── raw/                     ← Raw CSV logs from experiments
    └── processed/               ← Generated plots and analysis
```

Every experiment follows the same pattern:
1. A shell script creates a fresh `kind` cluster.
2. It deploys the server, load generator, and monitoring.
3. It runs the load pattern, collecting logs every few seconds.
4. It saves raw logs to `results/raw/`.
5. An analysis Python script parses the logs and generates plots.

---

## 4. Phase 0 — Base Paper Implementation (The Foundation)

Before the WebSocket experiments, an earlier piece of research evaluated HPA on **stateless** HTTP workloads. This section is crucial context because it explains *why* the team even considered building a custom controller.

### 4.1 KRM Experiment — CPU-based HPA

**KRM** = Kubernetes Resource Metrics (the native metrics-server pipeline).

#### What was tested

A simple HTTP server that, when it receives a request, runs a CPU-intensive spin loop for a configurable number of iterations. The load generator fires HTTP requests at it at high rate. HPA watches CPU and scales the deployment up or down.

The key variable: **`--metric-resolution`** (how often metrics-server collects CPU samples). Values tested: 15s, 30s, 60s.

#### What was found

- At `15s` resolution: HPA reacted quickly. Scaling lag was minimal.
- At `60s` resolution: HPA saw stale data. The "staircase effect" appeared — HPA would see the same old CPU value across multiple 15-second sync cycles and take multiple scale-up steps when one would have been enough.
- **Insight**: Because CPU is a *lagging indicator* (it's already high by the time HPA notices), there is always some hysteresis (delay between load arrival and scaling actuation).

#### Key metric: `pod_seconds`

`pod_seconds` = (number of replicas) × (time each replica was running). This is a proxy for cloud resource cost. Over-provisioning wastes `pod_seconds`. Under-provisioning drops requests.

#### Caveat

This experiment proved only that the *timing* of CPU sampling matters for stateless apps. It did not expose anything about connection state, because HTTP requests are stateless — a pod can be terminated mid-request and the client just retries.

---

### 4.2 PCM Experiment — Prometheus Custom Metrics HPA

**PCM** = Prometheus Custom Metrics. Instead of using the built-in metrics-server CPU signal, HPA is pointed at custom metrics exposed by Prometheus.

#### Three configurations tested

| Name | Metric used by HPA |
|------|--------------------|
| PCM-CPU | CPU, but routed through Prometheus (to isolate scrape latency) |
| PCM-H | `http_requests_per_second` (a leading indicator — directly measures incoming traffic) |
| PCM-CH | Hybrid: `max(CPU_recommendation, HTTP_recommendation)` |

#### The Staircase Effect — explained

```
Prometheus scrape_interval = 60s.
HPA sync = 15s.

t=0s:   Load spikes. CPU goes to 200%.
t=0s:   Prometheus hasn't scraped yet — still has old data (0%).
t=15s:  HPA checks. Prometheus metric = 0%. HPA does nothing.
t=30s:  HPA checks. Prometheus metric = 0%. HPA does nothing.
t=45s:  HPA checks. Prometheus metric = 0%. HPA does nothing.
t=60s:  Prometheus finally scrapes. Metric = 200%.
t=60s:  HPA wakes up: "Oh! 200% CPU." Scales up.

→ 60 seconds of unhandled load. Users experienced slowness for a full minute.
```

With `scrape_interval=15s`, this collapses to ~15 seconds of lag — much better.

#### PCM-H: Leading indicator

`http_requests_per_second` is measured *at the ingress* — the second a new request lands, the metric changes. This is a **leading indicator**: it signals load before CPU even has time to rise. PCM-H dramatically reduced scaling lag.

#### PCM-CH: Hybrid max-selection

Using `max(CPU, HTTP)` means HPA will scale up if *either* metric says so. This prevents a scenario where CPU is low but request rate is suddenly spiking — the HTTP metric catches it first.

#### Caveat and the bridge to this project

The PCM experiments made HPA faster and smarter — for stateless HTTP. But they still fundamentally relied on the assumption that scaling down is safe. For WebSocket workloads, no metric tuning can fix the fact that **tearing down a pod forcibly severs live connections**. That is an architectural problem, not a measurement problem.

---

### 4.3 Lessons from the Base Paper

| Lesson | Implication for WebSocket work |
|--------|-------------------------------|
| CPU is a lagging indicator | Even if you could use CPU for WebSockets, you'd still be too slow |
| Prometheus custom metrics give leading signals | The custom controller should use Prometheus `active_connections` |
| Scrape interval matters | Set Prometheus `scrape_interval: 15s` in all experiments |
| Hybrid metric selection prevents saturation | Future work: combine connection count with CPU ceiling |
| Stateless assumptions baked into HPA | Fundamental incompatibility with persistent connections |

---

## 5. Phase 1 — WebSocket Experiments (The Main Research)

### 5.1 Shared Infrastructure for All Experiments

Every WebSocket experiment shares the same basic cluster setup. Understand this once and you'll understand all experiments.

#### The Cluster

```bash
kind create cluster --config scripts/kind.yml
# kind.yml defines: 1 control-plane node + 2 worker nodes
```

#### The WebSocket Server (`workloads/websocket/app/server.py`)

A Python `asyncio` server using the `websockets` library.

Key behaviours:
- Accepts persistent WebSocket connections.
- On connection open: increments `active_connections` Prometheus gauge.
- On connection close: decrements `active_connections` gauge.
- On message receipt: optionally runs a CPU spin-loop (`CPU_WORK=1`) or does nothing (`CPU_WORK=0`).
- Exposes `/metrics` on port `8080` in Prometheus text format.
- Exposes `/drain` on port `8080` — when POSTed to, the server rejects new connections and waits for existing ones to close on their own (used by the custom controller, not by HPA).

```python
# Simplified server logic
async def handler(websocket):
    ACTIVE_CONNECTIONS.inc()        # Prometheus gauge +1
    NEW_CONNECTIONS.inc()           # Prometheus counter +1
    try:
        async for message in websocket:
            if CPU_WORK > 0:
                for _ in range(CPU_WORK):  # Artificial CPU burn
                    pass
            await websocket.send("ack")
    finally:
        ACTIVE_CONNECTIONS.dec()    # Prometheus gauge -1
```

The `CPU_WORK` environment variable is set in the Kubernetes Deployment manifest. Setting it to `1` makes every ping generate measurable CPU. Setting it to `0` makes the server idle regardless of how many connections it holds.

#### The Load Generator (`load-generator/websocket-client/client.py`)

A Python `asyncio` client that runs as a Kubernetes Job. Spawns N concurrent WebSocket connections.

Key feature — **linear stagger** to avoid overwhelming the server before HPA can scale:
```python
# Don't open all N connections at the same moment
delay = (client_index / CLIENTS) * RAMP_UP_DURATION
await asyncio.sleep(delay)
# Then connect:
async with websockets.connect(SERVER_URL) as websocket:
    ...
```
This smoothly distributes 800 connection attempts over 90 seconds.

#### Prometheus Monitoring

Installed using the Prometheus Helm chart (or raw manifests). Scrapes all pods with the annotation `prometheus.io/scrape: "true"` on port `8080` every 15 seconds.

```yaml
# prometheus configmap
global:
  scrape_interval: 15s
```

#### Metrics Server

Required for HPA to function. Patched to use `--metric-resolution=15s` (default is 60s) so that CPU data reaches HPA faster.

---

### 5.2 Experiment A — Baseline: Does HPA Even Work for WebSockets?

**Location**: `scripts/run-experiment-a.sh`, `experiments/websocket/experiment-a-hpa-baseline/`

#### Goal

Before declaring HPA broken for WebSockets, check: does it work at all under the most favorable possible conditions?

#### Why "most favorable"?

HPA only understands CPU. For HPA to correctly scale a WebSocket workload, CPU must be tightly correlated with connection count. The server is run with `CPU_WORK=1` — every ping message triggers a CPU spin loop. This creates an artificial but perfect correlation:

```
More connections → More pings → More CPU work → Higher CPU% → HPA scales up
Fewer connections → Fewer pings → Less CPU work → Lower CPU% → HPA scales down
```

This is NOT how real WebSocket workloads behave (in practice, connections are mostly idle), but it gives HPA the best possible chance to succeed.

#### Setup

| Parameter | Value |
|-----------|-------|
| `CPU_WORK` | `1` (each ping triggers spin loop) |
| Load | 800 clients ramp up over ~90s, stay connected and ping for 330s total |
| HPA target CPU | 60% average utilization |
| minReplicas | 2 |
| maxReplicas | 10 |
| Stabilization window (scale-down) | 300s (default — 5 minutes) |

#### What Happened

```
t=0s:    2 pods running. No connections.
t=30s:   400 connections established. CPU spikes to 97% per pod.
t=60s:   HPA scales: 2 → 4 pods.
t=90s:   CPU still high. HPA scales: 4 → 5 pods.
t=120s:  5 pods. CPU settles at ~60% per pod. Stable.
t=330s:  Load generator terminates. All 400 connections drop. CPU → 0%.
t=680s:  After 350 seconds of 0% CPU, HPA finally scales down: 5 → 2 pods.
```

#### Result: HPA "works" here

Under ideal (artificial) conditions, CPU-based HPA correctly scaled the WebSocket server.

**Peak connections**: 388 active.
**Peak replicas**: 5.
**Scale-down lag**: 350 seconds (the 5-minute stabilization window plus some buffer).

#### The Hidden Danger

The 350-second scale-down lag is intentional — it prevents HPA from scaling down too quickly when load temporarily dips. But it also means if clients are still connected and just idle for a moment, HPA will eventually try to scale down anyway. The next experiment exposes what happens during that scale-down.

#### Edge Cases / Caveats

- **The artificial CPU correlation is the whole reason this works.** Real WebSocket apps (chat, IoT, games) spend most of their time idle. Remove `CPU_WORK=1` and HPA would never see a signal to scale at all.
- **388 connections, not 400**: Some connections failed to establish due to the initial pod being overwhelmed before the stagger took effect (a tiny race condition at t=0).
- **The 5-minute stabilization window**: This was intentionally kept at default to show "best case" HPA behavior. Shortening it (as done in B3) makes things far more dangerous.

---

### 5.3 Experiment B1 — Cyclic Churn: Over-Provisioning Trap

**Location**: `scripts/run-experiment-b1.sh`, `experiments/websocket/experiment-b1-hpa-churn/`

#### Goal

Simulate a realistic workload that alternates between high activity and idle periods. Many real applications have this pattern (e.g., a game server during rounds vs. between rounds, a stock trading server during market hours vs. off-hours).

#### Load Pattern

```
HIGH phase (60s): 800 clients pinging heavily (CPU > 60%)
LOW phase (30s):  clients go idle (CPU ≈ 0%), but connections stay OPEN
... repeat × 5 cycles
```

The total cycle period is only 90 seconds — far shorter than HPA's default **300-second (5-minute)** scale-down stabilization window. This means HPA can never finish a scale-down before the next HIGH phase starts. In fact, even after 5 full cycles (450 seconds total), the 300-second stabilization window means HPA needs yet another 300+ seconds to recover to `minReplicas` after the final cycle ends.

#### What Happened

```
t=5s:    HIGH starts. 419 connections. CPU spikes to 122%.
t=12s:   HPA: 2 → 5 pods.
t=27s:   HPA: 5 → 8 pods.
t=65s:   LOW starts. CPU drops. HPA wants to scale down, but stabilization window starts.
t=83s:   NEW HIGH starts. HPA: 8 → 10 pods (still going up!).
t=99s:   HPA hits maxReplicas = 15. Ceiling hit within 99 seconds.
t=415s:  After a very long LOW phase, HPA finally starts scaling: 15 → 13.
t=655s:  Still descending: 13 → 12.
t=700s:  12 → 11.
t=732s:  11 → 6.
t=747s:  6 → 2. (Finally back to minimum after ~650 seconds.)
```

#### Result: HPA is stuck at maxReplicas

HPA hit the hard ceiling of 15 replicas within 99 seconds and stayed there for nearly 11 minutes. During this time, 13 extra pods sat idle, consuming cluster resources, holding no active useful work.

#### Why This Happens

The 5-minute (300-second) default stabilization window exists to prevent premature scale-downs. But with 90-second cycles (60s HIGH + 30s LOW), every LOW phase (only 30 seconds long) ends before the stabilization window even begins to measure low CPU. HPA keeps accumulating replicas from the HIGH phases but never gets to release them. The replica count ratchets upward.

Here is the math:
```
300s window to authorise scale-down.
LOW phase = 30s.
30s < 300s → stabilization never expires → HPA never issues a scale-down.
Even after 5 cycles (450s total), the window must restart from the final LOW phase.
Total convergence time ≈ 450s + 300s + scale-down steps ≈ 750–800 seconds.
```

#### Edge Cases / Caveats

- **B1 uses the DEFAULT 300-second stabilization window** (not the 60s window used by B2-Instrumented and B3). The paper explicitly chose to leave it at default to test HPA under its factory settings — not under an artificially aggressive configuration.
- **LOW phase is only 30 seconds**: Even though the LOW phase looks long on a timeline, it's actually only 30 seconds. The 300s stabilization window means HPA would need the LOW phase to last 5 minutes before it would start scaling down. With a 30-second LOW phase, HPA never even gets close.
- **Connections dropped to ~45–55 during LOW** (not 0): some connections may still be held open. HPA ran 15 pods for these ~50 connections — massive over-provisioning.
- **This experiment did NOT observe scale-down killing connections** because the stabilization window kept HPA from scaling down during the experiment window. That failure mode is covered in B2.
- **maxReplicas acts as a hard budget ceiling**: In production, this prevents runaway cost but also prevents the system from scaling to meet genuine demand.

---

### 5.4 Experiment B2 (Extended LOW) — The Experimental Wander *(not in the paper)*

**Location**: `scripts/run-experiment-b2.sh`, `experiments/websocket/experiment-b2-hpa-churn/`

> **⚠️ Important for SDE-1 readers**: This experiment does **not appear as a standalone section in the research paper**. It was a necessary stepping stone during development — a "trial run" to check if the failure mode was real before spending time building the full measurement setup. Understanding *why* it was dropped from the paper is as important as understanding what it found.

#### What Is an "Experimental Wander"?

In research, an "experimental wander" is a run you do to check a hunch. You're not yet ready to measure things precisely — you just want to know: *is anything interesting happening here at all?* If the answer is yes, you go back, build proper tools, and run it again properly. The second, properly-measured run is what you actually publish.

B2 Extended LOW is exactly that. It answered "yes, connections definitely die when HPA scales down" — but it couldn't tell you *how many* connections died or *how fast* clients reconnected. Those are the numbers the paper needs. That's why B2 Instrumented (Section 5.5) exists: it's the same idea, done properly with Prometheus metrics.

#### What Was the Goal Here?

From B1, we know HPA gets stuck at `maxReplicas` when cycles are fast and never scales down during the experiment. So the next logical question is: **what actually happens when HPA eventually does scale down?** To force that, make the LOW phase so long that it outlasts the 5-minute stabilization window.

```
HIGH (60s): 500 connections, pinging hard (CPU high).      ← HPA scales UP
Extended LOW (200s+): clients go silent, connections stay open. ← HPA eventually scales DOWN
→ The LOW outlasts the 5-minute window, so HPA has no choice but to start killing pods.
```

#### What Happened (3 Cycles)

Each cycle followed the same pattern:

1. HIGH: HPA scales up to 8–10 pods.
2. Extended LOW: CPU is 0%. After 5+ minutes, HPA scales back down to 2 pods.
3. Kubernetes terminates 6–8 pods. Each pod holds ~80–100 live WebSocket connections.
4. Those ~600 connections are hard-killed (TCP RST — the networking equivalent of hanging up on someone mid-sentence).
5. Clients detect disconnect and immediately try to reconnect.
6. Reconnection burst hits the now-tiny 2-pod cluster.
7. CPU spikes from the reconnection rush. HPA scales back up. Cycle repeats.

Full replica transition log: `2 → 6 → 8 → 2 → 6 → 8 → 10 → 2 → 5 → 10 → 4 → 2`

#### Why It Was Dropped from the Paper

This experiment had one fatal flaw: **it had no way to measure what it claimed to show.**

The server at this point had no Prometheus metrics. There was no `active_connections` gauge, no connection counter. The only data collected was:
- `kubectl top pods` (CPU numbers)
- `kubectl get hpa` (replica counts)
- `kubectl get pods` (lifecycle events)

None of these tell you how many connections were severed, or how fast clients reconnected. You can *see* the pods being killed and *assume* connections died, but you can't put a number on it. A research paper needs numbers.

Specifically, B2 Extended LOW **cannot answer**:
- How many connections were severed per scale-down event?
- At what rate (connections/second) did clients flood back in?
- Did the server briefly see more connections than the target (overshoot)?

Without those answers, you have an observation but not evidence. The paper needs evidence.

#### What It *Did* Accomplish (Its Real Value)

Even though it doesn't appear in the paper, this experiment was not a waste. It did exactly what a pilot run should do:

1. **Confirmed the failure is real** — connections really do die when HPA scales down. The hunch was right.
2. **Defined what needs to be measured** — you saw clients reconnecting but had no numbers. That told you exactly what instrumentation to add.
3. **Made the case for building B2 Instrumented** — you would not invest in setting up a full Prometheus stack without first checking the failure was real.

Think of it like this: before writing a full test suite for a bug, you write a quick one-liner to reproduce it first. B2 Extended LOW was the one-liner. B2 Instrumented was the test suite.

#### Caveats Discovered Here (That Informed B2 Instrumented)

- **The 30-second termination limbo was first noticed here**: Visually, there was a gap between "HPA decided to scale down" and "connections actually disappeared." No exact timestamps, but the delay was visible. This led to the detailed timestamp analysis in B3.
- **Race condition at scale-down**: When Kubernetes sends `SIGTERM` to a pod, it removes the pod from the Service endpoints first (new connections stop going there), but the existing live connections maintained by the OS kernel stay open until `SIGKILL`. This was suspected here but only measured precisely in B3.
- **Clients reconnecting aggressively creates a new CPU spike**: Also seen here qualitatively. Exact rates measured in B2 Instrumented (1,400 conn/s).

---

### 5.5 Experiment B2 (Instrumented) — Quantifying the Reconnection Storm

**Location**: `scripts/run-experiment-b2-instrumented.sh`, `experiments/websocket/experiment-b2-hpa-churn-instrumented/`

> **This is the experiment that actually appears in the research paper.** Everything B2 Extended LOW showed qualitatively, this experiment shows with real numbers.

#### Goal

Now that the failure mode is confirmed (from B2 Extended LOW), add Prometheus instrumentation so we can put actual numbers on it. Answer: *how many connections per second are being lost and re-established?* And: *does the reconnection storm overshoot the original connection count?*

#### What Changed Compared to B2 Extended

- Server upgraded to `app-instrumented/server.py` — now exports:
  - `active_connections` (Gauge): current number of open connections.
  - `new_connections_total` (Counter): total connections ever opened (never decreases).
  - Reconnection rate = `rate(new_connections_total[15s])` = new connections per second in the last 15s window.
- 800 connections (unchanged from B2 Extended).
- **5 full HIGH/LOW cycles** (HIGH=60s, LOW=90s; total period=150s per cycle).
- HPA policy: `stabilizationWindowSeconds: 0` for scale-up (react immediately to CPU), `stabilizationWindowSeconds: 60` for scale-down.
- The 90s LOW was deliberately chosen to be greater than the 60s scale-down window, guaranteeing one full scale-down per cycle.
- Full Prometheus + scrape pipeline at 15s.

#### What Happened

**Replica behaviour (across 4 cycles):**

| Phase | Replicas | CPU% |
|-------|----------|------|
| Start | 2 | 52% |
| Cycle 1 HIGH peak | 15 | 461% → 65% |
| Cycle 1 LOW | 15 → 7 | 5% → 0% |
| Cycle 2 HIGH | 7 → 12 → 15 | 73% → 104% |
| Cycle 2 LOW | 15 → 6 | 0% |
| Cycle 3 HIGH | 6 → 15 | 87% → 138% |
| Cycle 3 LOW | 15 → 5 | 0% |
| Cycle 4 HIGH | 5 → 15 | 73% → 150% |
| Final (all load stopped) | 15 → 10 → 2 | 0% |

**Reconnection storm rates measured:**

| Cycle | Peak reconnection rate |
|-------|----------------------|
| Cycle 1 | **1,400.9 conn/s** |
| Cycle 2 | **1,298.3 conn/s** |
| Cycle 3 | **1,399.5 conn/s** |
| Cycle 4 | **1,251.8 conn/s** |
| Cycle 5 | (partial — connection pool partially degraded by this point) |

**Connection overshoot**: During Cycle 2, the active connection count spiked to **1,215** — above the 800 target. This is because clients reconnected so fast that new connections arrived before the old (dead) connections had been cleaned up server-side. The server briefly saw 1,215 connection objects, even though only 800 were genuinely active.

#### Edge Cases / Caveats

- **HPA hit maxReplicas=15 in all 4 cycles, every time.** The system was always resource-constrained at peak. It never once had enough capacity.
- **The connection overshoot (1,215 > 800)** is critical: it means the server experienced more connections than it was designed for during the storm, potentially degrading performance for all users.
- **Immediate causation proven**: The reconnection rate spiked within one Prometheus scrape interval (15 seconds) of each HPA-initiated scale-down event. This causally links HPA scale-down → connection drops → storm.
- **The 5-minute default stabilization window** was used here. This made scale-downs happen slowly. B3 will deliberately shorten this to make the problem more acute.

---

### 5.6 Experiment B3 — The Fatal Flaw (Control Baseline)

**Location**: `scripts/run-experiment-b3.sh`, `experiments/websocket/experiment-b3-hpa-idle-connections/`

#### Goal

Create a clean, single-cycle, perfectly controlled demonstration of HPA's fatal flaw:

> HPA scales down purely on CPU. It does not know or care how many live connections the pods it kills are holding.

This is the "control" experiment — the definitive proof that directly contrasts with Experiment C.

#### Key Design Decisions

1. **`scaleDownStabilizationWindowSeconds: 60`** — Instead of the 5-minute default, HPA is configured to scale down after just 60 seconds of low CPU. This makes the scale-down happen within an observable window.
2. **Two-phase client behavior**:
   - `CONNECT phase (0–120s)`: clients ping actively (CPU_WORK=1), driving CPU up, causing HPA to scale up.
   - `IDLE phase (120s+)`: clients stop all pings but **keep the connection open**. CPU crashes to 0%. Connections stay at 800.
3. **No reconnection on disconnect**: When a client's connection is killed during the IDLE phase, it detects the disconnect and exits without reconnecting. This is the smoking gun — you can see exactly how many connections HPA permanently destroyed.

#### HPA Manifest (the key change)

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
spec:
  minReplicas: 2
  maxReplicas: 15
  behavior:
    scaleDown:
      stabilizationWindowSeconds: 60  # ← Was 300 in all previous experiments
    scaleUp:
      stabilizationWindowSeconds: 0   # ← Fast scale-up
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 60
```

#### What Happened

```
t=0s:      2 pods. CONNECT phase begins (CONNECT_DURATION=120s).
t=0–90s:   800 clients ramp up gradually. CPU spikes on initial pods.
           HPA: 2 → 6 → 10 → 15 replicas. (scaleUp window = 0s, so immediate)
t=90s:     All 800 connections established, balanced across 15 pods (~53/pod).
t=120s:    IDLE phase begins (IDLE_MAX_DURATION=240s).
           Clients stop pinging. CPU: 0%. Connections: 800 (still flat — TCP sessions open).
t=180s:    60 seconds into IDLE. HPA scale-down stabilization window expires.
           HPA: "CPU has been < 60% for 60s. Scale down."
           HPA: 15 → 11 pods. (4 pods sent SIGTERM + removed from endpoints)
t=180s:    Connections still show 744... (30-second SIGTERM limbo begins)
t=210s:    SIGKILL fires on the 4 pods. OS kernel RSTs all open TCP sockets.
           Connections: 744 → ~697. Step-down visible in graph.
           HPA: "Still 0% CPU." Sends 11 → 7 (4 more pods get SIGTERM).
t=246s:    SIGKILL again. Connections: ~697 → ~445.
t=270s+:   7 → 3 → 2 pods. Connections: ~445 → ~79 → 0.
           All 800 original sessions permanently destroyed.
```

**Why do connections drop in steps, not instantly?** Because of the 30-second SIGTERM grace period. Kubernetes sends SIGTERM, removes the pod from the Service endpoint slice immediately (no new connections will go there), but the OS keeps existing TCP connections alive. Only after 30 seconds does Kubernetes send SIGKILL, which forces the OS to close all file descriptors (including TCP sockets), sending a TCP RST to every connected client. So every "HPA event" you see in the graph is followed by a ~30-second delay before the connections actually fall off the cliff.

#### The 30-Second Termination Limbo — A Critical Kubernetes Insight

This was one of the most important empirical discoveries of the entire project. Here are the exact observed timestamps:

| HPA Event | Replica Count | Connection count | Time until connections actually drop |
|-----------|--------------|-----------------|--------------------------------------|
| Scale-down triggered | 15 → 11 | 744 connections | ~43 seconds |
| Scale-down triggered | 11 → 7 | 697 connections | ~36 seconds |
| Scale-down triggered | 7 → 3 | 445 connections | ~36 seconds |

**Why the ~35-second delay?**

When Kubernetes decides to terminate a pod:
1. It removes the pod from the Service endpoints (no *new* traffic routed to it).
2. It sends `SIGTERM` to the container process.
3. The Node.js / Python process receives `SIGTERM` but has no shutdown handler for WebSocket connections — it ignores the signal and continues running.
4. After `terminationGracePeriodSeconds` (default: **30 seconds**), Kubernetes sends `SIGKILL`.
5. The process is forcefully killed. All open file descriptors (including TCP sockets) are closed by the OS kernel.
6. Connected clients receive a TCP RST (connection reset). The disconnect is registered.

This means every user whose connection was on a terminating pod spent up to 30 seconds in a "zombie state" — their connection was effectively doomed, but it hadn't actually died yet. New connections were not being routed to that pod, but their existing connection was still "alive" in a false sense.

**Why this is powerful for the research paper**: The 30-second graceful window exists to allow stateless apps to finish in-flight requests. For WebSocket connections that can last hours, 30 seconds is meaningless. The connection is doomed the moment HPA pulls the trigger.

#### Edge Cases / Caveats

- **Connections don't hit exactly 800**: Due to how Kubernetes load-balancing works, slightly different numbers of connections land on each pod. When a pod with more connections is killed, the step-down is larger.
- **The IDLE phase relies on `ping_timeout=None`**: Earlier versions of the experiment used a default ping timeout. The `websockets` library sends WebSocket ping frames periodically to check if the connection is alive. Under heavy load, servers were slow to respond to these pings, causing the library to *incorrectly* close connections due to timeout. In the final version, `ping_timeout=None` disables this, preventing false disconnects before HPA even acts.
- **`CPU_WORK=1` is required for HPA to scale up**: If `CPU_WORK=0`, the server generates no CPU even when clients are sending pings, and HPA would never scale up. B3 is designed to prove that HPA scales up fine (on CPU) but scales down dangerously (oblivious to connections).
- **The 60-second stabilization window is key**: Without it, HPA would take ~5 minutes to react, making the idle phase impractically long.
- **Permanent connection loss is intentional**: By programming clients to never reconnect during IDLE, the graph shows a clean, permanent staircase step-down — irrefutable visual evidence of destroyed sessions.

---

### 5.7 Experiment C — The Custom StatefulAutoscaler (The Solution)

**Location**: `scripts/run-experiment-c.sh`, `experiments/websocket/experiment-c-stateful/`

#### Goal

Prove that a custom controller that scales **only on connection count** — and uses a cooldown window to resist temporary drops — completely solves every failure mode identified in A through B3.

#### Key Differences from All Previous Experiments

| Parameter | B3 (HPA) | C (Custom Controller) |
|-----------|----------|----------------------|
| Scaler | Kubernetes HPA | Custom `StatefulAutoscaler` CRD |
| Scale signal | CPU utilization | `active_connections` (Prometheus) |
| `CPU_WORK` | **1** | **0** (server does no CPU work) |
| Scale-down protection | None | `scaleDownCooldownSeconds: 120` |
| Reconnection handling | None | Cooldown window keeps pods warm |
| Connection awareness | **Zero** | **Exact** |

Note: `CPU_WORK=0` is used deliberately. If CPU is always 0% and replicas still scale correctly based on connection count, this definitively proves that the controller is NOT using CPU — it is purely connection-driven.

#### The StatefulAutoscaler CRD

```yaml
apiVersion: autoscaling.star.io/v1alpha1
kind: StatefulAutoscaler
metadata:
  name: websocket-autoscaler
spec:
  targetRef:
    name: websocket-server        # Which Deployment to scale
  targetConnectionsPerPod: 100    # Target: max 100 connections per pod
  minReplicas: 2
  maxReplicas: 15
  scaleDownCooldownSeconds: 120   # Wait 120s of silence before scaling down
  maxScaleDownStep: 2             # Never remove more than 2 pods at once
```

The formula: `desired_pods = ceil(total_active_connections / targetConnectionsPerPod)`

- 800 connections → `ceil(800/100)` = **8 pods**
- 0 connections starts cooldown → after 120s of silence → scale down

#### The 2-Cycle Restorm Simulation

The experiment is designed to simulate a real-world scenario: a temporary outage (all connections drop to 0) followed by a massive reconnection wave.

```
CYCLE 1 (t=0 to t=150s):
  800 clients connect and actively ping.
  Controller sees 800 connections → scales to 8 pods.
  Clients stop pinging at t=120s (CPU falls to 0).
  Controller still sees 800 connections → holds 8 pods. (CPU ignored!)

DROP 1 (t=150s to t=240s):
  All 800 clients forcefully disconnected (Job deleted).
  Connections crash to 0.
  HPA would immediately begin scale-down.
  Controller: "Connections are 0, but cooldown is 120s. I'll wait."
  Pods remain at 8. The pods are "warm" — ready to receive.

CYCLE 2 - THE RESTORM (t=240s to t=390s):
  90 seconds into the gap (cooldown not yet expired!), 800 clients reconnect.
  Because all 8 pods are still running, clients connect with zero wait.
  No storms. No oscillation. No delay.
  Controller: "800 connections → 8 pods. Already correct. Nothing to do."

FINAL DROP (t=390s to t=570s):
  All clients permanently disconnect.
  Connections = 0. Cooldown timer starts.
  120 seconds of absolute silence.
  Cooldown expires. Controller scales down: 8 → 6 → 4 → 2 pods.
```

#### What Happened (Observed Results)

- **CPU graph**: Two spikes (active ping phases) then flat 0. **Zero correlation with replica count.**
- **Connections graph**: Two "blocks" of 800 connections separated by a 90-second gap.
- **Replicas graph**: Steps up to 8 during Cycle 1. Stays flat at 8 across the entire Drop 1 gap and Cycle 2. Steps down cleanly after the final 120s cooldown expires.
- **Connection overshoot during restorm**: 854 (slightly above 800) — the controller smoothly scaled to 9 pods to accommodate.
- **Zero reconnection storms**: No sudden CPU spikes. No oscillation.

#### Head-to-Head Comparison

| Behaviour | HPA (B3) | StatefulAutoscaler (C) |
|-----------|----------|----------------------|
| Scale-up signal | CPU (can only see it if `CPU_WORK=1`) | `active_connections` (always visible) |
| Scale-down signal | CPU drops to 0% | `active_connections` drops AND cooldown expires |
| Scale-down during brief outage | Immediately starts (60s window) | Suppressed — holds warm pods |
| Connections surviving scale-down | **None** (all killed) | **All** (scale-down only after connections are gone) |
| Reconnection storm resistance | **None** | **Complete** |
| Behaviour when clients idle | Begins scale-down | Holds replicas since connections = 800 |
| Proof of connection awareness | N/A | Scales correctly with CPU=0% throughout |

#### Edge Cases / Caveats

- **The cooldown sliding window is a critical tuning parameter.** A 120-second cooldown is correct for a short restorm gap. If clients take 5 minutes to reconnect after an outage, the cooldown would expire and pods would be scaled down — causing a scale-up on reconnect. The value must be tuned to the expected reconnection latency of the application.
- **Connection overshoot to 854**: The restorm brought 854 connections (not exactly 800) because some clients reconnected before others disconnected fully. The controller handled this gracefully by scaling to 9 pods.
- **`maxScaleDownStep: 2`**: To prevent sudden massive scale-downs (which would still drop connections if timed poorly), the controller limits itself to removing at most 2 pods per reconciliation loop. This prevents large abrupt changes.
- **The controller queries Prometheus via HTTP**: It uses `http://prometheus.monitoring.svc.cluster.local:9090/api/v1/query?query=sum(active_connections)`. If Prometheus is unreachable, the controller must fail safely (no scale-down) to avoid false 0-connection readings causing premature pod deletion.
- **The 15-second Prometheus scrape interval introduces lag**: If all 800 connections disconnect simultaneously, the controller might not see 0 connections for up to 15 seconds. During that window, it correctly holds replicas (though it "doesn't know" yet). The cooldown clock doesn't start until the metric reads 0.
- **`CPU_WORK=0` is essential to the proof**: If the controller scaled correctly only when CPU was high, a skeptic could say "maybe it still uses CPU somehow." Running with `CPU_WORK=0` eliminates this objection.

---

## 6. The Custom Controller — Architecture Deep Dive

The custom controller lives in `controller/` and is built using **Kubebuilder** — a Go framework for building Kubernetes operators.

### How a Kubernetes Controller Works (Conceptually)

```
Observe current state → Compare with desired state → Act to reconcile
```

This is called the **reconciliation loop**. The controller runs this loop continuously (every few seconds). In our case:

- **Observe**: Query Prometheus for `sum(active_connections)`.
- **Compare**: Calculate `desired_pods = ceil(connections / targetConnectionsPerPod)`. Compare with current replica count.
- **Act**: If different, patch the Deployment's `spec.replicas`.

### Key Files

| File | Purpose |
|------|---------|
| `controller/api/v1alpha1/statefulautoscaler_types.go` | Defines the Go struct for the CRD (what fields `StatefulAutoscaler` has) |
| `controller/internal/controller/statefulautoscaler_controller.go` | The reconciliation loop |
| `controller/internal/controller/prometheus.go` | HTTP client to query Prometheus API |
| `controller/config/crd/` | Auto-generated YAML for the CRD (run `make manifests`) |
| `controller/config/samples/` | Example `StatefulAutoscaler` YAML you can apply |

### The Reconciliation Loop (Simplified)

```go
func (r *Reconciler) Reconcile(ctx context.Context, req reconcile.Request) {
    // 1. Load the StatefulAutoscaler CR
    autoscaler := &StatefulAutoscaler{}
    r.Get(ctx, req.NamespacedName, autoscaler)

    // 2. Query Prometheus for total connections
    totalConnections := queryPrometheus("sum(active_connections)")

    // 3. Calculate desired replicas
    desired := int32(math.Ceil(
        float64(totalConnections) /
        float64(autoscaler.Spec.TargetConnectionsPerPod),
    ))
    desired = clamp(desired, autoscaler.Spec.MinReplicas, autoscaler.Spec.MaxReplicas)

    // 4. Scale-down cooldown logic
    if desired < currentReplicas {
        if timeSinceLastConnectionDrop < autoscaler.Spec.ScaleDownCooldownSeconds {
            // Don't scale down yet — wait for cooldown
            return
        }
    }

    // 5. Apply maxScaleDownStep limit
    if currentReplicas - desired > autoscaler.Spec.MaxScaleDownStep {
        desired = currentReplicas - autoscaler.Spec.MaxScaleDownStep
    }

    // 6. Patch the Deployment
    deployment.Spec.Replicas = &desired
    r.Update(ctx, deployment)
}
```

### Building and Deploying the Controller

```bash
# In the controller/ directory:

# Generate CRD manifests and deepcopy functions
make manifests generate

# Build the Docker image
make docker-build IMG=localhost/stateful-autoscaler:latest

# Load the image into the kind cluster (no push needed for local testing)
kind load docker-image localhost/stateful-autoscaler:latest

# Install the CRD into the cluster
make install

# Deploy the controller
make deploy IMG=localhost/stateful-autoscaler:latest

# Apply a StatefulAutoscaler resource
kubectl apply -f config/samples/statefulautoscaler.yaml
```

### RBAC — Why the Controller Needs Permissions

The controller needs explicit permission to:
- Read `StatefulAutoscaler` CRs (to know its config).
- Read and Update `Deployments` (to change replica count).
- Read `Pods` (to count running replicas).

These permissions are declared as annotations in the Go code:
```go
// +kubebuilder:rbac:groups=apps,resources=deployments,verbs=get;list;watch;update;patch
// +kubebuilder:rbac:groups=core,resources=pods,verbs=get;list;watch
```
Running `make manifests` generates the corresponding `ClusterRole` YAML automatically.

---

## 7. Phase 2 — MQTT Experiments (Future Work)

**Location**: `md/mqtt-experiment-plan.md`, `workloads/mqtt/`, `load-generator/mqtt-client/`

### Why MQTT?

The WebSocket experiments proved the problem and the solution for one protocol. MQTT generalises the argument to a second, industrially significant protocol. If the same failure modes appear with MQTT and the same controller fixes them, the research claim becomes much stronger.

### What is MQTT (in this context)?

MQTT clients connect to a **broker** (a server) and subscribe to topics. Each client maintains a persistent TCP session with the broker. This is identical in structure to WebSockets from the scaling perspective: N devices connected = N persistent sessions on the broker pods.

### Architecture

A **custom Python MQTT broker** is being built using the `amqtt` library (since vanilla Mosquitto does not expose Prometheus `/metrics` or a `/drain` endpoint). This mirrors the WebSocket server architecture exactly.

```python
# workloads/mqtt/app/broker.py
# MQTT on port 1883 (via amqtt)
# /metrics on port 8080 → exposes active_connections
# /drain on port 8080 → stops accepting new connections
```

### Three Planned MQTT Experiments

| Experiment | Scaler | Research Question |
|-----------|--------|-------------------|
| **MQTT-A** (HPA Baseline) | CPU HPA | Does HPA disrupt active MQTT sessions during scale-down? |
| **MQTT-B** (StatefulAutoscaler) | Custom controller | Does the STAR controller scale MQTT brokers proportionally to connections without disruption? |
| **MQTT-C** (Idle Connections) | Both compared | Does HPA waste resources when MQTT clients are idle, while STAR holds replicas steady? |

### Expected Outcomes

- MQTT-A will replicate the same failures as WebSocket B3: HPA kills brokers holding live device sessions.
- MQTT-B will replicate the same success as WebSocket C: controller holds brokers alive until devices disconnect.
- MQTT-C will quantify resource waste: HPA drifts to minReplicas when devices are idle; STAR holds correct replica count.

### Key Technical Challenge

MQTT session state (QoS level, subscriptions, retained messages) is stored per-connection. If a broker pod is killed, the device loses its subscribed topics and must re-subscribe. For QoS 1/2 messages, unacknowledged messages may be lost or duplicated. This is arguably worse than WebSocket disconnects for IoT applications.

### File Structure (to be created)

```
workloads/mqtt/app/broker.py         ← Custom Python MQTT broker
load-generator/mqtt-client/client.py ← MQTT load generator
experiments/mqtt/experiment-a/run.sh
experiments/mqtt/experiment-b/run.sh
experiments/mqtt/experiment-c/run.sh
scripts/run-experiment-mqtt-a.sh
scripts/run-experiment-mqtt-b.sh
scripts/run-experiment-mqtt-c.sh
analysis/mqtt/plot_experiment_mqtt.py
```

---

## 8. Edge Cases and Caveats

This section collects all the non-obvious behaviours encountered across this project, from infrastructure quirks to protocol-level subtleties.

### Infrastructure & Kubernetes

#### 1. The 30-Second Termination Limbo (Critical)
When HPA scales down, Kubernetes sends `SIGTERM` and waits `terminationGracePeriodSeconds` (default 30s) before `SIGKILL`. During those 30 seconds, the pod is removed from Service endpoints (no new traffic) but existing connections stay alive. After 30 seconds, `SIGKILL` destroys everything. This means every "HPA scale-down event" in the graphs is followed by a ~30-second delay before you see connections drop. **This is not an experiment bug — it is core Kubernetes behaviour.**

**Implication for the paper**: Even Kubernetes's own graceful shutdown mechanism fails to protect persistent connections, because it doesn't know there *are* persistent connections to protect.

#### 2. The `kind` Cluster is Single-Machine
`kind` (Kubernetes in Docker) runs all the "nodes" as Docker containers on a single machine. This means:
- CPU resource measurements are relative to the host machine.
- In a real multi-node cluster, pod scheduling would be different.
- Network latency between "nodes" is near-zero (all localhost).
- Results are directionally correct but absolute CPU numbers would differ on real clusters.

#### 3. Metrics Server Patch Required for Kind
The default `metrics-server` deployment has TLS validation enabled for kubelet — kubelet in `kind` uses a self-signed cert that metrics-server rejects. The `--kubelet-insecure-tls` flag is required for Kind clusters. **Never use this flag in production.**

#### 4. HPA Has a 15-Second Sync Loop
Even with `scrape_interval=15s` on metrics-server, HPA only re-evaluates every 15 seconds by default. This means worst-case scaling latency is 30 seconds (15s metrics lag + 15s HPA sync lag).

#### 5. HPA Minimum Replicas during Scale-Down
HPA will never scale below `minReplicas` (set to 2 in all experiments). This means even with 0 connections, 2 pods are always running. This is intentional — having 0 pods means a new connection would have no server to connect to at all.

---

### WebSocket Protocol Edge Cases

#### 6. WebSocket Ping/Pong Frames (`ping_timeout=None`)
The `websockets` Python library automatically sends WebSocket-level ping frames to detect dead connections. If the server is under heavy load and responds slowly to pings, the client will conclude the connection is dead and close it. In early B3 experiments, this caused connections to drop from 800 to 744 before HPA even acted — making it look like connections were dropping for a different reason. **Fix**: Set `ping_timeout=None` in the client to disable this mechanism. Only use this in controlled experiments where you know the server is alive.

#### 7. Connection Overshoot During Reconnection Storms
In B2-Instrumented, `active_connections` spiked to 1,215 when the target was 800. This happens because:
- 800 clients disconnect and immediately reconnect.
- New connections arrive faster than the server cleans up old `CLOSE_WAIT` TCP states.
- Momentarily, both old (dead) and new (alive) connection objects exist in the server's memory.

**Implication**: During a reconnection storm, your server may briefly handle *more* connections than your replica count was sized for, potentially degrading performance for everyone.

#### 8. Load Balancing is Not Perfect
Kubernetes routes new connections to pods via round-robin or random selection at the Service level. Over time, connections distribute roughly evenly, but not perfectly. Some pods may hold 60 connections while others hold 45. When a pod with 60 connections is killed, you lose 60; when one with 45 is killed, you lose 45. This causes variability in the size of connection drop "steps" in the graphs.

---

### Custom Controller Edge Cases

#### 9. Prometheus Unreachability
The controller queries Prometheus at every reconciliation cycle. If Prometheus is temporarily unreachable (crash, network blip), the controller receives an error. **Safe default**: do not scale down if Prometheus is unreachable. An errored query should be treated as "unknown, not 0." If treated as 0, a Prometheus restart could trigger a mass pod deletion.

#### 10. The Cooldown Timer is Per-Controller, Not Per-Pod
The `scaleDownCooldownSeconds` is a single sliding window for the entire deployment, not per-pod. If connections drop from 800 to 400 (not 0), the cooldown starts for the 400-connection delta. However, if connections recover to 800 within the cooldown, the timer resets. If connections never recover to 400 after the cooldown, the controller scales down by the appropriate amount.

#### 11. Controller Restart Loses Cooldown State
The cooldown window is stored in memory (not persisted to etcd or status subresource, unless explicitly implemented). If the controller Pod crashes and restarts, the cooldown timer resets to 0. This could allow a premature scale-down right after a controller restart if connections happen to be at 0.

**Fix**: Store the last-active timestamp in the `StatefulAutoscaler` status field so it survives restarts. This is a known open improvement.

#### 12. The Controller Conflicts with HPA
If both HPA and StatefulAutoscaler are deployed for the same Deployment, they will fight — both will try to set `spec.replicas`, and the last writer wins. Always delete the HPA before applying StatefulAutoscaler (this is handled in `run-experiment-c.sh` automatically).

#### 13. `maxScaleDownStep` Can Slow Emergency Scale-Down
If traffic permanently drops from 800 to 0 connections and `maxScaleDownStep=2`, the controller will scale down by 2 pods per reconciliation cycle (every ~15 seconds). Going from 8 to 2 pods takes `(8-2)/2 * 15s = 45 seconds`. During this time, 6 pods are running idle. This wastes resources but is safe (no connection drops since connections are already 0).

---

### Analysis and Measurement Edge Cases

#### 14. Log Timestamps are Wall-Clock, Not Cluster-Clock
The experiment scripts collect logs using `date +%s%3N` (Unix milliseconds). If the host clock drifts or the machine sleeps, log timestamps may be inconsistent. When correlating `cpu.log`, `connections.log`, and `hpa.log`, always check that timestamps are monotonically increasing.

#### 15. Prometheus Scrape Timing Creates Step Functions in Plots
Because Prometheus scrapes every 15 seconds, all connection metrics appear as step functions in plots (values jump rather than smoothly changing). The true connection count between scrapes is unknown. When a connection drop appears to take 36 seconds, it might have actually taken 30 seconds but the scrape happened 6 seconds after the fact.

---

## 9. Summary Evidence Chain

The experiments form a deliberate logical progression. Each one answers a specific question and motivates the next:

```
[Base Paper] KRM:
  CPU-based HPA works for stateless HTTP, but has scrape latency.
  → Insight: metrics freshness matters.

[Base Paper] PCM:
  Prometheus custom metrics solve the latency. Hybrid metrics eliminate saturation.
  → Insight: better signals → better scaling. But this only helps STATELESS apps.

[Experiment A] CPU HPA + WebSockets (ideal conditions):
  HPA CAN scale WebSockets if every connection generates CPU.
  → This is an artificial scenario. Real WebSocket workloads are mostly idle.

[Experiment B1] CPU HPA + Cyclic Churn:
  HPA gets stuck at maxReplicas. Cannot scale down quickly enough.
  → HPA over-provisions catastrophically under real cyclic workloads.

[Experiment B2 Extended] CPU HPA + Forced Scale-Down:  ⚠️  PILOT RUN — NOT IN PAPER
  When HPA finally does scale down, it kills live connections.
  → Reconnection storms qualitatively observed. BUT no Prometheus metrics attached.
  → Cannot publish: no connection counts, no storm rates, no overshoot numbers.
  → This pilot's only job was to confirm the failure mode is real enough to merit
     the effort of setting up Prometheus. It succeeded at that job.
  → Superseded entirely by B2 Instrumented.

[Experiment B2 Instrumented] CPU HPA + Quantification:  ← This is the one in the paper
  Reconnection storms measured: up to 1,400 connections/second.
  Connection overshoot to 1,215 (above 800 target).
  → HPA + persistent connections = quantified chaos.

[Experiment B3] CPU HPA + Short Stabilization Window:
  With 60s window, scale-down happens visibly fast.
  30-second termination limbo documented.
  Permanent connection drop staircase proven.
  → The fatal flaw is definitively demonstrated.

[Experiment C] Custom StatefulAutoscaler:
  Scales on connections, not CPU.
  Holds pods warm during 90-second outage gap.
  Handles 800-connection restorm with zero disruption.
  No reconnection storms. No oscillation. No connection drops.
  → The problem is completely solved.

[Future: MQTT] Generalisation:
  Same problem, same solution, different protocol.
  → The research conclusion generalises beyond WebSockets.
```

---

## 10. Key Numbers Across All Experiments

The table below shows all experiments including B2 Extended LOW. The column is greyed out to indicate it is a **pilot run only** and not a standalone paper experiment.

| Metric | Exp A | Exp B1 | ~~B2-ext~~ *(pilot)* | Exp B2-inst *(paper)* | Exp B3 | Exp C |
|--------|-------|--------|-----------|------------|--------|-------|
| **In paper?** | ✅ | ✅ | ❌ Pilot only | ✅ | ✅ | ✅ |
| Scaler | HPA | HPA | HPA | HPA | HPA | **Custom** |
| CPU_WORK | 1 | 1 | 1 | 1 | **1** | **0** |
| Scale-down window | 5 min | 5 min | 5 min | 5 min | **60s** | N/A |
| Target connections | 400 | 500 | ~500 | **800** | **800** | **800** |
| Peak connections seen | 388 | 419 | ~500 (no metric) | **1,215\*** | ~800 | 854 |
| Peak replicas | 5 | **15** | 10 | **15** | 8–15 | **8–9** |
| Scale events | 2 | 5+ | 12+ | 18+ | 3+ | 4 |
| Reconnection storm | ❌ No | ❌ No | ✅ Yes (unquantified) | ✅ **1,400/s** | ✅ Yes | **❌ None** |
| Connections killed | 0 | 0 | Many (unquantified) | Many (measured) | **All (measured)** | **0** |
| Connection-aware | ❌ | ❌ | ❌ | ❌ | ❌ | **✅** |

\* B2-inst overshoot above 800 due to reconnection storm creating zombie connections.

---

## 11. Glossary

| Term | Definition |
|------|-----------|
| **Active Connection** | An open, established WebSocket or MQTT TCP session between a client and a server pod. Consuming memory and file descriptors on the server. |
| **Cooldown Window** | A time period during which the custom controller suppresses scale-down actions, despite connection count being low, to avoid prematurely destroying capacity before clients reconnect. |
| **CRD** | Custom Resource Definition. Extends Kubernetes with new object types. The `StatefulAutoscaler` is a CRD. |
| **HPA** | Horizontal Pod Autoscaler. Built-in Kubernetes controller that adjusts pod replica count based on metrics (usually CPU). |
| **kind** | Kubernetes in Docker. Runs a fake multi-node cluster entirely on your laptop. |
| **KRM** | Kubernetes Resource Metrics. The native CPU/memory metrics pipeline (via metrics-server). |
| **Kubebuilder** | A Go framework for building Kubernetes operators (custom controllers). |
| **Leading Indicator** | A metric that signals workload *before* it fully manifests (e.g., http_requests_per_second spikes before CPU does). |
| **Lagging Indicator** | A metric that signals workload *after* it already happened (e.g., CPU is high because requests already arrived). |
| **maxScaleDownStep** | A safety parameter limiting how many pods the controller can remove in a single reconciliation cycle. |
| **Metrics Server** | A K8s add-on that collects CPU/memory from each node/pod via the kubelet API. Required for HPA. |
| **MQTT** | Message Queuing Telemetry Transport. A publish-subscribe protocol for IoT devices. Persistent connections to a broker. |
| **Operator** | A Kubernetes application that manages other applications: watches resources and takes automated action. |
| **PCM** | Prometheus Custom Metrics. Using Prometheus (instead of metrics-server) as the HPA signal source. |
| **Pod** | The smallest K8s unit. Wraps one or more containers. One running instance of your application. |
| **Prometheus** | Open-source metrics collection and time-series storage system. Scrapes `/metrics` endpoints from applications. |
| **RBAC** | Role-Based Access Control. Kubernetes permission system. |
| **Reconnection Storm** | When many clients simultaneously reconnect after a server-side disconnection event, causing a burst of CPU and network load. |
| **Reconciliation Loop** | The "observe → compare → act" loop that a Kubernetes controller runs continuously. |
| **Replicas** | The number of identical pod instances running for a Deployment. HPA adjusts this number. |
| **SIGKILL** | Forceful process termination. No cleanup possible. All open connections die instantly. |
| **SIGTERM** | Polite process shutdown request. The process can clean up (but our servers ignore it for WebSocket connections). |
| **Staircase Effect** | When a long Prometheus scrape interval causes HPA to see the same stale metric value for multiple consecutive sync cycles, generating discrete "staircase" steps in the replica count instead of a smooth curve. |
| **StatefulAutoscaler** | The custom Kubernetes CRD and controller built in this project. Scales deployments based on active connection count from Prometheus. |
| **Stateful Workload** | An application that maintains per-client session state across multiple requests/messages (WebSocket, MQTT, gRPC streaming). |
| **Stateless Workload** | An application that handles each request independently with no memory of prior requests (REST API, HTTP server). |
| **Stabilization Window** | The duration HPA waits before acting on a scaling decision, to prevent over-reaction to transient metric changes. |
| **terminationGracePeriodSeconds** | Kubernetes setting (default 30s) for how long to wait after SIGTERM before sending SIGKILL to a terminating pod. |
| **WebSocket** | A protocol providing full-duplex persistent communication over a single TCP connection. |
| **Zombie Connection** | A live WebSocket/MQTT connection on a pod that is in `Terminating` state — the connection is doomed but not yet dead. |
