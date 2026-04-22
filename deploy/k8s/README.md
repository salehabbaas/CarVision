<div align="center">

# ☸️ CarVision — Kubernetes Deployment

**Production-grade multi-node deployment with horizontal autoscaling**

[![Kubernetes](https://img.shields.io/badge/Kubernetes-1.28+-326CE5?style=flat-square&logo=kubernetes&logoColor=white)](https://kubernetes.io)
[![Kustomize](https://img.shields.io/badge/Kustomize-Base-326CE5?style=flat-square&logo=kubernetes&logoColor=white)](https://kustomize.io)

</div>

---

## 🏗️ What's Included

```
deploy/k8s/base/
│
├── namespace.yaml           # carvision namespace
├── configmap.yaml           # Shared app configuration
├── secret-template.yaml     # Secret key reference (values injected externally)
│
├── api-deployment.yaml      # FastAPI backend — Deployment + Service
├── api-hpa.yaml             # Horizontal Pod Autoscaler for API
├── frontend-deployment.yaml # React frontend — Deployment + Service
│
├── worker-ingest.yaml       # Camera ingest worker
├── worker-detection.yaml    # Detection processing worker
├── worker-training.yaml     # YOLO training worker
│
├── media-pvc.yaml           # Persistent Volume Claim for media files
└── ingress.yaml             # NGINX Ingress routing
```

---

## 📋 Prerequisites

Before applying, ensure your cluster has:

| Requirement | Why |
|---|---|
| Kubernetes ≥ 1.28 | Base compatibility |
| **Metrics Server** | Required for HPA CPU/memory scaling |
| **NGINX Ingress Controller** | HTTP routing & TLS termination |
| Persistent Volume provisioner | For the media PVC |

---

## 🔐 Create Required Secrets

```bash
# Create the namespace
kubectl create namespace carvision

# Create the secrets (replace values with your own)
kubectl -n carvision create secret generic carvision-secrets \
  --from-literal=database_url="postgresql://user:pass@host:5432/carvision" \
  --from-literal=jwt_secret="your-strong-random-secret-here" \
  --from-literal=api_admin_user="admin" \
  --from-literal=api_admin_pass="your-admin-password"
```

---

## 🚀 Deploy

```bash
# Apply all base manifests with Kustomize
kubectl apply -k deploy/k8s/base

# Watch pods come up
kubectl -n carvision get pods -w
```

---

## ✅ Validate

```bash
# Check all pods are Running
kubectl -n carvision get pods

# Check autoscalers
kubectl -n carvision get hpa

# Check ingress routing
kubectl -n carvision get ingress

# Check persistent volume claim
kubectl -n carvision get pvc

# View API logs
kubectl -n carvision logs -l app=carvision-api --tail=50 -f

# View detection worker logs
kubectl -n carvision logs -l app=carvision-worker-detection --tail=50 -f
```

---

## ⚖️ Autoscaling

The API deployment has an HPA configured:

```yaml
# api-hpa.yaml
minReplicas: 1
maxReplicas: 5
metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
```

Workers scale independently — the training worker is intentionally kept at 1 replica to avoid concurrent training conflicts.

---

## 🌐 Ingress Routing

```
Internet
    │
    ▼
NGINX Ingress
    ├── /          →  frontend-service:80
    └── /api/      →  api-service:8000
```

Update `ingress.yaml` with your domain name before applying.

---

## 🗂️ Architecture Overview

```
┌─────────────────────────────────────────────────────┐
│                  carvision namespace                 │
│                                                      │
│  ┌────────────────┐   ┌──────────────────────────┐  │
│  │    Frontend    │   │      API  (HPA 1-5)      │  │
│  │  Deployment    │   │      Deployment          │  │
│  │  Service:80    │   │      Service:8000        │  │
│  └────────────────┘   └──────────────────────────┘  │
│                                │                     │
│                                ▼                     │
│                       ┌────────────────┐             │
│                       │  PostgreSQL    │             │
│                       │  (external or  │             │
│                       │   in-cluster)  │             │
│                       └────────────────┘             │
│                                                      │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────┐  │
│  │    Ingest    │  │  Detection   │  │ Training  │  │
│  │    Worker    │  │   Worker     │  │  Worker   │  │
│  └──────────────┘  └──────────────┘  └───────────┘  │
│                                                      │
│  ┌───────────────────────────────────────────────┐   │
│  │           Media PVC  (ReadWriteMany)          │   │
│  └───────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────┘
```

---

## 🗺️ Next Steps

- [ ] Add a message broker (Redis / RabbitMQ) for event-driven worker communication
- [ ] Configure TLS via cert-manager + Let's Encrypt on the Ingress
- [ ] Set up external PostgreSQL with connection pooling (PgBouncer)
- [ ] Add Prometheus + Grafana for observability
- [ ] Tune resource requests/limits per workload profile
