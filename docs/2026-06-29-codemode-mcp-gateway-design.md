# Code-Mode MCP Gateway + qwen-coder Worker — Design

**Date:** 2026-06-29
**Status:** Approved design, pre-implementation
**Author:** Chris Knuteson (with Claude)
**Location of record:** `new_localai/docs/`

---

## 1. Intent

Local coding agents (Claude Code, Codex, `pi`, opencode — whatever runs on Chris's
Mac) should be able to **offload scoped coding work to the homelab**: hand off a task,
have the cheap local Qwen model do the grunt editing against the Spark inference box,
and get a **diff back** to review/apply. Zero tokens/compute spent on the Mac for the
edit loop itself.

This generalizes beyond Qwen: the front door is a **code-mode gateway** that any local
agent connects to, behind which any number of MCP tool servers can be registered.
`qwen-coder` is the first one.

**Non-goals:** No cloud dependency (no Cloudflare, no tunnel — everything stays on the
homelab LAN). Not a kagent capability (kagent was evaluated and explicitly set aside;
this is a standalone hosted MCP service). No new management GUI (reuse the existing
`mcpo-control-panel`).

## 2. Background — what exists today

- **The thing being hosted:** `~/.codex/mcp/qwen-spark-coder/server.mjs`, a ~540-line
  hand-rolled stdio MCP server. Tools: `qwen_implement`, `qwen_repair`, `qwen_status`,
  `qwen_smoke_test`. Each takes an absolute `workspace` path and shells out to
  `<workspace>/scripts/qwen-worktree`, which runs the `pi` CLI agent editing a git
  worktree in place. Today it is launched **only by Codex** as a stdio child process on
  the Mac.
- **`pi`** = `@earendil-works/pi-coding-agent@0.80.2`, a published npm CLI. **Portable.**
  Config at `~/.pi/agent/` (`models.json`, `settings.json`, extensions). Per pi.dev
  containerization docs: `node:24-bookworm-slim` + `npm i -g`, config at
  `/root/.pi/agent`, workspace mounted at `/workspace`. No HTTP/server mode (TUI/CLI
  only) — so an MCP-over-HTTP layer must wrap it.
- **Spark inference:** `http://10.0.0.69:9090/v1` (llama-swap/vLLM), model
  `coder-fp8`. OpenAI-compatible. On the LAN, separate box from the K3s control plane
  (`elitemini`, `10.0.0.76`). Already reachable.
- **Reusable homelab assets:**
  - **K3s + ArgoCD** GitOps (`k8s-kustomized/`, `overlays/production`). Never imperative.
  - **Gitea** `git.example.com` (git hosting + container registry
    `git.example.com/homelab/<image>`).
  - **`mcpo`** (MCP→OpenAPI proxy) at `mcpo.example.com`, and
    **`mcpo-control-panel`** (`ghcr.io/chrisknu/mcpo-control-panel`) — a **web UI that
    manages the MCP-server registry**, at `gateway-admin.example.com`, data in hostPath
    `/opt/mcpo-control-panel-data`. **This is the GUI for adding MCP tools.**
  - Existing Node service conventions in `services/` (Express, Helmet/CORS/Morgan,
    non-root, readOnlyRootFilesystem, `/health`, Gitea registry with
    `--provenance=false --sbom=false`).

## 3. Architecture

Two local containers on K3s, plus the existing registry/GUI.

```
Local agents (Claude Code / Codex / pi / opencode on the Mac)
   │  MCP (Streamable HTTP) + Bearer.  ONE tool: run_code(ts)
   │  Tool description carries generated TS types for every registered MCP namespace.
   ▼
┌────────────────────────────────────────────────────────────┐
│  CODE-MODE GATEWAY            codemode.example.com          │
│  (new container, MCP server)                                │
│  - reads MCP-server registry (shared with mcpo)             │
│  - MCP-client to each backend; introspects tools/list       │
│  - schema → namespaced TS API + doc comments                │
│  - run_code: spawn locked Deno sandbox, inject `mcp` client │
│      (no fs / no env / net → internal RPC socket only)       │
│  - marshals sandbox calls → MCP calls to backends            │
│  - holds all backend tokens; sandbox never sees them         │
└───────────────┬────────────────────────────────────────────┘
                │ in-cluster MCP call (ClusterIP svc)
                ▼
┌────────────────────────────────────────────────────────────┐
│  qwen-coder WORKER           (ClusterIP only, no public host)│
│  (new container, MCP server)                                │
│  supergateway → server.mjs (unchanged tool logic)           │
│   → generalized runner → pi --provider spark --model coder  │
│  clone repo → git worktree → edit → return unified diff      │
└───────────────┬────────────────────────────────────────────┘
                │ OpenAI-compatible HTTP
                ▼
        Spark  http://10.0.0.69:9090/v1  (coder-fp8)

REGISTRY / GUI (existing, reused):
  mcpo-control-panel (gateway-admin.example.com) → manages the MCP-server list.
  Gateway consumes the same list. Add a server in the panel ⇒ appears in code-mode.
```

### 3.1 End-to-end flow (qwen offload)

1. A local agent calls the gateway's single `run_code` tool, passing TypeScript such as:
   *"`const d = await mcp.qwen.implement({repo, ref, instructions}); if (!d.ok) { for (let i=0;i<3;i++){ const r = await mcp.qwen.repair({...}); if (r.ok) break; } } return d.diff;`"*
2. Gateway runs that TS in a locked-down Deno sandbox. `mcp.qwen.*` are injected
   functions that RPC to the gateway supervisor.
3. Supervisor translates each call into an MCP `tools/call` to the **qwen-coder worker**.
4. Worker clones the repo to its PVC, `git worktree add`, runs `pi --provider spark
   --model coder-fp8` with the workspace-guard extension, captures the diff, returns it.
5. The TS returns the final diff; the gateway returns it as the `run_code` result.
6. The calling agent reviews/applies the diff locally. **The orchestration loop ran on
   the homelab, not the Mac.**

## 4. Component: qwen-coder worker

**Purpose:** Do the actual Qwen-on-Spark editing on a server-side checkout and return a
diff. Internal-only; reachable only from the gateway.

**Image** `git.example.com/homelab/qwen-coder`:
- Base `node:24-bookworm-slim`; install `git`, `bash`, `npm i -g
  @earendil-works/pi-coding-agent` and `supergateway`.
- Copy `server.mjs` in **unchanged** (its MCP/JSON-RPC logic is preserved).
- Bake `/root/.pi/agent/models.json` (Spark provider → `http://10.0.0.69:9090/v1`,
  `coder-fp8`) and `settings.json`.
- Bake a **generalized runner + `workspace-guard.ts`** into the image (see 4.2) so the
  worker works on *any* cloned repo and does not depend on the target repo shipping
  `scripts/qwen-worktree`.
- Entrypoint: `supergateway --stdio "node /app/server.mjs" --port 8080` → Streamable
  HTTP MCP.

**Tool contract change (4.1):** Tools take `repo` (git URL) + `ref` (branch/sha) +
`instructions` (and for repair, `command`/`failure`) **instead of** an absolute
`workspace` path. The worker:
- clones `repo@ref` into `/work/<taskId>` on a PVC, `git worktree add` an isolated
  branch,
- runs the generalized runner (Qwen edits via `read,edit,write` only, guarded),
- returns `{ ok, exitCode, diff (unified), changedFiles, stdout, stderr }`,
- optionally pushes `qwen/<ticket>` back to the origin when asked.
- Auth: mount **both** a Gitea deploy token and a GitHub token so either origin works.

**Generalized runner (4.2):** Port `scripts/qwen-worktree` into the image as
`/app/qwen-run`. Keep its guarantees: refuse to edit the main checkout (operate only in
an added worktree), enforce the workspace-guard extension, `--tools read,edit,write`,
`--thinking off --offline --no-extensions --extension workspace-guard.ts
--no-context-files --print`, system prompt jailing edits to the workspace. After the run,
diff the worktree (`git diff`) to produce the returned patch.

**server.mjs adaptation:** The handler functions (`qwenImplement`, `qwenRepair`, etc.)
change from "resolve `workspace`" to "clone `repo@ref` → worktree → run → diff." The MCP
framing, tool schemas (input properties updated to `repo`/`ref`), and result shape stay
in the same file. `requireWorkspace` becomes `prepareWorktree`.

**Deploy:** Deployment (1 replica, non-root, readOnlyRootFilesystem except `/work` PVC
and pi cache), ClusterIP Service on 8080, PVC for `/work`, sealed-secret for git tokens,
**NetworkPolicy** (egress: Spark + git origin + DNS only — see §7). **No IngressRoute** —
not publicly reachable.

## 5. Component: code-mode gateway

**Purpose:** Present one `run_code` tool to local agents, turn registered MCP servers
into a TypeScript API, and run the model's generated TS in a local sandbox with the MCP
backends bound in. Needs **no LLM of its own** — the calling agent is the model.

**Surface:**
- An MCP server (Streamable HTTP, bearer auth) exposing a single tool `run_code({
  typescript: string })`. The tool description embeds the generated `.d.ts` for all
  enabled namespaces (e.g. `mcp.qwen.implement(input): Promise<...>`), with doc comments
  derived from each backend tool's JSON schema.
- Optional `list_apis` helper tool returning the current TS type surface (so agents can
  refresh types without a full description reload).

**Registry (shared with mcpo):**
- The set of backend MCP servers is the **same registry `mcpo-control-panel` manages**.
- Build-time task: determine the panel's on-disk format (`/opt/mcpo-control-panel-data`)
  and read it directly. **Fallback** if its format is not cleanly consumable: introduce
  a shared `mcpServers` ConfigMap (Claude-style `{name → {transport,url/command,auth}}`)
  that both the panel writes and the gateway reads. Either way: **one registry, one GUI,
  adding a server in the panel surfaces it in code-mode.**
- Each entry → the gateway opens an MCP client, calls `tools/list`, and codegens a
  namespaced TS module. Hot-reload on registry change (watch the file/ConfigMap).

**Sandbox (the local replacement for Cloudflare's isolate):**
- **Deno subprocess per `run_code` call**, launched with least privilege: `--deny-read
  --deny-write --deny-env --deny-ffi --deny-run`, and `--allow-net` scoped **only** to
  the gateway's internal RPC endpoint (loopback host:port or unix socket). No general
  network, no filesystem, no env.
- A tiny injected client exposes `globalThis.mcp.<namespace>.<tool>(input)` →
  JSON-RPC-over-loopback to the supervisor, which performs the real MCP `tools/call`
  against the backend (holding the token). Enforce wall-clock timeout, output-size cap,
  and memory limit on the subprocess.
- *Alternative considered:* `isolated-vm` (true per-call V8 isolates, closest to the
  blog). Rejected for v1: native-addon build friction; Deno's permission model is a
  simpler, robust local sandbox. Revisit if subprocess spawn latency matters.

**Deploy:** Deployment (1 replica), ClusterIP Service, Traefik IngressRoute at
`codemode.example.com` (add host to `example-tls` SAN list + `ingress-routes.yaml`),
sealed-secret for the gateway bearer token + per-backend tokens, **NetworkPolicy**
(egress: in-cluster backend MCP services + DNS only — see §7). Reuse existing Node
service security context.

## 6. Naming / ingress

| Host | Role | Visibility |
| --- | --- | --- |
| `codemode.example.com` | **Code-mode gateway** — the single MCP entrypoint agents connect to | LAN/ingress, bearer |
| (none) `qwen-coder` svc | Worker — Qwen/pi/Spark editing | ClusterIP only |
| `gateway-admin.example.com` | **Existing** `mcpo-control-panel` — add/manage MCP servers | existing |
| `mcpo.example.com` | **Existing** mcpo OpenAPI mode | existing |

`mcp.example.com` is already reserved in the TLS SANs; we claim the unused
`codemode.example.com` rather than contend for it. **Verify** with `kubectl get
ingressroute -A` before committing the host.

## 7. Security & isolation

- **Worker** is never publicly reachable; only the gateway's ClusterIP can call it.
- **Gateway** requires a bearer token at the ingress; the model's generated code runs in
  a no-fs/no-env/no-arbitrary-net Deno sandbox and can reach **only** the bound MCP RPC.
- **Tokens** (git deploy tokens, backend MCP tokens, Spark — currently `dummy-key`) live
  in sealed-secrets and in the supervisor; **the sandbox/model never sees them**, matching
  the Code Mode security property.
- **Worktree jail** preserved from the original (`workspace-guard.ts` + main-checkout
  refusal) as defense-in-depth even though the worker container is already a boundary.
- **NetworkPolicy (homelab convention).** Per `new_localai/CLAUDE.md` ("no cloud egress
  by accident", post-paperclip rule), both new pods ship a NetworkPolicy. The **worker**
  egress allowlist is exactly: Spark (`10.0.0.69:9090`), the git origin(s) it clones
  from (Gitea in-cluster / `git.example.com`, and GitHub only if a target repo lives
  there), and DNS — nothing else. The **gateway** egress is the worker's ClusterIP plus
  any in-cluster backend MCP services; the Deno sandbox already has `--allow-net` scoped
  to the loopback RPC socket only, so the NetworkPolicy is the outer ring of the same
  containment. No cloud LLM endpoints are reachable from either pod.

## 8. Deployment (GitOps)

- New kustomize bases under `k8s-kustomized/base/ai-services/`: `qwen-coder.yaml`,
  `codemode-gateway.yaml` (Deployment + Service + PVC), wired into the `ai-services`
  kustomization and the production overlay; IngressRoute + TLS SAN for the gateway.
- Images built for `linux/amd64 --provenance=false --sbom=false`, pushed to
  `git.example.com/homelab/`, pulled with `gitea-registry-secret`.
- Verify via Job manifests / ArgoCD sync — no imperative `kubectl apply`.

## 9. Phasing

1. **Worker, standalone & testable.** Build the qwen-coder image; adapt `server.mjs` to
   `repo`/`ref` + diff return; generalized runner; deploy ClusterIP. Test by port-forward
   + a raw MCP `tools/call` that implements a trivial change in a Gitea test repo and
   returns a diff.
2. **Gateway core.** `run_code` + Deno sandbox + schema→TS codegen, with qwen-coder as
   the single hardcoded backend. Deploy at `codemode.example.com`. Test the
   implement→repair loop as one `run_code` submission.
3. **Registry integration.** Wire the gateway to the shared mcpo registry (or the
   fallback ConfigMap). Confirm: add an MCP server in `mcpo-control-panel` ⇒ new
   `namespace.*` appears in the gateway's TS surface.
4. **Client wiring.** Document the one MCP entry each local agent adds
   (`codemode.example.com` + bearer) for Claude Code, Codex, pi, opencode.

## 10. Known limitations / v2

- **Committed state only.** Clone-from-git means the worker sees committed state, not the
  Mac's uncommitted buffer. Fine for scoped implement/repair offloads.
  **Decision (2026-06-30): deferred, not built.** Accepting a `basePatch` to reproduce dirty
  state is a real feature but has **no consumer yet** — nothing currently passes an uncommitted
  buffer to the worker. Building it now is speculative (YAGNI). **Trigger to implement:** a
  caller (a local agent via the code-mode gateway, or a wrapper) that needs to offload
  uncommitted local changes. Implementation when triggered: optional `basePatch` input →
  `git apply` in the worktree after `prepareWorktree`, before `runQwen`. Small (~1 task).
- **Spark availability.** If Spark (`10.0.0.69:9090`) is down the worker fails fast;
  surface a clear error through the diff/result.
- **Deno spawn latency.** Acceptable for coding offloads (seconds-to-minutes tasks). Move
  to `isolated-vm` only if it becomes a bottleneck.

## 10.1 Alternatives considered

- **omnigent** (`github.com/omnigent-ai/omnigent`, Apache-2.0, alpha) — a meta-harness /
  agent-orchestration layer that already does much of the *end goal*: its "Polly" example
  agent delegates coding to sub-agents (Claude Code / Codex / **pi**) in **parallel git
  worktrees** and returns results, with a policy engine (spend caps, approval gates, tool
  limits), LAN-only self-hosting, OpenAI-compatible backends (so Spark slots in), and MCP
  servers as a tool type. Evaluated 2026-06-29 and **set aside** for this build. Why custom:
  (1) the distinctive capability we want is the **Code Mode `run_code` pattern** (MCP→TS API,
  single tool, sandboxed TS with MCP bound via RPC), which omnigent does not implement;
  (2) it's **alpha** and a **Python 3.12/uv** service, vs. our all-Node + kustomize stack and
  full control; (3) governance/worktree/diff behavior we need is small enough to own directly.
  Revisit if the custom gateway's maintenance cost outgrows its benefit, or if a code-mode
  tool could simply be registered *into* omnigent instead.

## 11. Open items to confirm at build time

1. Exact on-disk format of `mcpo-control-panel` data (`/opt/mcpo-control-panel-data`) —
   read directly vs. shared-ConfigMap fallback.
2. `codemode.example.com` is free (`kubectl get ingressroute -A`).
3. `supergateway` Streamable-HTTP flag/behavior vs. the MCP clients in use (Claude Code,
   Codex, pi, opencode) — confirm each speaks Streamable HTTP, else add the SSE shim.
4. Which git origin(s) the target repos actually live in (Gitea, GitHub, or both) — mount
   the matching token(s).
5. Spark auth: keep `dummy-key` or set a real key on llama-swap.
