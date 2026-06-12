#!/usr/bin/env bash
set -euo pipefail
# ==============================================================================
# Experiment-B3-Tuning: HPA Stabilization Window Sensitivity Study
#
# Env vars:
#   STABILIZATION_WINDOW — HPA scaleDown stabilizationWindowSeconds (default: 60)
#   GAP_DURATION         — Idle gap duration in seconds (default: 45)
#   RUN_ID               — Optional run identifier for multi-run batches
# ==============================================================================

cleanup() {
  echo "[CLEANUP] Stopping background processes..."
  kill ${HPA_PID:-} ${CPU_PID:-} ${PROM_COLLECT_PID:-} ${PROM_PID:-} ${POD_PID:-} 2>/dev/null || true
  wait 2>/dev/null || true
}
trap cleanup EXIT

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

CLUSTER_NAME="stateful-exp"
STABILIZATION_WINDOW="${STABILIZATION_WINDOW:-60}"
GAP_DURATION="${GAP_DURATION:-45}"
RUN_ID="${RUN_ID:-}"
EXPERIMENT_NAME="experiment-b3-tuning"
SUBDIR="window${STABILIZATION_WINDOW}s_gap${GAP_DURATION}s"
CONNECT_DURATION=120
SCRAPE_INTERVAL=5

if [ -n "$RUN_ID" ]; then
  RESULT_DIR="$PROJECT_ROOT/results/raw/websocket/$EXPERIMENT_NAME/$SUBDIR/run_${RUN_ID}"
else
  RESULT_DIR="$PROJECT_ROOT/results/raw/websocket/$EXPERIMENT_NAME/$SUBDIR"
fi

section() { echo -e "\n============================================================\n  $1\n============================================================"; }
log() { echo "[$(date '+%H:%M:%S')] $1"; }

# --- 1. Setup ---
section "1. Setup — Window=${STABILIZATION_WINDOW}s, Gap=${GAP_DURATION}s, Run=${RUN_ID:-single}"
mkdir -p "$RESULT_DIR"
cat > "$RESULT_DIR/params.json" <<PEOF
{"stabilization_window_s":$STABILIZATION_WINDOW,"gap_duration_s":$GAP_DURATION,"run_id":"${RUN_ID:-single}","timestamp":"$(date -Iseconds)"}
PEOF

# --- 2. Kind Cluster ---
section "2. Creating Fresh Kind Cluster"
kind delete cluster --name "$CLUSTER_NAME" 2>/dev/null || true
kind create cluster --name "$CLUSTER_NAME" --config "$PROJECT_ROOT/scripts/kind.yml"
log "Kind cluster created."

# --- 3. Metrics Server ---
section "3. Installing Metrics Server"
kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml
kubectl -n kube-system patch deployment metrics-server --type='json' -p='[{"op":"replace","path":"/spec/template/spec/containers/0/args","value":["--cert-dir=/tmp","--secure-port=10250","--kubelet-preferred-address-types=InternalIP,ExternalIP,Hostname","--kubelet-use-node-status-port","--metric-resolution=15s","--kubelet-insecure-tls"]}]'
kubectl -n kube-system rollout status deployment/metrics-server --timeout=300s
WAITED=0; while ! kubectl top pods >/dev/null 2>&1; do [ "$WAITED" -ge 180 ] && break; sleep 5; WAITED=$((WAITED+5)); done
log "Metrics API ready (${WAITED}s)."

# --- 4. Prometheus ---
section "4. Deploying Prometheus"
kubectl apply -f monitoring/prometheus/namespace.yaml
kubectl apply -f monitoring/prometheus/rbac.yaml
kubectl apply -f monitoring/prometheus/configmap.yaml
kubectl apply -f monitoring/prometheus/deployment.yaml
kubectl apply -f monitoring/prometheus/service.yaml
kubectl -n monitoring rollout status deployment/prometheus --timeout=300s

# --- 5. Docker Images ---
section "5. Building Docker Images"
cd "$PROJECT_ROOT/workloads/websocket/app-instrumented"; docker build -t websocket-server-instrumented:latest .; kind load docker-image websocket-server-instrumented:latest --name "$CLUSTER_NAME"
cd "$PROJECT_ROOT/load-generator/websocket-client"; docker build -t websocket-loadgen:latest .; kind load docker-image websocket-loadgen:latest --name "$CLUSTER_NAME"
cd "$PROJECT_ROOT"

# --- 6. Deploy Workload ---
section "6. Deploying WebSocket Workload"
kubectl apply -f workloads/websocket/k8s/deployment-instrumented.yml
kubectl apply -f workloads/websocket/k8s/service.yml
kubectl wait --for=condition=ready pod -l app=websocket-server --timeout=180s

# --- 7. HPA with variable stabilization window ---
section "7. Applying HPA (scaleDown window: ${STABILIZATION_WINDOW}s)"
cat <<EOF | kubectl apply -f -
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: websocket-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: websocket-server
  minReplicas: 2
  maxReplicas: 15
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 60
  behavior:
    scaleUp:
      stabilizationWindowSeconds: 0
      policies:
        - type: Pods
          value: 4
          periodSeconds: 15
    scaleDown:
      stabilizationWindowSeconds: ${STABILIZATION_WINDOW}
      policies:
        - type: Pods
          value: 4
          periodSeconds: 60
EOF
log "HPA applied (scaleDown window: ${STABILIZATION_WINDOW}s)."

# --- 8. Wait for HPA metrics ---
section "8. Waiting for HPA Metrics"
WAITED=0; while true; do TOP=$(kubectl top pods -l app=websocket-server --no-headers 2>/dev/null || echo ""); [ -n "$TOP" ] && break; [ "$WAITED" -ge 180 ] && break; sleep 10; WAITED=$((WAITED+10)); done

# --- 9. Prometheus port-forward ---
section "9. Prometheus Port-Forward"
kubectl -n monitoring port-forward svc/prometheus 9090:9090 >/dev/null 2>&1 &
PROM_PID=$!
until curl -s http://localhost:9090/-/ready >/dev/null 2>&1; do sleep 2; done
PROM_WAIT=0; until curl -s "http://localhost:9090/api/v1/query?query=active_connections" | grep -q '"result":\[{'; do [ "$PROM_WAIT" -ge 120 ] && break; sleep 10; PROM_WAIT=$((PROM_WAIT+10)); done

# --- 10. Start collectors ---
section "10. Starting Metric Collectors"
( while true; do echo "$(date +%s)" >> "$RESULT_DIR/hpa.log"; kubectl get hpa websocket-hpa >> "$RESULT_DIR/hpa.log" 2>/dev/null || true; sleep "$SCRAPE_INTERVAL"; done ) &
HPA_PID=$!
( while true; do M=$(kubectl top pods -l app=websocket-server --no-headers 2>/dev/null || true); [ -n "$M" ] && { echo "$(date +%s)" >> "$RESULT_DIR/cpu.log"; echo "$M" >> "$RESULT_DIR/cpu.log"; }; sleep "$SCRAPE_INTERVAL"; done ) &
CPU_PID=$!
( while true; do echo "$(date +%s)" >> "$RESULT_DIR/pods.log"; kubectl get pods -l app=websocket-server -o wide >> "$RESULT_DIR/pods.log" 2>/dev/null || true; sleep "$SCRAPE_INTERVAL"; done ) &
POD_PID=$!
echo "timestamp,active_connections,reconnect_rate" > "$RESULT_DIR/prometheus_dump.csv"
( set +e; while true; do TS=$(date +%s); AV=$(curl -s "http://localhost:9090/api/v1/query?query=sum(active_connections)" | jq -r '.data.result[0].value[1] // 0'); RV=$(curl -s "http://localhost:9090/api/v1/query?query=sum(increase(new_connections_total%5B30s%5D))" | jq -r '.data.result[0].value[1] // 0'); echo "$TS,$AV,$RV" >> "$RESULT_DIR/prometheus_dump.csv"; sleep "$SCRAPE_INTERVAL"; done ) &
PROM_COLLECT_PID=$!
sleep 15

# --- 11. Load Phases ---
section "11. Running Load Phases"

# PHASE 1: CONNECT
log "PHASE: CONNECT -- 800 clients, CPU_WORK=1, ${CONNECT_DURATION}s"
echo "$(date +%s),CONNECT" >> "$RESULT_DIR/phase.log"
kubectl delete job websocket-loadgen --ignore-not-found=true 2>/dev/null || true; sleep 2
kubectl apply -f "$PROJECT_ROOT/load-generator/websocket-client/k8s/job.yaml"
CONNS_BEFORE_IDLE="0"; REPLICAS_BEFORE_IDLE="?"
ELAPSED=0
while [ "$ELAPSED" -lt "$CONNECT_DURATION" ]; do
  REPLICAS=$(kubectl get hpa websocket-hpa -o jsonpath='{.status.currentReplicas}' 2>/dev/null || echo "?")
  CPU_PCT=$(kubectl get hpa websocket-hpa -o jsonpath='{.status.currentMetrics[0].resource.current.averageUtilization}' 2>/dev/null || echo "?")
  CONNS=$(curl -s "http://localhost:9090/api/v1/query?query=sum(active_connections)" | jq -r '.data.result[0].value[1] // "?"' 2>/dev/null || echo "?")
  log "  [CONNECT +${ELAPSED}s] replicas=$REPLICAS cpu=${CPU_PCT}% connections=$CONNS"
  if [ "$ELAPSED" -ge $((CONNECT_DURATION - 15)) ]; then CONNS_BEFORE_IDLE="$CONNS"; REPLICAS_BEFORE_IDLE="$REPLICAS"; fi
  sleep 15; ELAPSED=$((ELAPSED + 15))
done

# PHASE 2: IDLE GAP
log "PHASE: IDLE GAP -- ${GAP_DURATION}s (window=${STABILIZATION_WINDOW}s)"
echo "$(date +%s),IDLE_GAP" >> "$RESULT_DIR/phase.log"
ELAPSED=0
while [ "$ELAPSED" -lt "$GAP_DURATION" ]; do
  REPLICAS=$(kubectl get hpa websocket-hpa -o jsonpath='{.status.currentReplicas}' 2>/dev/null || echo "?")
  CONNS=$(curl -s "http://localhost:9090/api/v1/query?query=sum(active_connections)" | jq -r '.data.result[0].value[1] // "?"' 2>/dev/null || echo "?")
  log "  [IDLE_GAP +${ELAPSED}s] replicas=$REPLICAS connections=$CONNS"
  sleep 15; ELAPSED=$((ELAPSED + 15))
done

# PHASE 3: CHECK
echo "$(date +%s),CHECK" >> "$RESULT_DIR/phase.log"
sleep 15
CONNS_AFTER_IDLE=$(curl -s "http://localhost:9090/api/v1/query?query=sum(active_connections)" | jq -r '.data.result[0].value[1] // "0"' 2>/dev/null || echo "0")
REPLICAS_AFTER_IDLE=$(kubectl get hpa websocket-hpa -o jsonpath='{.status.currentReplicas}' 2>/dev/null || echo "?")
CONNS_BEFORE_NUM=$(echo "$CONNS_BEFORE_IDLE" | awk '{printf "%d", $1+0}')
CONNS_AFTER_NUM=$(echo "$CONNS_AFTER_IDLE" | awk '{printf "%d", $1+0}')
[ "$CONNS_BEFORE_NUM" -gt 0 ] && LOSS_PCT=$(awk "BEGIN {printf \"%.1f\", (($CONNS_BEFORE_NUM-$CONNS_AFTER_NUM)/$CONNS_BEFORE_NUM)*100}") || LOSS_PCT="0.0"
[ "$CONNS_AFTER_NUM" -ge $((CONNS_BEFORE_NUM * 90 / 100)) ] && SURVIVED="true" || SURVIVED="false"
GAP_REL=$([ "$GAP_DURATION" -lt "$STABILIZATION_WINDOW" ] && echo "below" || echo "above")

cat > "$RESULT_DIR/tuning_result.csv" <<TEOF
stabilization_window_s,gap_duration_s,gap_relation,connections_before,connections_after,connections_survived,pct_lost,replicas_before,replicas_after
${STABILIZATION_WINDOW},${GAP_DURATION},${GAP_REL},${CONNS_BEFORE_NUM},${CONNS_AFTER_NUM},${SURVIVED},${LOSS_PCT},${REPLICAS_BEFORE_IDLE},${REPLICAS_AFTER_IDLE}
TEOF
log "Result: survived=$SURVIVED loss=${LOSS_PCT}% (before=$CONNS_BEFORE_NUM after=$CONNS_AFTER_NUM)"

# --- 12. Stop Collectors ---
section "12. Stopping Collectors"
kill $HPA_PID $CPU_PID $PROM_COLLECT_PID $POD_PID $PROM_PID 2>/dev/null || true; wait 2>/dev/null || true

# --- 13. Analysis ---
section "13. Running Analysis"
PROCESSED_DIR="$PROJECT_ROOT/results/processed/websocket/$EXPERIMENT_NAME/$SUBDIR"
[ -n "$RUN_ID" ] && PROCESSED_DIR="${PROCESSED_DIR}/run_${RUN_ID}"
mkdir -p "$PROCESSED_DIR"
export RAW_DIR="$RESULT_DIR"; export PROCESSED_DIR
python3 "$PROJECT_ROOT/analysis/experiment-b3/parse_logs_experiment_b3.py" || log "Parse failed"
cp "$RESULT_DIR/tuning_result.csv" "$PROCESSED_DIR/" 2>/dev/null || true

# --- 14. Cleanup ---
section "14. Deleting Kind Cluster"
kind delete cluster --name "$CLUSTER_NAME"

section "Done — Window=${STABILIZATION_WINDOW}s Gap=${GAP_DURATION}s Survived=${SURVIVED}"
