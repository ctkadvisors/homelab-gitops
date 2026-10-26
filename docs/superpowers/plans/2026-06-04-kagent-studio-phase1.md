# kagent Studio — Phase 1 (Architect chat → draft) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a chat-to-create "Architect" to the kagent workbench: describe an agent in natural language, get a validated `AgentTemplate` candidate back, and "Try it" by instantiating into a live, ArgoCD-unmanaged `kagent-draft` namespace where it traces in Langfuse. No promote-to-git yet (Phase 2).

**Architecture:** Reuse the substrate's existing typed machinery rather than inventing it. The Architect LLM (via the gateway's OpenAI-compatible `/v1`) emits a **template-candidate YAML** (the existing `application/x-kagent-template-candidate+yaml` artifact), validated by the existing `@kagent/dto` `parseTemplateCandidate`. A validate→self-correct loop feeds parse errors back to the LLM. "Try it" creates the `AgentTemplate` CR + a seed `AgentTask` in `kagent-draft` via `@kubernetes/client-node`, mirroring the existing `routes/review-queue.ts` accept handler's create pattern.

**Tech Stack:** TypeScript, Hono, `@kubernetes/client-node`, `@kagent/dto`, Vitest (workbench-api); React + Vite (workbench-ui); Kustomize/ArgoCD + cert-manager + NetworkPolicy (new_localai). Two repos: `ctkadvisors/kagent` (workbench) and `new_localai` (GitOps).

**Repos / working dirs:**
- `kagent` = `github.com/ctkadvisors/kagent` (clone fresh; `pnpm install` at root). Workspace pkgs: `packages/workbench-api`, `packages/workbench-ui`, `packages/dto`.
- `new_localai` = this repo (`k8s-kustomized/overlays/production/kagent/`).

**Conventions confirmed from the codebase:**
- Routes are factory fns `xxxRoute(deps): Hono`, mounted in `packages/workbench-api/src/router.ts` `buildRouter()` via `app.route('/api/...', xxxRoute(deps))`.
- Write surface is gated: a route only mutates when `deps.customApi` (a `CustomObjectsApi`) is present; otherwise it 503s with the `write surface disabled` message (see `routes/review-queue.ts`).
- Tests: Vitest, build the route with fake deps + in-memory `SnapshotCache`, drive via Hono `app.request(path, init)`.
- `API_GROUP_VERSION` and CR types come from `@kagent/dto`.
- Run from repo root: `pnpm --filter @kagent/workbench-api test`, `... typecheck`, `... lint`.

---

## File Structure

**kagent repo:**
- Create `packages/workbench-api/src/architect-client.ts` — OpenAI-compatible chat client against the gateway `/v1/chat/completions`. One responsibility: turn a message list into an assistant string (+ usage), with timeout + error scrubbing.
- Create `packages/workbench-api/src/architect-prompt.ts` — the system prompt + few-shot teaching the template-candidate YAML contract. Pure data/string-builder.
- Create `packages/workbench-api/src/routes/architect.ts` — `POST /api/architect/draft` (chat→candidate→validate→self-correct) and `POST /api/architect/try` (instantiate candidate into `kagent-draft`).
- Create `packages/workbench-api/src/routes/architect.test.ts` — route tests with fake architect-client + fake `customApi`.
- Create `packages/workbench-api/src/architect-client.test.ts` — client tests with `vi.fn()` fetch.
- Modify `packages/workbench-api/src/router.ts` — wire `architectRoute` into `buildRouter`, thread new deps.
- Modify `packages/workbench-api/src/main.ts` — construct `ArchitectClient` from env (gateway base URL + token + model), pass to router.
- Create `packages/workbench-ui/src/ArchitectPage.tsx` — chat panel + rendered candidate preview + "Try it" button.
- Modify `packages/workbench-ui/src/api.ts` — `architectDraft()` + `architectTry()` client methods.
- Modify `packages/workbench-ui/src/App.tsx` — add the Architect route/nav entry.

**new_localai repo:**
- Create `k8s-kustomized/overlays/production/kagent/draft-namespace.yaml` — `kagent-draft` Namespace + default-deny NetworkPolicy + egress-to-gateway allow + RBAC (Role/RoleBinding granting the workbench-api SA create/get/list/delete on the kagent CRs + ConfigMaps in `kagent-draft`).
- Modify `k8s-kustomized/overlays/production/kagent/kustomization.yaml` — add `draft-namespace.yaml` to `resources`.
- Modify `k8s-kustomized/overlays/production/kagent/workbench-application.yaml` — set Helm values to enable the write surface + inject the architect env (`KAGENT_ARCHITECT_GATEWAY_URL`, token secretRef, model).

> **Cross-repo note:** the workbench Helm chart lives in the `kagent` repo (`packages/operator/charts/...` or a workbench chart). The `workbench-application.yaml` in `new_localai` only sets *values*. Any new chart value keys (e.g. `architect.*`) must first exist in the chart (kagent repo). Task 7 covers the chart value plumbing.

---

## Task 1: `kagent-draft` namespace + RBAC + NetworkPolicy (new_localai)

**Files:**
- Create: `k8s-kustomized/overlays/production/kagent/draft-namespace.yaml`
- Modify: `k8s-kustomized/overlays/production/kagent/kustomization.yaml`

- [ ] **Step 1: Write the draft-namespace manifest**

Create `k8s-kustomized/overlays/production/kagent/draft-namespace.yaml`:

```yaml
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Chris Knuteson
#
# kagent-draft — live iteration zone for kagent Studio. Deliberately
# NOT in any ArgoCD-managed path (homelab-apps prunes overlays/production;
# this namespace's CONTENTS are created imperatively by workbench-api).
# The namespace OBJECT itself is managed here so RBAC + NetworkPolicy
# are GitOps-pinned; the Agents/Templates/Tasks inside are ephemeral and
# operator/workbench-owned (Argo ignores them — they carry no
# app.kubernetes.io/instance from homelab-apps).
---
apiVersion: v1
kind: Namespace
metadata:
  name: kagent-draft
  labels:
    name: kagent-draft
    app.kubernetes.io/part-of: kagent
    kagent.example.com/draft: 'true'
  annotations:
    argocd.argoproj.io/sync-wave: '6'
---
# Default-deny all ingress + egress; the allow policy below re-opens
# only what a draft agent needs. Paperclip rule: an un-promoted agent
# cannot reach the internet.
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: kagent-draft-default-deny
  namespace: kagent-draft
  annotations:
    argocd.argoproj.io/sync-wave: '6'
spec:
  podSelector: {}
  policyTypes: [Ingress, Egress]
---
# Egress allow: DNS + the LLM gateway + the K8s API. NOTHING else
# (no cloud LLM endpoints — those stay unreachable until a committed
# policy change, per the Hermes governance convention).
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: kagent-draft-egress
  namespace: kagent-draft
  annotations:
    argocd.argoproj.io/sync-wave: '6'
spec:
  podSelector: {}
  policyTypes: [Egress]
  egress:
    - to: # DNS
        - namespaceSelector: {}
          podSelector:
            matchLabels:
              k8s-app: kube-dns
      ports:
        - { protocol: UDP, port: 53 }
        - { protocol: TCP, port: 53 }
    - to: # LLM gateway in kagent-system
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: kagent-system
      ports:
        - { protocol: TCP, port: 4000 }
---
# RBAC: let the workbench-api ServiceAccount create/manage the kagent
# CRs + disposition ConfigMaps in kagent-draft ONLY. SA name/namespace
# mirror the workbench chart's serviceAccountName (kagent-workbench-api,
# namespace kagent-system). Adjust if the chart's SA differs.
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: kagent-draft-writer
  namespace: kagent-draft
  annotations:
    argocd.argoproj.io/sync-wave: '6'
rules:
  - apiGroups: ['kagent.example.com']
    resources: ['agents', 'agenttemplates', 'agenttasks']
    verbs: ['create', 'get', 'list', 'watch', 'delete', 'patch']
  - apiGroups: ['']
    resources: ['configmaps']
    verbs: ['create', 'get', 'list', 'delete', 'patch']
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: kagent-draft-writer
  namespace: kagent-draft
  annotations:
    argocd.argoproj.io/sync-wave: '6'
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: kagent-draft-writer
subjects:
  - kind: ServiceAccount
    name: kagent-workbench-api
    namespace: kagent-system
```

- [ ] **Step 2: Add it to the overlay kustomization**

In `k8s-kustomized/overlays/production/kagent/kustomization.yaml`, add `- draft-namespace.yaml` to the `resources:` list (alongside the other kagent resources).

- [ ] **Step 3: Validate the render**

Run: `kubectl kustomize k8s-kustomized/overlays/production | grep -A2 'kind: Namespace' | grep kagent-draft`
Expected: `kagent-draft` namespace appears in the rendered output, no kustomize errors.

- [ ] **Step 4: Confirm the workbench SA name**

Run: `git -C /tmp/kagent-explore grep -rnE 'serviceAccountName|name: kagent-workbench' -- 'packages/**/charts/**' | head`
Expected: confirms the workbench-api SA name. If it is NOT `kagent-workbench-api`, fix the `RoleBinding.subjects[0].name` in Step 1 to match.

- [ ] **Step 5: Commit**

```bash
git add k8s-kustomized/overlays/production/kagent/draft-namespace.yaml \
        k8s-kustomized/overlays/production/kagent/kustomization.yaml
git commit -m "feat(kagent): kagent-draft namespace + RBAC + NetworkPolicy for Studio drafts"
```

---

## Task 2: Architect system prompt module (kagent repo)

**Files:**
- Create: `packages/workbench-api/src/architect-prompt.ts`
- Test: `packages/workbench-api/src/architect-prompt.test.ts`

- [ ] **Step 1: Write the failing test**

```typescript
// architect-prompt.test.ts
import { describe, expect, it } from 'vitest';
import { buildArchitectMessages, REPAIR_PREFIX } from './architect-prompt.js';

describe('buildArchitectMessages', () => {
  it('puts the candidate contract in the system message and the user ask last', () => {
    const msgs = buildArchitectMessages({ userGoal: 'a summarizer agent' });
    expect(msgs[0].role).toBe('system');
    expect(msgs[0].content).toContain('x-kagent-template-candidate');
    expect(msgs[0].content).toContain('agentSpec');
    expect(msgs.at(-1)).toEqual({ role: 'user', content: 'a summarizer agent' });
  });

  it('appends a repair turn carrying the validation error when provided', () => {
    const msgs = buildArchitectMessages({
      userGoal: 'x',
      priorYaml: 'agentSpec: {}',
      validationError: 'parameters[0].type must be one of string|integer|toolSelection',
    });
    const last = msgs.at(-1)!;
    expect(last.role).toBe('user');
    expect(last.content).toContain(REPAIR_PREFIX);
    expect(last.content).toContain('must be one of');
    expect(last.content).toContain('agentSpec: {}');
  });
});
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `pnpm --filter @kagent/workbench-api test architect-prompt`
Expected: FAIL — `Cannot find module './architect-prompt.js'`.

- [ ] **Step 3: Implement the prompt module**

```typescript
// architect-prompt.ts
/**
 * SPDX-License-Identifier: MIT
 * Copyright (c) 2026 Chris Knuteson
 */

/** OpenAI-compatible chat message. */
export interface ChatMessage {
  readonly role: 'system' | 'user' | 'assistant';
  readonly content: string;
}

export const REPAIR_PREFIX = 'Your previous candidate failed validation. Fix ONLY the error below and return the full corrected YAML.';

const SYSTEM = `You are the kagent Architect. Turn the user's request into a single
AgentTemplate candidate, emitted as YAML and NOTHING else (no prose, no code fences).

The YAML MUST conform to the x-kagent-template-candidate contract:
  agentSpec:        # REQUIRED object — the Agent.spec body
    displayName: string
    systemPrompt: string        # the agent's behaviour
    model: string               # e.g. "workers-ai/@cf/meta/llama-4-scout-17b-16e-instruct"
  templateVersion: 1            # optional, default 1
  parameters:                   # optional array
    - name: string
      type: string|integer|toolSelection
      required: true|false
  budget:                       # optional — KEEP CONSERVATIVE (paperclip rule)
    maxIterations: <= 10
    maxCostUsdPerRun: <= 0.50
    maxParallelInstances: 1
  toolAllowlist: [string]       # optional; omit = no tools

Rules:
- Default budget to maxIterations 6, maxCostUsdPerRun 0.10, maxParallelInstances 1 unless the user is explicit.
- Never include cloud credentials or tools the user did not ask for.
- Output ONLY the YAML document.`;

export interface ArchitectPromptInput {
  readonly userGoal: string;
  readonly priorYaml?: string;
  readonly validationError?: string;
}

export function buildArchitectMessages(input: ArchitectPromptInput): ChatMessage[] {
  const msgs: ChatMessage[] = [{ role: 'system', content: SYSTEM }];
  if (input.priorYaml !== undefined && input.validationError !== undefined) {
    msgs.push({ role: 'user', content: input.userGoal });
    msgs.push({ role: 'assistant', content: input.priorYaml });
    msgs.push({
      role: 'user',
      content: `${REPAIR_PREFIX}\n\nERROR: ${input.validationError}\n\nPREVIOUS YAML:\n${input.priorYaml}`,
    });
  } else {
    msgs.push({ role: 'user', content: input.userGoal });
  }
  return msgs;
}
```

- [ ] **Step 4: Run the test to confirm it passes**

Run: `pnpm --filter @kagent/workbench-api test architect-prompt`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add packages/workbench-api/src/architect-prompt.ts packages/workbench-api/src/architect-prompt.test.ts
git commit -m "feat(workbench-api): architect system prompt + repair-turn builder"
```

---

## Task 3: Architect gateway chat client (kagent repo)

**Files:**
- Create: `packages/workbench-api/src/architect-client.ts`
- Test: `packages/workbench-api/src/architect-client.test.ts`

- [ ] **Step 1: Write the failing test**

```typescript
// architect-client.test.ts
import { describe, expect, it, vi } from 'vitest';
import { ArchitectClient } from './architect-client.js';

function fakeFetch(body: unknown, status = 200) {
  return vi.fn(async () =>
    new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } }),
  );
}

describe('ArchitectClient.complete', () => {
  it('POSTs to the gateway /v1/chat/completions with bearer auth and returns the message', async () => {
    const fetchMock = fakeFetch({ choices: [{ message: { content: 'agentSpec: {}' } }] });
    const client = new ArchitectClient(
      { baseUrl: 'http://gw:4000/v1', token: 'sk-x', model: 'm1' },
      fetchMock as unknown as typeof fetch,
    );
    const out = await client.complete([{ role: 'user', content: 'hi' }]);
    expect(out).toBe('agentSpec: {}');
    const [url, init] = fetchMock.mock.calls[0]!;
    expect(url).toBe('http://gw:4000/v1/chat/completions');
    expect((init!.headers as Record<string, string>).Authorization).toBe('Bearer sk-x');
    expect(JSON.parse(init!.body as string).model).toBe('m1');
  });

  it('throws a scrubbed error on a 5xx (no gateway internals leak)', async () => {
    const fetchMock = fakeFetch({ error: 'pod kagent-llm-gateway-xyz crashed' }, 502);
    const client = new ArchitectClient(
      { baseUrl: 'http://gw:4000/v1', token: 'sk-x', model: 'm1' },
      fetchMock as unknown as typeof fetch,
    );
    await expect(client.complete([{ role: 'user', content: 'hi' }])).rejects.toThrow(/architect upstream/i);
  });
});
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `pnpm --filter @kagent/workbench-api test architect-client`
Expected: FAIL — `Cannot find module './architect-client.js'`.

- [ ] **Step 3: Implement the client**

```typescript
// architect-client.ts
/**
 * SPDX-License-Identifier: MIT
 * Copyright (c) 2026 Chris Knuteson
 */
import type { ChatMessage } from './architect-prompt.js';

export interface ArchitectClientConfig {
  readonly baseUrl: string; // e.g. http://kagent-llm-gateway.kagent-system:4000/v1
  readonly token: string;
  readonly model: string;
  readonly timeoutMs?: number;
}

export class ArchitectClient {
  constructor(
    private readonly cfg: ArchitectClientConfig,
    private readonly fetchFn: typeof fetch = fetch,
  ) {}

  async complete(messages: readonly ChatMessage[]): Promise<string> {
    const ctrl = new AbortController();
    const t = setTimeout(() => ctrl.abort(), this.cfg.timeoutMs ?? 60_000);
    try {
      const res = await this.fetchFn(`${this.cfg.baseUrl}/chat/completions`, {
        method: 'POST',
        signal: ctrl.signal,
        headers: {
          'content-type': 'application/json',
          Authorization: `Bearer ${this.cfg.token}`,
        },
        body: JSON.stringify({
          model: this.cfg.model,
          temperature: 0,
          messages,
        }),
      });
      if (!res.ok) {
        // Do NOT surface the upstream body — it may name gateway pods.
        throw new Error(`architect upstream error (status ${res.status})`);
      }
      const json = (await res.json()) as { choices?: Array<{ message?: { content?: string } }> };
      const content = json.choices?.[0]?.message?.content;
      if (typeof content !== 'string') throw new Error('architect upstream returned no message content');
      return content;
    } finally {
      clearTimeout(t);
    }
  }
}
```

- [ ] **Step 4: Run the test to confirm it passes**

Run: `pnpm --filter @kagent/workbench-api test architect-client`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add packages/workbench-api/src/architect-client.ts packages/workbench-api/src/architect-client.test.ts
git commit -m "feat(workbench-api): gateway-backed Architect chat client"
```

---

## Task 4: `POST /api/architect/draft` — generate + validate + self-correct (kagent repo)

**Files:**
- Create: `packages/workbench-api/src/routes/architect.ts`
- Test: `packages/workbench-api/src/routes/architect.test.ts`

> **Pre-req read:** open `packages/dto/src/template-candidate.ts` and confirm the exported parser name + return shape. This plan assumes `parseTemplateCandidate(yaml: string): { ok: true; value: AgentTemplateCandidate } | { ok: false; error: string }`. If the export differs, use the actual name/shape in the code below.

- [ ] **Step 1: Write the failing test**

```typescript
// architect.test.ts
import { describe, expect, it, vi } from 'vitest';
import { architectRoute } from './architect.js';

const VALID = 'agentSpec:\n  displayName: Sum\n  systemPrompt: summarize\n  model: m1\nbudget:\n  maxIterations: 6\n';

function deps(over: Partial<Parameters<typeof architectRoute>[0]> = {}) {
  return {
    architect: { complete: vi.fn(async () => VALID) },
    maxRepairs: 2,
    ...over,
  } as Parameters<typeof architectRoute>[0];
}

describe('POST /api/architect/draft', () => {
  it('returns the candidate + parsed preview when the LLM emits valid YAML', async () => {
    const app = architectRoute(deps());
    const res = await app.request('/draft', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ goal: 'a summarizer' }),
    });
    expect(res.status).toBe(200);
    const body = (await res.json()) as { ok: boolean; candidateYaml: string; preview: unknown };
    expect(body.ok).toBe(true);
    expect(body.candidateYaml).toContain('displayName: Sum');
    expect(body.preview).toBeDefined();
  });

  it('runs the repair loop when the first output is invalid, then succeeds', async () => {
    const complete = vi
      .fn()
      .mockResolvedValueOnce('not: a: valid: candidate')
      .mockResolvedValueOnce(VALID);
    const app = architectRoute(deps({ architect: { complete } }));
    const res = await app.request('/draft', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ goal: 'x' }),
    });
    expect(res.status).toBe(200);
    expect(complete).toHaveBeenCalledTimes(2);
  });

  it('returns 422 with the last validation error after exhausting repairs', async () => {
    const complete = vi.fn(async () => 'totally invalid');
    const app = architectRoute(deps({ architect: { complete }, maxRepairs: 1 }));
    const res = await app.request('/draft', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ goal: 'x' }),
    });
    expect(res.status).toBe(422);
    const body = (await res.json()) as { error: string };
    expect(body.error).toMatch(/could not produce a valid/i);
  });

  it('400s when goal is missing or empty', async () => {
    const app = architectRoute(deps());
    const res = await app.request('/draft', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ goal: '   ' }),
    });
    expect(res.status).toBe(400);
  });
});
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `pnpm --filter @kagent/workbench-api test routes/architect`
Expected: FAIL — `Cannot find module './architect.js'`.

- [ ] **Step 3: Implement the draft handler**

```typescript
// architect.ts
/**
 * SPDX-License-Identifier: MIT
 * Copyright (c) 2026 Chris Knuteson
 */
import { Hono } from 'hono';
import { parseTemplateCandidate } from '@kagent/dto';

import { buildArchitectMessages } from '../architect-prompt.js';

/** Minimal surface of ArchitectClient the route needs (for test injection). */
export interface ArchitectLike {
  complete(messages: ReadonlyArray<{ role: 'system' | 'user' | 'assistant'; content: string }>): Promise<string>;
}

export interface ArchitectRouteDeps {
  readonly architect: ArchitectLike;
  /** Max self-correct retries after the first attempt. Default 2. */
  readonly maxRepairs?: number;
}

/** Strip accidental ``` fences the model may add despite instructions. */
function stripFences(s: string): string {
  return s.replace(/^\s*```(?:ya?ml)?\s*/i, '').replace(/\s*```\s*$/i, '').trim();
}

export function architectRoute(deps: ArchitectRouteDeps): Hono {
  const app = new Hono();
  const maxRepairs = deps.maxRepairs ?? 2;

  app.post('/draft', async (c) => {
    const body = (await c.req.json().catch(() => ({}))) as { goal?: unknown };
    const goal = typeof body.goal === 'string' ? body.goal.trim() : '';
    if (goal.length === 0) return c.json({ error: 'goal is required' }, 400);

    let priorYaml: string | undefined;
    let lastError = 'unknown';
    for (let attempt = 0; attempt <= maxRepairs; attempt++) {
      const messages =
        priorYaml === undefined
          ? buildArchitectMessages({ userGoal: goal })
          : buildArchitectMessages({ userGoal: goal, priorYaml, validationError: lastError });
      const raw = stripFences(await deps.architect.complete(messages));
      const parsed = parseTemplateCandidate(raw);
      if (parsed.ok) {
        return c.json({ ok: true, candidateYaml: raw, preview: parsed.value }, 200);
      }
      priorYaml = raw;
      lastError = parsed.error;
    }
    return c.json({ error: `architect could not produce a valid candidate: ${lastError}` }, 422);
  });

  return app;
}
```

- [ ] **Step 4: Run the test to confirm it passes**

Run: `pnpm --filter @kagent/workbench-api test routes/architect`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add packages/workbench-api/src/routes/architect.ts packages/workbench-api/src/routes/architect.test.ts
git commit -m "feat(workbench-api): POST /api/architect/draft with validate+self-correct loop"
```

---

## Task 5: `POST /api/architect/try` — instantiate candidate into kagent-draft (kagent repo)

**Files:**
- Modify: `packages/workbench-api/src/routes/architect.ts`
- Modify: `packages/workbench-api/src/routes/architect.test.ts`

> **Pre-req read:** open `packages/workbench-api/src/routes/review-queue.ts` accept handler (the `createNamespacedCustomObject` call that creates the `AgentTemplate` CR) and copy its exact `CustomObjectsApi` call signature (group/version/plural/namespace/body). The `@kubernetes/client-node` API signature changed across versions — mirror what the existing code uses, don't guess.

- [ ] **Step 1: Add the failing test**

Append to `architect.test.ts`:

```typescript
describe('POST /api/architect/try', () => {
  it('503s when no customApi is configured (write surface disabled)', async () => {
    const app = architectRoute(deps()); // no customApi
    const res = await app.request('/try', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ candidateYaml: VALID }),
    });
    expect(res.status).toBe(503);
  });

  it('creates an AgentTemplate in kagent-draft and returns its ref', async () => {
    const createNamespacedCustomObject = vi.fn(async () => ({
      body: { metadata: { name: 'sum-abc123', namespace: 'kagent-draft', uid: 'u1' } },
    }));
    const app = architectRoute(
      deps({ customApi: { createNamespacedCustomObject } as never, draftNamespace: 'kagent-draft' }),
    );
    const res = await app.request('/try', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ candidateYaml: VALID }),
    });
    expect(res.status).toBe(201);
    const body = (await res.json()) as { namespace: string; name: string };
    expect(body.namespace).toBe('kagent-draft');
    expect(createNamespacedCustomObject).toHaveBeenCalledTimes(1);
  });

  it('422s when candidateYaml fails validation', async () => {
    const app = architectRoute(
      deps({ customApi: { createNamespacedCustomObject: vi.fn() } as never }),
    );
    const res = await app.request('/try', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ candidateYaml: 'garbage' }),
    });
    expect(res.status).toBe(422);
  });
});
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `pnpm --filter @kagent/workbench-api test routes/architect`
Expected: FAIL — `/try` returns 404 (handler not yet defined).

- [ ] **Step 3: Extend deps + implement `/try`**

In `architect.ts`, extend `ArchitectRouteDeps`:

```typescript
import type { CustomObjectsApi } from '@kubernetes/client-node';
import { API_GROUP, API_VERSION } from '@kagent/dto'; // confirm exact exports; else inline 'kagent.example.com' / 'v1alpha1'

export interface ArchitectRouteDeps {
  readonly architect: ArchitectLike;
  readonly maxRepairs?: number;
  /** Present => write surface enabled. */
  readonly customApi?: CustomObjectsApi;
  /** Namespace drafts land in. Default 'kagent-draft'. */
  readonly draftNamespace?: string;
  /** Test seam for the instance name. */
  readonly generateName?: () => string;
}

const WRITE_DISABLED = 'write surface disabled (no CustomObjects client configured); set actions.create=true on the chart';
```

Add the handler inside `architectRoute`, before `return app;`:

```typescript
  app.post('/try', async (c) => {
    if (!deps.customApi) return c.json({ error: WRITE_DISABLED }, 503);
    const ns = deps.draftNamespace ?? 'kagent-draft';
    const body = (await c.req.json().catch(() => ({}))) as { candidateYaml?: unknown };
    const yaml = typeof body.candidateYaml === 'string' ? body.candidateYaml : '';
    const parsed = parseTemplateCandidate(yaml);
    if (!parsed.ok) return c.json({ error: 'invalid candidate', detail: parsed.error }, 422);

    const display = (parsed.value as { agentSpec?: { displayName?: string } }).agentSpec?.displayName ?? 'agent';
    const slug = display.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/(^-|-$)/g, '').slice(0, 40) || 'agent';
    const suffix = (deps.generateName ?? (() => Math.random().toString(36).slice(2, 8)))();
    const name = `${slug}-${suffix}`;

    // Mirror the createNamespacedCustomObject signature used in routes/review-queue.ts.
    const created = await deps.customApi.createNamespacedCustomObject(
      API_GROUP, // 'kagent.example.com'
      API_VERSION, // 'v1alpha1'
      ns,
      'agenttemplates',
      {
        apiVersion: `${API_GROUP}/${API_VERSION}`,
        kind: 'AgentTemplate',
        metadata: { name, namespace: ns, labels: { 'kagent.example.com/draft': 'true' } },
        spec: parsed.value,
      },
    );
    const meta = (created as { body?: { metadata?: { name?: string; uid?: string } } }).body?.metadata;
    return c.json(
      {
        namespace: ns,
        name: meta?.name ?? name,
        uid: meta?.uid,
        _links: { langfuse: 'https://langfuse.example.com' },
      },
      201,
    );
  });
```

- [ ] **Step 4: Run the test to confirm it passes**

Run: `pnpm --filter @kagent/workbench-api test routes/architect`
Expected: PASS (7 tests total in file).

- [ ] **Step 5: typecheck + lint, then commit**

Run: `pnpm --filter @kagent/workbench-api typecheck && pnpm --filter @kagent/workbench-api lint`
Expected: no errors.

```bash
git add packages/workbench-api/src/routes/architect.ts packages/workbench-api/src/routes/architect.test.ts
git commit -m "feat(workbench-api): POST /api/architect/try instantiates AgentTemplate into kagent-draft"
```

---

## Task 6: Wire the route into the router + main (kagent repo)

**Files:**
- Modify: `packages/workbench-api/src/router.ts`
- Modify: `packages/workbench-api/src/main.ts`
- Modify: `packages/workbench-api/src/router.test.ts` (if present; else add a focused test)

- [ ] **Step 1: Add a router-level failing test**

In `router.test.ts` (mirror the existing router test setup — build the router with minimal deps), add:

```typescript
it('mounts /api/architect/draft', async () => {
  const app = buildRouter({
    ...baseDeps, // reuse the file's existing minimal deps fixture
    architect: { complete: async () => 'agentSpec:\n  displayName: X\n  systemPrompt: y\n  model: m\n' },
  } as never);
  const res = await app.request('/api/architect/draft', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ goal: 'x' }),
  });
  expect(res.status).toBe(200);
});
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `pnpm --filter @kagent/workbench-api test router`
Expected: FAIL — 404 on `/api/architect/draft`.

- [ ] **Step 3: Wire it in `router.ts`**

Add the import alongside the other route imports:

```typescript
import { architectRoute, type ArchitectLike } from './routes/architect.js';
```

Add to `RouterDeps`:

```typescript
  /** Architect chat client; when omitted, /api/architect/* is not mounted. */
  readonly architect?: ArchitectLike;
  /** Namespace drafts land in (default 'kagent-draft'). */
  readonly draftNamespace?: string;
```

Inside `buildRouter`, after the other `app.route(...)` calls:

```typescript
  if (deps.architect) {
    app.route(
      '/api/architect',
      architectRoute({
        architect: deps.architect,
        customApi: deps.customApi,
        draftNamespace: deps.draftNamespace,
      }),
    );
  }
```

- [ ] **Step 4: Run the router test**

Run: `pnpm --filter @kagent/workbench-api test router`
Expected: PASS.

- [ ] **Step 5: Construct the client in `main.ts`**

In `main.ts`, where deps are assembled, add (guarded by env so local read-only dev still boots):

```typescript
import { ArchitectClient } from './architect-client.js';

const gwUrl = process.env.KAGENT_ARCHITECT_GATEWAY_URL;
const gwToken = process.env.KAGENT_ARCHITECT_GATEWAY_TOKEN;
const gwModel = process.env.KAGENT_ARCHITECT_MODEL;
const architect =
  gwUrl && gwToken && gwModel
    ? new ArchitectClient({ baseUrl: gwUrl, token: gwToken, model: gwModel })
    : undefined;
```

Pass `architect` (and `draftNamespace: process.env.KAGENT_DRAFT_NAMESPACE ?? 'kagent-draft'`) into the `buildRouter({ ... })` call.

- [ ] **Step 6: Full package gate, then commit**

Run: `pnpm --filter @kagent/workbench-api test && pnpm --filter @kagent/workbench-api typecheck && pnpm --filter @kagent/workbench-api lint`
Expected: all green.

```bash
git add packages/workbench-api/src/router.ts packages/workbench-api/src/main.ts packages/workbench-api/src/router.test.ts
git commit -m "feat(workbench-api): mount /api/architect when gateway env is configured"
```

---

## Task 7: Chart values + Argo wiring for the Architect env (both repos)

**Files:**
- Modify (kagent repo): the workbench Helm chart values + Deployment template (locate via `git -C /tmp/kagent-explore grep -rln 'workbench-api' -- '**/charts/**'`).
- Modify (new_localai): `k8s-kustomized/overlays/production/kagent/workbench-application.yaml`

- [ ] **Step 1: Add chart value plumbing (kagent repo)**

In the workbench chart, add an `architect` value block and inject env into the workbench-api container:

```yaml
# values.yaml additions
architect:
  enabled: false
  gatewayUrl: ''        # e.g. http://kagent-llm-gateway.kagent-system.svc.cluster.local:4000/v1
  model: ''             # e.g. workers-ai/@cf/meta/llama-4-scout-17b-16e-instruct
  tokenSecret:
    name: kagent-llm-gateway-token
    key: token
actions:
  create: false         # gates the /try write surface (mirrors existing pattern)
```

```yaml
# deployment template — workbench-api container env (only when architect.enabled)
{{- if .Values.architect.enabled }}
- name: KAGENT_ARCHITECT_GATEWAY_URL
  value: {{ .Values.architect.gatewayUrl | quote }}
- name: KAGENT_ARCHITECT_MODEL
  value: {{ .Values.architect.model | quote }}
- name: KAGENT_ARCHITECT_GATEWAY_TOKEN
  valueFrom:
    secretKeyRef:
      name: {{ .Values.architect.tokenSecret.name }}
      key: {{ .Values.architect.tokenSecret.key }}
{{- end }}
```

> The workbench-api SA already reads `kagent-llm-gateway-token` for the Gateway page; confirm it's mounted/readable in `kagent-system`. The RBAC for writing into `kagent-draft` was added in Task 1.

Commit in the kagent repo:

```bash
git add <chart values.yaml> <chart deployment template>
git commit -m "feat(workbench): architect.* + actions.create chart values for kagent Studio"
```

- [ ] **Step 2: Set the values from new_localai**

In `workbench-application.yaml`, under `spec.source.helm.values`, add:

```yaml
        architect:
          enabled: true
          gatewayUrl: 'http://kagent-llm-gateway.kagent-system.svc.cluster.local:4000/v1'
          model: 'workers-ai/@cf/meta/llama-4-scout-17b-16e-instruct'
          tokenSecret:
            name: kagent-llm-gateway-token
            key: token
        actions:
          create: true
```

- [ ] **Step 3: Validate render**

Run: `kubectl kustomize k8s-kustomized/overlays/production | grep -A30 'name: kagent-workbench' | grep -iE 'architect|actions'`
Expected: the architect values appear in the rendered Application.

- [ ] **Step 4: Commit (new_localai)**

```bash
git add k8s-kustomized/overlays/production/kagent/workbench-application.yaml
git commit -m "feat(kagent): enable workbench Architect (gateway model + write surface)"
```

---

## Task 8: Architect UI page (kagent repo)

**Files:**
- Create: `packages/workbench-ui/src/ArchitectPage.tsx`
- Modify: `packages/workbench-ui/src/api.ts`
- Modify: `packages/workbench-ui/src/App.tsx`

> **Pre-req read:** open `api.ts` and `NewTaskModal.tsx` to copy the existing fetch wrapper + error-handling idiom; open `App.tsx` to copy the existing nav/route registration idiom. Match them exactly rather than introducing a new pattern.

- [ ] **Step 1: Add API client methods**

In `api.ts`, mirroring the existing fetch helper, add:

```typescript
export interface ArchitectDraftResult {
  ok: boolean;
  candidateYaml: string;
  preview: unknown;
}

export async function architectDraft(goal: string): Promise<ArchitectDraftResult> {
  // use the file's existing apiFetch/jsonPost helper instead of bare fetch
  return jsonPost<ArchitectDraftResult>('/api/architect/draft', { goal });
}

export async function architectTry(candidateYaml: string): Promise<{ namespace: string; name: string; _links?: { langfuse?: string } }> {
  return jsonPost('/api/architect/try', { candidateYaml });
}
```

- [ ] **Step 2: Create `ArchitectPage.tsx`**

```tsx
// ArchitectPage.tsx
/**
 * SPDX-License-Identifier: MIT
 * Copyright (c) 2026 Chris Knuteson
 */
import { useState } from 'react';
import { architectDraft, architectTry, type ArchitectDraftResult } from './api.js';

export function ArchitectPage(): JSX.Element {
  const [goal, setGoal] = useState('');
  const [draft, setDraft] = useState<ArchitectDraftResult | null>(null);
  const [status, setStatus] = useState<string>('');
  const [busy, setBusy] = useState(false);

  async function onDraft() {
    setBusy(true); setStatus('Architecting…'); setDraft(null);
    try { setDraft(await architectDraft(goal)); setStatus(''); }
    catch (e) { setStatus(`Draft failed: ${(e as Error).message}`); }
    finally { setBusy(false); }
  }

  async function onTry() {
    if (!draft) return;
    setBusy(true); setStatus('Instantiating in kagent-draft…');
    try {
      const r = await architectTry(draft.candidateYaml);
      setStatus(`Created ${r.namespace}/${r.name}. Watch it in Langfuse: ${r._links?.langfuse ?? ''}`);
    } catch (e) { setStatus(`Try failed: ${(e as Error).message}`); }
    finally { setBusy(false); }
  }

  return (
    <div className="architect-page">
      <h2>Architect — chat to create</h2>
      <textarea value={goal} onChange={(e) => setGoal(e.target.value)} placeholder="Describe the agent you want…" rows={3} />
      <button disabled={busy || goal.trim() === ''} onClick={onDraft}>Draft</button>
      {draft && (
        <>
          <pre className="candidate-preview">{draft.candidateYaml}</pre>
          <button disabled={busy} onClick={onTry}>Try it in kagent-draft</button>
        </>
      )}
      {status && <p className="architect-status">{status}</p>}
    </div>
  );
}
```

- [ ] **Step 3: Register the page in `App.tsx`**

Add an `ArchitectPage` entry to the existing nav/route structure (copy the idiom used by `ClusterPage`/`ReviewPage`). E.g. a nav item labeled "Architect" → renders `<ArchitectPage />`.

- [ ] **Step 4: Build the UI to verify it compiles**

Run: `pnpm --filter @kagent/workbench-ui build`
Expected: build succeeds, no type errors.

- [ ] **Step 5: Commit**

```bash
git add packages/workbench-ui/src/ArchitectPage.tsx packages/workbench-ui/src/api.ts packages/workbench-ui/src/App.tsx
git commit -m "feat(workbench-ui): Architect chat page (draft + try in kagent-draft)"
```

---

## Task 9: End-to-end manual verification (after both repos ship via CI/ArgoCD)

**Files:** none (operational verification).

- [ ] **Step 1: Confirm rollout**

Run: `ssh elitemini "kubectl get pods -n kagent-system -l app.kubernetes.io/name=kagent-workbench-api; kubectl get ns kagent-draft"`
Expected: workbench-api pod Running on the new image; `kagent-draft` namespace exists.

- [ ] **Step 2: Draft an agent via the API**

Run: `ssh elitemini "kubectl exec -n kagent-system deploy/kagent-workbench-api -- wget -qO- --post-data='{\"goal\":\"a haiku-writing agent\"}' --header=content-type:application/json http://localhost:PORT/api/architect/draft"` (use the chart's container port).
Expected: JSON with `ok:true` and a `candidateYaml` containing `agentSpec`.

- [ ] **Step 3: Try it, then confirm the AgentTemplate landed in kagent-draft**

Drive the "Try it" path (UI at `workbench.example.com`, or POST `/api/architect/try`).
Run: `ssh elitemini "kubectl get agenttemplate -n kagent-draft"`
Expected: a new `AgentTemplate` named `<slug>-<suffix>`.

- [ ] **Step 4: Confirm the draft is NOT adopted by ArgoCD**

Run: `ssh elitemini "kubectl get application -n argocd homelab-apps -o jsonpath='{.status.resources[?(@.namespace==\"kagent-draft\")].name}'"`
Expected: empty — ArgoCD does not manage kagent-draft contents (no prune risk).

- [ ] **Step 5: Confirm the trace in Langfuse**

Open `https://langfuse.example.com` → the Architect chat-completion (gateway call) appears as a generation; if a draft agent ran a task, its run appears too.

---

## Self-Review notes (gaps to watch during execution)

- **`parseTemplateCandidate` signature** (Tasks 4–5) and **`@kagent/dto` group/version exports** (Task 5) are assumed; the pre-req reads in those tasks force confirmation against the real source before coding.
- **`createNamespacedCustomObject` call shape** (Task 5) varies by `@kubernetes/client-node` major version — Task 5 Step pre-req says copy it from `routes/review-queue.ts`, which is the authoritative in-repo usage.
- **Workbench-api SA name** (Task 1 Step 4) is verified against the chart before the RoleBinding is trusted.
- **Phase boundary:** promote-to-git and the read-write operate actions (start/stop, kill switch, inline disposition edit) are intentionally **out of this plan** — they are Phase 2/3 per the spec.
