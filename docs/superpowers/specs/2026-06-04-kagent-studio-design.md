# kagent Studio — chat-to-create + operate console

**Date:** 2026-06-04
**Status:** Approved (design); implementation pending
**Author:** Chris Knuteson (with Claude)

## Goal

Evolve the read-only kagent-workbench into "mission control": a management
console where you **chat to create** kagent agents (natural language → deployed,
governed agent) and **operate** the fleet (run/stop tasks, edit dispositions,
watch traces, kill runaways). Dogfoods the existing stack — the authoring brain
runs through the LLM gateway and is therefore auto-traced in Langfuse.

## Existing substrate (build on, don't reinvent)

- **CRDs** (`kagent.example.com/v1alpha1`): `Tenant` → `Agent` →
  `AgentDisposition` (ConfigMap w/ `disposition.yaml`: attention budget,
  proposal scope, `maxProposalsPerDay`) → `ModelEndpoint` → `AgentTask`.
  Capability-JWTs scope tools; audit events emitted.
- **kagent-workbench** (`ctkadvisors/kagent` repo): `@kagent/workbench-api`
  facade + `@kagent/workbench-ui` (Vite/React), read-only "Command Center"
  (renders dispositions via the operator overlay-loader → `/api/dispositions`).
  Images `ghcr.io/ctkadvisors/kagent-workbench-{api,ui}`. Deployed via ArgoCD
  (`workbench-application.yaml`), Tailscale-trust, no app auth.
- **Gateway** `kagent-llm-gateway.kagent-system:4000/v1` — OpenAI-compatible,
  bearer-token, admission control + AIMD caps, the LLM chokepoint. Agents route
  LLM calls through it (`llmGateway.enabled: true`).
- **Langfuse** `langfuse-web.langfuse-system:3000` — OTel trace sink (GenAI
  semconv → Generations/Tools) + system-prompt registry; agents fetch prompts
  from it at boot.
- **GitOps**: this repo (`new_localai`) `overlays/production/kagent/`, ArgoCD
  `homelab-apps` auto-sync + **prune** + self-heal, sync waves.
- **`@kagent/dto`**: disposition schema. **`ensure_agent_from_template`**: an
  existing agent tool that instantiates agents from templates.

## Core decisions (locked)

1. **Full create + operate console** — workbench read-only → read-write.
2. **Hybrid write path** — live draft namespace for instant iteration, then
   "Promote" commits to git and ArgoCD takes over.
3. **Authoring brain through the gateway** — every "create an agent" chat is a
   gateway client, so it's governed + auto-traced in Langfuse.
4. **Typed intermediate representation, not freeform YAML** (see Architecture).

## Architecture

### The Architect (authoring brain)

The Architect does NOT emit raw CRs. Pipeline:

```
chat ──▶ Architect (LLM via gateway) ──▶ typed AgentSpec (JSON, @kagent/dto-validated)
                                                  │  deterministic templating
                                                  ▼
                        Agent CR + AgentDisposition + ModelEndpoint binding
                        + system prompt (written to Langfuse prompt registry)
```

- LLM's only job: **fill the typed `AgentSpec` form from conversation** —
  structured-output, tractable for CF Scout (no frontier model required).
- **Validate → self-correct loop**: candidate spec validated against the
  `AgentSpec` schema → rendered CRs validated against CRD OpenAPI + **server-side
  dry-run** → any errors fed back to the LLM for another pass (bounded retries).
- **Advanced escape hatch**: freeform overlay fields for cases the form can't
  express, validated through the same dry-run gate.
- Runs via an OpenAI-compatible client → gateway `:4000/v1` (model CF Scout
  today; a frontier backend can be wired into the gateway later). Auto-traced in
  Langfuse.

**Rationale for typed-IR over pure-LLM-YAML:** ~10x fewer invalid outputs, clean
diff/preview, smaller model works, and it extends the existing `@kagent/dto` +
`ensure_agent_from_template` machinery rather than competing with it.

### Create flow (hybrid write path)

1. Chat → Architect proposes `AgentSpec` → UI shows a **rendered diff** (actual
   CRs + the system prompt).
2. **"Try it"** → workbench-api applies the rendered CRs to a live
   **`kagent-draft`** namespace — deliberately OUTSIDE any ArgoCD-managed path
   so prune never touches it. Agent spins up; run a task; watch it **trace live
   in Langfuse**; iterate by chatting further.
3. **"Promote"** → renders artifacts into the repo layout
   (`overlays/production/kagent/agents/<name>/`), opens a **commit/PR to
   `new_localai`**; ArgoCD reconciles into the managed namespace; the draft copy
   is torn down. Git is now source of truth.

### Operate surface (workbench read-only → read-write)

Extend the Command Center with actions: start/stop & suspend/resume `AgentTask`s
(admission control already exists); **inline disposition editing** (panel already
renders them); per-agent **embedded Langfuse traces**; live **budget/cost**
(`tokensRemainingToday` + gateway usage rows); **global kill switch** (scale-to-0).

### Safety rails (non-negotiable — paperclip lesson)

Every chat-created agent is born paperclip-safe: conservative default disposition
(low `tokensPerDay`, low `maxProposalsPerDay`), pod resource caps, a default-deny
**NetworkPolicy** (Hermes pattern), and confinement to `kagent-draft` until
explicit promote. Gateway admission control + AIMD caps backstop runaway
inference. One-click kill switch in the UI.

### Code locations (cross-repo, like the workbench already is)

- **`ctkadvisors/kagent`**: workbench-api gains `/architect` (chat → generate →
  validate), draft-apply, and promote endpoints; workbench-ui gains the chat
  panel + action buttons; `@kagent/dto` gains the `AgentSpec` schema + templating.
- **`new_localai`**: `kagent-draft` namespace + scoped RBAC for workbench-api to
  write there; sealed git-write creds for promote; gateway backend wiring for the
  authoring model.

## Phasing

- **Phase 1 (MVP):** Architect chat → `AgentSpec` → diff → **Try it in
  `kagent-draft`** → watch in Langfuse. No promote. Proves generation reliability
  and is the headline demo loop.
- **Phase 2:** Promote-to-git (commit/PR) + read-write operate actions
  (start/stop, kill switch).
- **Phase 3:** Inline disposition editing, budget/cost dashboards, advanced
  freeform overlays.

## Out of scope (for now)

- Multi-user / SSO (Tailscale-trust single-user stays).
- Multi-tenant authoring beyond the `homelab` Tenant.
- Auto-promote without human confirmation (promote always produces a
  reviewable commit/PR).
- Replacing Langfuse with MLflow for agent tracing (Langfuse is the live path;
  MLflow stays the hands-on playground).

## Validation & rollout

- Generation reliability measured by: % of Architect outputs that pass dry-run
  on first try, and after the self-correct loop (target: ~all after loop).
- `kagent-draft` apply path proven before promote is built (Phase 1 gate).
- Rollout per workbench convention: tag `ctkadvisors/kagent` → images publish →
  ArgoCD syncs workbench; `new_localai` overlay changes via the normal GitOps flow.
