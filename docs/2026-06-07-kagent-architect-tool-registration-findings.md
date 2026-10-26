# kagent Architect — tool-registration findings (2026-06-07)

Investigation of two deployment-wiring gaps for the kagent workbench /
Architect (Studio chat-to-create) running at `kagent.example.com`.

> Scope note: the authoritative fixes for items B and C below are
> **code changes in the `kagent` repo** (`packages/agent-pod`,
> `packages/dto`, `packages/workbench-api`, `packages/operator`). This
> doc lives in `new_localai` because that was the only writable repo in
> this session; mirror it into `kagent/docs/` when a kagent-repo change
> lands. The one change made directly here is the GitOps value fix in
> §A.

---

## A. Langfuse "View trace" links were pointed at an unreachable host (FIXED here)

### What the workbench actually consumes for Langfuse

The workbench-api consumes **exactly one** Langfuse input: the
`LANGFUSE_BASE_URL` env var (chart value `api.langfuseBaseUrl`). It does
**not** read `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` / project id /
any auth — verified by grep across `packages/workbench-api/src` and
`packages/workbench-ui/src` (only hit: `main.ts:119
process.env.LANGFUSE_BASE_URL`).

Trace **push** is OTLP-from-the-agent-pod (`@kagent/trace-sinks`
`OtelTraceSink`, driven by `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` +
`OTEL_EXPORTER_OTLP_HEADERS`, authenticated by the Langfuse public key in
the OTLP `authorization` header). Trace **query** is never done. The
workbench's only job is to render a deterministic **deep-link** the user
clicks in their browser:

```
url = `${LANGFUSE_BASE_URL}/trace/${sha256(taskUID)[0..32]}`
```

The trace ID is the `sha256(runId)[0..32]` value the OtelTraceSink emits
(`packages/dto/src/map.ts:deriveTraceId`, mirrored from
`packages/trace-sinks/src/otel-sink.ts:traceIdFromRunId`) — **not** the
raw AgentTask UID. A link built from the UID 404s in Langfuse.

### Conclusion on the proposed "wire the langfuse creds secret in"

**No `kagent-llm-langfuse-creds` wiring is warranted on the workbench
Deployment.** The workbench never authenticates to Langfuse; adding
`LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` envFrom/secretKeyRef would
be dead env the code never reads. The chart has no plumbing for them by
design (`charts/kagent-workbench/templates/deployment.yaml` only emits
`LANGFUSE_BASE_URL` from `api.langfuseBaseUrl`; the one `secretKeyRef` in
that template is the unrelated gateway-admin token).

### The real bug, and the fix made

`api.langfuseBaseUrl` in the deployed values
(`k8s-kustomized/overlays/production/kagent/workbench-application.yaml`)
was set to the **in-cluster service URL**:

```
http://langfuse-web.langfuse-system.svc.cluster.local:3000
```

That URL is used **only** to build the browser deep-link — and a browser
cannot resolve cluster DNS. So every "View trace" link on a task detail
was dead on click. Fixed to the browser-reachable public ingress
(`overlays/production/langfuse/ingressroute.yaml` fronts the same
`langfuse-web` Service at `langfuse.example.com`, Tailscale subnet-routed):

```diff
- langfuseBaseUrl: 'http://langfuse-web.langfuse-system.svc.cluster.local:3000'
+ langfuseBaseUrl: 'https://langfuse.example.com'
```

This is a pure GitOps value change; ArgoCD redeploys the workbench with
the corrected env. No image rebuild needed.

### Two remaining INCONSISTENT trace-URL builders (kagent-repo code fix)

There are **three** trace-link construction sites and they disagree:

| Site | File | Builds | ID used | Path | Status |
|------|------|--------|---------|------|--------|
| Task detail | `dto/src/map.ts` `renderTraceUrl('langfuse',…)` (via `traceLink()`, consumed by `workbench-api/src/routes/tasks.ts`) | `{base}/trace/{sha256(uid)[0..32]}` | **derived** ✓ | `/trace/` (singular) ✓ | **canonical** |
| Review queue | `workbench-api/src/routes/review-queue.ts:811` | `` `${langfuseBaseUrl}/traces/${uid}` `` | **raw UID** ✗ | `/traces/` (plural) ✗ | **broken** |
| Architect "Try it live" | `operator/src/template-server.ts` (`_links.langfuse`) | bare root `https://langfuse.example.com`, no trace id | — ✗ | — ✗ | **broken** (owned by operator-fix agent) |

Recommended kagent-repo fix (could not be applied — kagent repo is
read-only in this session):

1. Export a single `langfuseTraceUrl(baseUrl, runId)` helper from
   `@kagent/dto` (thin wrapper over the existing private
   `renderTraceUrl('langfuse', …)`), so there is ONE builder.
2. `review-queue.ts:809-812` — replace
   `` `${langfuseBaseUrl}/traces/${uid}` `` with
   `langfuseTraceUrl(langfuseBaseUrl, uid)`. This fixes both the
   raw-UID-instead-of-derived-id bug and the `/traces/` vs `/trace/`
   path bug in one line, and unifies it with the task-detail builder.
3. `template-server.ts` `_links.langfuse` — route through the same
   helper (operator-fix agent is handling this).

### On `/trace/{id}` vs `/project/{projectId}/traces/{id}`

The coordinator asked whether Langfuse needs a project segment. The
homelab Langfuse is single-org / single-project (manual first-run setup
per `kagent/.../values-references/langfuse.yaml`), and the existing
canonical builder (`dto`) and the substrate sink (`trace-sinks`) both use
the project-agnostic `/trace/{id}` form, which Langfuse self-hosted
redirects to the project-scoped URL for an authenticated single-project
user. That form is therefore correct for this deployment **today**.
If/when a second Langfuse project is created, the builder will need a
`projectId` and the path becomes `/project/{projectId}/traces/{id}`; at
that point `langfuseTraceUrl` is the single place to thread it through,
and the workbench would need a new `api.langfuseProjectId` chart value
(the project id is NOT currently available to the workbench — another
reason to keep this as a follow-up rather than guess a value now).

---

## B. Tool registration — there is no ToolServer in this fork

### Is there a built-in/registered tool catalog the Architect should be constrained to?

**Yes — a fixed, code-defined registry of 9 built-in tools. There is no
`ToolServer` / `Tool` CRD in this fork at all** (this `kagent` is the
Knuteson agent-substrate, NOT `kagent.dev` the K8s-ops project; the CRD
group `kagent.example.com` has `Agent`, `AgentTask`, `AgentWorkflow`,
`AgentCapability`, `Tenant`, `Workspace`, `Schedule` — and no
ToolServer/Tool). Searched `packages/` and `examples/`: zero ToolServer
references.

An `Agent`'s tools are declared as a **free-form `tools: []string`**
array on `Agent.spec` (`operator/manifests/crds/agent.yaml:88-91`), with
**no admission-time referential validation** against any catalog. The
validation happens at **runtime, in the agent pod**:
`packages/agent-pod/src/builtin-tools.ts:resolveBuiltinTools()` looks
each name up in the registry built by `buildBuiltinToolRegistry()` and
**throws** on an unknown name:

```
unknown built-in tool "<name>" (known built-ins: …). Edit Agent.spec.tools
to drop the name, or extend packages/agent-pod/src/builtin-tools.ts to add it.
```

This is exactly the runtime failure seen in the Command Center activity
feed (`rc-pilot-bad-tool failed: runner threw: unknown built-in tool
"nonexistent_tool_for_testing"`).

### The 9 known built-in tools (authoritative)

Confirmed both from source and from the live runtime error string:

| Tool | Provider source | When wired |
|------|-----------------|-----------|
| `http_get` | `builtin-tools.ts buildBuiltinToolRegistry` | always |
| `rss_fetch` | `builtin-tools.ts` | always |
| `extract_text` | `builtin-tools.ts` | always |
| `write_artifact` | `builtin-tools.ts` | always (refuses unless artifact PVC env is set) |
| `get_my_context` | `builtin-tools.ts defineGetMyContext` (substrate) | always (runner-appended) |
| `spawn_child_task` | `builtin-tools-spawn.ts` (substrate) | when spawn is enabled |
| `wait_for_child_task` | `builtin-tools-wait.ts` (substrate) | when spawn is enabled |
| `wait_for_children_all` | `builtin-tools-wait.ts` (substrate) | when spawn is enabled |
| `ensure_agent_from_template` | `builtin-tools-template.ts` (substrate) | when enabled |

(There is also a `publish_event` tool and blackboard tools that are
conditionally wired via `externallyProvidedNames`; the runtime error's
"known built-ins" list above is the set present in a default rc-pilot
agent pod.)

**`kubectl` is NOT in the set.** It appears only in source comments. So
when the Architect drafts `tools: [kubectl, …]`, the resulting Agent
pod throws `unknown built-in tool "kubectl"` the moment that Agent runs —
the hallucinated tool is a hard runtime failure, not a no-op.

### What it would take to register a real `kubectl` / k8s ToolServer

There is no ToolServer abstraction to register against. To give agents a
real `kubectl`-style capability you would either:

- **(cheap, in-tree)** add a new in-process tool to
  `buildBuiltinToolRegistry()` in `builtin-tools.ts` (e.g. a narrowly
  scoped `k8s_get` / `k8s_describe` read tool using the pod's
  ServiceAccount + a kube client), gated behind an operator chart flag
  and an RBAC Role — same pattern as `http_get`'s allowlist gating. This
  is the substrate-appropriate path and stays inside the §11 bounds test
  (declared capability + bounded drain + auditable output).
- **(heavy, out-of-scope)** introduce a ToolServer/MCP CRD + the
  `mcp-tool-provider` (which already exists in `packages/mcp-tool-provider`)
  wired to an external `kubectl`/k8s MCP server. This is a real feature,
  not a wiring fix, and per the kagent CLAUDE.md a *consumer* concern.

**Recommendation: do NOT build a kubectl ToolServer** unless the user
explicitly wants agents to operate the cluster. The homelab governance
convention (Hermes pattern: smallest-egress, runaway killswitch) argues
against handing generated agents cluster-write tools by default.

### Should the Architect's drafting prompt be constrained to registered tools?

**Yes — this is the real fix for the "hallucinated tool" finding.** The
Architect (in `operator/src/template-server.ts`, owned by the
operator-fix agent) currently lets the LLM emit arbitrary tool strings.
It should be constrained two ways (belt-and-suspenders):

1. **Prompt-level**: inject the exact known-tool list (the 9 names above)
   into the drafting system prompt and instruct the model to ONLY emit
   tools from that set (or none).
2. **Validator-level (authoritative)**: after the draft, validate every
   `tools[]` entry against the known-tool names. Share a single source of
   truth — export the registry key set from
   `packages/agent-pod/src/builtin-tools.ts` (e.g.
   `export const BUILTIN_TOOL_NAMES = [...]`) and import it in
   `template-server.ts`. On an unknown name, either **drop it** (lenient)
   or **fail the draft** with a helpful message naming the allowed set —
   the same UX the runtime guard already gives, but at draft time instead
   of at first-run. Failing the draft is preferable: it surfaces the
   problem to the user in the Studio chat before an AgentTemplate with a
   landmine ever lands in `kagent-draft`.

This is a cheap, correct fix (constrain to the existing 9) that does not
require building any new tool infrastructure.
