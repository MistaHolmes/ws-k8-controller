# WebSocket Server
### Build Image

```bash
cd future-work/workloads/websocket/app
docker build -t websocket-server .
```

### Run Container

```bash
docker run -p 8765:8765 -p 8080:8080 websocket-server
```

### Verify Metrics

```bash
curl http://localhost:8080/metrics
```
# WebSocket Load Generator
### Build Image

```bash
cd future-work/load-generator/websocket-loadgen
docker build -t websocket-loadgen .
```

### Run 1000 Clients

```bash
docker run websocket-loadgen ws://host.docker.internal:8765 1000
```

If running on Linux (no `host.docker.internal`), use:

```bash
docker run --network="host" websocket-loadgen ws://localhost:8765 1000
```

# MQTT Broker (Mosquitto)
### Start Broker

```bash
cd future-work/workloads/mqtt/app
docker compose up
```

Broker runs on:
```
localhost:1883
```

# MQTT Load Generator
### Build Image

```bash
cd future-work/load-generator/mqtt-loadgen
docker build -t mqtt-loadgen .
```
### Run 1000 MQTT Clients

```bash
docker run mqtt-loadgen host.docker.internal 1000
```

On Linux:

```bash
docker run --network="host" mqtt-loadgen localhost 1000
```

---

# Quick Summary Table

| Component         | Build Command                         | Run Command                                                        |
| ----------------- | ------------------------------------- | ------------------------------------------------------------------ |
| WebSocket Server  | `docker build -t websocket-server .`  | `docker run -p 8765:8765 -p 8080:8080 websocket-server`            |
| WebSocket LoadGen | `docker build -t websocket-loadgen .` | `docker run websocket-loadgen ws://host.docker.internal:8765 1000` |
| MQTT Broker       | `docker compose up`                   | (same command)                                                     |
| MQTT LoadGen      | `docker build -t mqtt-loadgen .`      | `docker run mqtt-loadgen host.docker.internal 1000`                |


# WebSocket Workload Setup on Kind

## 1. Build Docker Image

cd future-work/workloads/websocket/app
docker build -t websocket-server:latest .

---

## 2. Load Image into Kind Cluster

kind load docker-image websocket-server:latest

---

## 3. Deploy WebSocket Workload

cd ../k8s
kubectl apply -f deployment.yaml
kubectl apply -f service.yaml

---

## 4. Verify Deployment

kubectl get pods
kubectl get svc

---

## 5. Port Forward WebSocket Service

kubectl port-forward svc/websocket-service 8765:8765

---

## 6. Port Forward Metrics Endpoint

kubectl port-forward svc/websocket-service 8080:8080

---

## 7. Verify Metrics

curl http://localhost:8080/metrics


# Apply Prometheus Stack

From root of project:
```bash
kubectl apply -f monitoring/prometheus/namespace.yaml
kubectl apply -f monitoring/prometheus/rbac.yaml
kubectl apply -f monitoring/prometheus/configmap.yaml
kubectl apply -f monitoring/prometheus/deployment.yaml
kubectl apply -f monitoring/prometheus/service.yaml
```
### Wait for readiness:
```bash
kubectl -n monitoring rollout status deployment/prometheus
```
### Port-forward (recommended):
```bash
kubectl -n monitoring port-forward svc/prometheus 9090:9090
```
### Open:
```bash
http://localhost:9090
```


### Check Logs During Experiment
```bash
kubectl get hpa -w
```

```bash
 watch -n 2 ls -lh results/raw/websocket/experiment-b2-hpa-churn-instrumented/
```