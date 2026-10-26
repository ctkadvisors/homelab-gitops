# Agent fleet: inference & upgrade runbook

Written 2026-08-29 after the fleet went DOA on a dead model. Read this first
when "the agents stopped working" or when swapping the default model.

## The 60-second mental model

```
Agent (kagent CR, spec.modelClass) 
  → modelClasses map (application.yaml)  ── logical tier → model id
  → kagent-llm-gateway (:4000/v1)        ── the ACTIVE router (not the litellmBaseUrl)
  → ModelEndpoint (model-endpoints.yaml) ── model id → backend URL
  → spark-llamaswap (:9090) | jetson1 ollama (:11434) | CF workers-ai
```

- **Two gateways, don't confuse them.** `ai-gateway` (product, `api.example.com`,
  the OpenAI-compat router we hardened) **predates spark** and routes to the
  *jetson* localai/ollama only. `kagent-llm-gateway` (`:4000`) is kagent's own
  router and is what agents actually use. Consolidating agents onto the
  ai-gateway is a *future* task — it needs spark registered as a gateway
  provider (the router only knows `LOCALAI_BASE_URL`/`OLLAMA_BASE_URL` today).
- **Inference lives on spark** (`spark-llamaswap`, tailnet `100.64.0.69:9090`,
  in-cluster `http://spark-llamaswap.ai-services.svc.cluster.local:9090/v1`).
  It's `llama-swap` — swaps models on demand, OpenAI-compatible, no auth.
- `litellmBaseUrl` in application.yaml is **legacy/moot** — `llmGateway.enabled`
  makes the `:4000` gateway win. Don't chase the jetson1:11434 URL.

## Failure mode we hit (DOA fleet)

**Symptom:** every agent run fails on inference; only `*-nemotron` classes work.
**Cause:** `modelClasses` all pointed at `coder`, which still *lists* on
spark-llamaswap but 502/503s. A dead/renamed model id = whole fleet down.
**Diagnose:**
```bash
# what does spark actually serve right now?
kubectl -n ai-services run p --rm -i --image=curlimages/curl:8.10.1 --restart=Never -- \
  curl -s http://spark-llamaswap.ai-services.svc.cluster.local:9090/v1/models
# what do the classes point at?
grep -A10 'modelClasses:' overlays/production/kagent/application.yaml
```
**Fix:** point `modelClasses` at a live model id + ensure a ModelEndpoint maps
it. That's all this repo's 2026-08-29 commit did.

## How to swap the default model (the upgrade path)

1. Confirm the new id is live: `curl .../v1/models` on spark-llamaswap.
2. Add/confirm a `ModelEndpoint` in `overlays/production/kagent/model-endpoints.yaml`
   with `model: '<id>'`, `backendKind: localai` (llama-swap is unauthenticated —
   `openai` backendKind 502s without a key), `backendUrl:` the spark-llamaswap svc.
3. Point the tiers in `overlays/production/kagent/application.yaml` →
   `modelClasses:` at `<id>`.
4. Commit + push → ArgoCD (`kagent` app) syncs. Watch: `kubectl -n kagent-system
   get modelendpoints` and run a smoke agent task.

Model tiers to keep distinct: `*-nemotron` = small always-warm (jetson1),
default tiers = spark, and a heavy tier (`workers-ai-llama-33-70b`) exists as an
endpoint but is **unmapped to any class** — wire it when you want a beefy fanout.

## HARD-WON GOTCHAS (2026-08-29 — read these)

- **Use `ornith15`, NOT `ornith`.** `ornith15` = Ornith-1.5-35B-A3B-NVFP4
  (vLLM, `ornith-b12x-serve` container, resident `ttl:0`, ~81 tok/s, verified
  200/1.2s through the gateway). Plain `ornith` (36.9G q8 GGUF via
  `launch-ornith.sh` → :8207) has a **broken/OOM'ing backend** — llama-swap
  logs `running ornith exited: upstream command exited prematurely` and
  requests **hang** (not 502 — a silent hang, which is what makes it look like
  a gateway/network problem). Pointing modelClasses at a model whose llama-swap
  backend won't start = whole fleet hangs.
- **Diagnose from the RIGHT place.** A test pod pinned to `compute-worker`
  (elitemini2) CANNOT reach spark's tailnet IP — only **elitemini** (the
  `homelab-k8s` tailscale node) can. Agents are fine because they route through
  `kagent-llm-gateway` (which runs on elitemini). To test the real path, hit the
  gateway (`:4000`, needs the bearer from secret `kagent-llm-gateway-token`), or
  a pod with `nodeSelector node-type=control-plane`. Testing from elitemini2
  gives a false "cluster can't reach spark."
- **Don't diagnose llama-swap models with short-timeout bursts.** Cold loads are
  long; failures trip the gateway's AIMD limiter down to `cap=1` and can leak an
  in-flight slot → instant `429 model X at capacity (in-flight=1 cap=1)` for
  everything. Fix: `kubectl -n kagent-system rollout restart deploy/kagent-llm-gateway`.
- **Spark is shared with training.** `ornith15` holds ~97GB VRAM resident. A
  model **swap** (any request for a spark model that isn't already loaded) can
  OOM against that + training. Keep ALL agent spark-tiers on `ornith15` (already
  a resident, `ttl:0` model) so agents never trigger a swap. Check contention:
  `ssh spark nvidia-smi` and `ssh spark 'docker ps'`.

## Execution isolation upgrade (Kata microVM) — staged

The kagent chart already has `runtimeClasses:` (sandboxProfile → RuntimeClass).
To move agent pods into KVM microVMs (elitemini2 has `/dev/kvm`):
1. Node install per `k8s-kustomized/base/kata/README.md` (kata-qemu/clh, NOT
   kata-fc — Firecracker needs devmapper k3s lacks).
2. Set `runtimeClasses.default: kata-qemu` in application.yaml.
Don't set it before the node install or every agent pod fails to schedule.

## The brain (planned, not built)

neo4j (graph) + Qdrant (vectors, already in `vector-db` ns via doc-ingester) =
hybrid GraphRAG memory tool for agents. **neo4j is currently NOT deployed
anywhere** — it was in the cluster once and is gone. Deploy it (a jetson or
x86 both fine), wire as an MCP/HTTP tool alongside `search_personal_memory`.

## Capability roadmap

Computer-use: Steel (have, browser) + Bytebot (desktop, to add). Voice: whisper
STT → model → chris-tts (have) → SIP/WebRTC transport (net-new). Triggers:
0 KagentSchedules/AgentWorkflows exist — port project_tracker's queue+cron+verdict.
