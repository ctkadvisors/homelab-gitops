# OpenSearch Agent Memory Runbook

## Node Prep

Target node:

- Hostname label: `kubernetes.io/hostname=elitemini2`
- LAN IP: `10.0.0.58` (static since 2026-08-12; `config/network.yaml` is the source of truth)
- Data path: `/opt/opensearch-data`

OpenSearch needs `vm.max_map_count=262144`. The Deployment includes a privileged init container that sets it before startup, but the durable host setting should also be applied on `elitemini2`:

```bash
ssh elitemini2 'echo vm.max_map_count=262144 | sudo tee /etc/sysctl.d/99-opensearch.conf && sudo sysctl --system'
ssh elitemini2 'sudo mkdir -p /opt/opensearch-data && sudo chown -R 1000:1000 /opt/opensearch-data'
```

Also fix the stale K3s external IP if it still points at `10.0.0.74`.

## Build MCP Image

```bash
cd services/agent-memory-mcp
npm install
npm test
docker build --platform linux/amd64 --provenance=false --sbom=false \
  -t git.example.com/homelab/agent-memory-mcp:0.1.0 .
docker push git.example.com/homelab/agent-memory-mcp:0.1.0
```

## Validate GitOps Render

```bash
kubectl kustomize k8s-kustomized/base/search
kubectl kustomize k8s-kustomized/overlays/production
```

## Rollout Checks

```bash
kubectl get pods -n search -o wide
kubectl logs -n search job/opensearch-agent-memory-init
kubectl get ingressroute -n search
```

Expected endpoints:

- `https://search.example.com`
- `https://agent-memory.example.com/healthz`
- `https://agent-memory.example.com/mcp`

The MCP endpoint uses `MCP_BEARER_TOKEN` from `opensearch-credentials`; configure Claude/Codex HTTP MCP clients with an `Authorization: Bearer ...` header.

## Reseal Credentials

When the Kubernetes API is reachable again:

```bash
kubeseal --fetch-cert \
  --controller-name=sealed-secrets-controller \
  --controller-namespace=sealed-secrets \
  > /tmp/sealed-secrets.pem
kubectl create secret generic opensearch-credentials \
  --namespace search \
  --from-literal=admin-username=admin \
  --from-literal=admin-password='<new-password>' \
  --from-literal=mcp-bearer-token='<new-token>' \
  --dry-run=client -o yaml > /tmp/opensearch-credentials.yaml
kubeseal --cert /tmp/sealed-secrets.pem --format yaml \
  < /tmp/opensearch-credentials.yaml \
  > k8s-kustomized/base/search/opensearch-secret-sealed.yaml
```

The search base should reference `opensearch-secret-sealed.yaml`; do not commit the generated plaintext secret.
