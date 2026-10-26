# qwen-coder Worker — Hosting Plan (host the harness; don't rebuild it)

> Execution: delegate steps to Codex via `delegating-to-codex`; orchestrator reviews diffs before commit.

**Division of labor (two parallel tasks):**
- **Harness task (in `frontend-cag` / `~/.codex/mcp/qwen-spark-coder/server.mjs`) — NOT this repo.** Owns the MCP server, tool contract, worktree isolation + main-checkout refusal, guarded tools (read/edit/write/grep/module_report/read_symbol/lsp_diagnostics/lsp_navigation/ast_grep_search), deterministic verification (prettier/`git diff --check`/test/build/parent-contamination), repair loop, JSON traces, eval suite.
- **THIS plan (new_localai) — hosting only.** Containerize the harness, expose it over HTTP, wire it to Spark in-cluster, deploy on K3s, govern it. Do **not** modify `server.mjs` or the tool logic — vendor it.

**Goal:** Run the harness on the homelab against the $4000 Spark so Codex/Claude get autonomous Qwen implementation with **zero Mac inference budget**.

## Hard constraints (from repo + harness spec)

- Model: **Qwen3-Coder-Next-NVFP4**, llama-swap alias **`coder`** (never `coder-fp8`).
- Spark in-cluster: `http://spark-llamaswap.ai-services.svc.cluster.local:9090/v1`; Endpoint `100.64.0.69:9090`, reachable **only from the control-plane node** → `nodeSelector: node-type: control-plane`. ~18s cold start, no backend probe.
- GitOps only; image `--platform linux/amd64 --provenance=false --sbom=false` → `git.example.com/homelab/qwen-coder`, pull via `gitea-registry-secret`.
- Governance: NetworkPolicy egress allowlist + resource ceiling + PVC (copy `hermes-agent.yaml`). ClusterIP only, no IngressRoute.
- **The container must ship the harness's deterministic toolchain** (see step 2) — the harness assumes these binaries exist.

## Blocked-on

Vendoring waits until the harness task **freezes** (don't copy a moving target). Steps 2–4 below are independent of `server.mjs` internals — they run `node server.mjs` behind supergateway regardless — so they can be built in parallel; step 1 (vendor) and step 5 (acceptance) need the frozen harness.

## Steps

- [ ] **1. Vendor the frozen harness** (after the harness task lands). Copy `server.mjs` + its `.pi` extensions/runner + `agent/models.json` (Spark provider, `baseUrl=${SPARK_BASE_URL}`, model `coder`) into `services/qwen-coder/`. No logic edits.

- [ ] **2. Container toolchain + transport.** `Dockerfile` (`node:24-bookworm-slim`) installs: `git bash ca-certificates gettext-base ripgrep`, `ast-grep` (sg), a TS language server (`typescript typescript-language-server`) for the LSP tools, `prettier`, and `npm i -g @earendil-works/pi-coding-agent@0.80.2 supergateway`. Entrypoint renders `models.json` via `envsubst`, then `exec supergateway --stdio "node /app/server.mjs" --outputTransport streamableHttp --port 8080`. Build + local `tools/list` smoke test.

- [ ] **3. Deploy (copy hermes pattern).** `k8s-kustomized/base/ai-services/qwen-coder.yaml`: ConfigMap (`SPARK_BASE_URL`, `QWEN_SPARK_MODEL=coder`, worktree/trace dirs), PVC (worktrees + traces, local-path RWO), Deployment (`nodeSelector: node-type: control-plane`, securityContext 10000, resource ceiling, `gitea-registry-secret`, readiness tcp:8080), ClusterIP Service :8080, NetworkPolicy egress (DNS, `100.64.0.69:9090`, Gitea host, public :443). Wire into `kustomization.yaml`. `kubectl kustomize overlays/production` to validate.

- [ ] **4. Secrets.** Sealed `qwen-coder-secrets` (git token, optional Spark key) via `secrets.example.com`.

- [ ] **5. Acceptance.** Branch, commit, push → ArgoCD sync. Port-forward `svc/qwen-coder`; `qwen_smoke_test` (first-token from `coder`) then `qwen_implement` on a small Gitea repo; assert a clean diff + trace returns and the parent-contamination check is clean. **Done = autonomous Qwen edit on Spark, diff+trace back, zero Mac inference.**

## Open items
1. supergateway streamable-HTTP flag/path. 2. Exact harness toolchain deps (LSP/AST binaries) — confirm against the frozen harness. 3. Gitea host IP for egress. 4. Trace persistence location (PVC dir vs sidecar). 5. base kustomization securityContext patch interaction. 6. git origin(s) → token(s).
