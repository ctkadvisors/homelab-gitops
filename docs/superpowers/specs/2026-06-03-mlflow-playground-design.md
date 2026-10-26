# MLflow Playground — Design

**Date:** 2026-06-03
**Status:** Approved (design); implementation pending
**Author:** Chris Knuteson (with Claude)

## Goal

Stand up a self-hosted MLflow 3.x tracking + UI server at
`https://mlflow.example.com` as a personal playground to learn MLflow's
GenAI features (tracing/observability, LLM eval + judges, prompt
registry) and classic experiment tracking, wired to experiment against
the existing OpenAI-compatible LLM gateway (`kagent-llm-gateway`).

## Key insight that shapes scope

MLflow's GenAI eval/judge and autolog LLM calls happen **client-side**
— in the process where `mlflow.openai.autolog()` / `mlflow.genai.evaluate()`
runs — not on the tracking server. The MLflow server only stores
traces/metrics/artifacts. Therefore the MLflow server **never needs to
reach `kagent-llm-gateway`**, and we do not touch the gateway's
ingress-locking NetworkPolicy. "Gateway integration" is purely a
client-side wiring concern, delivered as documentation.

## Architecture

A single MLflow server container, deployed via raw Kustomize manifests
(mirrors the `langfuse` overlay layout) and synced by the `homelab-apps`
ArgoCD Application that reconciles `overlays/production`. No separate
ArgoCD Application or Helm chart — MLflow-the-server is one process, so
raw manifests are more transparent than the community chart.

```
k8s-kustomized/overlays/production/mlflow/
  namespace.yaml        # mlflow-system namespace
  db-bootstrap.yaml     # Secret + idempotent Job → creates mlflow db/user
                        #   on the shared pgvector instance (langfuse pattern)
  deployment.yaml       # MLflow Deployment + Service (ClusterIP :5000) + artifacts PVC
  ingressroute.yaml     # Traefik IngressRoute mlflow.example.com + cert-manager Certificate
  kustomization.yaml
  README.md             # client-side gateway wiring snippet
# overlays/production/kustomization.yaml gains one line: "- mlflow"
```

### Components

**MLflow server (deployment.yaml)**
- Image: official `ghcr.io/mlflow/mlflow` (pin a 3.x tag).
- Command (v1): `sh -c "pip install psycopg2-binary && mlflow server \
  --host 0.0.0.0 --port 5000 \
  --backend-store-uri postgresql://mlflow:<pw>@postgresql.database.svc.cluster.local:5432/mlflow \
  --artifacts-destination file:///mlartifacts --serve-artifacts"`
  - `--serve-artifacts` → clients upload/download artifacts *through* the
    server (proxied artifact access), so the Mac only ever talks to the
    one subdomain; no direct artifact-store access needed.
  - Runtime `pip install psycopg2-binary` avoids a custom image build.
    Trade-off: slightly slower pod start. Follow-up option: build a tiny
    pinned image for the Gitea registry for faster starts.
- Service: ClusterIP, port 5000.
- Artifacts: `local-path` PVC, 10Gi, mounted at `/mlartifacts`.
- Resources: requests cpu 100m / mem 256Mi; limits cpu 1 / mem 1Gi.
- `nodeSelector: kubernetes.io/arch: amd64` — lands on either x86 node
  (elitemini / elitemini2), not pinned to elitemini2 (which goes offline
  in Windows/Sunshine dual-boot mode). Jetsons (ARM/GPU) excluded.

**Backend store + DB (db-bootstrap.yaml)**
- New `mlflow` role + `mlflow` database on the existing
  `postgresql.database.svc.cluster.local` (pgvector/pgvector:pg16).
- Idempotent bootstrap `Job` in the `database` namespace (exact langfuse
  pattern: wait for pg_isready, `CREATE DATABASE`/`CREATE ROLE` guarded
  by existence checks, grant + schema owner).
- Password stored as a plaintext Secret in-git — matches the homelab's
  existing single-user posture for langfuse and the gateway. Consumed by
  the deployment as an env var / assembled DSN.

**Ingress + TLS (ingressroute.yaml)**
- Traefik `IngressRoute`, entryPoint `websecure`, host
  `mlflow.example.com`, routed to the MLflow Service :5000, with the
  `ingress-system-security-headers@kubernetescrd` middleware.
- cert-manager `Certificate` (issuer `letsencrypt-prod`, ClusterIssuer)
  for `mlflow.example.com` → secret `example-tls-mlflow`.

### Auth / trust boundary

No application auth. Tailscale VPN + cluster NetworkPolicy is the trust
boundary, identical to the langfuse precedent.

### Gateway wiring (documentation, not deployment)

The gateway (`kagent-llm-gateway.kagent-system:4000`, OpenAI-compatible,
bearer token in secret `kagent-llm-gateway-token`) is internal-only by
design. From the Mac, the playground flow is:

```python
import mlflow, openai
mlflow.set_tracking_uri("https://mlflow.example.com")
mlflow.set_experiment("playground")
mlflow.openai.autolog()  # auto-traces every call into MLflow
# separate terminal:
#   kubectl port-forward -n kagent-system svc/kagent-llm-gateway 4000:4000
client = openai.OpenAI(
    base_url="http://localhost:4000/v1",
    api_key="sk-kagent-REDACTED",
)
client.chat.completions.create(model="nemotron-3-nano:4b", messages=[...])
```

This snippet lives in the mlflow folder `README.md`.

## Out of scope

- MLflow basic-auth / Traefik basicAuth middleware.
- MinIO / S3 artifact store (local-path PVC is sufficient).
- Exposing `kagent-llm-gateway` externally.
- Server-side, in-cluster LLM-judge eval. That would require adding
  `mlflow-system` to the gateway chart's ingress allowlist, which lives
  in the `ctkadvisors/kagent` repo — noted follow-up, not this change.
- A pre-built MLflow image for the Gitea registry (runtime pip-install
  is the v1 approach).

## Validation & rollout

- Local (offline-capable): `kubectl kustomize k8s-kustomized/overlays/production`
  must render cleanly with the new resources.
- Rollout is GitOps: commit + push; `homelab-apps` auto-syncs when the
  cluster is powered on. (Homelab is currently powered off — manifests
  wait for power-on.)
- Post-power-on checks: bootstrap Job `Completed`; MLflow pod `Running`
  and `/health` OK; cert `Ready`; `https://mlflow.example.com` loads the
  UI; a test run from the Mac shows up in the UI.
