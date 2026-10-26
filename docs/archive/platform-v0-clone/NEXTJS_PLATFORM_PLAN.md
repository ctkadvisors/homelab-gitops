# Next.js Application Hosting Platform

## 🎯 Vision

Create a **Vercel-like experience** for hosting Next.js applications on our homelab infrastructure, with multi-tenancy support and seamless integration with our Supabase backend.

## 🚀 Current State vs Target

### ✅ What We Have (Production Ready)

- **Infrastructure**: K3s cluster with monitoring, ArgoCD, Traefik
- **Backend**: Supabase with auth, database, realtime, API
- **Observability**: Prometheus, Grafana, Alertmanager
- **GitOps**: ArgoCD for infrastructure management

### 🎯 What We Need (Next.js Platform)

- **Application Hosting**: Dynamic Next.js app deployment
- **Multi-tenancy**: Multiple projects per team/user
- **CI/CD Pipeline**: Git-based deployments
- **Developer Experience**: Dashboard, logs, metrics per app

## 📋 Implementation Plan

### Phase 1: Core Platform (Week 1-2)

**Goal**: Deploy and manage Next.js apps via ArgoCD

#### 1.1 Next.js App Template

- [x] Create standardized Next.js app template
- [x] Kubernetes manifests for Next.js deployment
- [x] Environment variable management
- [x] Health checks and readiness probes

#### 1.2 Dynamic Deployment System

- [ ] ArgoCD Application-of-Applications pattern
- [ ] Namespace-per-app isolation
- [ ] Automatic ingress route generation
- [ ] TLS certificate management

#### 1.3 Basic Multi-tenancy

- [ ] App naming conventions (`team-project-env`)
- [ ] Resource quotas per namespace
- [ ] Network policies for isolation

### Phase 2: Developer Experience (Week 3-4)

**Goal**: Self-service app deployment and management

#### 2.1 Platform Dashboard

- [ ] Web UI for app management
- [ ] Deploy new apps from Git repos
- [ ] View app status, logs, metrics
- [ ] Environment variable management

#### 2.2 CI/CD Integration

- [ ] GitHub webhook integration
- [ ] Automatic builds on push
- [ ] Preview environments for PRs
- [ ] Production deployments on merge

#### 2.3 Observability per App

- [ ] App-specific Grafana dashboards
- [ ] Log aggregation per app
- [ ] Performance metrics
- [ ] Error tracking

### Phase 3: Advanced Features (Week 5-6)

**Goal**: Production-grade platform capabilities

#### 3.1 Database Integration

- [ ] Automatic Supabase project creation
- [ ] Database per app/environment
- [ ] Migration management
- [ ] Backup/restore capabilities

#### 3.2 Scaling & Performance

- [ ] Horizontal pod autoscaling
- [ ] Resource optimization
- [ ] CDN integration (optional)
- [ ] Build caching

#### 3.3 Security & Compliance

- [ ] RBAC for platform access
- [ ] Secret management
- [ ] Security scanning
- [ ] Audit logging

## 🏗️ Technical Architecture

### Application Deployment Flow

```
GitHub Repo → Webhook → Platform API → ArgoCD → K8s Deployment → Traefik Ingress
```

### Multi-tenancy Model

```
Namespace: team-project-env
- team: Organization/user identifier
- project: Application name
- env: development/staging/production
```

### URL Structure

```
https://app-name-team.homelab          # Production
https://app-name-team-staging.homelab  # Staging
https://app-name-team-pr-123.homelab   # PR Preview
```

## 🛠️ Technology Stack

### Core Platform

- **Container Orchestration**: Kubernetes (K3s)
- **GitOps**: ArgoCD for deployment management
- **Ingress**: Traefik with automatic TLS
- **Monitoring**: Prometheus + Grafana per app

### Platform Services

- **API**: Node.js/Express or Go for platform management
- **Dashboard**: Next.js web interface
- **Database**: PostgreSQL (shared with Supabase)
- **Build System**: Docker builds with caching

### Integration Points

- **Backend**: Supabase for auth, database, realtime
- **CI/CD**: GitHub Actions or GitLab CI
- **Monitoring**: Existing Prometheus/Grafana stack
- **DNS**: Existing homelab DNS setup

## 📊 Resource Planning

### Per Application

- **CPU**: 100m-500m (burstable)
- **Memory**: 128Mi-512Mi (burstable)
- **Storage**: 1Gi for app files
- **Database**: Shared PostgreSQL with per-app schemas

### Platform Overhead

- **Platform API**: 200m CPU, 256Mi RAM
- **Dashboard**: 100m CPU, 128Mi RAM
- **Build System**: 500m CPU, 1Gi RAM (burst)

### Node Distribution

- **EliteMini**: Platform services, production apps
- **Jetson Nodes**: Development/staging apps
- **RPi**: Monitoring, DNS, lightweight services

## 🔄 Migration Strategy

### From Current State

1. **Keep Existing**: All current infrastructure stays
2. **Add Platform**: Deploy platform services alongside
3. **Gradual Migration**: Move apps one by one
4. **Validate**: Test each app thoroughly

### Supabase Integration

- **Single Backend**: One Supabase instance serves all apps
- **Multi-schema**: Database schemas per app
- **Shared Auth**: Common authentication across apps
- **API Keys**: Per-app API key management

## 📈 Success Metrics

### Developer Experience

- **Deployment Time**: < 5 minutes from push to live
- **Setup Time**: < 10 minutes for new app
- **Reliability**: 99.9% uptime for platform services

### Resource Efficiency

- **Utilization**: > 70% CPU/memory utilization
- **Cost**: < $0.10 per app per month (electricity)
- **Scaling**: Support 50+ concurrent apps

### Platform Adoption

- **Apps Deployed**: 10+ apps in first month
- **Developer Satisfaction**: > 4.5/5 rating
- **Issue Resolution**: < 24 hours average

## 🚦 Getting Started

### Immediate Next Steps

1. **Create App Template**: Standard Next.js + Supabase template
2. **Design Namespace Strategy**: Implement multi-tenancy model
3. **Build Platform API**: Core deployment management
4. **Create Dashboard**: Basic web interface

### Week 1 Deliverables

- [ ] Next.js app template with Kubernetes manifests
- [ ] ArgoCD application-of-applications setup
- [ ] Basic platform API for app management
- [ ] Documentation for manual app deployment

Would you like me to start implementing any specific component of this plan?
