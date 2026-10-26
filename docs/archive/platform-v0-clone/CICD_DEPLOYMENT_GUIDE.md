# 🚀 CI/CD Platform Deployment Guide

## Quick Start: Testing the New CI/CD Functionality

### Prerequisites

1. **Kubernetes cluster** with kubectl access
2. **GitHub Container Registry** access token
3. **Platform API and Dashboard** deployed
4. **Git repository** for testing (we'll use `ctkadvisors/base_nextjs`)

### Step 1: Set Up GitHub Container Registry Access

Create a Kubernetes secret for GitHub Container Registry:

```bash
# Create the secret for GitHub registry access
kubectl create secret generic github-registry-secret \
  --from-literal=token=YOUR_GITHUB_TOKEN \
  -n platform

# Verify the secret
kubectl get secret github-registry-secret -n platform
```

### Step 2: Deploy Updated Platform API

```bash
# Navigate to platform-api directory
cd platform-api

# Build the updated API
npm run build

# Build Docker image
docker build -t ghcr.io/ctkadvisors/platform-api:latest .

# Push to registry
docker push ghcr.io/ctkadvisors/platform-api:latest

# Update the deployment (if using GitOps, commit and push)
kubectl rollout restart deployment platform-api -n platform
```

### Step 3: Test the New Functionality

#### 3.1 Create a Test Project

```bash
# Use the platform dashboard or API to create a project
curl -X POST https://platform.homelab/api/projects \
  -H "Content-Type: application/json" \
  -d '{
    "name": "test-nextjs-app",
    "displayName": "Test Next.js App",
    "description": "Testing the new CI/CD functionality",
    "repositoryUrl": "https://github.com/ctkadvisors/base_nextjs.git",
    "gitBranch": "main",
    "autoDeployEnabled": true,
    "previewDeployEnabled": true
  }'
```

#### 3.2 Trigger a Manual Deployment

```bash
# Get the project ID from the response above, then trigger deployment
curl -X POST https://platform.homelab/api/projects/{PROJECT_ID}/deploy \
  -H "Content-Type: application/json" \
  -d '{
    "branch": "main",
    "isPreview": false
  }'
```

#### 3.3 Monitor the Deployment

```bash
# Check deployment status
curl https://platform.homelab/api/projects/{PROJECT_ID}/status

# List all deployments for the project
curl https://platform.homelab/api/projects/{PROJECT_ID}/deployments

# Get build logs (once deployment is created)
curl https://platform.homelab/api/deployments/{DEPLOYMENT_ID}/logs
```

#### 3.4 Check Kubernetes Resources

```bash
# Check if build namespace was created
kubectl get namespace platform-builds

# Monitor build jobs
kubectl get jobs -n platform-builds

# Check build job logs
kubectl logs -n platform-builds job/{BUILD_JOB_NAME} -c builder

# Check project namespace
kubectl get namespace project-test-nextjs-app

# Check project deployment
kubectl get all -n project-test-nextjs-app
```

### Step 4: Set Up GitHub Webhooks (Optional)

1. Go to your GitHub repository settings
2. Navigate to "Webhooks"
3. Add a new webhook:
   - **Payload URL**: `https://platform.homelab/api/projects/{PROJECT_ID}/webhook`
   - **Content type**: `application/json`
   - **Secret**: Generate using the webhook service or use a secure random string
   - **Events**: Select "Just the push event"

### Step 5: Test Webhook Integration

```bash
# Make a commit to your repository and push
git commit --allow-empty -m "Test webhook deployment"
git push origin main

# Check if deployment was triggered automatically
curl https://platform.homelab/api/projects/{PROJECT_ID}/deployments
```

### Step 6: Test Preview Deployments

```bash
# Create a feature branch and push
git checkout -b feature/test-preview
git commit --allow-empty -m "Test preview deployment"
git push origin feature/test-preview

# Check if preview deployment was created
curl https://platform.homelab/api/projects/{PROJECT_ID}/deployments
```

## Troubleshooting

### Common Issues

#### 1. Build Jobs Failing

```bash
# Check build job status
kubectl describe job {BUILD_JOB_NAME} -n platform-builds

# Check pod logs
kubectl logs -n platform-builds -l job-name={BUILD_JOB_NAME} -c builder

# Check if Docker daemon is running
kubectl logs -n platform-builds -l job-name={BUILD_JOB_NAME} -c docker-daemon
```

#### 2. Repository Access Issues

```bash
# Test repository validation
curl -X POST https://platform.homelab/api/projects/{PROJECT_ID}/validate-repository \
  -H "Content-Type: application/json" \
  -d '{}'

# Check repository information
curl https://platform.homelab/api/projects/{PROJECT_ID}/repository-info
```

#### 3. Deployment Not Accessible

```bash
# Check ingress configuration
kubectl get ingress -n project-test-nextjs-app

# Check service endpoints
kubectl get endpoints -n project-test-nextjs-app

# Check pod status
kubectl get pods -n project-test-nextjs-app
```

### Monitoring Commands

```bash
# Watch build jobs in real-time
kubectl get jobs -n platform-builds -w

# Monitor project deployments
kubectl get deployments -n project-test-nextjs-app -w

# Check platform API logs
kubectl logs -f deployment/platform-api -n platform

# Check all platform resources
kubectl get all -n platform
```

## Expected Results

After successful deployment, you should see:

1. **Build Job**: Created in `platform-builds` namespace
2. **Docker Image**: Pushed to `ghcr.io/ctkadvisors/test-nextjs-app:latest`
3. **Project Deployment**: Running in `project-test-nextjs-app` namespace
4. **Accessible URL**: `https://test-nextjs-app.homelab`
5. **Preview URLs**: `https://feature-test-preview--{commit}--test-nextjs-app.homelab`

## Next Steps

1. **Database Integration**: Implement persistent deployment records
2. **Real-time UI**: Update dashboard with live deployment status
3. **Advanced Features**: Add rollback, scaling, and monitoring
4. **Production Hardening**: Add proper authentication and rate limiting

This guide provides a complete testing workflow for the new CI/CD functionality. The platform now supports the full Vercel-like experience with automatic builds, deployments, and preview environments!
