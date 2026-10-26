# Local AI Infrastructure TODO List

**Last Updated**: 2025-06-21

## ✅ Completed Tasks

- **Fix monitoring-stack ArgoCD application** - Resolved path issues, now using k8s-kustomized/base/monitoring
- **Deploy missing node-exporter and kube-state-metrics** - Complete monitoring stack deployed and functional
- **Fix Prometheus storage lock conflict** - Resolved deployment conflicts between old and new instances
- **Restore working n8n instance** - Fixed after MCP integration issues, now accessible at https://n8n.example.com

## 🔄 Pending Tasks

### High Priority
- **Design AI development platform integration** - Integrate Claude Code + Cursor/Augment + SDLC automation for idea-to-deployment workflow

### Medium Priority
- **Integrate n8n-mcp-memory** - Complete AI-generated workflow creation integration (image access issues to resolve)
- **Research iCloud backup integration** - Set up Apple Photos backup to NAS via Tailscale network
- **Enhance Platform (NextJS) integration** - Better integration with rest of infrastructure stack

## 📊 Infrastructure Status

### ✅ Working Services
- **Grafana**: https://grafana.example.com (credentials: admin/<set at install>)
- **Prometheus**: https://prometheus.example.com
- **n8n**: https://n8n.example.com
- **OpenWebUI**: https://chat.example.com
- **ArgoCD**: https://argocd.example.com
- **Platform**: https://platform.example.com

### 🔧 Monitoring Stack
- **Node Exporter**: Running on all 4 nodes (DaemonSet)
- **Kube State Metrics**: Running and collecting K8s metrics
- **Grafana**: Configured with Prometheus datasource
- **Prometheus**: Collecting metrics from all components

### 💾 Resource Allocation (EliteMini)
- **Current Usage**: 95% memory requests, 260% memory limits (overcommitted)
- **n8n**: Optimized to 1Gi memory request (was 2Gi)
- **Recommendation**: Monitor resource usage, consider moving some services to other nodes

## 🎯 Next Session Goals

1. **AI Development Platform** - Design the idea-to-deployment automation system
2. **MCP Integration** - Resolve image access and complete n8n-mcp-memory deployment
3. **iCloud Backup Research** - Investigate Apple Photos backup solutions with NAS integration
4. **Resource Optimization** - Better distribute services across cluster nodes

## 🚨 Known Issues

- **n8n-mcp-memory image access** - `ghcr.io/ctkadvisors/n8n-mcp-memory:main` requires authentication
- **EliteMini memory pressure** - Need to optimize service distribution
- **Legacy documentation** - Some cleanup still needed (DOCUMENTATION_AUDIT.md has details)

## 🔗 Key Repository Files

- **Main Documentation**: `CLAUDE.md` (single source of truth)
- **Documentation Audit**: `DOCUMENTATION_AUDIT.md` (cleanup status)
- **Quick Start**: `QUICK_START.md` (basic usage)
- **Troubleshooting**: `TROUBLESHOOTING.md` (common issues)

---

**GitOps Reminder**: ALL changes must go through Git → ArgoCD. Never use `kubectl` to modify resources directly.