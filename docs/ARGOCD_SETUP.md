# ArgoCD GitOps Setup Guide

This document provides comprehensive instructions for setting up and using ArgoCD as the GitOps controller for the Local AI Homelab.

## Overview

ArgoCD is a declarative, GitOps continuous delivery tool for Kubernetes. It monitors Git repositories for changes and automatically synchronizes the desired state with the live cluster state.

## Architecture

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Git Repo      │    │    ArgoCD       │    │   K3s Cluster   │
│                 │    │                 │    │                 │
│ ├─ k8s-kustomized │──▶│ ├─ Applications │──▶│ ├─ Deployments  │
│ ├─ manifests    │    │ ├─ Projects     │    │ ├─ Services     │
│ └─ configs      │    │ └─ Repositories │    │ └─ ConfigMaps   │
└─────────────────┘    └─────────────────┘    └─────────────────┘
```

## Installation

### Prerequisites

- K3s cluster running and accessible
- kubectl configured to access the cluster
- DNS resolution for `argocd.homelab` pointing to your cluster

### Quick Installation

```bash
# Deploy ArgoCD
./scripts/deploy-argocd.sh

# Validate installation
./scripts/validate-argocd.sh
```

### Manual Installation

1. **Create namespace:**
   ```bash
   kubectl create namespace argocd
   ```

2. **Deploy using Kustomize:**
   ```bash
   kubectl apply -k k8s-kustomized/overlays/production/argocd
   ```

3. **Wait for pods to be ready:**
   ```bash
   kubectl wait --for=condition=available --timeout=300s deployment/argocd-server -n argocd
   ```

## Initial Setup

### 1. Access ArgoCD UI

- **URL:** https://argocd.homelab
- **Username:** admin
- **Password:** Retrieved from secret (see below)

### 2. Get Admin Password

```bash
kubectl get secret argocd-initial-admin-secret -n argocd -o jsonpath="{.data.password}" | base64 -d
```

### 3. Change Admin Password

After first login, change the admin password:

1. Go to User Info (click on admin in top right)
2. Click "Update Password"
3. Enter new password
4. Delete the initial secret:
   ```bash
   kubectl delete secret argocd-initial-admin-secret -n argocd
   ```

## Configuration

### Repository Configuration

ArgoCD is pre-configured to monitor this repository:
- **Repository:** https://github.com/ctkadvisors/new_localai.git
- **Path:** k8s-kustomized/overlays/production
- **Target Revision:** HEAD

### Applications

The following applications are automatically managed by ArgoCD:

1. **homelab-apps** - Main application stack
2. **monitoring-stack** - Prometheus, Grafana, etc.
3. **networking-stack** - MetalLB, Traefik, etc.

### Sync Policies

- **Automated Sync:** Enabled with self-healing
- **Prune:** Enabled (removes resources not in Git)
- **Self-Heal:** Enabled (reverts manual changes)

## Usage

### Adding New Applications

1. **Create Application manifest:**
   ```yaml
   apiVersion: argoproj.io/v1alpha1
   kind: Application
   metadata:
     name: my-app
     namespace: argocd
   spec:
     project: default
     source:
       repoURL: https://github.com/ctkadvisors/new_localai.git
       targetRevision: HEAD
       path: k8s-kustomized/base/my-app
     destination:
       server: https://kubernetes.default.svc
       namespace: my-namespace
     syncPolicy:
       automated:
         prune: true
         selfHeal: true
   ```

2. **Apply the manifest:**
   ```bash
   kubectl apply -f my-app-application.yaml
   ```

### Manual Sync

If automatic sync is disabled or you want to force a sync:

```bash
# Using ArgoCD CLI
argocd app sync my-app

# Using kubectl
kubectl patch application my-app -n argocd --type merge -p '{"operation":{"sync":{}}}'
```

### Viewing Application Status

```bash
# List all applications
argocd app list

# Get application details
argocd app get my-app

# View application logs
argocd app logs my-app
```

## Troubleshooting

### Common Issues

1. **Application stuck in "OutOfSync" state:**
   - Check if the Git repository is accessible
   - Verify the path in the application spec
   - Check for syntax errors in manifests

2. **Sync fails with permission errors:**
   - Verify RBAC configuration
   - Check if target namespace exists
   - Ensure ArgoCD has necessary permissions

3. **UI not accessible:**
   - Check ingress configuration
   - Verify DNS resolution for argocd.homelab
   - Check if argocd-server pod is running

### Debugging Commands

```bash
# Check ArgoCD pods
kubectl get pods -n argocd

# View ArgoCD server logs
kubectl logs deployment/argocd-server -n argocd

# Check application controller logs
kubectl logs deployment/argocd-application-controller -n argocd

# View application events
kubectl describe application my-app -n argocd
```

### Reset ArgoCD

If you need to completely reset ArgoCD:

```bash
# Delete all applications first
kubectl delete applications --all -n argocd

# Delete ArgoCD
kubectl delete -k k8s-kustomized/overlays/production/argocd

# Redeploy
./scripts/deploy-argocd.sh
```

## Security Considerations

### RBAC

ArgoCD is configured with:
- Admin role for full access
- Readonly role as default for other users
- Project-based access control

### Network Security

- ArgoCD UI is exposed via HTTPS only
- Internal communication uses cluster networking
- No external access to ArgoCD API without authentication

### Secret Management

- Initial admin password is auto-generated
- Secrets are stored in Kubernetes secrets
- Repository access uses HTTPS (no credentials stored)

## Best Practices

### Git Repository Structure

- Keep manifests in dedicated directories
- Use Kustomize for environment-specific configurations
- Tag releases for stable deployments
- Use meaningful commit messages

### Application Management

- Group related resources in single applications
- Use projects for multi-tenant scenarios
- Set appropriate sync policies
- Monitor application health regularly

### Monitoring

- Enable ArgoCD metrics collection
- Set up alerts for sync failures
- Monitor Git repository accessibility
- Track application deployment frequency

## Integration with Existing Infrastructure

### Ansible Integration

ArgoCD complements the Ansible-based node provisioning:
- Ansible provisions and configures K3s nodes
- ArgoCD manages application deployments
- Both use GitOps principles for consistency

### Monitoring Integration

ArgoCD integrates with the monitoring stack:
- Prometheus scrapes ArgoCD metrics
- Grafana dashboards show deployment status
- Alerts notify of sync failures

## Next Steps

1. **Configure additional repositories** if needed
2. **Set up webhooks** for faster sync triggers
3. **Implement progressive delivery** with Argo Rollouts
4. **Add SSO integration** for team access
5. **Configure notifications** for deployment events

## References

- [ArgoCD Documentation](https://argo-cd.readthedocs.io/)
- [GitOps Best Practices](https://www.gitops.tech/)
- [Kustomize Documentation](https://kustomize.io/)
- [K3s Documentation](https://docs.k3s.io/)
