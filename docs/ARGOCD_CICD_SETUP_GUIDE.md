# ArgoCD CI/CD Pipeline Setup Guide

This guide walks you through setting up a complete CI/CD pipeline with ArgoCD, ArgoCD Image Updater, and GitHub Actions for automatic builds and deployments.

## Architecture Overview

```
Code Push (main) → GitHub Actions → Build Images → Push to Registry → Update Manifests → ArgoCD Sync
                                                                    ↓
                                             ArgoCD Image Updater → Monitor Images → Update Deployments
```

## Components

1. **GitHub Actions**: Builds Docker images and pushes to Gitea registry
2. **ArgoCD**: GitOps deployment tool that syncs K8s manifests
3. **ArgoCD Image Updater**: Monitors registry for new images and updates deployments
4. **Gitea Registry**: Private container registry at git.example.com

## Prerequisites

- K3s cluster running with ArgoCD deployed
- Gitea instance at git.example.com with container registry enabled
- GitHub repository with necessary secrets configured
- kubectl access to the cluster

## Step 1: Configure GitHub Actions Secrets

Add these secrets to your GitHub repository (Settings → Secrets and variables → Actions):

- `GITEA_USERNAME`: Your Gitea username (e.g., homelab)
- `GITEA_TOKEN`: Gitea access token with `write:packages` permission

### Creating Gitea Access Token

1. Go to https://git.example.com/user/settings/applications
2. Click "Generate New Token"
3. Set name: "GitHub Actions CI/CD"
4. Select scope: `write:packages`
5. Copy the generated token

## Step 2: Setup ArgoCD Authentication

### Install ArgoCD CLI

```bash
# Linux/macOS
curl -sSL -o argocd-linux-amd64 https://github.com/argoproj/argo-cd/releases/latest/download/argocd-linux-amd64
sudo install -m 555 argocd-linux-amd64 /usr/local/bin/argocd
rm argocd-linux-amd64
```

### Create ArgoCD Token

```bash
# Port-forward ArgoCD server
kubectl port-forward svc/argocd-server -n argocd 8080:443 &

# Get initial admin password
ARGOCD_PASSWORD=$(kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath="{.data.password}" | base64 -d)

# Login to ArgoCD
argocd login localhost:8080 --username admin --password $ARGOCD_PASSWORD --insecure

# Create service account for Image Updater
argocd account create argocd-image-updater --account argocd-image-updater

# Generate token
ARGOCD_TOKEN=$(argocd account generate-token --account argocd-image-updater)
echo "ArgoCD Token: $ARGOCD_TOKEN"
```

## Step 3: Setup Secrets and Authentication

Run the setup script to configure all necessary secrets:

```bash
./scripts/setup-cicd-secrets.sh
```

This script will:
- Guide you through setting up GitHub Actions secrets
- Create ArgoCD authentication token
- Configure Gitea registry authentication
- Generate SSH keys for Git operations
- Apply secrets to the Kubernetes cluster

## Step 4: Deploy ArgoCD Image Updater

```bash
# Deploy ArgoCD Image Updater with configuration
kubectl apply -k k8s-kustomized/base/argocd-image-updater/

# Verify deployment
kubectl get pods -n argocd -l app.kubernetes.io/name=argocd-image-updater
```

## Step 5: Configure GitHub Webhook (Optional)

For immediate sync triggers, configure a webhook:

1. Go to GitHub repository Settings → Webhooks
2. Add webhook:
   - URL: `https://argocd-webhook.example.com/api/webhook`
   - Content type: `application/json`
   - Secret: Use the same secret from webhook-config.yaml
   - Events: Select "Push" and "Pull requests"

## Step 6: Deploy Platform Applications

```bash
# Deploy the platform with GitOps
kubectl apply -k k8s-kustomized/overlays/production/

# Verify deployments
kubectl get apps -n argocd
kubectl get deployments -n platform
```

## Step 7: Test the CI/CD Pipeline

### Test 1: Code Change Deployment

1. Make a change to platform-api or platform-dashboard code
2. Commit and push to main branch:
   ```bash
   git add .
   git commit -m "feat: test CI/CD pipeline"
   git push origin main
   ```
3. Observe the pipeline:
   - GitHub Actions builds and pushes Docker images
   - GitHub Actions updates image tags in K8s manifests
   - ArgoCD detects changes and syncs applications
   - New pods are deployed with updated images

### Test 2: Manual Image Update

1. Manually push an image to the registry with a new tag
2. ArgoCD Image Updater should detect and update the deployment
3. Verify the deployment uses the new image tag

## Monitoring and Troubleshooting

### Check GitHub Actions

View workflow runs at: `https://github.com/your-org/your-repo/actions`

### Check ArgoCD Status

```bash
# Check application sync status
kubectl get apps -n argocd

# View application details
kubectl describe app platform-app -n argocd

# Check ArgoCD server logs
kubectl logs -n argocd deployment/argocd-server
```

### Check ArgoCD Image Updater

```bash
# Check Image Updater status
kubectl get pods -n argocd -l app.kubernetes.io/name=argocd-image-updater

# View Image Updater logs
kubectl logs -n argocd deployment/argocd-image-updater

# Check configuration
kubectl get configmap argocd-image-updater-config -n argocd -o yaml
```

### Common Issues

#### 1. GitHub Actions can't push to registry
- Verify GITEA_USERNAME and GITEA_TOKEN secrets
- Check Gitea token has write:packages permission
- Ensure registry is accessible from GitHub Actions

#### 2. ArgoCD can't sync applications
- Check ArgoCD has access to GitHub repository
- Verify repository URL in ArgoCD application
- Check network connectivity to GitHub

#### 3. Image Updater not updating images
- Verify registry credentials in ArgoCD namespace
- Check image update annotations on deployments
- Review Image Updater configuration and logs

#### 4. Images pulled with ImagePullBackOff
- Verify gitea-registry-secret exists in platform namespace
- Check registry authentication is working
- Ensure image tags are correct

## Pipeline Flow Details

### On Code Push to Main:

1. **GitHub Actions Workflow** (`.github/workflows/build-deploy.yml`):
   - Detects changes in platform-api or platform-dashboard
   - Runs tests and builds
   - Builds Docker images with SHA-based tags
   - Pushes images to git.example.com registry
   - Updates image tags in K8s manifests
   - Commits changes back to repository

2. **ArgoCD Sync**:
   - Detects manifest changes (via webhook or polling)
   - Syncs applications to match Git state
   - Deploys updated applications with new image tags

3. **ArgoCD Image Updater** (optional):
   - Monitors registry for new images (every 2 minutes)
   - Updates deployments when new images match tag patterns
   - Commits image tag updates to Git
   - ArgoCD syncs the updated manifests

### Image Tag Strategy

- **Development**: `main-<sha7>` (e.g., `main-a1b2c3d`)
- **Latest**: `latest` (points to most recent main build)
- **Versioned**: `v1.0.0` (for releases)

### Security Considerations

- All registry access uses authentication tokens
- SSH keys for Git operations are managed securely
- Secrets are stored in Kubernetes Secret objects
- Webhook endpoints are secured with secret tokens
- Network policies can restrict registry access

## Maintenance

### Updating Secrets

Use the setup script to rotate credentials:
```bash
./scripts/setup-cicd-secrets.sh
```

### Monitoring Pipeline Health

- Set up alerts for failed GitHub Actions workflows
- Monitor ArgoCD sync health in ArgoCD UI
- Check registry storage usage and cleanup old images
- Review Image Updater logs for update failures

### Backup and Recovery

- ArgoCD applications are declaratively defined in Git
- Secrets should be documented (not stored) for recovery
- Registry images provide rollback capabilities
- K8s manifests in Git provide complete deployment history

## Next Steps

1. **Security Enhancements**:
   - Implement image vulnerability scanning
   - Add policy enforcement with OPA Gatekeeper
   - Set up network policies for registry access

2. **Monitoring and Observability**:
   - Integrate with Prometheus for pipeline metrics
   - Set up alerts for deployment failures
   - Add deployment tracking in Grafana dashboards

3. **Advanced Features**:
   - Multi-environment deployments (staging, production)
   - Canary deployments with ArgoCD Rollouts
   - Integration with external secret management (Vault, etc.)

## Resources

- [ArgoCD Documentation](https://argo-cd.readthedocs.io/)
- [ArgoCD Image Updater Documentation](https://argocd-image-updater.readthedocs.io/)
- [GitHub Actions Documentation](https://docs.github.com/en/actions)
- [Docker Registry API](https://docs.docker.com/registry/spec/api/)