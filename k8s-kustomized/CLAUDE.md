# k8s-kustomized/

Kubernetes manifests, the GitOps source of truth. Reconciled by ArgoCD, never by
`kubectl apply`. Read the root `../CLAUDE.md` first for the workflow and the
kubectl guardrails. Rewritten 2026-09-02 from the live cluster.

## Golden rule

Edit → `kubectl kustomize overlays/production > /dev/null` → commit → push →
ArgoCD syncs within about three minutes. If a sync sticks, look at `homelab-apps`
in Argo before touching anything: a crash-looping Deployment blocks the app until
its retries exhaust.

## Layout

```
base/
  ai-services/     graphiti-mcp (brain MCP + nginx auth sidecar), spark-llamaswap Service,
                   brain-scribe CronJob, bytebot, openwebui, doc-ingester, ai-gateway, hermes
  automation/      n8n (+ KagentAgent custom node ConfigMap), redis
  backup/          nas-backup + nas-backup-elitemini2 CronJobs, RBAC, sealed ssh key
  database/        postgres/pgvector, neo4j (brain store, hostPath /opt/neo4j-data on elitemini2), pgadmin
  search/          searxng (web search for agents), opensearch, agent-memory-mcp
  kata/            kata-deploy notes; agent pods run kata-qemu (see README there)
  monitoring/      prometheus + rules, grafana, alertmanager, exporters — separate Argo app
  argocd/          Application CRDs
  infrastructure/  sealed-secrets, cert-manager, nvidia plugin, reflector
  networking/      traefik, metallb, dns
  vector-db/       qdrant (elitemini2 hostPath)
  ml-registry/     minio, mlflow, minio-spark-backup CronJob
  platform/        LEGACY v0-clone (scaled to 0; Argo app nextjs-platform reads ../k8s instead)
  storage/ buildkit/ dashboard/ redis/ cleanup/ gitea/

overlays/production/
  kustomization.yaml         active overlay: base-without-monitoring + automation, dashboard,
                             database, gitea, kagent, bytebot, langfuse
  kagent/                    THE FLEET — see below
  base-without-monitoring/   base minus monitoring (monitoring nodeSelectors conflict)
  argocd/ langfuse/ bytebot/ gitea/ database/ automation/ dashboard/
```

## overlays/production/kagent/ (the fleet)

| File | What |
| -- | -- |
| `application.yaml` | Argo app for the operator chart: image tags for operator, agent-pod, tool-gateway, adapters; `modelClasses` (all → `ornith15`, `contextWindowTokens: 262144`); tool profiles (`browser-code-researcher`, `brain-memory`, `builder-shell`); telegram adapter brain values |
| `llm-gateway-application.yaml`, `model-endpoints.yaml` | the inference chokepoint and its model → backend map (spark llama-swap). Cloud endpoints are commented out and stay that way |
| `workbench-application.yaml` | workbench API/UI + its ingress netpol allowlist (n8n, improve-daily) |
| `concierge-agent.yaml`, `operator-investigator-agent.yaml`, `homelab-builder-agent.yaml`, `brain-auditor.yaml` | the four Agents; brain-auditor carries the daily KagentSchedule |
| `channel-control.yaml` | Channel + ChannelBinding: Telegram → concierge, WhatsApp → operator-investigator |
| `external-providers-sealed.yaml` | tool-gateway providers JSON (brain remoteMcp, GitHub http tools, SearXNG `http.web_search`) — re-seal the whole JSON to change |
| `improve-daily.yaml` | 05:15 UTC staged self-improvement pipeline (collect → investigate → adjudicate → implement → test → publish), scripts embedded in the ConfigMap |
| `pr-reviewer.yaml` | 15-minute PR verdicts; merges same-repo PRs from trusted authors, escalates the rest to Telegram |
| `fleet-hooks.yaml` | GitHub App webhook receiver behind the Cloudflare tunnel: PR/CI events → review, `mission` issues → triage, pushes → brain episodes; HMAC + GitHub source-IP gate |
| `fleet-ledger.yaml` | the ledger: Postgres db `fleet` (candidate, run, decision, outcome, scheduler) behind the GitHub-issue queue; sealed bootstrap + DSN, migrate Job |
| `fleet-reconcile.yaml` | the scheduler: every 5 min, six fail-closed idle signals, ledger lease, daily budget; launches an improve run from the improve-daily template. Knobs live here |
| `fleet-console.yaml` | fleet.example.com (LAN, no auth): health (own failed pods, self-pause + resume), the forum (agents and Chris talking; ideas feed the collector), scheduler state, announced merges with veto, the board (run / decline / ask), runs, knobs. The tool-gateway may call its API (the concierge's forum access) |
| `*-sealed.yaml`, `*-secrets.yaml` | sealed tokens (gateway, channel gateway, telegram bot, builder git, langfuse, webhook, ledger, console auth) |

Version discipline: six kagent components are pinned here by tag. Keep them on
**one** tag; the operator drifted twelve tags behind its chart once and every
operator-side fix was blocked by it.

## ArgoCD Applications (live 2026-09-02)

| App | Source | Notes |
| -- | -- | -- |
| homelab-apps | new_localai `k8s-kustomized/overlays/production` | auto-sync, self-heal, prune |
| monitoring-stack | new_localai `k8s-kustomized/base/monitoring` | separate on purpose |
| kagent | kagent `packages/operator/charts/kagent-operator` @ tag | values from `application.yaml` |
| kagent-llm-gateway | kagent `packages/llm-gateway/charts/llm-gateway` @ tag | |
| kagent-workbench | kagent `packages/operator/charts/kagent-workbench` @ tag | |
| kata-deploy | kata-containers helm chart 4.1.0 | |
| langfuse | langfuse-k8s chart | uses the shared postgres |
| cert-manager | jetstack chart | |
| ai-gateway, homelab-orchestrator | their own repos | older agent surfaces, under review |
| nextjs-platform, supabase-stack | new_localai legacy `k8s/` | should be retired with `k8s/` |

## Node labels that matter

| Label | Used by |
| -- | -- |
| `node-role.kubernetes.io/control-plane: "true"` | control-plane pinned services (n8n, postgres, openwebui, homepage, backup job) |
| `node-type: compute-worker` | agent pods, operator, kata, searxng, most kagent-system |
| `kubernetes.io/hostname: elitemini2` | qdrant, neo4j, opensearch, minio, bytebot, elitemini2 backup job |
| `kubernetes.io/hostname: jetson2` | localai-secondary, model-manager |

## Alerts

Rules in `base/monitoring/prometheus.yaml`; Alertmanager → Telegram; brain-scribe
also writes new alerts into the graph hourly. `KubernetesPodNotHealthy` ignores
pods whose init containers are still running (improve-daily sits in Pending for
up to an hour by design).

## Secrets

Sealed-Secrets only (see root CLAUDE.md for the kubeseal-from-Mac recipe). The
brain token is sealed in `ai-services` and reflected into `kagent-system` via
reflector annotations. Never commit a raw token.

## Known drift / disabled

- `platform/` deployments scaled to 0 (2026-09-02); `supabase` runs but nothing here uses it.
- NFS storage disabled in `base/ai-services/kustomization.yaml`; Qdrant on hostPath.
- `rpi-dns-manager` is `.yaml.disabled`; leave it.
- LocalAI on jetson2 (`localai-secondary`) is not on any agent path; agents use the spark.
