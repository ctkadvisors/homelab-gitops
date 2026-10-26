# CLAUDE.md

Guidance for Claude Code working in this repository. Rewritten 2026-09-02 from the
live cluster; the previous version described April.

## What this repo is

The GitOps source of truth for Chris's homelab K3s cluster, plus the docs and
runbooks for running it. ArgoCD reconciles `k8s-kustomized/` into the cluster.
Everything else in the repo is either a service source tree that still ships from
here (`services/`), or legacy (`platform-api/`, `platform-dashboard/`, `k8s/`,
`functions/`, most of `scripts/`).

The cluster's job today: run the **kagent** agent fleet (operator, agents, the
Telegram concierge), all inference on the **spark** (DGX GB10) through the kagent
LLM gateway, memory in the **graphiti brain** (neo4j), observability in Langfuse
and Prometheus. No cloud inference, ever (Chris, 2026-09-01).

## Scoped CLAUDE.md files

- `k8s-kustomized/CLAUDE.md` — base/overlay layout, ArgoCD apps, secrets, node labels
- `services/CLAUDE.md` — doc-ingester, codegen, chris-tts, model-manager sources
- `platform-api/CLAUDE.md`, `platform-dashboard/CLAUDE.md`, `functions/CLAUDE.md` — legacy, do not build on

## GitOps is the only way to change cluster state

ArgoCD owns `k8s-kustomized/overlays/production` (app `homelab-apps`) and
`k8s-kustomized/base/monitoring` (app `monitoring-stack`). Change flow:

```bash
# 1. edit k8s-kustomized/
kubectl kustomize k8s-kustomized/overlays/production > /dev/null   # 2. validate
git add k8s-kustomized && git commit -m "..." && git push            # 3. Argo syncs (~3 min)
```

kubectl from this Mac is **not** authorized against the cluster. Read and operate
through `ssh elitemini 'sudo kubectl ...'`. Allowed imperatively: `get`, `describe`,
`logs`, `top`, pod deletes, `create job --from=cronjob/...` for a manual run, and
runtime objects nothing in git owns (AgentTasks, draft agents). Never `edit`,
`patch`, or `apply -f` a GitOps-managed object; Argo self-heals it back anyway.

Argo gotcha: a crash-looping Deployment makes `homelab-apps` blow its health
deadline and block further syncs until retries exhaust. Fix the crash first.

## Cluster topology (verified 2026-09-02)

Source of truth for IPs: `config/network.yaml`. The Deco router's DHCP
reservations drift after power events; see `docs/power-outage-recovery-runbook.md`.

| Node | IP | Hardware | Role |
| -- | -- | -- | -- |
| elitemini | 10.0.0.76 | Ryzen 5 7640HS, 30 GB, 1 TB | K3s control plane; Gitea, Argo, Postgres, n8n, OpenWebUI, monitoring, Traefik |
| elitemini2 | 10.0.0.58 | Ryzen 5 7640HS, 60 GB, 1 TB, KVM | Kata agent pods, neo4j (brain), Qdrant, OpenSearch, Langfuse, Bytebot, MinIO |
| jetson2 | 10.0.0.75 | Orin Nano 8 GB | GPU worker in name; used as the builder's SSH target |
| spark | 10.0.0.69 | NVIDIA GB10, 121 GB unified, 3.7 TB | **Off-cluster.** All inference (llama-swap :9090) and training; also the backup target. Since 2026-09-08 three models are resident: `ornith15` (vLLM, `--gpu-memory-utilization 0.40`, chat and hands), `qwen38` (Qwen3.8-27B, llama-server :8210, thinking on, the fleet's judge, llama-swap group `judge`, no big-model lease) and `embed`; ~40 GB stays free. `ssh spark 'bash -s' < script` is a non-login shell: `hf`/`vllm` live in `~/.local/bin`, use `bash -lc`. A llama-swap config edit re-runs its startup preload and stops running models |
| valhalla | 10.0.0.67 | Synology NAS | Backup target (SSH on since 2026-09-03). DHCP-drifted .54 -> .67 on 2026-09-08 and .54 went to another device; give it a static address in DSM. `dscacheutil -q host -a name valhalla.local` from the Mac finds it |

Retired: jetson1 (out of the cluster, unreachable), k3s-reconciler (a Multipass
arm64 VM on Mini-3, deleted from the cluster 2026-09-02 and from Multipass on
2026-09-07). It kept coming back: a root LaunchDaemon on Mini-3,
`/Library/LaunchDaemons/io.homelab.k3s-reconciler-watchdog.plist`, ran
`multipass start k3s-reconciler` every 60 s, so after the 2026-09-05 power loss
it rejoined with the old node token and every fleet-scripts pod scheduled there
died with "exec format error". The VM is purged; the watchdog now logs "not
found" once a minute until a human removes it (`sudo launchctl bootout system
/Library/LaunchDaemons/io.homelab.k3s-reconciler-watchdog.plist`, needs the
Mini-3 admin password). Fleet pods are pinned to amd64 and reconcile deletes a
cordoned NotReady non-amd64 node through the node runner, so a reappearance
costs nothing. Mac minis exist but are not part of any workload.

`ssh {elitemini,elitemini2,jetson2,spark}` are passwordless aliases. Node-to-node
ssh is not set up; always hop from the Mac.

## What runs where (namespaces)

- `kagent-system` — the fleet: operator, tool-gateway (Steel browser, shell runner,
  external MCP/HTTP providers), llm-gateway (:4000, the only inference chokepoint),
  workbench (API + UI), telegram and whatsapp adapters, agents
  (`concierge`, `operator-investigator`, `homelab-builder`, `brain-auditor`),
  CronJobs `improve-daily` (05:15 UTC staged self-improvement pipeline) and
  `pr-reviewer` (hourly at :07; a manual run is `kubectl create job --from=cronjob/pr-reviewer <name>`).
  The stages that decide (investigate, adjudicate, test) and the reviewer run on the
  judge model (`dsh-patch-judge.yml`, qwen38); implement and fix passes run on ornith15. Manifests: `k8s-kustomized/overlays/production/kagent/`.
- `ai-services` — graphiti-mcp (the brain's MCP interface, bearer-auth sidecar),
  spark-llamaswap Service (LAN-routed to the spark), brain-scribe CronJob
  (alerts → brain, hourly), Bytebot, OpenWebUI, doc-ingester, ai-gateway (the older
  gateway product; not what agents use), hermes-agent (reporting only).
- `database` — shared Postgres/pgvector (gateway usage, Langfuse, platform), neo4j.
- `search` — SearXNG (`http.web_search` for agents), OpenSearch, agent-memory-mcp.
- `automation` — n8n (custom `KagentAgent` node; no workflows use it), Redis.
- `backup` — nightly CronJobs to the spark (see Backups).
- `langfuse-system`, `monitoring`, `gitea`, `argocd`, `sealed-secrets`,
  `ingress-system`, `metallb-system`, `cert-manager`, `vector-db`, `ml-registry`,
  `dashboard` — platform services.
- `platform`, `supabase`, `homelab-orchestrator` — **legacy or under review.**
  platform-api/dashboard scaled to 0 on 2026-09-02 (Argo app `nextjs-platform`
  points at legacy `k8s/platform`). supabase-stack likewise points at `k8s/supabase`.
  homelab-orchestrator is a separate agent runtime whose digest belongs on a
  KagentSchedule.

Public hostnames are `*.example.com` behind Traefik. Check
`ssh elitemini 'sudo kubectl get ingress,ingressroute -A'` before claiming one.

## The fleet, in one paragraph

Telegram DM → channel gateway → `concierge` AgentTask (ornith15 via the llm-gateway;
tools: brain read/write, SearXNG search, Steel browser, code interpreter; children:
operator-investigator, homelab-builder). Every exchange is written to the brain by
the telegram adapter; the previous exchange is bridged into the next message to
cover graphiti's ingestion lag. Code changes ship through the dsh staged pipeline
(`improve-daily.yaml`: collect → investigate → adjudicate → implement → test →
publish) and `pr-reviewer` merges trusted PRs. Design notes:
`docs/superpowers/specs/2026-09-02-telegram-concierge-design.md`, runbook
`docs/runbooks/agent-inference-upgrade.md`. Inference rules: default and heavy
tiers are `ornith15` (resident); anything else on the spark is a one-at-a-time swap
that competes with training. Never route an agent to a cloud model.

## The self-driving loop (2026-09-04)

Chris: "it should not be human dependent. it SHOULD be self driving, but with [the console] for steering."
`fleet-reconcile` (CronJob, 5 min) watches six signals (spark GPU util, fleet Jobs, AgentTasks, CI runner pods,
chat quiet, webhook quiet; unknown = busy), keeps an idle streak in the ledger and, within a daily budget,
launches one improve run (the staged pipeline, `RUN_TRIGGER=idle`). pr-reviewer classifies every agent PR by
risk tier from touched paths: tier 0 (docs, tests) merges at once, tier 1 (code) after a 15-minute veto
window, tier 2 (workflows, manifests, lockfiles) after 120 minutes, tier 3 (secrets, rails, policy) never on
its own. Halts file `fleet:halt` issues with the dsh log tail. The ledger (`services/fleet-scripts/fleet/ledger.py`)
is the structured record; GitHub issues are the human-visible queue (label = decision); the brain mirrors
both. The console (fleet.example.com, LAN, no auth: never put it on the tunnel) shows it all: scheduler, announced
merges with veto, candidates with attempts/cost/outcomes, standing objections, the board (run / decline / ask), and
runs with why-it-halted (stage, reason, exit code, dsh tail), retry and feedback. Framed as Govern > Fleet in the
workbench (kagent PR #20). Design and
its adversarial review: `docs/superpowers/specs/2026-09-04-idle-improvement-*.md`.
A merge to main under `services/fleet-scripts/` builds the image and bumps the overlay tag by itself
(`.github/workflows/fleet-scripts.yml`, ship job, over the tailnet); nobody tags fleet-scripts by hand any more.

## Independence, the forum and kid gloves (2026-09-06)

Chris: "trust but verify", "they're little people and need people skills", "kid gloves around harknote and
seekarc". Tier 3 now merges too, after a 720-minute announced window (`VETO_MINUTES_T3`); the 24h/7d outcome
checks and the console veto are the verify. Repos carrying the GitHub topic `fleet-kid-gloves` (harknote,
ai-interviewer = seekarc.io) are reviewed and never merged by the fleet, and never chosen for a speculative
improve run; `github.kid_gloves()` reads the topic, nothing names the repos in code. The forum is the ledger's
`post` table, rendered and writable on fleet.example.com (`/api/forum`, `/api/post`): reconcile posts what it
launched and why, the reviewer posts every verdict addressed to the implementer, publish posts what it did and did
not do (or what would unblock a halt), the concierge reads and posts through the console API from its code
interpreter, and `idea`/`question` posts become collector evidence. `fleet/voice.txt` is how every role talks
(appended to every stage prompt by stage.sh and to the reviewer's). Reviewer feedback no longer pings Telegram;
Telegram carries announcements, merges, escalations, halts and the fleet pausing itself. Self-repair: reconcile
reads its own namespace's failed pods each tick (`self_health` kv, the Health section on the console), files a
`mission` + `fleet:repair` issue on new_localai when the same failure repeats (`REPAIR_AFTER`), and pauses launches
for `PAUSE_MINUTES` when failures pile up (`PAUSE_AFTER`; resume from the console). Improve runs work the repo with
the most open `fleet:halt`/`fleet:repair` issues (`reconcile.choose_repo`), default kagent.

The loop closes on itself (evening of 2026-09-06, after mission 22 was relaunched three times into an OOM and
nobody read its questions): `reconcile.reap_failed_runs` records a Job that died before publish as outcome
`failed` with the stage and exit code, says so on the forum and the issue; `relay_questions` sends a forum
`question` that mentions chris to Telegram once, and board-first waits on an open question (answer it with the
reply button; the answer rides into the next brief via `context_for`, along with how the last attempt ended);
`retry_reviewed` relaunches a PR the reviewer objected to or CI rejected on the PR's own branch (`branch` on the
launcher, `clone.py` continues it, `publish.open_pr` comments on the existing PR), capped by `REVIEW_ROUNDS`.
Stage pods reach the forum in-cluster on the console's port 8081 and can no longer reach the MetalLB address, so
the LAN page's steering endpoints are for humans only. Implement and test stages get 4Gi.
What a stage can see (Chris, 2026-09-06: "if YOU could do it, what would YOU want to have access to"): read
everything, write through PRs. Missions and improve runs run as ServiceAccount `fleet-stage` (`fleet-stage.yaml`:
get/list/logs on pods, jobs, cronjobs, deployments, events, netpols in kagent-system, ai-services, database,
monitoring, arc-runners, plus nodes) with `/fleet/bin/kubectl` in the fleet-scripts image; they can search
(SearXNG JSON API) and the collector reads active Alertmanager alerts as evidence. `BUDGET_PER_DAY` is 3.
Deep links: every forum post is `https://fleet.example.com/#post-<id>` (the page scrolls to it and lights it up);
Telegram messages about a post carry that link and the subject's short name (`brutalist_todo#22`,
`telegram.ref_label`); the "Needs you" section at the top of the page lists open questions.

## GitHub Actions minutes

The org gets 2,000 hosted minutes a month; macOS bills 10x. On 2026-09-08 it hit
90%. Nothing the fleet runs may use hosted runners: every job is `runs-on: homelab`
(ARC, Kata dind: docker works, kind does not, no tailscale). Usage by repo:
`gh api "/organizations/ctkadvisors/settings/billing/usage?year=Y&month=M"`.

## Secrets

Sealed-Secrets. From this Mac, `kubeseal` needs the controller cert:

```bash
ssh elitemini 'curl -s http://$(sudo kubectl get svc -n sealed-secrets sealed-secrets-controller -o jsonpath="{.spec.clusterIP}"):8080/v1/cert.pem' > /tmp/cert.pem
kubectl create secret generic NAME -n NS --from-literal=k=v --dry-run=client -o yaml | kubeseal --cert /tmp/cert.pem --format yaml
```

The tool-gateway's external providers (brain token, GitHub PAT, web search) live in
one sealed JSON (`overlays/production/kagent/external-providers-sealed.yaml`); to
change it, read the live Secret on elitemini, edit, re-seal the whole thing. The
sealed-secrets master key is backed up nightly (see Backups). Known plaintext
placeholders: `base/storage/smb-credentials.yaml`, `base/buildkit/docker-registry-secret.yaml`.

## Backups (armed 2026-09-02)

`base/backup/`: `nas-backup` (03:30, control plane) ships the k3s SQLite datastore,
the sealed-secrets key, a `pg_dumpall` of the shared Postgres, local-path PVCs, and
n8n/OpenWebUI/Traefik hostPath state; `nas-backup-elitemini2` (03:50) ships neo4j,
Qdrant, OpenSearch, Redis and that node's PVCs. Target is
`spark:~/backups/homelab/` until the NAS has SSH. Restore sketch in
`base/backup/README.md`. Manual run:
`ssh elitemini 'sudo kubectl -n backup create job --from=cronjob/nas-backup nas-backup-manual'`.

## Building images

Images go to Gitea's registry; it rejects provenance/SBOM attestations, and the
cluster is x86:

```bash
docker build --platform linux/amd64 --provenance=false --sbom=false -t git.example.com/homelab/<image>:<tag> .
```

The agent images (`homelab/agent-coder`) are built from `../agent-vms`.

## Known debt (2026-09-02)

- 700 lines of Python/shell/JS live inside ConfigMaps (`improve-daily.yaml`,
  `pr-reviewer.yaml`, `n8n-kagent-node.yaml`, `brain-scribe.yaml`): untested. Moving
  them into the agent-coder image is queued.
- `overlays/production/kagent/application.yaml` pins six kagent components by hand;
  keep them on one tag.
- `k8s/` is legacy but two Argo apps still read it; `scripts/` is mostly stale.
- graphiti-mcp's `get_episodes` does not return the most recent episodes (our fork);
  the concierge compensates with the previous-turn bridge.
- The Deco router ages wired clients out of its table; `deco-keepalive.service`
  runs on both eliteminis. If a node can be reached over ssh but reaches nothing
  itself: `ip neigh flush dev enp2s0 to 10.0.0.1`. The Mac gets it too: an
  ARP entry for a node pointing at the Deco's MAC shows as "ssh: connection
  refused"; `sudo arp -d <ip>` or hop through elitemini.
- k3s's network-policy controller on the destination node adds a new pod's
  address to a policy's allow-list a few seconds after the pod starts, so a
  Job's first request from another node is rejected ("connection refused")
  until then. The digest failed every morning from 2026-09-04 to 09-06 on this.
  In-cluster calls from short-lived pods go through `fleet/net.py urlopen_retry`.
  To see a policy's state: `sudo iptables -S | grep <policy>` and
  `sudo /var/lib/rancher/k3s/data/*/bin/ipset list KUBE-SRC-...` (system ipset
  is not installed).
