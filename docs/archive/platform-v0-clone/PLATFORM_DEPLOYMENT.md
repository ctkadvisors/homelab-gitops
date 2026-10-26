# 🚀 Next.js Platform Deployment Guide

## 📋 Our Main Goal - Step by Step

Following our planned execution:

1. ✅ **Deploy Dashboard to K8s** ← We are here
2. 📋 **Connect to K8s Management API** 
3. 📋 **Test Simple UI-Only Stacks**
4. 📋 **Test Supabase-per-Namespace**

## 🏗️ **Step 1: Deploy Dashboard to K8s (GitOps)**

### **ArgoCD Application Structure**

We've organized the platform into proper ArgoCD applications:

```
k8s/argocd-apps/
├── nextjs-platform-app.yaml      # Core platform (dashboard + API)
└── vercel-apps-manager.yaml      # User apps manager

k8s/platform/
├── namespace.yaml                 # Platform namespace + RBAC
├── dashboard.yaml                 # Platform dashboard deployment
└── api.yaml                      # Platform API deployment

k8s/vercel-apps/
└── README.md                     # User apps will be created here
```

### **Deployment Commands**

#### **Option 1: GitOps Deployment (Recommended)**
```bash
# Deploy via ArgoCD (follows GitOps best practices)
./scripts/deploy-platform-gitops.sh
```

#### **Option 2: Build and Deploy (Development)**
```bash
# Build images and deploy (for development/testing)
./scripts/build-platform.sh
```

### **What Gets Deployed**

#### **Platform Namespace**
- **Namespace**: `platform`
- **RBAC**: Service account with cluster-wide permissions for K8s management
- **Secrets**: Database credentials, JWT secrets

#### **Platform Dashboard**
- **Image**: `platform-dashboard:latest`
- **URL**: https://platform.homelab
- **Replicas**: 2 (on EliteMini control-plane nodes)
- **Resources**: 256Mi memory, 100m CPU

#### **Platform API**
- **Image**: `platform-api:latest`
- **Internal URL**: `http://platform-api.platform.svc.cluster.local:3001`
- **Replicas**: 2 (on EliteMini control-plane nodes)
- **Resources**: 256Mi memory, 100m CPU
- **Permissions**: Full K8s cluster management via RBAC

## 🔧 **Step 2: Connect to K8s Management API**

The Platform API has been configured with:

### **Kubernetes RBAC Permissions**
```yaml
# ClusterRole: platform-api-manager
- Namespace management (create, delete, list)
- Deployment management (create, update, delete)
- Service and Ingress management
- ConfigMap and Secret management
- ArgoCD Application management
- Resource monitoring (metrics)
```

### **API Endpoints for K8s Management**
```typescript
// These will be implemented in the Platform API
POST /api/projects                    // Create new project + namespace
GET  /api/projects                    // List all projects
DELETE /api/projects/:id              // Delete project + cleanup

POST /api/projects/:id/deploy         // Deploy/redeploy project
POST /api/projects/:id/start          // Start project stack
POST /api/projects/:id/stop           // Stop project stack

GET  /api/resources                   // Cluster resource usage
GET  /api/projects/:id/resources      // Project-specific resources
```

## 🧪 **Step 3: Test Simple UI-Only Stacks**

### **Test Plan**
1. **Create a simple Next.js project** via dashboard
2. **Deploy without Supabase** (UI-only)
3. **Verify URL generation**: `https://test-app.homelab`
4. **Test stack controls**: start/stop/delete

### **Expected Kubernetes Resources**
```yaml
# Namespace: app-test-app
apiVersion: v1
kind: Namespace
metadata:
  name: app-test-app

# Deployment: test-app-main
apiVersion: apps/v1
kind: Deployment
metadata:
  name: test-app-main
  namespace: app-test-app

# Service: test-app-main
apiVersion: v1
kind: Service
metadata:
  name: test-app-main
  namespace: app-test-app

# Ingress: test-app-ingress
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: test-app-ingress
  namespace: app-test-app
spec:
  rules:
  - host: test-app.homelab
```

## 🗄️ **Step 4: Test Supabase-per-Namespace**

### **Test Plan**
1. **Create a project with Supabase enabled**
2. **Deploy full stack**: Next.js + Supabase services
3. **Verify database schema creation**
4. **Test Supabase Studio access**

### **Expected Kubernetes Resources**
```yaml
# Namespace: app-fullstack-app
# Contains:
- fullstack-app-main          # Next.js application
- fullstack-app-auth          # Supabase Auth (GoTrue)
- fullstack-app-api           # Supabase API (PostgREST)
- fullstack-app-studio        # Supabase Studio (optional)
- fullstack-app-secrets       # Project-specific secrets
```

### **Database Schema**
```sql
-- PostgreSQL schema per project
CREATE SCHEMA project_fullstack_app;

-- Supabase tables in project schema
-- project_fullstack_app.auth_users
-- project_fullstack_app.auth_sessions
-- project_fullstack_app.custom_tables
```

## 🚀 **Deployment Status**

### **Current Status**
- ✅ ArgoCD applications created
- ✅ GitOps structure in place
- ✅ RBAC permissions configured
- ✅ Platform namespace ready
- 📋 Waiting for image builds
- 📋 Waiting for ArgoCD sync

### **Next Actions**

#### **1. Build Images**
```bash
# Build platform images
cd platform-dashboard && docker build -t platform-dashboard:latest .
cd platform-api && docker build -t platform-api:latest .
```

#### **2. Deploy via GitOps**
```bash
# Deploy to cluster
./scripts/deploy-platform-gitops.sh
```

#### **3. Monitor Deployment**
```bash
# Check ArgoCD sync status
kubectl get applications -n argocd

# Check platform pods
kubectl get pods -n platform

# Check platform ingress
kubectl get ingress -n platform
```

#### **4. Access Dashboard**
```bash
# Once deployed, access at:
https://platform.homelab
```

## 🔍 **Monitoring & Troubleshooting**

### **ArgoCD Monitoring**
```bash
# Check application sync status
kubectl describe application nextjs-platform -n argocd

# Check sync logs
kubectl logs -n argocd deployment/argocd-application-controller
```

### **Platform Logs**
```bash
# Dashboard logs
kubectl logs -f deployment/platform-dashboard -n platform

# API logs
kubectl logs -f deployment/platform-api -n platform
```

### **Common Issues**
1. **Images not found**: Build images locally or push to registry
2. **RBAC errors**: Check service account permissions
3. **Database connection**: Verify PostgreSQL is running
4. **Ingress not working**: Check Traefik configuration

## 🎯 **Success Criteria**

### **Step 1 Complete When:**
- ✅ Platform dashboard accessible at https://platform.homelab
- ✅ Platform API responding to health checks
- ✅ ArgoCD applications synced and healthy

### **Step 2 Complete When:**
- ✅ Dashboard can list cluster resources
- ✅ API can create/delete namespaces
- ✅ RBAC permissions working correctly

### **Step 3 Complete When:**
- ✅ Can create simple Next.js project via UI
- ✅ Project deploys to `app-{name}` namespace
- ✅ App accessible at `https://{name}.homelab`
- ✅ Can start/stop/delete project stack

### **Step 4 Complete When:**
- ✅ Can create project with Supabase enabled
- ✅ Supabase services deploy in project namespace
- ✅ Database schema created per project
- ✅ Supabase Studio accessible per project

Ready to execute Step 1! 🚀
