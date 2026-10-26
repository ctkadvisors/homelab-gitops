# Agent Memory Attribution And Claude Wiring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make agent-memory writes attributable to a specific recorder and source, expose that attribution in recall, and connect Claude Code to the deployed MCP endpoint.

**Architecture:** Keep the existing OpenSearch-backed Streamable HTTP MCP server. Add attribution fields to normalized memory documents, tool schemas, recall output, and the OpenSearch mapping, then deploy the MCP server with a new immutable image tag through GitOps.

**Tech Stack:** Node.js ESM, MCP TypeScript SDK, OpenSearch 3.7, Kustomize, Argo CD, Claude Code MCP HTTP config.

---

### Task 1: Attribution Contract

**Files:**
- Modify: `services/agent-memory-mcp/src/memory.mjs`
- Modify: `services/agent-memory-mcp/src/tools.mjs`
- Modify: `services/agent-memory-mcp/server.mjs`
- Test: `services/agent-memory-mcp/test/memory.test.mjs`
- Test: `services/agent-memory-mcp/test/tools.test.mjs`

- [ ] Write failing tests proving `agent_memory_remember` requires `recorded_by`, `source_kind`, `source_ref`, and `source_actor`.
- [ ] Write failing tests proving recall results include `recorded_by`, `source_kind`, `source_ref`, and `source_actor`.
- [ ] Update `buildMemoryDocument()` to require and normalize those fields.
- [ ] Update `rankRecallHits()` and `formatRecallResult()` to preserve and show attribution.
- [ ] Update MCP input schemas and tool descriptions so Claude and Codex see attribution as required.
- [ ] Run `npm test` in `services/agent-memory-mcp`.

### Task 2: GitOps Mapping And Image Tag

**Files:**
- Modify: `k8s-kustomized/base/search/opensearch-init-job.yaml`
- Modify: `k8s-kustomized/base/search/agent-memory-mcp.yaml`
- Modify: `services/agent-memory-mcp/package.json`
- Modify: `services/agent-memory-mcp/README.md`

- [ ] Add attribution fields to the `agent-memory` OpenSearch mapping as keywords.
- [ ] Bump the service version and deployment image tag to `0.1.1`.
- [ ] Validate with `kubectl kustomize k8s-kustomized/base/search`.
- [ ] Build and push `git.example.com/homelab/agent-memory-mcp:0.1.1` with `--platform linux/amd64 --provenance=false --sbom=false`.

### Task 3: Deploy And Verify

**Files:**
- Modify external user config through Claude CLI or `~/.claude.json`.

- [ ] Commit and push GitOps changes to `origin/main`.
- [ ] Watch Argo apply the updated deployment.
- [ ] Verify pod image is `git.example.com/homelab/agent-memory-mcp:0.1.1`.
- [ ] Verify MCP health, attributed write, attributed recall, and 768-dimensional embedding.
- [ ] Add Claude Code project-scoped `agent-memory` MCP pointing to `https://agent-memory.example.com/mcp` with the bearer token.
- [ ] Verify `claude mcp get agent-memory` can see the server, or if Claude health checks hang, verify the config entry directly and note the CLI limitation.
