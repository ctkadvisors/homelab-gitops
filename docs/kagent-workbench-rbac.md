# kagent-workbench — RBAC + Auth Deployment Plan

**Date:** 2026-04-26
**Status:** Plan only — chart + images do not yet exist (see "Blockers" below).
**Owners:** kagent platform (RBAC source-of-truth lives in the kagent
repo's Helm chart, not here).

This document describes how the kagent Workbench API + UI will be
deployed onto the homelab K3s cluster, what RBAC the API needs, and
which existing homelab patterns it integrates with. It is a *planning*
artifact in `new_localai/` — the actual RBAC YAML belongs in the
Workbench Helm chart at
`packages/workbench-api/charts/kagent-workbench/templates/rbac.yaml`
inside the kagent repo, NOT here.

---

## 1. Workload shape

Two pods, one Application:

- **`kagent-workbench-api`** — Node 22 + tsx; thin facade over the
  Kubernetes API. Watches `Agent`, `AgentTask`, `AgentCapability`, and
  the operator-owned `batch/Job` + `Pod` objects. Streams DTOs to the
  UI by SSE/WS. See `kagent/docs/WORKBENCH.md` §5.
- **`kagent-workbench-ui`** — Next.js 15 / React 19; pure browser
  client. Talks only to the API in-cluster and to Langfuse-style
  external trace links. No K8s creds itself.

Both deploy into the **`kagent-system`** namespace alongside the
operator. Same trust boundary, same pull-secret
(`gitea-registry-secret`), same image registry
(`git.example.com/homelab/`).

---

## 2. RBAC plan (read-only first)

The Workbench API is the only component that needs Kubernetes
credentials. The UI runs entirely in the browser.

### 2.1 ServiceAccount

```yaml
# templates/rbac.yaml in the workbench chart
apiVersion: v1
kind: ServiceAccount
metadata:
  name: kagent-workbench
  namespace: kagent-system
```

### 2.2 ClusterRole

The operator runs cluster-scoped (it watches `Agent` /
`AgentTask` across all namespaces in v0.1), so the read surface
must also be cluster-scoped. **No write verbs in the read-only MVP.**

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: kagent-workbench-reader
rules:
  # kagent CRDs — the core of the read surface
  - apiGroups: ['kagent.example.com']
    resources:
      - agents
      - agenttasks
      - agentcapabilities
    verbs: ['get', 'list', 'watch']

  # Status subresources (operator updates these; UI shows them)
  - apiGroups: ['kagent.example.com']
    resources:
      - agents/status
      - agenttasks/status
      - agentcapabilities/status
    verbs: ['get']

  # Operator-managed Jobs/Pods. The label selector
  #   kagent.example.com/managed-by=kagent-operator
  # is enforced in the API code (filter on watch + on list);
  # RBAC at the Kubernetes layer cannot scope by label, so the
  # ClusterRole grants the broad verb. This is an accepted
  # trade-off: the API code is the trust boundary for selector
  # enforcement; the RBAC keeps this read-only at the K8s layer.
  - apiGroups: ['batch']
    resources: ['jobs']
    verbs: ['get', 'list', 'watch']
  - apiGroups: ['']
    resources: ['pods']
    verbs: ['get', 'list', 'watch']
  - apiGroups: ['']
    resources: ['pods/log']
    verbs: ['get']  # task-detail panel; opt-in flag

  # Events for the per-task event timeline (WORKBENCH.md §3.2)
  - apiGroups: ['']
    resources: ['events']
    verbs: ['get', 'list', 'watch']
  - apiGroups: ['events.k8s.io']
    resources: ['events']
    verbs: ['get', 'list', 'watch']

  # Explicitly NO write verbs. Actions (cancel/retry/create task)
  # land in a *separate* ClusterRole behind a values flag in v0.2:
  #   actions.enabled: false  (default)
  # When that flag is set, an additional ClusterRole grants:
  #   - kagent.example.com/agenttasks: create, delete, patch
  # and is bound separately. Splitting it keeps the read-only
  # MVP install accidentally-write-proof.
```

### 2.3 ClusterRoleBinding

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: kagent-workbench-reader
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: kagent-workbench-reader
subjects:
  - kind: ServiceAccount
    name: kagent-workbench
    namespace: kagent-system
```

### 2.4 Why ClusterRole and not Role

Per `kagent/docs/WORKBENCH.md` §6, the operator is currently
cluster-scoped. A namespace-scoped `Role` would force the Workbench
to either (a) only see one namespace (useless for an operator
console) or (b) duplicate a `Role` in every namespace where an Agent
might land. Cluster-scoped read with selector enforcement in the API
is the simpler, safer-to-audit shape.

---

## 3. Ingress + auth integration

### 3.1 What the homelab actually has

Surveyed `new_localai/k8s-kustomized/base/networking/ingress-routes.yaml`
and `overlays/production/ingress-production.yaml`:

- **Ingress controller:** Traefik (IngressRoute CRD; entryPoint
  `websecure`).
- **TLS:** wildcard `example-tls` Secret (cert-manager,
  `*.example.com`).
- **Shared Middlewares in use:** `security-headers` (HSTS, CSP,
  XFO), `rate-limit` (50/100), `argocd-server-redirect`
  (HTTPS redirect).
- **No `oauth2-proxy`.** No `authelia`. No `forwardAuth` Middleware
  pointing at a shared SSO. (Verified: `grep -rE
  '(oauth2-proxy|authelia|forwardAuth)' k8s-kustomized/` — only one
  hit, and it's a partial `forwardAuth` block in `traefik-timeout-
  middleware.yaml` that doesn't actually point anywhere.)
- **App-level auth is the convention.** Per
  `docs/DOMAIN_STRATEGY.md`: `*.example.com` services rely on
  per-app auth (Argo's login, Gitea's login, OpenWebUI's login);
  `*.homelab` services rely on Tailscale VPN as the network
  boundary.

### 3.2 Recommended auth pattern for the Workbench

The Workbench has no built-in auth in the MVP, so we must put
something in front. Two acceptable options, both of which the
chart exposes via `ingress.authMiddleware`:

**Option A — preferred for first cut: Tailscale-only.**
Bind the ingress to the `*.homelab` subdomain instead of
`*.example.com`. Hostname becomes `kagent.homelab`. No public DNS,
no public TLS — accessible only over the existing Tailscale VPN.
Mirrors how `argocd.homelab`, `git.homelab`, and `grafana.homelab`
are reached today. This is the lowest-risk default for an
operator-console UI in the read-only MVP.

**Option B — if external access is required: Traefik basic-auth
Middleware.** Sealed-Secret in `kagent-system` holds an htpasswd
blob; chart provisions a `traefik.io/v1alpha1 Middleware` of kind
`basicAuth` named `kagent-workbench-basic-auth` and references it
in the IngressRoute. This is sufficient for a single-operator
homelab use case — not a multi-tenant production pattern, but
explicit and auditable.

**Future option (NOT this slice):** when the homelab grows a
shared SSO (oauth2-proxy in front of Authentik or similar), the
`ingress.authMiddleware` value just changes to point at the
shared `forwardAuth` Middleware in `ingress-system`.

### 3.3 Helm chart values the chart needs

The chart in the kagent repo will accept:

```yaml
ingress:
  enabled: true
  host: kagent.example.com     # or kagent.homelab for option A
  ingressClass: traefik
  tls:
    secretName: example-tls   # or omit for *.homelab
  authMiddleware: kagent-workbench-basic-auth   # '' to disable
```

The IngressRoute itself is rendered by the chart; this doc
describes the inputs, not the YAML.

---

## 4. Hostname

**Chosen:** `kagent.example.com` (with basic-auth middleware) for the
external recipe, OR `kagent.homelab` (Tailscale-only) for the
preferred first-cut recipe.

**Conflict check (2026-04-26):**

```bash
find new_localai -type f \( -name '*.yaml' -o -name '*.yml' \) \
  | xargs grep -l 'kagent.example.com' 2>/dev/null
# → only k8s/argocd-apps/kagent-app.yaml, and the only
#   reference there is the CRD api group string
#   `kagent.example.com/v1alpha1` — that is a Kubernetes API
#   group, NOT a DNS hostname. Safe to take.
```

Cross-checked existing hostnames in
`k8s-kustomized/base/networking/ingress-routes.yaml`: `chat`,
`n8n`, `argocd`, `traefik`, `mcpo`, `qdrant`, `grafana`,
`prometheus`, `platform`, `api`, `n8n-mcp` — none collide.

---

## 5. Pull-secret

The `gitea-registry-secret` already in `kagent-system` (created by
`new_localai/k8s/argocd-apps/kagent-registry-secret.yaml`) covers
both Workbench images. **No second secret manifest is needed.**
The existing `kagent-app.yaml` has been annotated to reflect the
shared use.

---

## 6. Image build path

Both Workbench images build via the **same** Gitea Actions workflow
that builds the operator + agent-pod images
(`.gitea/workflows/build.yaml` in the kagent repo):

1. Tag push on `github.com/ctkadvisors/kagent` (e.g.
   `v0.0.5-workbench-mvp`).
2. One-way Gitea push mirror picks up the tag.
3. Gitea Actions runs the workflow; BuildKit builds + pushes:
   - `git.example.com/homelab/kagent-operator:v0.0.5-workbench-mvp`
   - `git.example.com/homelab/kagent-agent-pod:v0.0.5-workbench-mvp`
   - **NEW** `git.example.com/homelab/kagent-workbench-api:v0.0.5-workbench-mvp`
   - **NEW** `git.example.com/homelab/kagent-workbench-ui:v0.0.5-workbench-mvp`
4. Argo `kagent-workbench` Application bumps the values tag and
   reconciles (Argo Image Updater can also automate the bump if
   desired).

The workflow file in kagent will need two additional
`docker/build-push-action` steps; the metadata-action and login
steps are already shared. Image tag policy: same as the operator
(`v*-phase*`, `vX.Y.Z`).

---

## 7. Where this RBAC actually lives

**Not in `new_localai`.** This document is the *plan*; the
implementation belongs in the workbench Helm chart in the kagent
repo, alongside the Deployment + Service + IngressRoute templates
that compose the workload:

```
kagent/packages/workbench-api/charts/kagent-workbench/
├── Chart.yaml
├── values.yaml
└── templates/
    ├── api-deployment.yaml
    ├── api-service.yaml
    ├── ui-deployment.yaml
    ├── ui-service.yaml
    ├── ingressroute.yaml
    ├── basic-auth-middleware.yaml   # rendered when enabled
    └── rbac.yaml                    # ServiceAccount + ClusterRole
                                     # + ClusterRoleBinding above
```

`new_localai` only references that chart via the ArgoCD
Application (`kagent-workbench-app.yaml`).

---

## 8. Blockers (do not apply)

The ArgoCD Application manifest at
`new_localai/k8s/argocd-apps/kagent-workbench-app.yaml` is staged
but NOT committed because:

1. **Helm chart does not exist yet** in the kagent repo at
   `packages/workbench-api/charts/kagent-workbench/`. Workstream 5
   (chart + RBAC templates) is in flight.
2. **Workbench API + UI images do not exist yet.** Workstreams 1 +
   2 (`@kagent/dto`, `@kagent/workbench-api`,
   `@kagent/workbench-ui`) are being implemented in parallel.
   The Gitea Actions workflow has not been extended with the two
   new build steps.
3. **No basic-auth Sealed-Secret exists** in `kagent-system` for
   `kagent-workbench-basic-auth`. If we go with Option B, that
   needs to land via the existing `secrets.example.com` Sealed-
   Secrets web UI before sync.

---

## 9. Recommended next-step sequence

1. Workstreams 1 + 2 land `@kagent/dto`, `@kagent/workbench-api`,
   `@kagent/workbench-ui` in the kagent repo (and pass `helm
   template` locally).
2. Workstream 5 lands the Helm chart at
   `packages/workbench-api/charts/kagent-workbench/` — including
   the RBAC templates spelled out in §2 above.
3. Extend `kagent/.gitea/workflows/build.yaml` with two new
   `docker/build-push-action` steps for the workbench-api and
   workbench-ui images.
4. Tag `v0.0.5-workbench-mvp` on `github.com/ctkadvisors/kagent`.
   Verify all four images appear in the homelab Gitea registry.
5. Decide auth recipe (A or B). For B, create the basic-auth
   Sealed-Secret via the secrets.example.com UI in
   `kagent-system`.
6. Open a PR in `new_localai` from the
   `feat/kagent-workbench-deploy` branch that adds
   `kagent-workbench-app.yaml`. Per kagent CLAUDE.md "Don't
   auto-merge PRs" — explicit consent required before merge.
7. Once merged, Argo picks it up at sync wave 7 (after operator,
   wave 6). Ship a verify-via-Job manifest that curls the
   workbench API `/api/healthz` from inside `kagent-system` and
   exits non-zero on failure.
