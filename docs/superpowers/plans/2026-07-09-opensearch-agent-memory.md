# OpenSearch Agent Memory Implementation Plan

> **Status:** Implemented in `feature/opensearch-agent-memory`; pending image build, push, commit, and Argo sync.

## Goal

Deploy OpenSearch, OpenSearch Dashboards, and an OpenSearch-backed MCP service for persistent local agent memory in the homelab stack using the existing Kustomize/ArgoCD flow.

## Decisions

- Use OpenSearch instead of Elastic for the first implementation.
- Keep OpenSearch API internal-only as a ClusterIP service.
- Expose Dashboards at `search.example.com`.
- Expose MCP at `agent-memory.example.com/mcp`.
- Pin OpenSearch and OpenSearch Dashboards to `3.7.0`.
- Pin the MCP image to `git.example.com/homelab/agent-memory-mcp:0.1.0`.
- Pin the stack to `elitemini2` by hostname label.
- Use `/opt/opensearch-data` hostPath on `elitemini2`.

## Files

- `k8s-kustomized/base/search/`
- `services/agent-memory-mcp/`
- `docs/runbooks/opensearch-agent-memory.md`
- `config/network.yaml`
- `k8s-kustomized/base/kustomization.yaml`
- `k8s-kustomized/overlays/production/base-without-monitoring/kustomization.yaml`

## Rollout

1. Verify `elitemini2` host prep:
   - `vm.max_map_count=262144`
   - `/opt/opensearch-data` exists and is writable by the OpenSearch container.
   - K3s node external IP is corrected from the stale `.74` value to `10.0.0.66`.
2. Build and push `services/agent-memory-mcp` image.
3. Run local verification:
   - `npm test` in `services/agent-memory-mcp`
   - `kubectl kustomize k8s-kustomized/base/search`
   - `kubectl kustomize k8s-kustomized/overlays/production`
4. Commit and push through GitOps.
5. Let ArgoCD sync `homelab-apps`.
6. Verify:
   - OpenSearch pod ready.
   - Dashboards reachable at `https://search.example.com`.
   - MCP health reachable at `https://agent-memory.example.com/healthz`.
   - MCP tool `agent_memory_health` succeeds.

## Known Follow-Ups

- The control-plane API at `10.0.0.76:6443` refused connections during implementation, so live Argo/Kubernetes sync verification is blocked until that is restored.
- The OpenSearch credential is currently a Kubernetes Secret manifest to match existing repo practice under `base/database` and `base/ai-services`. Reseal it with SealedSecrets once the cluster API is reachable.
- The model bootstrap job attempts to register `huggingface/sentence-transformers/all-distilroberta-v1`. If model download is blocked, lexical recall still works and the job exits successfully after creating indices.
