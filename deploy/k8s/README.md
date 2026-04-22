# CarVision Kubernetes Base Manifests

This directory provides a baseline multi-node deployment layout with:

- API deployment + HPA
- Frontend deployment
- Ingest, Detection, and Training worker deployments
- Shared config map
- Media PVC
- Ingress routing

## Prerequisites

- Kubernetes cluster with Metrics Server
- NGINX Ingress Controller
- Secret named `carvision-secrets` in namespace `carvision` with keys:
  - `database_url`
  - `jwt_secret`
  - `api_admin_user`
  - `api_admin_pass`

## Apply

```bash
kubectl apply -k deploy/k8s/base
```

## Validate

```bash
kubectl -n carvision get pods
kubectl -n carvision get hpa
kubectl -n carvision get ingress
```

## Notes

- Worker deployments currently provide isolated process boundaries and independent scaling.
- Queue/broker integration is the next step for full event-driven processing.
