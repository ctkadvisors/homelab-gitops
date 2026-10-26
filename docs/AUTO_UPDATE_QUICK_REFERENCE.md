# ArgoCD Image Updater Quick Reference

## Current Status

### ✅ Auto-Updating Services

- **OpenWebUI**: `ghcr.io/open-webui/open-webui` → `v0.6.15` (from `main`)

### 🎯 Ready to Configure

#### n8n (High Priority)

```bash
# Add n8n to auto-updates
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

#### Ollama (High Priority)

```bash
# Add Ollama to auto-updates
kubectl patch application homelab-apps -n argocd --type merge -p '{
  "metadata": {
    "annotations": {
      "argocd-image-updater.argoproj.io/image-list": "openwebui=ghcr.io/open-webui/open-webui,ollama=ollama/ollama",
      "argocd-image-updater.argoproj.io/ollama.update-strategy": "latest",
      "argocd-image-updater.argoproj.io/ollama.allow-tags": "regexp:^latest$|^v[0-9]+\\\\.[0-9]+\\\\.[0-9]+$",
      "argocd-image-updater.argoproj.io/ollama.force-update": "true"
    }
  }
}'
```

## Tag Filtering Patterns

### Semantic Versions Only

```yaml
allow-tags: "regexp:^v[0-9]+\\.[0-9]+\\.[0-9]+$"
# Matches: v1.2.3, v2.0.1, v10.5.2
# Ignores: latest, main, alpha, beta
```

### Latest + Semantic Versions

```yaml
allow-tags: "regexp:^latest$|^v[0-9]+\\.[0-9]+\\.[0-9]+$"
# Matches: latest, v1.2.3, v2.0.1
# Ignores: main, alpha, beta
```

### Main Branch + Semantic Versions

```yaml
allow-tags: "regexp:^main$|^v[0-9]+\\.[0-9]+\\.[0-9]+$"
# Matches: main, v1.2.3, v2.0.1
# Ignores: latest, alpha, beta
```

### Exclude Pre-releases

```yaml
ignore-tags: "alpha,beta,rc,dev,nightly"
```

## Update Strategies

| Strategy | Description         | Best For                             |
| -------- | ------------------- | ------------------------------------ |
| `latest` | Always newest tag   | Fast-moving apps (OpenWebUI, Ollama) |
| `semver` | Semantic versioning | Stable apps (n8n, Grafana)           |
| `digest` | Image SHA tracking  | Maximum stability                    |

## Monitoring Commands

### Check ArgoCD Image Updater Status

```bash
kubectl logs -f deployment/argocd-image-updater -n argocd
```

**Note**: Updates run daily at midnight UTC. Check logs around that time for activity.

### View Recent Auto-Updates

```bash
git log --oneline --grep="automatic update" -10
```

### Check Application Sync Status

```bash
kubectl get applications -n argocd
```

### View Current Image Tags

```bash
kubectl get deployments -A -o jsonpath='{range .items[*]}{.metadata.namespace}{"\t"}{.metadata.name}{"\t"}{.spec.template.spec.containers[0].image}{"\n"}{end}' | column -t
```

## Emergency Procedures

### Disable Auto-Updates

```bash
# Scale down image updater
kubectl scale deployment/argocd-image-updater --replicas=0 -n argocd
```

### Rollback Bad Update

```bash
# Find the problematic commit
git log --oneline --grep="automatic update" -5

# Revert the commit
git revert <commit-hash>
git push origin main

# ArgoCD will automatically sync the rollback
```

### Remove Service from Auto-Updates

```bash
# Remove specific service from image-list
kubectl patch application homelab-apps -n argocd --type merge -p '{
  "metadata": {
    "annotations": {
      "argocd-image-updater.argoproj.io/image-list": "openwebui=ghcr.io/open-webui/open-webui"
    }
  }
}'
```

## Service Priority Matrix

### 🟢 High Priority (Auto-Update Recommended)

- **OpenWebUI** ✅ (Already configured)
- **n8n** (Automation platform)
- **Ollama** (AI model runner)
- **Qdrant** (Vector database)

### 🟡 Medium Priority (Consider Later)

- **Gitea** (Git hosting)
- **Grafana** (Monitoring)
- **Prometheus** (Metrics)

### 🔴 Low Priority (Manual Only)

- **PostgreSQL** (Database stability critical)
- **Traefik** (Ingress controller)
- **ArgoCD** (GitOps controller)
- **Custom Images** (Platform dashboard, etc.)

## Next Steps

1. **Add n8n auto-updates** (most beneficial after OpenWebUI)
2. **Add Ollama auto-updates** (AI model improvements)
3. **Monitor for 1-2 weeks** before adding more services
4. **Document any issues** and adjust tag filters as needed
