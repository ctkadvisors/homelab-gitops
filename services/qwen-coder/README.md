# qwen-coder

Hosted MCP worker that offloads scoped coding tasks to **Qwen3-Coder-Next-NVFP4 on the
DGX Spark**. A caller hands it a git `repo` + `ref` + `instructions`; it clones into an
isolated worktree, lets the guarded `pi` agent edit against Spark, and returns a **unified
diff** — no inference budget spent on the caller's machine.

This hosts the existing local harness (`~/.codex/mcp/qwen-spark-coder`); it does not
reimplement the agent loop.

## Architecture

```
caller (Claude Code / Codex / pi)  --MCP Streamable HTTP /mcp:8080-->  server.mjs
  server.mjs: prepareWorktree(repo,ref) -> git clone --mirror + worktree add
            -> /app/qwen-run (pi --provider spark --model coder, guarded tools)
            -> git add -A && git diff --cached  -> return {diff, changedFiles, ...}
  pi -> Spark OpenAI-compatible endpoint (spark-llamaswap.ai-services.svc:9090/v1)
```

- **Transport:** native MCP Streamable HTTP via `@modelcontextprotocol/sdk` (no
  supergateway). **Stateless — a fresh `Server`+transport is built per request**
  (`buildServer()` in the `/mcp` handler). A shared singleton returns intermittent 500s;
  do not "optimize" it back to one instance.
- **Guard:** `workspace-guard.ts` jails read/edit/write to the worktree; tools are
  `read,edit,write,module_report,read_symbol,lsp_diagnostics,lsp_navigation,ast_grep_search`
  (the image ships `typescript-language-server`, `@ast-grep/cli`, `ripgrep`, `prettier`).
- **Input safety:** `repo`/`ref` are validated — leading-dash and git remote-helper
  transports (`ext::` RCE) rejected; `git clone` runs with `protocol.ext.allow=never` and `--`.

## Tools

| tool | inputs | returns |
| -- | -- | -- |
| `qwen_status` | repo, ref? | worktree + branch + git status |
| `qwen_implement` | repo, instructions, ref?, ticket?, verification? | diff, changedFiles, stdout |
| `qwen_repair` | repo, command, failure, ref?, instructions? | diff (after a fix attempt) |
| `qwen_smoke_test` | repo, mode=`relative-edit` | sentinel edit proof |

## Deploy

GitOps only. Image `git.example.com/homelab/qwen-coder:<tag>`, built
`--platform linux/amd64 --provenance=false --sbom=false`, pushed to Gitea, pulled via
`gitea-registry-secret`. Manifest: `k8s-kustomized/base/ai-services/qwen-coder.yaml`
(ClusterIP only, NetworkPolicy egress allowlist, resource ceiling, PVC at `/work`).

**Must run on the control-plane node** (`nodeSelector: node-type: control-plane`) — it is the
only node with Tailscale reach to the Spark. Runs as root (base kustomization securityContext
patch); entrypoint pins `HOME=/root` so `pi` finds `/root/.pi/agent/models.json`.

Bump the image tag in the manifest, commit, push to `main` → ArgoCD syncs.

## Reach it from a workstation

ClusterIP only by design. Tunnel through the control-plane node:

```bash
ssh -L 8771:localhost:18771 elitemini 'kubectl port-forward -n ai-services svc/qwen-coder 18771:8080'
claude mcp add --transport http --scope user qwen-coder http://localhost:8771/mcp
```

The tunnel is ephemeral; durable, authenticated access is the planned **code-mode gateway's**
job (see `docs/2026-06-29-codemode-mcp-gateway-design.md`).

## Local dev

```bash
npm install
npm test                 # node:test (worktree/diff/security)
PORT=8099 node server.mjs # serves /mcp locally (Spark unreachable off the homelab LAN)
```

## Known follow-ups

- **LSP/AST tooling on non-code repos:** the implement loop works on docs-only repos, but the
  added value / latency of the LSP tools on real TS projects vs. plain read/edit/write is not
  yet benchmarked. Consider gating the LSP toolset to repos that have a language server config.
- **Dirty-state offload:** the worker only sees committed state (clone from a ref). A future
  option: accept a base patch alongside the task to reproduce uncommitted local changes.
- **Code-mode gateway:** the generic `run_code` front door that would front this worker (and
  other MCP tools) and hold auth/tokens is still unbuilt.
