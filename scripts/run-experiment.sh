# run-experiment.sh — Unified Orchestrator (WebSocket Stateful Project)

# Supported scenarios:
#   hpa-baseline
#   stateful
#
# Usage:
#   ./run-experiment.sh hpa-baseline
#   ./run-experiment.sh stateful
#   ./run-experiment.sh hpa-baseline stateful

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKLOAD_DIR="$SCRIPT_DIR/../workloads/websocket/k8s"
LOADGEN_DIR="$SCRIPT_DIR/../load-generator/websocket-loadgen/k8s"
MONITORING_DIR="$SCRIPT_DIR/../monitoring"
RESULTS_BASE="$SCRIPT_DIR/results"

SCENARIOS=("${@:-hpa-baseline stateful}")

NUM_CLIENTS=1000
EXPERIMENT_DURATION=300

# -------------------------
# Helper Functions
# -------------------------

reset_monitoring() {
    echo "[*] Resetting monitoring namespace..."
    kubectl delete namespace monitoring --ignore-not-found
    kubectl create namespace monitoring
}

install_prometheus() {
    echo "[*] Installing Prometheus..."
    kubectl apply -f "$MONITORING_DIR/prometheus.yaml"
    kubectl -n monitoring rollout status deployment/prometheus --timeout=300s
}

install_metrics_server() {
    echo "[*] Ensuring metrics-server is installed..."
    if ! kubectl -n kube-system get deployment metrics-server &>/dev/null; then
        kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml
        kubectl -n kube-system rollout status deployment/metrics-server --timeout=300s
    fi
}

deploy_workload() {
    echo "[*] Deploying WebSocket workload..."
    kubectl apply -f "$WORKLOAD_DIR/deployment.yaml"
    kubectl apply -f "$WORKLOAD_DIR/service.yaml"
    kubectl wait --for=condition=ready pod -l app=websocket-server --timeout=120s
}

cleanup_workload() {
    echo "[*] Cleaning workload..."
    kubectl delete hpa websocket-hpa --ignore-not-found
    kubectl delete deployment websocket-server --ignore-not-found
    kubectl delete job websocket-loadgen --ignore-not-found
}

deploy_load_generator() {
    echo "[*] Deploying load generator..."
    kubectl apply -f "$LOADGEN_DIR/job.yaml"
}

apply_hpa_baseline() {
    echo "[*] Applying CPU-based HPA..."
    kubectl apply -f "$WORKLOAD_DIR/hpa.yaml"
}

apply_stateful_controller() {
    echo "[*] Applying Stateful Autoscaler..."
    kubectl apply -f "$SCRIPT_DIR/../controller/config/deployment.yaml"
    kubectl apply -f "$SCRIPT_DIR/../controller/config/crd.yaml"
    kubectl apply -f "$SCRIPT_DIR/../controller/config/statefulhpa.yaml"
}

start_collectors() {
    local outdir="$1"
    mkdir -p "$outdir"
    echo "[*] Starting collectors..."
    kubectl get pods -o wide > "$outdir/pods_initial.txt"
}

snapshot_state() {
    local outdir="$1"
    kubectl get pods -o wide > "$outdir/pods_final.txt"
    kubectl get hpa > "$outdir/hpa_status.txt" 2>/dev/null || true
}

run_experiment() {
    local scenario="$1"
    local run_dir="$RESULTS_BASE/$scenario"

    mkdir -p "$run_dir"

    echo "=================================================="
    echo " Running Scenario: $scenario"
    echo "=================================================="

    cleanup_workload
    reset_monitoring
    install_prometheus
    install_metrics_server
    deploy_workload

    sleep 30  # Prometheus warm-up

    case "$scenario" in
        hpa-baseline)
            apply_hpa_baseline
            ;;
        stateful)
            apply_stateful_controller
            ;;
    esac

    deploy_load_generator
    start_collectors "$run_dir"

    echo "[*] Running for ${EXPERIMENT_DURATION}s..."
    sleep "$EXPERIMENT_DURATION"

    snapshot_state "$run_dir"
    cleanup_workload

    echo "[✓] Scenario completed: $scenario"
}

# -------------------------
# Main
# -------------------------

echo "=================================================="
echo " WebSocket Stateful Autoscaling Experiments"
echo " Scenarios: ${SCENARIOS[*]}"
echo "=================================================="

for scenario in "${SCENARIOS[@]}"; do
    run_experiment "$scenario"
done

echo ""
echo "[✓] All experiments completed"