# 🚀 Quick Start - Local AI Infrastructure

## Prerequisites

- **EliteMini M4** (Control Plane) at `192.168.131.111`
- **EliteMini2** (High-Memory Compute Worker) at `192.168.131.209`
- **NVIDIA Jetson Orin Nano** (GPU Workers) at `192.168.131.123`, `192.168.131.163`
- **SSH access** to all devices with keys configured

## GitOps Deployment (Current Method)

The infrastructure uses ArgoCD for GitOps deployment:

```bash
# Infrastructure is automatically deployed via ArgoCD
# Source: k8s-kustomized/overlays/production
# Status: kubectl get applications -n argocd
```

## Access Services

Services are available via \*.example.com domains (requires Tailscale for off-network access):

- **🤖 OpenWebUI (Chat)**: https://chat.example.com
- **⚡ n8n (Automation)**: https://n8n.example.com
- **🧠 Ollama API**: https://ollama.example.com
- **📊 ArgoCD**: https://argo.example.com
- **📈 Grafana**: https://grafana.example.com

## Cluster Management

```bash
# Set kubeconfig
export KUBECONFIG=./kubeconfig

# Check cluster status
kubectl get nodes -o wide
kubectl get pods -A

# Check ArgoCD applications
kubectl get applications -n argocd
```

## Troubleshooting

Common issues and solutions:

```bash
# Check ArgoCD sync status
kubectl get applications -n argocd

# Restart stuck pods
kubectl rollout restart deployment/<name> -n <namespace>

# Check logs
kubectl logs -f deployment/ollama -n ai-services
```

## Next Steps

- **Complete Documentation**: [CLAUDE.md](./CLAUDE.md) - Single source of truth
- **Documentation Audit**: [DOCUMENTATION_AUDIT.md](./DOCUMENTATION_AUDIT.md) - Cleanup status
