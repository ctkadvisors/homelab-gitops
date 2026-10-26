# MLflow Model Registry (Homelab) — Design

**Date:** 2026-07-08
**Status:** Approved (brainstorm complete)
**Repo:** new_localai (GitOps via Kustomize/ArgoCD)

## Goal

A self-hosted MLflow in the K3s homelab to track ML experiments and version/register
models — replacing loose model files (adapters, GGUFs) scattered on the Spark.
**Self-hosted, internal-only**: served at `mlflow.example.com` — a homelab domain whose
public DNS resolves to a private (RFC1918) MetalLB IP reachable only over Tailscale, so
it is not internet-exposed. The copyrighted-derived weights (e.g. the Tolkien 27B) never
leave the private network.

## Scope

**This spec = the MLflow + MinIO infrastructure only.** Instrumenting `tolkien-llm`
training code to log runs and back-registering existing models is a separate
follow-on spec (Phase 2).

## Architecture

Three components, deployed via Kustomize under `k8s-kustomized/base/ml-registry/`,
reconciled by ArgoCD (added to the base kustomization / production overlay):

1. **MinIO** — S3-compatible artifact store.
   - Deployment pinned to **elitemini2** (`kubernetes.io/hostname: elitemini2`),
     hostPath `/opt/minio-data` (mirrors the Qdrant hostPath pattern). ~454GB free
     now on a 1TB SSD (expandable).
   - ClusterIP service (`minio.ml-registry.svc:9000` API, `:9001` console).
   - One bucket: `mlflow-artifacts` (created by an init step).
   - Root creds via **Sealed-Secrets** (`secrets.example.com`).

2. **MLflow tracking server** — Deployment.
   - **Backend store:** the existing Postgres (`database` ns) — a new `mlflow`
     database + role. Tracking URI `postgresql://mlflow@postgresql.database.svc/mlflow`.
   - **Artifact store:** MinIO — `--default-artifact-root s3://mlflow-artifacts/`,
     `MLFLOW_S3_ENDPOINT_URL=http://minio.ml-registry.svc:9000`, AWS creds = MinIO creds.
   - ClusterIP service (`mlflow.ml-registry.svc:5000`).
   - Pinned to control-plane (matches OpenWebUI/other services' nodeSelector pattern).

3. **Postgres init** — a one-shot Kubernetes Job that connects to the existing
   Postgres and runs `CREATE DATABASE mlflow` + `CREATE ROLE mlflow` (idempotent,
   guarded). No new database server. Credentials sealed.

## Access & exposure

**`mlflow.example.com` is internal, not internet-exposed.** Verified against the real
manifests (`base/database/pgadmin.yaml`, `overlays/production/kagent/`): `*.example.com`
has a public cert but its DNS resolves to **10.0.0.200 (MetalLB primary LB IP, an
RFC1918 address)**, reachable only from devices on the user's Tailscale tailnet
(subnet route). The **Tailscale network boundary is the primary gate** — same posture
as `argocd.example.com` and `pgadmin.example.com`. This is why the URL satisfies both
"on my domain" and "keep it in my homelab."

Traefik IngressRoute mirrors the existing pattern exactly:
`entryPoints: [websecure]`, `match: Host(`mlflow.example.com`)`, `tls: secretName: example-tls`.

**Defense-in-depth basic-auth (recommended, optional).** Unlike pgAdmin/ArgoCD (which
have their own logins), MLflow ships with **no authentication at all** — so even behind
Tailscale, a second layer is cheap insurance. The homelab already has a **Traefik
`basicAuth` Middleware pattern** (`overlays/production/kagent/`, Sealed-Secret-backed);
reuse it: a `Middleware` referencing a sealed htpasswd, attached to the IngressRoute.
If matching the current homelab posture (Tailscale-only, no app auth) is preferred,
the middleware can be omitted — but given MLflow has zero built-in auth and holds the
copyrighted-derived weights, keeping it is the safer default.

The **MinIO API stays ClusterIP-only** (no ingress — reached only by the in-cluster
MLflow server); the MinIO console is not exposed (port-forward when needed).

## Data flow

Training on the Spark (in the `tolkien-dev` container) uses the `mlflow` Python client
with `MLFLOW_TRACKING_URI=https://mlflow.example.com` plus `MLFLOW_TRACKING_USERNAME` /
`MLFLOW_TRACKING_PASSWORD` (the basic-auth creds) → params/metrics go to Postgres,
artifacts (adapters, GGUFs) stream to MinIO via the MLflow server. Runs and the model
registry are browsed at `mlflow.example.com` (behind the same auth prompt); model
versions move through stages (None → Staging → Production).

## GitOps layout

```
k8s-kustomized/base/ml-registry/
  namespace.yaml            # ns: ml-registry
  minio.yaml                # Deployment (elitemini2, hostPath) + Service
  minio-sealed-secret.yaml  # root user/password
  mlflow.yaml               # Deployment + Service
  mlflow-sealed-secret.yaml # DB password + S3 (MinIO) creds
  postgres-init-job.yaml    # creates mlflow DB + role
  ingressroute.yaml         # Traefik: mlflow.example.com + basicAuth middleware
  basicauth-middleware.yaml # Traefik Middleware (basicAuth) referencing the sealed htpasswd
  basicauth-sealed-secret.yaml # htpasswd (user:password) for the middleware
  kustomization.yaml
```
Added to `base/kustomization.yaml` resources; ArgoCD `homelab-apps` auto-syncs.
Follows conventions: Sealed-Secrets for creds, node-label nodeSelectors, hostPath
storage on elitemini2, pod resource limits.

## Verification

1. ArgoCD syncs; MinIO + MLflow pods Running; init Job created the `mlflow` DB + bucket.
2. From the Spark: `mlflow` client (with the basic-auth env vars) logs a throwaway run
   (a param + metric + a small artifact file) to `https://mlflow.example.com`.
3. The run appears in the MLflow UI; the artifact lands in the `mlflow-artifacts`
   bucket in MinIO. That round-trip = done.

## Risks & mitigations

| Risk | Mitigation |
|---|---|
| MLflow has no built-in auth | Primary gate is the Tailscale network boundary (example.com → RFC1918 IP). Optional Traefik basicAuth middleware (reusing the kagent pattern, sealed htpasswd) as defense-in-depth. |
| Route accidentally made internet-routable | Would require changing MetalLB IP / DNS to a public address — a committed, reviewable change, not a default. |
| Artifact disk fills (28GB+ models) | elitemini2 hostPath ~454GB free of 1TB; monitor, expand partition toward 1TB as needed. |
| Spark not always in-cluster (Tailscale/sleep) | Logging happens during training (Spark awake); registry/UI live in the always-on cluster independent of the Spark. |
| MinIO single-node hostPath (not HA) | Acceptable for a personal homelab; data on elitemini2 SSD. Back up the bucket if models become precious. |
| Secrets in git | All creds via Sealed-Secrets; nothing plaintext committed. |

## Out of scope (→ later)

- Instrumenting `tolkien-llm` training to log to MLflow + back-registering the 27B/9B (Phase 2 spec).
- MLflow authentication / OIDC.
- HA / multi-node MinIO (distributed erasure coding).
- Public exposure of any kind.
