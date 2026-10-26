# 🔧 Troubleshooting Guide

## Common Issues

### Service Access Issues

```bash
# Test service access (uses *.example.com domains via Traefik)
curl -I https://chat.example.com
curl -I https://ollama.example.com

# Check Traefik ingress
kubectl get ingress -A
kubectl logs -f deployment/traefik -n ingress-system
```

### ArgoCD Sync Issues

```bash
# Check application status
kubectl get applications -n argocd

# Force sync if needed
kubectl patch application homelab-apps -n argocd --type merge -p '{"operation":{"sync":{"prune":true}}}'

# Check ArgoCD server
kubectl logs -f deployment/argocd-server -n argocd
```

### Services Not Starting

```bash
# Check cluster status
kubectl get nodes
kubectl get pods -A

# Check specific service
kubectl describe pod <pod-name> -n <namespace>
kubectl logs <pod-name> -n <namespace>
```

### Ollama Not Working

```bash
# Check Jetson node
kubectl describe node jetson1

# Use manual fallback
./scripts/setup-jetson-ollama.sh deploy

# Test API directly
curl http://192.168.131.123:11434/api/tags
```

### Complete Reset

```bash
# Nuclear option - reset everything
./scripts/reset-complete-stack.sh
```

## Getting Help

1. **Run validation**: `./scripts/validate-iac.sh`
2. **Check logs**: `kubectl logs -f deployment/<service> -n <namespace>`
3. **Test connectivity**: `./scripts/test-dns.sh`

## Useful Commands

```bash
# Cluster management
kubectl get pods -A
kubectl get nodes -o wide
kubectl get services -A

# Service logs
kubectl logs -f deployment/ollama -n ai-services
kubectl logs -f deployment/openwebui -n ai-services
kubectl logs -f deployment/n8n -n automation

# DNS testing
ping chat.local
curl -k https://chat.local
curl -k https://n8n.local
```
