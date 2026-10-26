# ArgoCD Image Updater Guide

## Overview

ArgoCD Image Updater automatically monitors container registries and updates your Kubernetes deployments when new images are available. It's the GitOps-compliant alternative to Watchtower.

## How It Works

1. **Registry Polling**: Continuously checks registries for new images
2. **Git Updates**: Automatically commits image tag changes to your Git repository
3. **ArgoCD Sync**: ArgoCD detects Git changes and deploys updates
4. **Health Checks**: Kubernetes ensures new containers are healthy before completing rollout

## Configuration

### Deployment Annotations

Add these annotations to your deployments to enable auto-updates:

```yaml
metadata:
  annotations:
    # Basic configuration
    argocd-image-updater.argoproj.io/image-list: <name>=<image>
    argocd-image-updater.argoproj.io/write-back-method: git
    
    # Update strategy
    argocd-image-updater.argoproj.io/<name>.update-strategy: latest|semver|digest
    
    # Tag filtering
    argocd-image-updater.argoproj.io/<name>.allow-tags: regexp:^pattern$
    argocd-image-updater.argoproj.io/<name>.ignore-tags: alpha,beta,rc
    
    # Force updates (useful for 'latest' tags)
    argocd-image-updater.argoproj.io/<name>.force-update: "true"
```

### Current Configuration

**OpenWebUI** (Auto-update enabled):
- **Image**: `ghcr.io/open-webui/open-webui`
- **Strategy**: `latest` (always newest)
- **Tags**: `main` branch and semantic versions only
- **Frequency**: Every 2 minutes

## Monitoring

### Via ArgoCD UI
1. Go to **Applications** → **homelab-apps**
2. Check **Details** tab for image updater status
3. View **Sync History** for automated updates

### Via CLI
```bash
# Check updater logs
kubectl logs -f deployment/argocd-image-updater -n argocd

# See tracked applications
kubectl get applications -n argocd -o yaml | grep image-updater

# Force immediate check
kubectl rollout restart deployment/argocd-image-updater -n argocd
```

### Via Git
- Automatic commits show what was updated
- Commit messages include image details
- Full audit trail in Git history

## Update Strategies

| Strategy | Description | Best For |
|----------|-------------|----------|
| `latest` | Always use newest available tag | Development, frequently updated apps |
| `semver` | Follow semantic versioning (v1.2.3) | Production, stable releases |
| `digest` | Track by image digest/SHA | Maximum stability, security |

## Safety Features

1. **Git-based**: All changes tracked in version control
2. **Rollback**: Easy to revert via Git or ArgoCD
3. **Health checks**: Kubernetes ensures new containers are healthy
4. **Selective**: Only updates what you configure
5. **Manual override**: Can still manually sync when needed

## Troubleshooting

### Common Issues

**Updates not happening:**
- Check registry credentials
- Verify annotation syntax
- Check updater logs for errors

**Too many updates:**
- Adjust polling interval
- Use more restrictive tag filters
- Switch to `semver` strategy

**Failed updates:**
- Check container health probes
- Verify image compatibility
- Review ArgoCD sync status

### Disable Auto-Updates

To temporarily disable auto-updates:
```bash
# Scale down image updater
kubectl scale deployment/argocd-image-updater --replicas=0 -n argocd

# Or remove annotations from deployments
```

## Best Practices

1. **Start small**: Enable for non-critical services first
2. **Use tag filters**: Avoid alpha/beta releases in production
3. **Monitor closely**: Watch logs and Git commits initially
4. **Test rollbacks**: Ensure you can revert changes quickly
5. **Document exceptions**: Note any services that shouldn't auto-update
