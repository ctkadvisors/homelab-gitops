# GitOps Deployment Guide

This document describes the new GitOps-based deployment procedures for the Local AI Homelab infrastructure.

## Overview

The infrastructure has been transitioned from manual `kubectl apply` deployments to a GitOps approach using ArgoCD. This provides:

- **Declarative Configuration**: Infrastructure defined in Git
- **Automatic Synchronization**: Changes in Git automatically deployed
- **Self-Healing**: Cluster state automatically corrects drift
- **Audit Trail**: Complete history of changes in Git
- **Rollback Capability**: Easy reversion to previous states

## Architecture

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Developer     │    │    Git Repo     │    │    ArgoCD       │
│                 │    │                 │    │                 │
│ 1. Edit YAML    │───▶│ 2. Commit/Push  │───▶│ 3. Auto Sync    │
│ 4. Monitor UI   │◀───│ 5. Git History  │◀───│ 6. Deploy K8s   │
└─────────────────┘    └─────────────────┘    └─────────────────┘
                                                        │
                                                        ▼
                                               ┌─────────────────┐
                                               │  K3s Cluster    │
                                               │                 │
                                               │ • AI Services   │
                                               │ • Networking    │
                                               │ • Monitoring    │
                                               └─────────────────┘
```

## Deployment Methods

### Method 1: GitOps-First Deployment (Recommended)

For new deployments or clean environments:

```bash
# 1. Deploy ArgoCD
./scripts/deploy-argocd.sh

# 2. Setup GitHub access
./scripts/setup-argocd-github-access.sh YOUR_GITHUB_TOKEN

# 3. Deploy via GitOps
./scripts/deploy-gitops-stack.sh
```

### Method 2: Migration from Existing Deployment

For existing deployments that need to transition to GitOps:

```bash
# 1. Analyze current state and backup
./scripts/migrate-to-gitops.sh
```

### Method 3: Hybrid Deployment

For environments that need both approaches:

```bash
# 1. Deploy ArgoCD
./scripts/deploy-argocd.sh

# 2. Deploy critical infrastructure manually
./scripts/deploy-apps.sh

# 3. Add GitOps management
./scripts/deploy-gitops-stack.sh
```

## GitOps Workflow

### 1. Making Changes

**Traditional Way (Deprecated):**
```bash
# ❌ Old way - direct kubectl
kubectl apply -f k8s/apps/ollama.yaml
```

**GitOps Way (Recommended):**
```bash
# ✅ New way - via Git
# 1. Edit the manifest
vim k8s/apps/ollama.yaml

# 2. Commit and push
git add k8s/apps/ollama.yaml
git commit -m "feat: update Ollama resource limits"
git push origin ansible

# 3. ArgoCD automatically syncs (within 3 minutes)
# 4. Monitor in ArgoCD UI
```

### 2. Monitoring Deployments

**ArgoCD UI:**
- URL: `http://192.168.131.101:8080`
- Username: `admin`
- Password: Get from secret

**Command Line:**
```bash
# Check application status
kubectl get applications -n argocd

# View application details
kubectl describe application homelab-stack -n argocd

# Force sync if needed
kubectl patch application homelab-stack -n argocd --type merge -p '{"operation":{"sync":{}}}'
```

### 3. Troubleshooting Sync Issues

**Common Issues:**

1. **OutOfSync Status:**
   ```bash
   # Check what's different
   kubectl describe application homelab-stack -n argocd
   
   # Force refresh
   kubectl patch application homelab-stack -n argocd --type merge -p '{"operation":{"sync":{}}}'
   ```

2. **Sync Failure:**
   ```bash
   # Check ArgoCD logs
   kubectl logs deployment/argocd-application-controller -n argocd
   
   # Check repository access
   kubectl get secret private-repo -n argocd -o yaml
   ```

3. **Resource Conflicts:**
   ```bash
   # Check for manual resources
   kubectl get all -A -l "!argocd.argoproj.io/instance"
   
   # Remove conflicting resources
   kubectl delete deployment manual-deployment -n ai-services
   ```

## Application Structure

### Current ArgoCD Applications

1. **test-nginx-app**: Simple test application for learning
2. **homelab-stack**: Main application stack (when created)
3. **networking-stack**: Traefik and ingress components
4. **ai-services**: Ollama, OpenWebUI, n8n, etc.

### Repository Structure

```
k8s/
├── apps/                    # Application manifests
│   ├── ollama.yaml
│   ├── openwebui.yaml
│   ├── n8n.yaml
│   └── ...
├── ingress/                 # Networking manifests
│   ├── traefik.yaml
│   └── ingress-routes.yaml
└── monitoring/              # Monitoring manifests
    ├── prometheus.yaml
    └── grafana.yaml

k8s-kustomized/             # Kustomize-based manifests
├── base/                   # Base configurations
│   ├── argocd/
│   ├── test-app/
│   └── ...
└── overlays/               # Environment-specific
    ├── production/
    └── development/
```

## Best Practices

### 1. Git Workflow

- **Use feature branches** for major changes
- **Test in development** overlay first
- **Use meaningful commit messages**
- **Tag releases** for stable versions

### 2. ArgoCD Configuration

- **Enable auto-sync** for non-critical applications
- **Disable auto-prune** for networking components
- **Set appropriate retry policies**
- **Monitor sync status regularly**

### 3. Manifest Management

- **Use Kustomize** for environment differences
- **Keep secrets in Kubernetes** (not Git)
- **Use resource limits** and requests
- **Include health checks** and probes

### 4. Troubleshooting

- **Check ArgoCD UI first** for visual status
- **Use kubectl describe** for detailed errors
- **Check application controller logs** for sync issues
- **Verify repository access** if sync fails

## Security Considerations

### Repository Access

- **Use GitHub tokens** with minimal permissions
- **Rotate tokens regularly**
- **Monitor repository access logs**
- **Use private repositories** for sensitive configs

### ArgoCD Security

- **Change default admin password**
- **Use RBAC** for multi-user access
- **Enable audit logging**
- **Secure ArgoCD UI** with proper ingress

### Secrets Management

- **Never commit secrets** to Git
- **Use Kubernetes secrets** for sensitive data
- **Consider external secret management** (Vault, etc.)
- **Rotate secrets regularly**

## Rollback Procedures

### 1. Git-based Rollback

```bash
# Revert to previous commit
git revert HEAD
git push origin ansible

# ArgoCD will automatically sync the revert
```

### 2. ArgoCD Rollback

```bash
# Rollback via ArgoCD
kubectl patch application homelab-stack -n argocd --type merge -p '{"operation":{"rollback":{"id":"previous-revision-id"}}}'
```

### 3. Emergency Rollback

```bash
# Use backup from migration
kubectl apply -f backup/20250103_143000/deployments.yaml

# Or use traditional deployment scripts
./scripts/deploy-apps.sh
```

## Monitoring and Alerting

### ArgoCD Metrics

- **Sync status** and frequency
- **Application health** status
- **Repository connectivity**
- **Sync duration** and failures

### Integration with Monitoring Stack

- **Prometheus scrapes** ArgoCD metrics
- **Grafana dashboards** show GitOps status
- **Alerts on sync failures** and drift detection

## Migration Checklist

- [ ] Backup current deployment state
- [ ] Install and configure ArgoCD
- [ ] Setup GitHub repository access
- [ ] Create ArgoCD applications
- [ ] Verify automatic synchronization
- [ ] Test rollback procedures
- [ ] Update documentation and runbooks
- [ ] Train team on GitOps workflow

## Troubleshooting Guide

### Common Commands

```bash
# Check ArgoCD status
kubectl get pods -n argocd

# View application status
kubectl get applications -n argocd -o wide

# Force application sync
kubectl patch application <app-name> -n argocd --type merge -p '{"operation":{"sync":{}}}'

# Check sync history
kubectl describe application <app-name> -n argocd

# View ArgoCD logs
kubectl logs deployment/argocd-application-controller -n argocd

# Check repository secret
kubectl get secret private-repo -n argocd -o yaml
```

### Emergency Procedures

1. **ArgoCD Down**: Use traditional deployment scripts
2. **Repository Inaccessible**: Check GitHub token and network
3. **Sync Failures**: Check manifest syntax and resource conflicts
4. **Complete Failure**: Restore from backup and redeploy

## Next Steps

1. **Complete migration** of all applications to GitOps
2. **Set up development environment** with separate ArgoCD
3. **Implement progressive delivery** with Argo Rollouts
4. **Add external secret management**
5. **Set up multi-cluster GitOps** for scaling

## References

- [ArgoCD Documentation](https://argo-cd.readthedocs.io/)
- [GitOps Principles](https://www.gitops.tech/)
- [Kustomize Documentation](https://kustomize.io/)
- [Kubernetes Best Practices](https://kubernetes.io/docs/concepts/)
