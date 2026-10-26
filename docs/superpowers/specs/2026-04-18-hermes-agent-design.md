# Hermes Agent on Homelab — Design

**Date**: 2026-04-18
**Status**: Approved for implementation planning

## Goal

Add a governed, always-on personal agent to the homelab without repeating the paperclip incident. Keep it GitOps-native, low-maintenance, and foundational enough that any future autonomous agent inherits the same governance pattern.

Composite ask (A + C + foundational D):
- **A**: daily personal assistant, reachable via messaging (Telegram/Signal)
- **C**: modern, demoable, keeps the homelab current
- **D**: sandbox/policy pattern that future agents inherit by convention

## Decisions

| Decision | Chosen | Notes |
| -- | -- | -- |
| Agent runtime | **Hermes** (NousResearch, v0.10+) | v0.10, 99k⭐, Python, model-agnostic, built-in messaging gateway, FTS5 persistent memory. Rejected NemoClaw+OpenClaw (alpha, its-own-k3s architecture conflicts with our GitOps). |
| Sandbox | Container + NetworkPolicy + ResourceQuota | Lighter than NemoClaw's Landlock/seccomp, sufficient for "paperclip-proof" (budget + egress allowlist + kill-switch). |
| Model | **Nemotron-3-Nano-4B Q4_K_M** | 18 tok/s on Orin Nano 8GB, purpose-built for edge agents, tool-calling works. Rejected Gemma 4 E2B (no tool-calling on Jetson llama.cpp path). |
| Inference host | **jetson1, bare-metal Ollama (out of K3s)** | Past pain co-tenanting k3s + inference on Orin Nano. Dedicated node, reached via Service+Endpoints into cluster. |
| Jetson reset | **In-place cleanup**, no reflash | User has no Linux/Windows host for NVIDIA SDK Manager. |
| Hermes scheduling | Float, no nodeSelector | Production overlay defaults to control-plane (elitemini). elitemini2 is taken by a pending Windows VFIO VM. |

## Architecture

```
┌─────────────────────── K3s cluster ──────────────────────┐
│  ai-services ns                                           │
│  ┌─────────────────────┐    ┌──────────────────────────┐  │
│  │  hermes-agent       │    │  Service + Endpoints     │  │
│  │  Deployment (1x)    │───▶│  ollama-nemotron         │  │
│  │  PVC /opt/data 10Gi │    │  → 10.0.0.73:11434   │  │
│  │  ConfigMap + Sealed │    │  (no pod in cluster)     │  │
│  │  NetworkPolicy      │    └──────────────────────────┘  │
│  │  ResourceQuota      │                                   │
│  └─────────────────────┘                                   │
│           │                                                │
│           ▼                                                │
│  doc-ingester.ai-services.svc:3002   (existing)           │
└───────────────────────────────────────────────────────────┘
                                                │ HTTP
                                                ▼
                   ┌─────────────────────────────────────┐
                   │  jetson1 (out of K3s)               │
                   │  systemd: ollama @ :11434           │
                   │  Nemotron-3-Nano-4B Q4_K_M          │
                   └─────────────────────────────────────┘

Hermes gateway → egress → Telegram/Signal/Discord → You
```

- **jetson2** unchanged: K3s gpu-worker, LocalAI embeddings + chris-tts.
- **elitemini2** untouched: pending Windows VFIO VM work; new workloads explicitly not placed here.
- **elitemini** (control-plane) absorbs Hermes via production-overlay defaulting.

## Kustomize layout

New files under `k8s-kustomized/base/ai-services/`:

```
hermes-agent.yaml          Deployment + Service + PVC (hermes-data, 10Gi)
                           + ConfigMap + NetworkPolicy + ResourceQuota
ollama-nemotron.yaml       Service (ClusterIP) + Endpoints → 10.0.0.73:11434
hermes-secrets.yaml        SealedSecret (Telegram token, optional OpenRouter fallback)
```

Updates:
- `k8s-kustomized/base/ai-services/kustomization.yaml` — append the three files to `resources:`.
- `k8s-kustomized/overlays/production/kustomization.yaml` — pin `hermes-agent` image tag once stable. No patches needed initially.

Follows the pattern of `doc-ingester.yaml` / `codegen-service.yaml`.

## Hermes config

ConfigMap `hermes-config`:
```yaml
HERMES_HOME: /opt/data
HERMES_MODEL_PROVIDER: ollama
HERMES_MODEL_ENDPOINT: http://ollama-nemotron.ai-services.svc.cluster.local:11434
HERMES_MODEL: nemotron3:4b-q4_k_m
HERMES_MEMORY_BACKEND: fts5
```

PVC `hermes-data` 10Gi at `/opt/data` — FTS5 sessions, skills DB, playwright cache.

## Secrets

SealedSecret `hermes-secrets` in `ai-services`:
- `TELEGRAM_BOT_TOKEN` — primary messaging channel
- `OPENROUTER_API_KEY` — fallback, **not wired by default**. Env set only when explicitly enabled.

Budget guarantee: with OpenRouter unset, Hermes can only reach Nemotron via local Ollama. Cloud LLM calls are impossible without a committed env change.

## Integrations

**doc-ingester bridge** — Hermes custom tool (HTTP):
```
http://doc-ingester.ai-services.svc.cluster.local:3002/api/search?q={query}
```
Registered as a tool definition in Hermes config. Gives the agent personal-memory search over the iMessage corpus without new infrastructure. Prefer MCP if Hermes supports it natively at install time; otherwise HTTP is sufficient.

**Messaging** — Telegram first. `hermes gateway` daemon runs in the same pod, token from secret. Outbound polling, no ingress required. Signal/Discord added as separate env entries if/when enabled.

**Web UI** — optional. If enabled, `hermes.example.com` Ingress gated by Tailscale via `*.homelab` convention. Deferred to post-MVP.

## Governance (foundational D)

Three layers, all GitOps:

1. **NetworkPolicy** `hermes-agent-egress`:
   - Allow: `ai-services` namespace (Ollama, doc-ingester), DNS, `api.telegram.org:443`, `huggingface.co:443`.
   - Deny: everything else. OpenAI/Anthropic/etc unreachable without committed policy change.
2. **ResourceQuota** on the pod: CPU + memory ceilings sized for Hermes baseline (~1 CPU / 2Gi) with burst (~2 CPU / 4Gi). OOM-kill > runaway token burn.
3. **Convention** in root `CLAUDE.md`:
   - New autonomous agents live in `ai-services`
   - Ship with a NetworkPolicy + ResourceQuota
   - Route through a local-first model endpoint
   - No cloud-LLM secrets in the pod's env unless explicitly scoped per agent
   Documented, not tool-enforced. Sufficient until a second agent exists.

## jetson1 preparation

Out-of-cluster, tracked in `ansible/roles/nemotron-host/` so reproducible.

**Step 1 — Audit (via SSH, reviewed before purging)**
```bash
systemctl list-units --state=running
dpkg -l | grep -E 'docker|nvidia-docker|k3s|localai'
df -h /; du -sh /var/lib/* /opt/* /root/*
docker ps -a; docker images
crontab -l; systemctl list-timers
nvidia-smi; cat /etc/nv_tegra_release
```

**Step 2 — Purge**
```bash
sudo systemctl stop k3s-agent
sudo /usr/local/bin/k3s-agent-uninstall.sh || true
sudo rm -rf /var/lib/rancher /etc/rancher /var/lib/kubelet
sudo apt purge -y docker-ce docker-ce-cli containerd.io \
  docker-buildx-plugin docker-compose-plugin \
  nvidia-docker2 nvidia-container-toolkit nvidia-container-runtime
sudo rm -rf /var/lib/docker /etc/docker
sudo rm -rf /opt/localai /var/lib/localai /root/.localai 2>/dev/null || true
sudo apt autoremove --purge -y && sudo apt clean
```

**Step 3 — L4T refresh (in place, not a major version jump)**
```bash
sudo apt update && sudo apt full-upgrade -y
sudo apt install --reinstall nvidia-jetpack
sudo reboot
```

**Step 4 — Ollama native**
```bash
curl -fsSL https://ollama.com/install.sh | sh
sudo systemctl edit ollama   # Environment="OLLAMA_HOST=0.0.0.0:11434"
sudo systemctl enable --now ollama
ollama pull nemotron3:4b-q4_k_m
curl 10.0.0.73:11434/api/tags   # verify from another host
journalctl -u ollama | grep -i cuda   # verify GPU detection
```

**Step 5 — Hardening**
- `ufw allow from 10.0.0.0/24 to any port 22 proto tcp`
- `ufw allow from 10.0.0.0/24 to any port 11434 proto tcp`
- `ufw default deny incoming; ufw enable`
- SSH password auth off; key-only.
- `unattended-upgrades` enabled.
- `prometheus-node-exporter` via apt → scraped by cluster Prometheus (add static target).
- Optional: `tailscale up` for remote access over VPN.

**Fallback if Ollama GPU detection fails on current L4T**

Accept docker back on the host (scoped exception), use NVIDIA's jetson-containers llama_cpp image with OpenAI-compat endpoint on the same port:
```bash
sudo apt install -y nvidia-container-toolkit docker.io
docker run -d --name nemotron --runtime nvidia --network host --restart unless-stopped \
  -v ~/.cache/huggingface:/root/.cache/huggingface \
  ghcr.io/nvidia-ai-iot/llama_cpp:latest-jetson-orin \
  llama-server -hf unsloth/NVIDIA-Nemotron-3-Nano-4B-GGUF:Q4_K_M --host 0.0.0.0 --port 11434
```
Flip Hermes config from `ollama` provider to `openai-compat` at the same endpoint.

## Cluster-side cleanup (after jetson1 leaves)

```bash
kubectl cordon jetson1
kubectl drain jetson1 --ignore-daemonsets --delete-emptydir-data
kubectl delete node jetson1
```

GitOps changes:
1. `k8s-kustomized/base/ai-services/localai.yaml` (or production overlay) — single replica, `nodeSelector: kubernetes.io/hostname: jetson2`.
2. `config/network.yaml` — jetson1 role `gpu-worker` → `inference-host`.
3. `./scripts/apply-network-config.sh` — propagates to docs + ansible inventory.
4. Commit + push. ArgoCD reconciles.

## Success criteria

- `curl 10.0.0.73:11434/api/tags` from anywhere on the LAN returns the Nemotron model.
- Telegram message to the bot round-trips a Nemotron response in ≤10s.
- Hermes pod restart preserves session memory (PVC round-trip).
- `kubectl -n ai-services exec deploy/hermes-agent -- hermes agent --local -m "test"` returns a sensible response.
- A NetworkPolicy denial shows up in logs when attempting to hit `api.openai.com` from inside the Hermes pod.
- Root CLAUDE.md contains the "new-agent convention" section citing this as the reference.

## Ops

- Upgrade: bump `ghcr.io/nousresearch/hermes-agent:<tag>` in the production overlay, commit, push, ArgoCD syncs.
- Ollama upgrade: `sudo systemctl restart ollama` after install script re-runs on jetson1. Nothing in the cluster to touch.
- Monitor: kube-state-metrics for Hermes pod health; node-exporter on jetson1 for host metrics. Hermes's own `/metrics` exposed if Hermes 0.10+ ships it — check at install.
- Logs: `kubectl logs -n ai-services deploy/hermes-agent -f`; Hermes's own session logs under `/opt/data` (PVC).

## Uninstall / exit

If the approach doesn't stick:
1. Delete three Kustomize files from `base/ai-services/` + kustomization entry.
2. `kubectl delete pvc hermes-data -n ai-services`.
3. Delete SealedSecret.
4. jetson1 can stay as-is (dedicated Nemotron host) or rejoin K3s via `k3sup join` against the control-plane.

Total rollback time: ~5 min in-cluster, jetson1 untouched unless you want it back in K3s.

## Risks / open questions

- **Nemotron-3-Nano-4B Ollama tag** may not be published under the exact name `nemotron3:4b-q4_k_m`; verify against https://ollama.com/library at implementation time. Fallback: `ollama create` from Unsloth GGUF.
- **Ollama GPU detection on existing JetPack**: if the in-place upgrade can't get CUDA current enough, fallback to jetson-containers llama_cpp (noted above) with an OpenAI-compat provider flip in Hermes config.
- **Hermes MCP support**: current docs reference custom endpoints; MCP specifically needs verification at install. Both paths reach doc-ingester, so not blocking.
- **Hermes `/metrics` endpoint**: not confirmed. If absent, kube-state-metrics covers pod health; deeper agent-level metrics deferred.
- **PVC storage class**: assume `local-path` (K3s default). Revisit if PVC needs to survive node loss on elitemini — currently Hermes memory isn't mission-critical, local-path is fine.
- **Tool-call format for Nemotron**: Nemotron-3-Nano advertises tool calling; Hermes needs matching format (OpenAI JSON-mode vs XML). Verify at first tool invocation; may require a config toggle.
