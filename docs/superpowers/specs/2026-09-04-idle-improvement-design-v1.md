# Idle-triggered self-improvement for the homelab fleet — design v1 (for adversarial review)

Owner: Chris Knuteson. Author of v1: Claude (Fable 5.1), 2026-09-04. Reviewer requested: Codex gpt-5.6-sol, adversarial.

## Context (what exists today, all verified live)

- K3s homelab cluster (elitemini control plane, elitemini2 worker with KVM/Kata), one DGX Spark (GB10, 121 GB) serving `ornith15` (Ornith-1.5-35B-A3B NVFP4, vLLM behind llama-swap :9090) for ALL agent inference. Two M4 Mac minis (16 GB each) now serve Qwen3.6-35B-A3B IQ4_XS split over a Thunderbolt 4 bridge with llama.cpp RPC (540 tok/s prefill, 24 tok/s gen), registered as the cheap tier `qwen36-minis`. Rule from Chris: NO cloud inference, ever.
- kagent: Chris's K8s agent operator (TypeScript). Agents run as AgentTasks in Kata microVMs. Concierge agent on Telegram with graphiti memory.
- graphiti brain: neo4j + graphiti-mcp; episodes -> entities/facts, bi-temporal. Ingestion is sequential per group, ~2 min/episode; extraction LLM just moved to the minis; embeddings on the spark. Telegram turns, mission publish stages and (since today) every GitHub push are written as episodes. A `brain-auditor` agent runs daily to correct over-eager fact invalidations (~20% noise).
- Staged self-improvement pipeline (`improve-daily`, CronJob 05:15 UTC): collect (failed AgentTasks from workbench API, alerts) -> investigate (dsh + model) -> adjudicate (weighted pro/con: correctness .35, blast radius .25, testability .20, reviewability .20; pass bar >=7.0) -> implement -> adversarial test (SHIP/REJECT gates the push) -> publish (PR on `agent/dsh-daily-*`, Telegram, brain episode). Each stage is a fresh dsh session in its own init container; only publish holds credentials. Guard: skip while a prior `agent/dsh-daily-*` PR is open.
- Missions: `mission-launcher` HTTP -> Job from a template (clone -> brief -> implement -> test -> publish); triggered by the concierge, by GitHub issues labelled `mission` (triage), now via webhooks in seconds. Tonight two missions halted in `implement` after ~7 min with "dsh session failed" and no captured error.
- pr-reviewer: judges only `agent/*` PRs; merges when confidence>=85 + CI green + trusted author + <400 lines + no sensitive paths (`.github/`, Dockerfile, lockfiles, secrets, Chart.yaml, `.claude/`); otherwise comments or escalates to Telegram.
- fleet-hooks: GitHub App webhook receiver (HMAC + GitHub source-IP gate, behind a Cloudflare tunnel exposing exactly one hostname). Routes PR/check/workflow events to review, issue events to triage, push events to the brain.
- CI: GitHub Actions on an ARC scale set (`runs-on: homelab`), runner pods in Kata microVMs with docker-in-docker.
- Signals available cheaply: llama-swap metrics on the LAN (`llamaswap_gpu_util_percent`), vLLM `num_requests_running` for ornith15 (spark-local), K8s lists of Jobs/AgentTasks/runner pods, brain episode timestamps (last Telegram turn), fleet-hooks event stream.

## Chris's ask (verbatim fragments)

"once that passes/validates the approach, can we have a 'idle watcher' (as opposed to a cron) that kicks off a self-improvement loop/agent? Id like a learning/growing system here. we're very close" ... "ideation/big brain time. anthropic recently released an article outlining 'dreaming' .. id like to cross that + self reflection/improvement + ideation around new tooling that 'just happens' (from my perspective)".

Reference: Anthropic's "dreaming" for Claude Managed Agents (May 2026): a scheduled background process between sessions that reviews past session logs, extracts recurring patterns/mistakes/successful strategies, consolidates and prunes the agent's external memory store (not weights), and leaves a cleaner state for the next session. Reported: Harvey saw large task-completion gains.

## Design v1

### 1. Idle detection
A sampler thread inside fleet-hooks (it already has the event stream and the brain client) evaluates every 60 s:
- spark GPU util < 10% and ornith15 requests_running == 0
- no mission/improve Jobs active, no AgentTasks in flight, no ARC runner pods
- no Telegram turn in the last 30 min (brain episode timestamps)
- no PR/push/CI webhook in the last 10 min
Idle = all true for 10 consecutive minutes.

### 2. Trigger policy
- On idle: start ONE improvement run. Min gap 2 h, max 4/day, never while an `agent/dsh-daily-*` PR is open. Runs are never pre-empted (one Kata pod).
- Runs use the minis (cheap tier), not the spark, so a user message during a run never contends with ornith15.
- The 05:15 cron remains as fallback.

### 3. What runs
The existing staged pipeline unchanged (collect -> investigate -> adjudicate -> implement -> test -> publish), launched through mission-launcher with `pipeline: improve`.

### 4. Learning loop ("dreaming" lite)
- Every run ends by writing a ledger episode to the brain: what it picked, why, adjudication scores, outcome (merged / feedback / rejected / halted + reason).
- collect reads the last 10 ledger episodes and the latest pr-reviewer feedback before choosing candidates: don't repeat rejected ideas, follow up on feedback, turn halts (like tonight's dsh failures) into candidates.
- New candidate sources: brain-auditor corrections, digest "surfaced but unresolved" items.

### 5. Guardrails
- Selection learns; rails (prompts, adjudication weights, reviewer gates) live in git and change only through reviewed PRs.
- Sensitive paths still escalate to a human.
- RBAC: list-only on Jobs/Pods/AgentTasks; launch only via mission-launcher's existing HTTP API.

## Questions for the reviewer
1. Where does this fail silently, loop, or waste the hardware?
2. Is "idle" well-defined? What false positives/negatives matter?
3. Is the learning loop real learning or a ledger that nobody reads? What would make it compound?
4. How should "dreaming" (memory consolidation over the brain + session logs) be crossed with this, concretely, given a 35B-A3B local model and a bi-temporal graph with a known 20% invalidation-noise problem?
5. "Tooling that just happens": what mechanism would let the system propose and ship NEW tools (MCP providers, kagent capabilities, fleet scripts) for itself with acceptable risk, and what must stay human-gated?
6. What is the smallest version worth building first, and what should be explicitly NOT built?
