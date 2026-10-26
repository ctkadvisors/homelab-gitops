# Code-Mode Gateway — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development (or executing-plans). Steps use `- [ ]`.
>
> **Execution for THIS project:** delegate edit loops to Codex via the `delegating-to-codex` skill; orchestrator (Claude) reviews each diff before commit. Spec: `docs/2026-06-29-codemode-mcp-gateway-design.md` §5. The qwen-coder worker (the first backend) is already deployed — see `services/qwen-coder/`.

**Goal:** A local MCP server exposing a single `run_code(typescript)` tool. It turns registered backend MCP servers into a typed TS API, runs the model's submitted TypeScript in a locked-down Deno sandbox with `globalThis.mcp.<ns>.<tool>(input)` bound by RPC to the supervisor, and returns the script's result — so an agent can orchestrate multi-step tool flows (e.g. an implement→repair loop against qwen-coder) in one call, on the homelab, with backend tokens never visible to the sandboxed code.

**Architecture:** Node + `@modelcontextprotocol/sdk` server (native Streamable HTTP, per-request transport — same pattern as qwen-coder, NO supergateway). Per `run_code` call it spawns a `deno run` subprocess with least privilege; the sandbox's injected `mcp` client JSON-RPCs over a loopback socket to the supervisor, which performs the real MCP `tools/call` against the backend (holding any auth). v1 backend set = qwen-coder only (hardcoded via env), then read the shared mcpo registry.

**Tech Stack:** Node 24 (ESM, `node:test`), `@modelcontextprotocol/sdk`, Deno (sandbox), K3s/ArgoCD, Traefik IngressRoute, Sealed-Secrets.

## Global Constraints

- GitOps only; image `--platform linux/amd64 --provenance=false --sbom=false` → `git.example.com/homelab/codemode-gateway`, pull via `gitea-registry-secret`.
- **Build traps (cost us cycles on the worker):** buildx on the cross-platform path needs `--load` or the tag silently stays stale — always verify *inside* the image, never trust the build exit code. Don't ship a lockfile generated against an offline npx cache (it references `_npx` paths and breaks clean `npm install`); dockerignore `package-lock.json` or regenerate it online.
- **MCP transport:** native Streamable HTTP via the SDK on `/mcp:8080`, **fresh Server+transport per request** (a shared singleton 500s — proven on the worker).
- Governance (post-paperclip): NetworkPolicy egress allowlist + resource ceiling. ClusterIP + bearer-gated IngressRoute.
- Tokens (backend bearer, etc.) live in the supervisor/sealed-secrets; **the Deno sandbox never sees them** — this is the core security property.
- `codemode.example.com` for the public host (verify free: `ssh elitemini 'kubectl get ingressroute -A'`). `mcp.example.com` is already reserved.

## File Structure

```
services/codemode-gateway/
  server.mjs            # MCP server: run_code tool + per-request transport
  registry.mjs          # backend MCP server list (env/ConfigMap) -> MCP clients
  codegen.mjs           # tools/list JSON schema -> namespaced .d.ts string
  sandbox.mjs           # spawn deno, wire loopback RPC <-> supervisor MCP calls
  sandbox-runtime.ts    # injected into the sandbox: builds globalThis.mcp.* from RPC
  package.json
  test/{codegen,sandbox,run-code}.test.mjs
  Dockerfile            # node:24 + deno
  docker-entrypoint.sh
  .dockerignore
  README.md
k8s-kustomized/base/ai-services/codemode-gateway.yaml   # Deployment+Service+NetworkPolicy+IngressRoute
```

---

## Phase 1 — Gateway core (run_code + Deno sandbox + qwen-coder hardcoded)

### Task 1: Scaffold + native MCP server with a stub `run_code`

**Files:** create `services/codemode-gateway/{package.json,server.mjs}`, `test/server.test.mjs`.

**Interfaces:** Produces an MCP server (Streamable HTTP `/mcp:8080`) exposing one tool `run_code({ typescript: string })`. Copy the worker's per-request transport pattern (`buildServer()` in the `/mcp` handler; `StreamableHTTPServerTransport({sessionIdGenerator: undefined})`; listener guarded to entrypoint-only).

- [ ] **Step 1: failing test** — spawn `node server.mjs` on a port, POST `tools/list`, assert one tool `run_code` with a `typescript` string param. (Model on worker's `test/run-diff` harness for HTTP framing.)
- [ ] **Step 2:** run → FAIL (no server).
- [ ] **Step 3:** implement scaffold + `run_code` handler that, for now, returns `{ content:[{type:'text', text:'stub'}] }`.
- [ ] **Step 4:** run → PASS.
- [ ] **Step 5:** commit `feat(codemode): scaffold gateway with native MCP run_code stub`.

### Task 2: schema → TS codegen

**Files:** create `codegen.mjs`, `test/codegen.test.mjs`.

**Interfaces:** `tsForTools(namespace, tools) -> string` — given a backend's `tools/list` array, emit a `.d.ts` block: `declare namespace mcp.<ns> { function <tool>(input: <TS from inputSchema>): Promise<unknown>; }` with the tool `description` as a doc comment. JSON Schema → TS: objects→interfaces, required vs optional, string/number/boolean/array, fallback `unknown`.

- [ ] **Step 1: failing test** — feed the qwen-coder `tools/list` (vendor a captured fixture) into `tsForTools('qwen', tools)`; assert output contains `function qwen_implement(input: { repo: string; instructions: string; ref?: string; ... }): Promise<unknown>` and the doc comment.
- [ ] **Step 2:** run → FAIL.
- [ ] **Step 3:** implement `tsForTools` + a `jsonSchemaToTs` helper.
- [ ] **Step 4:** run → PASS.
- [ ] **Step 5:** commit `feat(codemode): JSON-schema-to-TS codegen for backend tools`.

### Task 3: backend registry + MCP client (qwen-coder hardcoded)

**Files:** create `registry.mjs`, `test/registry.test.mjs`.

**Interfaces:** `loadBackends() -> [{ namespace, url }]` from env `CODEMODE_BACKENDS` (JSON: `[{"namespace":"qwen","url":"http://qwen-coder.ai-services.svc.cluster.local:8080/mcp"}]`). `mcpClient(url)` → connect via SDK `Client` + `StreamableHTTPClientTransport`; expose `listTools()` and `callTool(name, args)`. Produces: the supervisor's authoritative path to backends (holds any tokens; the sandbox never gets them).

- [ ] **Step 1: failing test** — point `mcpClient` at a tiny in-test MCP stub server, assert `listTools()` returns its tools and `callTool` round-trips.
- [ ] **Step 2:** run → FAIL.
- [ ] **Step 3:** implement registry + client.
- [ ] **Step 4:** run → PASS.
- [ ] **Step 5:** commit `feat(codemode): backend registry + MCP client (qwen-coder via env)`.

### Task 4: Deno sandbox + loopback RPC bridge

**Files:** create `sandbox.mjs`, `sandbox-runtime.ts`, `test/sandbox.test.mjs`.

**Interfaces:** `runInSandbox(tsSource, { rpcCall, timeoutMs, maxOutputBytes }) -> { result, logs }`.
- Supervisor opens a loopback HTTP/JSON-RPC endpoint on `127.0.0.1:<ephemeral>` that accepts `{ns, tool, input}` and calls `rpcCall(ns, tool, input)` → backend MCP `callTool`.
- Spawn `deno run --no-prompt --deny-read --deny-write --deny-env --deny-ffi --deny-run --allow-net=127.0.0.1:<port>` running a wrapper that: defines `globalThis.mcp` from `sandbox-runtime.ts` (each `mcp.<ns>.<tool>(input)` POSTs to the loopback endpoint), then `eval`/imports the user `tsSource`, captures its returned value + console logs, prints a JSON result line.
- Enforce wall-clock `timeoutMs` (kill subprocess) and `maxOutputBytes`.

- [ ] **Step 1: failing test** — `runInSandbox('return await mcp.qwen.ping({x:1})', {rpcCall: async(ns,t,i)=>({echoed:i})})` asserts result `{echoed:{x:1}}`; a second test asserts `--deny-write` blocks `Deno.writeTextFile` (script error surfaced, supervisor unharmed); a third asserts timeout kills a `while(true){}`.
- [ ] **Step 2:** run → FAIL (needs Deno on PATH; CI/dev must have it).
- [ ] **Step 3:** implement bridge + runtime + perms.
- [ ] **Step 4:** run → PASS.
- [ ] **Step 5:** commit `feat(codemode): Deno sandbox + loopback MCP RPC bridge`.

### Task 5: wire run_code end-to-end

**Files:** modify `server.mjs`; create `test/run-code.test.mjs`.

**Interfaces:** `run_code` handler = load backends → for each `listTools` → `tsForTools` (cache; refresh on registry change) → set the tool's description to the concatenated `.d.ts` (+ usage note) → on call, `runInSandbox(typescript, { rpcCall: (ns,tool,input)=>callTool(backend, tool, input) })` → return `{content:[{type:'text', text: JSON.stringify(result)}]}`. Add optional `list_apis` tool returning the current `.d.ts`.

- [ ] **Step 1: failing test** — against an in-test stub backend, submit `const r = await mcp.qwen.qwen_status({repo:'x'}); return r;` and assert the stub's response flows back through `run_code`.
- [ ] **Step 2–4:** RED → implement → GREEN.
- [ ] **Step 5:** commit `feat(codemode): wire run_code (codegen + sandbox + backend RPC)`.

### Task 6: containerize (Node + Deno) + deploy

**Files:** create `Dockerfile`, `docker-entrypoint.sh`, `.dockerignore`, `k8s-kustomized/base/ai-services/codemode-gateway.yaml`; edit ai-services `kustomization.yaml`.

- **Dockerfile:** `node:24-bookworm-slim`; install Deno (copy from `denoland/deno:bin` stage or curl the release pinned by version + checksum); `COPY package*.json` + `npm install --omit=dev`; COPY source; entrypoint `node server.mjs`.
- **Manifest (copy hermes/qwen-coder governance):** Deployment (resource ceiling, securityContext, `gitea-registry-secret`, readiness tcp:8080, env `CODEMODE_BACKENDS` + `secretRef` codemode-gateway-secrets for the gateway bearer), ClusterIP Service :8080, **NetworkPolicy** egress = DNS + qwen-coder pod:8080 only (the sandbox's `--allow-net` is loopback-only, NetworkPolicy is the outer ring), **Traefik IngressRoute** `codemode.example.com` with a bearer-check middleware + add the host to `example-tls` SAN. No control-plane pin needed (doesn't call Spark directly).
- [ ] Build (`--load`), verify supergateway-free / deno present / `tools/list` over `/mcp` **inside the image**, push.
- [ ] `kubectl kustomize overlays/production` renders; sealed `codemode-gateway-secrets`; commit + push → ArgoCD.
- [ ] **Acceptance:** from a tunnel, `run_code` submitting an implement→repair loop against qwen-coder returns the final diff — orchestration ran on the homelab.
- [ ] commit `feat(codemode): deploy gateway (ClusterIP, bearer IngressRoute, governed)`.

## Phase 2 — Shared registry integration

- [ ] Replace the hardcoded `CODEMODE_BACKENDS` with the registry `mcpo-control-panel` manages (`/opt/mcpo-control-panel-data` format — confirm at build; fallback: a shared `mcpServers` ConfigMap both write/read). Hot-reload codegen on change. **Acceptance:** add a server in the panel ⇒ a new `mcp.<ns>.*` appears in `list_apis`.

## Phase 3 — Client wiring

- [ ] Document the single MCP entry each local agent adds (`codemode.example.com` + bearer) for Claude Code / Codex / pi / opencode, plus the durable-access note (this is the gateway that replaces the worker's ad-hoc SSH tunnel).

## Self-Review

- Spec §5 coverage: run_code ✓(T1,5), registry ✓(T3,P2), codegen ✓(T2), Deno sandbox least-priv ✓(T4), token isolation ✓(T4 supervisor-holds), no-LLM-of-its-own ✓ (caller is the model), ingress/bearer ✓(T6), list_apis ✓(T5). 
- Decisions baked from worker build: native HTTP not supergateway; per-request transport; buildx `--load`; lockfile/dockerignore caution.
- Open items (confirm at build): Deno install method/version pin; mcpo on-disk registry format (P2); `codemode.example.com` free; bearer middleware wiring in Traefik; sandbox result protocol (stdout JSON line vs side channel).
