# MLflow Model Registry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Deploy self-hosted MLflow (tracking + model registry) into the K3s homelab, backed by the existing Postgres and a new MinIO S3 artifact store, served internally at `mlflow.example.com`, via Kustomize/ArgoCD.

**Architecture:** New `ml-registry` namespace under `k8s-kustomized/base/ml-registry/`. MinIO Deployment (hostPath on elitemini2, mirroring Qdrant) provides S3 artifact storage; a one-shot Job creates the `mlflow-artifacts` bucket. A Postgres-init Job creates the `mlflow` database + role in the existing `postgresql.database.svc`. The MLflow server Deployment uses Postgres as its backend store and MinIO as its artifact root. A Traefik IngressRoute exposes it at `mlflow.example.com` (internal — resolves to the RFC1918 MetalLB IP, Tailscale-only), with an optional basic-auth middleware.

**Tech Stack:** Kubernetes (K3s), Kustomize, ArgoCD, MinIO, MLflow (`ghcr.io/mlflow/mlflow`), PostgreSQL, Traefik IngressRoute.

## Global Constraints

- GitOps only: edit `k8s-kustomized/`, validate with `kubectl kustomize k8s-kustomized/overlays/production`, commit, push — never `kubectl apply -f`/`edit`/`patch`/`create` against the live cluster.
- Secrets follow the repo's actual pattern: **plaintext `kind: Secret` manifests** committed in-repo (as `base/database/postgresql.yaml` and the kagent overlay do). Not SealedSecrets. (Can be sealed later via `secrets.example.com`.)
- Postgres: host `postgresql.database.svc.cluster.local:5432`, superuser `postgres`, password `REDACTED` (from `base/database/postgresql.yaml`).
- MinIO storage: hostPath `/opt/minio-data` on **elitemini2** (`kubernetes.io/hostname: elitemini2`), same node/pattern as Qdrant's `/opt/qdrant-data`.
- Allowed exposure: `mlflow.example.com` via Traefik IngressRoute `entryPoints: [websecure]`, `tls: secretName: example-tls` (mirroring `base/database/pgadmin.yaml`). Internal-only (MetalLB RFC1918 IP, Tailscale).
- The production overlay force-patches many services' nodeSelector to control-plane; MinIO must stay on elitemini2. Verify the overlay does NOT patch `ml-registry` (Qdrant/vector-db is precedent — it stays on elitemini2).

---

## File Structure

```
k8s-kustomized/base/ml-registry/
  namespace.yaml            # ns: ml-registry
  minio-secret.yaml         # MinIO root user/password (plaintext Secret)
  minio.yaml                # Deployment (elitemini2, hostPath) + Service (api:9000, console:9001)
  minio-init-job.yaml       # Job: mc mb mlflow-artifacts (idempotent)
  postgres-init-job.yaml    # Job: CREATE DATABASE mlflow + role (idempotent)
  mlflow-secret.yaml        # MLflow DB URI + S3(MinIO) creds (plaintext Secret)
  mlflow.yaml               # Deployment + Service (:5000)
  ingressroute.yaml         # Traefik: mlflow.example.com (websecure, example-tls)
  kustomization.yaml
```
Plus: modify `k8s-kustomized/base/kustomization.yaml` to add `ml-registry/`.

---

### Task 1: Namespace + MinIO secret + kustomization skeleton

**Files:**
- Create: `k8s-kustomized/base/ml-registry/namespace.yaml`
- Create: `k8s-kustomized/base/ml-registry/minio-secret.yaml`
- Create: `k8s-kustomized/base/ml-registry/kustomization.yaml`

- [ ] **Step 1: Write `namespace.yaml`**

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: ml-registry
  labels:
    app.kubernetes.io/part-of: local-ai-homelab
```

- [ ] **Step 2: Write `minio-secret.yaml`**

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: minio-root
  namespace: ml-registry
type: Opaque
stringData:
  root-user: "mlflow-minio"
  root-password: "REDACTED"
```

- [ ] **Step 3: Write `kustomization.yaml` (resources added as tasks land)**

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: ml-registry
resources:
  - namespace.yaml
  - minio-secret.yaml
  - minio.yaml
  - minio-init-job.yaml
  - postgres-init-job.yaml
  - mlflow-secret.yaml
  - mlflow.yaml
  - ingressroute.yaml
```

- [ ] **Step 4: Validate render (only namespace + secret exist yet, so render just those first)**

Temporarily comment out not-yet-created resources, then:
Run: `kubectl kustomize k8s-kustomized/base/ml-registry`
Expected: renders the Namespace + Secret without error.

- [ ] **Step 5: Commit**

```bash
git add k8s-kustomized/base/ml-registry/{namespace,minio-secret,kustomization}.yaml
git commit -m "feat(ml-registry): namespace + minio secret + kustomization skeleton"
```

---

### Task 2: MinIO deployment + service

**Files:**
- Create: `k8s-kustomized/base/ml-registry/minio.yaml`

**Interfaces:**
- Consumes: `minio-root` Secret (Task 1).
- Produces: Service `minio.ml-registry.svc:9000` (S3 API), `:9001` (console); bucket store on elitemini2 hostPath.

- [ ] **Step 1: Write `minio.yaml`** (mirrors Qdrant: nodeSelector elitemini2, hostPath, Recreate)

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: minio
  namespace: ml-registry
  labels:
    app: minio
spec:
  replicas: 1
  strategy:
    type: Recreate
  selector:
    matchLabels:
      app: minio
  template:
    metadata:
      labels:
        app: minio
    spec:
      nodeSelector:
        kubernetes.io/hostname: elitemini2
      securityContext:
        fsGroup: 1000
      containers:
        - name: minio
          image: minio/minio:latest
          args: ["server", "/data", "--console-address", ":9001"]
          env:
            - name: MINIO_ROOT_USER
              valueFrom:
                secretKeyRef: { name: minio-root, key: root-user }
            - name: MINIO_ROOT_PASSWORD
              valueFrom:
                secretKeyRef: { name: minio-root, key: root-password }
          ports:
            - containerPort: 9000
              name: api
            - containerPort: 9001
              name: console
          resources:
            requests: { memory: "512Mi", cpu: "250m" }
            limits: { memory: "2Gi", cpu: "1000m" }
          volumeMounts:
            - name: minio-storage
              mountPath: /data
      volumes:
        - name: minio-storage
          hostPath:
            path: /opt/minio-data
            type: DirectoryOrCreate
---
apiVersion: v1
kind: Service
metadata:
  name: minio
  namespace: ml-registry
  labels:
    app: minio
spec:
  selector:
    app: minio
  ports:
    - name: api
      port: 9000
      targetPort: 9000
    - name: console
      port: 9001
      targetPort: 9001
```

- [ ] **Step 2: Validate render**

Run: `kubectl kustomize k8s-kustomized/base/ml-registry`
Expected: MinIO Deployment (nodeSelector elitemini2, hostPath /opt/minio-data) + Service render cleanly.

- [ ] **Step 3: Commit**

```bash
git add k8s-kustomized/base/ml-registry/minio.yaml
git commit -m "feat(ml-registry): MinIO deployment (elitemini2 hostPath) + service"
```

---

### Task 3: MinIO bucket-init Job

**Files:**
- Create: `k8s-kustomized/base/ml-registry/minio-init-job.yaml`

**Interfaces:**
- Consumes: `minio` Service (Task 2), `minio-root` Secret.
- Produces: the `mlflow-artifacts` bucket.

- [ ] **Step 1: Write `minio-init-job.yaml`** (idempotent — `--ignore-existing`; retries until MinIO is up)

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: minio-init-bucket
  namespace: ml-registry
spec:
  backoffLimit: 10
  template:
    spec:
      restartPolicy: OnFailure
      containers:
        - name: mc
          image: minio/mc:latest
          env:
            - name: ROOT_USER
              valueFrom: { secretKeyRef: { name: minio-root, key: root-user } }
            - name: ROOT_PASSWORD
              valueFrom: { secretKeyRef: { name: minio-root, key: root-password } }
          command: ["/bin/sh", "-c"]
          args:
            - |
              until mc alias set local http://minio.ml-registry.svc.cluster.local:9000 "$ROOT_USER" "$ROOT_PASSWORD"; do
                echo "waiting for minio..."; sleep 3;
              done
              mc mb --ignore-existing local/mlflow-artifacts
              echo "bucket ready"
```

- [ ] **Step 2: Validate render**

Run: `kubectl kustomize k8s-kustomized/base/ml-registry | grep -A2 minio-init-bucket`
Expected: the Job renders.

- [ ] **Step 3: Commit**

```bash
git add k8s-kustomized/base/ml-registry/minio-init-job.yaml
git commit -m "feat(ml-registry): MinIO bucket-init job (mlflow-artifacts)"
```

---

### Task 4: Postgres-init Job (create mlflow DB + role)

**Files:**
- Create: `k8s-kustomized/base/ml-registry/postgres-init-job.yaml`

**Interfaces:**
- Consumes: existing Postgres (`postgresql.database.svc:5432`, superuser `postgres`).
- Produces: `mlflow` database + `mlflow` role (password `REDACTED`).

- [ ] **Step 1: Write `postgres-init-job.yaml`** (idempotent via `IF NOT EXISTS` guards)

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: mlflow-postgres-init
  namespace: ml-registry
spec:
  backoffLimit: 10
  template:
    spec:
      restartPolicy: OnFailure
      containers:
        - name: psql
          image: postgres:16-alpine
          env:
            - name: PGHOST
              value: postgresql.database.svc.cluster.local
            - name: PGPORT
              value: "5432"
            - name: PGUSER
              value: postgres
            - name: PGPASSWORD
              value: "REDACTED"
          command: ["/bin/sh", "-c"]
          args:
            - |
              until pg_isready -h "$PGHOST" -p "$PGPORT" -U "$PGUSER"; do sleep 3; done
              psql -v ON_ERROR_STOP=1 -d postgres <<'SQL'
              DO $$ BEGIN
                IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='mlflow') THEN
                  CREATE ROLE mlflow LOGIN PASSWORD 'REDACTED';
                END IF;
              END $$;
              SELECT 'CREATE DATABASE mlflow OWNER mlflow'
              WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname='mlflow')\gexec
              SQL
              echo "mlflow db + role ready"
```

- [ ] **Step 2: Validate render**

Run: `kubectl kustomize k8s-kustomized/base/ml-registry | grep mlflow-postgres-init`
Expected: the Job renders.

- [ ] **Step 3: Commit**

```bash
git add k8s-kustomized/base/ml-registry/postgres-init-job.yaml
git commit -m "feat(ml-registry): postgres-init job creates mlflow db + role"
```

---

### Task 5: MLflow secret + deployment + service

**Files:**
- Create: `k8s-kustomized/base/ml-registry/mlflow-secret.yaml`
- Create: `k8s-kustomized/base/ml-registry/mlflow.yaml`

**Interfaces:**
- Consumes: `mlflow` DB (Task 4), `minio` Service + creds (Tasks 2–3), `mlflow-artifacts` bucket.
- Produces: Service `mlflow.ml-registry.svc:5000` (tracking + registry API + UI).

- [ ] **Step 1: Write `mlflow-secret.yaml`**

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: mlflow-config
  namespace: ml-registry
type: Opaque
stringData:
  backend-store-uri: "postgresql://mlflow:REDACTED@postgresql.database.svc.cluster.local:5432/mlflow"
  aws-access-key-id: "mlflow-minio"
  aws-secret-access-key: "REDACTED"
```

- [ ] **Step 2: Write `mlflow.yaml`** (official image; installs psycopg + boto3 at start; MinIO as S3)

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: mlflow
  namespace: ml-registry
  labels:
    app: mlflow
spec:
  replicas: 1
  selector:
    matchLabels:
      app: mlflow
  template:
    metadata:
      labels:
        app: mlflow
    spec:
      containers:
        - name: mlflow
          image: ghcr.io/mlflow/mlflow:v2.16.2
          command: ["/bin/sh", "-c"]
          args:
            - |
              pip install --no-cache-dir psycopg2-binary boto3 >/dev/null 2>&1
              exec mlflow server \
                --host 0.0.0.0 --port 5000 \
                --backend-store-uri "$BACKEND_STORE_URI" \
                --default-artifact-root s3://mlflow-artifacts/ \
                --serve-artifacts
          env:
            - name: BACKEND_STORE_URI
              valueFrom: { secretKeyRef: { name: mlflow-config, key: backend-store-uri } }
            - name: MLFLOW_S3_ENDPOINT_URL
              value: "http://minio.ml-registry.svc.cluster.local:9000"
            - name: AWS_ACCESS_KEY_ID
              valueFrom: { secretKeyRef: { name: mlflow-config, key: aws-access-key-id } }
            - name: AWS_SECRET_ACCESS_KEY
              valueFrom: { secretKeyRef: { name: mlflow-config, key: aws-secret-access-key } }
          ports:
            - containerPort: 5000
              name: http
          resources:
            requests: { memory: "512Mi", cpu: "250m" }
            limits: { memory: "2Gi", cpu: "1000m" }
---
apiVersion: v1
kind: Service
metadata:
  name: mlflow
  namespace: ml-registry
  labels:
    app: mlflow
spec:
  selector:
    app: mlflow
  ports:
    - name: http
      port: 5000
      targetPort: 5000
```

- [ ] **Step 3: Validate render**

Run: `kubectl kustomize k8s-kustomized/base/ml-registry | grep -E 'kind: Deployment|name: mlflow'`
Expected: MLflow Deployment + Service render; backend URI + S3 env wired from the secret.

- [ ] **Step 4: Commit**

```bash
git add k8s-kustomized/base/ml-registry/mlflow-secret.yaml k8s-kustomized/base/ml-registry/mlflow.yaml
git commit -m "feat(ml-registry): MLflow server (postgres backend + minio artifacts)"
```

---

### Task 6: IngressRoute (mlflow.example.com)

**Files:**
- Create: `k8s-kustomized/base/ml-registry/ingressroute.yaml`

**Interfaces:**
- Consumes: `mlflow` Service (Task 5).
- Produces: `https://mlflow.example.com` (internal via MetalLB RFC1918 / Tailscale).

- [ ] **Step 1: Write `ingressroute.yaml`** (mirrors `base/database/pgadmin.yaml`)

```yaml
apiVersion: traefik.io/v1alpha1
kind: IngressRoute
metadata:
  name: mlflow-ingress
  namespace: ml-registry
  labels:
    app: mlflow
spec:
  entryPoints:
    - websecure
  routes:
    - match: Host(`mlflow.example.com`)
      kind: Rule
      services:
        - name: mlflow
          port: 5000
  tls:
    secretName: example-tls
```

- [ ] **Step 2: Validate render**

Run: `kubectl kustomize k8s-kustomized/base/ml-registry | grep -A2 'kind: IngressRoute'`
Expected: IngressRoute for `mlflow.example.com`, websecure, `example-tls`.

> Note: `example-tls` must exist in the `ml-registry` namespace for TLS. Check how pgadmin/database get the cert (likely a shared/reflected secret or cert-manager Certificate). If it is namespace-scoped, add a cert-manager `Certificate` or secret-reflection for `ml-registry` — mirror whatever `base/database/` does. Confirm during Task 7 render.

- [ ] **Step 3: Commit**

```bash
git add k8s-kustomized/base/ml-registry/ingressroute.yaml
git commit -m "feat(ml-registry): internal IngressRoute mlflow.example.com"
```

---

### Task 7: Wire into base kustomization + full-overlay validation

**Files:**
- Modify: `k8s-kustomized/base/kustomization.yaml` (add `ml-registry/` to resources)

- [ ] **Step 1: Add `ml-registry/` to the resources list**

In `k8s-kustomized/base/kustomization.yaml`, under `resources:`, add `  - ml-registry/` (alongside `vector-db/`).

- [ ] **Step 2: Full production render (the real gate)**

Run: `kubectl kustomize k8s-kustomized/overlays/production > /tmp/prod-render.yaml && echo OK`
Expected: `OK`. Then verify MinIO's nodeSelector survived the overlay:
Run: `grep -A3 'name: minio' /tmp/prod-render.yaml | grep -A2 nodeSelector || grep -B2 -A6 'app: minio' /tmp/prod-render.yaml | grep hostname`
Expected: `kubernetes.io/hostname: elitemini2` still present (overlay did NOT force it to control-plane). If it was patched, add an exclusion/patch so ml-registry keeps its nodeSelector (mirror how vector-db is handled).

- [ ] **Step 3: Verify the cert secret resolves for the ingress namespace** (from the Task 6 note). If `example-tls` isn't available in `ml-registry`, add the cert-manager `Certificate` (mirroring `base/database/`) to `ml-registry/` and re-render.

- [ ] **Step 4: Commit**

```bash
git add k8s-kustomized/base/kustomization.yaml
git commit -m "feat(ml-registry): wire ml-registry into base kustomization"
```

---

### Task 8: Deploy (push) + verify end-to-end

**Files:** none (deployment + verification).

- [ ] **Step 1: Push — ArgoCD auto-syncs**

```bash
git push origin main
```

- [ ] **Step 2: Watch the sync + pods**

```bash
ssh elitemini "kubectl -n argocd get application homelab-apps -o jsonpath='{.status.sync.status}'; echo; kubectl -n ml-registry get pods,jobs"
```
Expected: `homelab-apps` progresses to Synced; `minio` + `mlflow` pods Running; `minio-init-bucket` and `mlflow-postgres-init` Jobs Complete.

- [ ] **Step 3: Verify the mlflow DB + bucket exist**

```bash
ssh elitemini "kubectl -n ml-registry logs job/mlflow-postgres-init | tail -2; kubectl -n ml-registry logs job/minio-init-bucket | tail -2"
```
Expected: `mlflow db + role ready` and `bucket ready`.

- [ ] **Step 4: Log a test run from the Spark (the true round-trip)**

On the Spark (`tolkien-dev` container or host with `pip install mlflow boto3`):
```bash
MLFLOW_TRACKING_URI=https://mlflow.example.com python - <<'PY'
import mlflow
mlflow.set_experiment("smoke")
with mlflow.start_run():
    mlflow.log_param("hello", "world")
    mlflow.log_metric("acc", 0.99)
    with open("/tmp/note.txt","w") as f: f.write("mlflow works")
    mlflow.log_artifact("/tmp/note.txt")
print("logged")
PY
```
Expected: `logged`, no error.

- [ ] **Step 5: Confirm in the UI + MinIO**

Browse `https://mlflow.example.com` (over Tailscale) → the `smoke` experiment shows the run with the param, metric, and `note.txt` artifact. The artifact object exists in the `mlflow-artifacts` bucket in MinIO. That round-trip = **done**.

---

## Self-Review

**Spec coverage:** MinIO artifact store (Tasks 1–3) ✓; Postgres backend via init Job (Task 4) ✓; MLflow server wired to both (Task 5) ✓; internal `mlflow.example.com` IngressRoute (Task 6) ✓; GitOps wiring + overlay nodeSelector guard (Task 7) ✓; deploy + round-trip verification (Task 8) ✓. Basic-auth middleware was **optional** in the spec (defense-in-depth) — deferred (Tailscale is the primary gate); add later as a small follow-up if desired.

**Placeholder scan:** No TBD/TODO in deliverables. The Task 6 cert-secret note and Task 7 overlay-nodeSelector check are explicit verification steps with concrete fallbacks, not hand-waves.

**Consistency:** Secret keys match across tasks — `minio-root`{root-user,root-password} used in minio.yaml + minio-init + mlflow-secret's S3 creds; `mlflow-config`{backend-store-uri,aws-*} used in mlflow.yaml; the `mlflow` DB/role/password (`REDACTED`) created in Task 4 matches the URI in Task 5. Service DNS names consistent (`minio.ml-registry.svc:9000`, `mlflow.ml-registry.svc:5000`).

**Deferred:** basic-auth middleware; sealing the plaintext secrets (repo currently commits plaintext — consistent with existing pattern); instrumenting `tolkien-llm` to log to MLflow + registering the 27B (the next, separate cycle).
