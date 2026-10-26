# ArgoCD Image Updater Configuration Guide

## Overview

ArgoCD Image Updater provides automated container image updates for your Kubernetes applications. This guide covers how to configure auto-updates for different services in your homelab.

## How It Works

1. **Registry Polling**: Checks container registries daily for new images
2. **Kustomization Updates**: Updates `kustomization.yaml` with new image tags
3. **Git Commits**: Automatically commits changes to your Git repository
4. **ArgoCD Sync**: ArgoCD detects Git changes and deploys updates
5. **Health Validation**: Kubernetes ensures new containers are healthy before completing rollout

## Configuration Methods

### Method 1: ArgoCD Application Annotations (Recommended)

Add annotations to your ArgoCD Application resource:

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: homelab-apps
  namespace: argocd
  annotations:
    # Basic configuration
    argocd-image-updater.argoproj.io/image-list: "service1=registry/image1,service2=registry/image2"
    argocd-image-updater.argoproj.io/write-back-method: "git"
    argocd-image-updater.argoproj.io/write-back-target: "kustomization"
    argocd-image-updater.argoproj.io/git-branch: "main"

    # Per-service configuration
    argocd-image-updater.argoproj.io/service1.update-strategy: "latest"
    argocd-image-updater.argoproj.io/service1.allow-tags: "regexp:^v[0-9]+\\.[0-9]+\\.[0-9]+$"
    argocd-image-updater.argoproj.io/service1.force-update: "true"
```

### Method 2: Deployment Annotations (Alternative)

Add annotations directly to Kubernetes Deployment resources:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  annotations:
    argocd-image-updater.argoproj.io/image-list: "service=registry/image"
    argocd-image-updater.argoproj.io/write-back-method: "git"
```

## Update Strategies

| Strategy | Description                     | Use Case                             |
| -------- | ------------------------------- | ------------------------------------ |
| `latest` | Always use newest available tag | Development, frequently updated apps |
| `semver` | Follow semantic versioning      | Production, stable releases          |
| `digest` | Track by image digest/SHA       | Maximum stability                    |

## Tag Filtering

Control which image tags are allowed for updates:

```yaml
# Only semantic versions (v1.2.3)
argocd-image-updater.argoproj.io/service.allow-tags: "regexp:^v[0-9]+\\.[0-9]+\\.[0-9]+$"

# Main branch and semantic versions
argocd-image-updater.argoproj.io/service.allow-tags: "regexp:^main$|^v[0-9]+\\.[0-9]+\\.[0-9]+$"

# Exclude alpha/beta/rc releases
argocd-image-updater.argoproj.io/service.ignore-tags: "alpha,beta,rc"

# Latest stable only
argocd-image-updater.argoproj.io/service.allow-tags: "regexp:^latest$"
```

## Configuration Examples

### OpenWebUI (Currently Configured)

```yaml
argocd-image-updater.argoproj.io/image-list: "openwebui=ghcr.io/open-webui/open-webui"
argocd-image-updater.argoproj.io/openwebui.update-strategy: "latest"
argocd-image-updater.argoproj.io/openwebui.allow-tags: "regexp:^main$|^v[0-9]+\\.[0-9]+\\.[0-9]+$"
argocd-image-updater.argoproj.io/openwebui.force-update: "true"
```

### n8n (Recommended)

```yaml
argocd-image-updater.argoproj.io/image-list: "n8n=n8nio/n8n"
argocd-image-updater.argoproj.io/n8n.update-strategy: "semver"
argocd-image-updater.argoproj.io/n8n.allow-tags: "regexp:^[0-9]+\\.[0-9]+\\.[0-9]+$"
argocd-image-updater.argoproj.io/n8n.force-update: "false"
```

### Ollama (Recommended)

```yaml
argocd-image-updater.argoproj.io/image-list: "ollama=ollama/ollama"
argocd-image-updater.argoproj.io/ollama.update-strategy: "latest"
argocd-image-updater.argoproj.io/ollama.allow-tags: "regexp:^latest$"
argocd-image-updater.argoproj.io/ollama.force-update: "true"
```

## Safety Features

1. **Git Tracking**: All changes are committed to Git with detailed messages
2. **Rollback Capability**: Easy to revert via `git revert` or ArgoCD
3. **Health Checks**: Kubernetes validates new containers before completing rollout
4. **Tag Filtering**: Prevents unwanted alpha/beta updates
5. **Manual Override**: Can still manually sync when needed

## Monitoring

### Check ArgoCD Image Updater Status

```bash
kubectl logs -f deployment/argocd-image-updater -n argocd
```

### View Recent Updates

```bash
git log --oneline --grep="automatic update"
```

### Check Application Sync Status

```bash
kubectl get applications -n argocd
```

## Troubleshooting

### Common Issues

**No updates happening:**

- Verify registry credentials
- Check annotation syntax
- Review updater logs for errors

**Too many updates:**

- Adjust polling interval
- Use more restrictive tag filters
- Switch to `semver` strategy

**Failed deployments:**

- Check container health probes
- Verify image compatibility
- Review ArgoCD sync status

### Disable Auto-Updates

Temporarily disable for maintenance:

```bash
# Scale down image updater
kubectl scale deployment/argocd-image-updater --replicas=0 -n argocd

# Or remove annotations from application
kubectl annotate application homelab-apps -n argocd argocd-image-updater.argoproj.io/image-list-
```

## Recommended Services for Auto-Updates

### 🟢 High Priority (Recommended)

| Service    | Image           | Current Tag        | Recommended Strategy | Rationale                                      |
| ---------- | --------------- | ------------------ | -------------------- | ---------------------------------------------- |
| **n8n**    | `n8nio/n8n`     | `latest`           | `semver`             | Frequent updates, stable releases              |
| **Ollama** | `ollama/ollama` | `0.9.0` → `latest` | `latest`             | AI model runner, benefits from latest features |
| **Qdrant** | `qdrant/qdrant` | `latest`           | `semver`             | Vector database, stable releases               |

### 🟡 Medium Priority (Consider)

| Service        | Image             | Current Tag | Recommended Strategy | Rationale                             |
| -------------- | ----------------- | ----------- | -------------------- | ------------------------------------- |
| **Gitea**      | `gitea/gitea`     | `latest`    | `semver`             | Git hosting, stable but less critical |
| **Grafana**    | `grafana/grafana` | `latest`    | `semver`             | Monitoring, stable releases           |
| **Prometheus** | `prom/prometheus` | `latest`    | `semver`             | Monitoring, stable releases           |

### 🔴 Low Priority (Manual Updates)

| Service                | Image                                 | Current Tag | Recommendation | Rationale                           |
| ---------------------- | ------------------------------------- | ----------- | -------------- | ----------------------------------- |
| **PostgreSQL**         | `pgvector/pgvector`                   | `pg16`      | Manual         | Database stability critical         |
| **Traefik**            | `traefik`                             | `v3.0`      | Manual         | Ingress controller, test thoroughly |
| **ArgoCD**             | `quay.io/argoproj/argocd`             | `v2.14.0`   | Manual         | GitOps controller, test thoroughly  |
| **Platform Dashboard** | `ghcr.io/chrisknu/platform-dashboard` | Custom      | Manual         | Custom image, manual control        |

### ✅ Already Configured

| Service       | Image                           | Status    | Configuration      |
| ------------- | ------------------------------- | --------- | ------------------ |
| **OpenWebUI** | `ghcr.io/open-webui/open-webui` | ✅ Active | `main` → `v0.6.15` |

## Service-Specific Configurations

### n8n (Automation Platform)

```yaml
# Add to homelab-apps Application annotations
argocd-image-updater.argoproj.io/image-list: "openwebui=ghcr.io/open-webui/open-webui,n8n=n8nio/n8n"
argocd-image-updater.argoproj.io/n8n.update-strategy: "semver"
argocd-image-updater.argoproj.io/n8n.allow-tags: "regexp:^[0-9]+\\.[0-9]+\\.[0-9]+$"
argocd-image-updater.argoproj.io/n8n.ignore-tags: "alpha,beta,rc"
```

### Ollama (AI Model Runner)

```yaml
# Add to homelab-apps Application annotations
argocd-image-updater.argoproj.io/image-list: "openwebui=ghcr.io/open-webui/open-webui,ollama=ollama/ollama"
argocd-image-updater.argoproj.io/ollama.update-strategy: "latest"
argocd-image-updater.argoproj.io/ollama.allow-tags: "regexp:^latest$|^v[0-9]+\\.[0-9]+\\.[0-9]+$"
argocd-image-updater.argoproj.io/ollama.force-update: "true"
```

### Qdrant (Vector Database)

```yaml
# Add to homelab-apps Application annotations
argocd-image-updater.argoproj.io/image-list: "openwebui=ghcr.io/open-webui/open-webui,qdrant=qdrant/qdrant"
argocd-image-updater.argoproj.io/qdrant.update-strategy: "semver"
argocd-image-updater.argoproj.io/qdrant.allow-tags: "regexp:^v[0-9]+\\.[0-9]+\\.[0-9]+$"
```

## Implementation Steps

### Step 1: Add n8n Auto-Updates

```bash
# Update ArgoCD Application with n8n configuration
kubectl patch application homelab-apps -n argocd --type merge -p '{
  "metadata": {
    "annotations": {
      "argocd-image-updater.argoproj.io/image-list": "openwebui=ghcr.io/open-webui/open-webui,n8n=n8nio/n8n",
      "argocd-image-updater.argoproj.io/n8n.update-strategy": "semver",
      "argocd-image-updater.argoproj.io/n8n.allow-tags": "regexp:^[0-9]+\\\\.[0-9]+\\\\.[0-9]+$",
      "argocd-image-updater.argoproj.io/n8n.ignore-tags": "alpha,beta,rc"
    }
  }
}'
```

### Step 2: Remove Hardcoded Tags

Update `k8s-kustomized/overlays/production/kustomization.yaml`:

```yaml
# Remove or comment out hardcoded tags for auto-updated services
images:
  - name: ollama/ollama
    newTag: "0.9.0" # Remove this line for auto-updates
  # - name: n8nio/n8n
  #   newTag: "latest" # Remove this line for auto-updates
```

### Step 3: Monitor and Validate

```bash
# Watch ArgoCD Image Updater logs
kubectl logs -f deployment/argocd-image-updater -n argocd

# Check for new commits
git log --oneline --grep="automatic update"

# Verify deployments
kubectl get deployments -A
```

## Best Practices

1. **Start Conservative**: Begin with stable services and restrictive tag filters
2. **Monitor Closely**: Watch logs and Git commits during initial setup
3. **Test Rollbacks**: Ensure you can quickly revert problematic updates
4. **Document Exceptions**: Note services that shouldn't auto-update
5. **Regular Reviews**: Periodically review which services are auto-updating
