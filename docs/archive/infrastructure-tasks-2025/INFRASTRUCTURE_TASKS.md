# Infrastructure Improvement Tasks

**Last Updated**: June 22, 2025
**Purpose**: Actionable task list for infrastructure improvements based on code analysis

## Priority 1: Critical Security Issues

### Task: Implement Sealed Secrets for Secret Management
**Problem**: Hardcoded database passwords in `k8s-kustomized/base/database/postgresql.yaml`
**Solution**: Deploy SealedSecret controller for GitOps-compliant secret management
**Files to Modify**:
- Create: `k8s-kustomized/base/infrastructure/sealed-secrets.yaml`
- Modify: `k8s-kustomized/base/database/postgresql.yaml` (remove hardcoded passwords)
- Create: `scripts/utilities/manage-secrets.sh` (kubectl plugin wrapper)

**Implementation Steps**:
1. Deploy SealedSecret controller via Kustomize
2. Generate sealed secrets for database passwords
3. Update PostgreSQL deployment to use sealed secrets
4. Test secret rotation workflow
5. Document secret management procedures

### Task: Clean Legacy TLS Assets
**Problem**: TLS private keys committed to Git in `k8s-kustomized/overlays/production/tls-secrets.yaml`
**Solution**: Remove private keys and rely on cert-manager
**Files to Modify**:
- Remove: Private key data from `tls-secrets.yaml`
- Verify: cert-manager is handling certificate automation

## Priority 2: Storage and Backup

### Task: Implement Local Node Storage
**Problem**: Remove NAS dependency, use local 1TB drives on nodes
**Solution**: Configure local persistent volumes on Jetson and EliteMini nodes
**Files to Modify**:
- `k8s-kustomized/base/storage/` - replace NAS with local storage
- Update storage classes to use local node storage
- Remove SMB CSI driver dependencies

### Task: Implement Backup Validation
**Problem**: No automated backup testing or disaster recovery validation
**Solution**: Create backup validation and testing procedures
**Files to Create**:
- `scripts/utilities/validate-backups.sh`
- `scripts/utilities/test-disaster-recovery.sh`
- Documentation for backup/restore procedures

## Priority 3: Observability Improvements

### Task: Deploy Log Aggregation
**Problem**: Loki configuration exists (`infrastructure/monitoring/loki-config.yml`) but not deployed in K8s
**Solution**: Convert existing config to Kubernetes manifests
**Files to Create**:
- `k8s-kustomized/base/monitoring/loki.yaml`
- `k8s-kustomized/base/monitoring/promtail.yaml`
**Files to Modify**:
- `k8s-kustomized/base/monitoring/kustomization.yaml` (add new resources)

### Task: Fix AlertManager Notifications
**Problem**: AlertManager webhook points to localhost (non-functional)
**Solution**: Configure homelab-appropriate notification channels
**Options**:
- Slack webhook integration
- Discord webhook for simple notifications
- Email via Gmail SMTP
- Pushover/Ntfy for mobile alerts

**Files to Modify**:
- `k8s-kustomized/base/monitoring/alertmanager.yaml`

### Task: Add ArgoCD Monitoring
**Problem**: No ArgoCD metrics integration in Prometheus
**Solution**: Add ArgoCD metrics scraping configuration
**Files to Modify**:
- `k8s-kustomized/base/monitoring/prometheus.yaml`

## Priority 4: Maintenance and Cleanup

### Task: Script Consolidation
**Problem**: 47 shell scripts with overlapping functionality
**Goal**: Reduce to ~15 focused scripts
**Categories to Create**:
- `scripts/deploy.sh` (complete deployment)
- `scripts/manage-services.sh` (service operations)
- `scripts/validate.sh` (testing and validation)
- `scripts/utilities/` (helper functions)

**Scripts to Evaluate for Removal/Consolidation**:
- Multiple deployment scripts with similar functionality
- One-off scripts that can be integrated into main workflows

### Task: Configuration Value Centralization
**Problem**: 46+ hardcoded IP addresses and values in scripts
**Solution**: Create environment configuration files
**Files to Create**:
- `config/environments/homelab.env`
- `config/hostnames.yaml`
**Scripts to Update**: All deployment and utility scripts

### Task: Documentation Restructuring
**Problem**: 15+ markdown files at root level
**Solution**: Organize into logical hierarchy
**Proposed Structure**:
```
docs/
├── user/           # User-facing guides
├── developer/      # Development workflows
├── operations/     # Operational procedures
├── architecture/   # Technical documentation
└── legacy/         # Archive old docs
```

## Priority 5: Feature Extensions

### Task: Photo Backup Integration - DEFERRED
**Status**: DEFERRED pending faster storage solution
**Reason**: Current NAS too slow, will revisit with new storage device

### Task: Resource Optimization
**Problem**: Fixed resource allocations without optimization
**Solution**: Analyze and tune resource requests/limits
**Investigation Required**:
1. Check current resource utilization across nodes
2. Identify over/under-allocated services
3. Adjust resource specifications

## Ongoing Tasks

### Task: GitOps Drift Detection
**Purpose**: Identify any manual changes bypassing GitOps workflow
**Process**:
1. Compare live cluster state with Git repository
2. Document any discovered drift
3. Either commit legitimate changes or revert through GitOps

### Task: Dependency Updates
**Components to Monitor**:
- ArgoCD version updates
- Prometheus/Grafana stack updates
- Kubernetes/K3s version compatibility
- Container image updates (especially GPU-specific images)

## Configuration Fixes Needed

### Hardcoded Values to Centralize
**IP Addresses**:
- EliteMini: 192.168.131.111 (control plane)
- Jetson1: 192.168.131.123 (GPU worker)
- Jetson2: 192.168.131.163 (GPU worker)
- EliteMini2: 192.168.131.209 (compute worker)
- Synology NAS: valhalla.local
- ~~raspberrypi1: 192.168.131.101~~ (REMOVED - node failed/offline)

**Paths and URLs**:
- /opt/* data directories
- Repository URLs
- Service endpoints

### Service Configuration Issues
**Complex Patches**: Production overlay has 60+ lines of patches indicating base configuration needs refinement
**Duplication**: Similar configurations repeated across overlays without proper abstraction

## Success Criteria

### Security
- [ ] Zero hardcoded secrets in Git repository
- [ ] Functional secret management with rotation capability
- [ ] Backup and recovery procedures validated

### Operations  
- [ ] Functional log aggregation and alerting
- [ ] Sub-5-minute deployment from Git to cluster
- [ ] Automated backup validation

### Maintenance
- [ ] Script count reduced from 47 to <15
- [ ] Documentation organized and current
- [ ] Configuration centralized and parameterized

### Extensions
- [ ] Photo management system (deferred pending faster storage)
- [ ] Local node storage implementation (1TB drives)
- [ ] Future NAS integration with faster device

---

## CRITICAL CLUSTER ISSUES DISCOVERED (June 22, 2025)

### Immediate Action Required
1. **ArgoCD Apps Out of Sync**: homelab-apps and monitoring-stack need manual sync
2. **GPU Exporters Failing**: nvidia-dcgm-exporter crash looping (NVML initialization error)  
3. **n8n Service Issues**: Duplicate pods, one pending due to node affinity mismatch
4. **Platform Build Failures**: build pods in error state
5. **Orphaned PVC**: gitea-data PVC stuck in Terminating state

### Node Status
- ✅ elitemini (control-plane): Ready, 13d uptime
- ✅ elitemini2: Ready, 25h uptime  
- ✅ jetson1: Ready, 9d uptime
- ✅ jetson2: Ready, 9d uptime
- ❌ raspberrypi1: NotReady (removed from network) - **CLEANED UP**

**Next Session Priorities**:
1. ✅ **Clean up raspberrypi1 references** - COMPLETED
2. Fix ArgoCD sync issues
3. Debug GPU exporter NVML failures  
4. Resolve n8n duplicate pod issues
5. Fix Synology NAS integration