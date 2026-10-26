# Local AI Homelab - Kustomize Configuration

This directory contains the **Kustomize-based** Kubernetes manifests for the Local AI Homelab, providing declarative configuration management with environment-specific overlays.

## 🏗️ Structure

```
k8s-kustomized/
├── base/                           # Base configurations
│   ├── ai-services/               # AI workload services
│   │   ├── namespace.yaml         # AI services namespace
│   │   ├── ollama.yaml           # Ollama AI inference
│   │   ├── openwebui.yaml        # OpenWebUI interface
│   │   ├── n8n.yaml              # n8n automation
│   │   └── kustomization.yaml    # AI services base config
│   ├── networking/               # Network infrastructure
│   │   ├── metallb.yaml          # Load balancer
│   │   ├── traefik.yaml          # Ingress controller
│   │   ├── ingress-routes.yaml   # Service routing
│   │   └── kustomization.yaml    # Networking base config
│   ├── infrastructure/           # Core infrastructure
│   │   ├── monitoring.yaml       # Metrics server
│   │   └── kustomization.yaml    # Infrastructure base config
│   └── kustomization.yaml        # Main base configuration
├── overlays/                     # Environment-specific overlays
│   └── production/               # Production environment
│       ├── kustomization.yaml    # Production overlay
│       └── ingress-production.yaml # Production ingress config
├── components/                   # Reusable components (future)
└── README.md                     # This file
```

## 🎯 Key Features

### ✅ **Declarative Configuration**

- **Base + Overlay Pattern**: Reusable base with environment-specific customizations
- **Component Organization**: Logical grouping by function (AI, networking, infrastructure)
- **Version Control**: All configurations tracked in Git

### ✅ **Environment Management**

- **Production Overlay**: Pinned image versions, enhanced security, resource optimization
- **Future Overlays**: Ready for dev, staging, or test environments
- **Configuration Inheritance**: Base settings with environment-specific overrides

### ✅ **Best Practices**

- **Consistent Labeling**: Standardized labels across all resources
- **Security Hardening**: Security contexts, resource limits, network policies
- **Resource Management**: Proper requests/limits for all containers

## 🚀 Usage

### Deploy Base Configuration

```bash
# Build and view the configuration
kubectl kustomize k8s-kustomized/base

# Deploy base configuration
kubectl apply -k k8s-kustomized/base
```

### Deploy Production Environment

```bash
# Build and view production configuration
kubectl kustomize k8s-kustomized/overlays/production

# Deploy production environment
kubectl apply -k k8s-kustomized/overlays/production
```

### Deploy Specific Components

```bash
# Deploy only networking
kubectl apply -k k8s-kustomized/base/networking

# Deploy only AI services
kubectl apply -k k8s-kustomized/base/ai-services

# Deploy only infrastructure
kubectl apply -k k8s-kustomized/base/infrastructure
```

## 📋 Service Overview

### AI Services (ai-services namespace)

| Service       | Description          | Port  | Ingress            |
| ------------- | -------------------- | ----- | ------------------ |
| **Ollama**    | AI inference engine  | 11434 | ollama.example.com |
| **OpenWebUI** | Web interface for AI | 8080  | chat.example.com   |
| **n8n**       | Workflow automation  | 5678  | n8n.example.com    |

### Networking (ingress-system namespace)

| Service     | Description        | Port   | Access                      |
| ----------- | ------------------ | ------ | --------------------------- |
| **Traefik** | Ingress controller | 80/443 | traefik.example.com         |
| **MetalLB** | Load balancer      | -      | IP Pool: 10.0.0.200-210 |

### Infrastructure (kube-system namespace)

| Service            | Description      | Port | Purpose         |
| ------------------ | ---------------- | ---- | --------------- |
| **Metrics Server** | Resource metrics | 4443 | HPA, monitoring |

## 🔧 Customization

### Adding New Services

1. **Create base manifest** in appropriate directory
2. **Update kustomization.yaml** to include new resource
3. **Add overlay patches** for environment-specific settings
4. **Test with** `kubectl kustomize`

### Environment-Specific Changes

1. **Create new overlay** in `overlays/` directory
2. **Reference base** in overlay kustomization
3. **Add patches** for environment-specific modifications
4. **Deploy with** `kubectl apply -k overlays/your-env`

### Image Version Management

```yaml
# In overlay kustomization.yaml
images:
  - name: ollama/ollama
    newTag: "0.1.26" # Pin to specific version
```

## 🔍 Validation

### Dry Run Deployment

```bash
# Check what would be deployed
kubectl apply -k k8s-kustomized/overlays/production --dry-run=client -o yaml

# Validate configuration
kubectl kustomize k8s-kustomized/overlays/production | kubectl apply --dry-run=server -f -
```

### Configuration Diff

```bash
# Compare base vs production
diff <(kubectl kustomize k8s-kustomized/base) <(kubectl kustomize k8s-kustomized/overlays/production)
```

## 📊 Migration from Original k8s/

### Differences from Original Structure

- **Organized by Function**: Services grouped logically vs. flat structure
- **Environment Support**: Base + overlay pattern vs. single configuration
- **Enhanced Metadata**: Consistent labels and annotations
- **Security Improvements**: Added security contexts and resource limits
- **Version Management**: Pinned image versions in production

### Migration Commands

```bash
# Deploy new Kustomize-based configuration
kubectl apply -k k8s-kustomized/overlays/production

# Remove old resources (if needed)
kubectl delete -f k8s/apps/
kubectl delete -f k8s/networking/
kubectl delete -f k8s/ingress/
```

## 🔄 GitOps Integration

This Kustomize structure is **GitOps-ready** for tools like:

- **ArgoCD**: Point to `k8s-kustomized/overlays/production`
- **Flux**: Use Kustomization resources
- **Manual**: `kubectl apply -k` commands

### ArgoCD Application Example

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: local-ai-homelab
spec:
  source:
    repoURL: https://github.com/your-org/local-ai-homelab
    path: k8s-kustomized/overlays/production
    targetRevision: main
  destination:
    server: https://kubernetes.default.svc
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
```

## 🎯 Next Steps

### Immediate

- [ ] **Test deployment** with `kubectl apply -k`
- [ ] **Validate services** are accessible
- [ ] **Configure DNS** for .homelab domains

### Phase III Continuation

- [ ] **Implement ArgoCD** for GitOps automation
- [ ] **Add monitoring** overlays (Prometheus/Grafana)
- [ ] **Enhance security** with network policies

### Future Enhancements

- [ ] **Multi-environment** support (dev, staging)
- [ ] **Helm integration** for complex applications
- [ ] **Policy enforcement** with OPA Gatekeeper

---

**Status**: Phase III - Kustomize Integration Complete  
**Next**: GitOps Controller Implementation  
**Ready for**: Production deployment via GitOps
