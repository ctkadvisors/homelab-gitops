# GitOps Lessons Learned

## Core Principle: STRICT GitOps Enforcement

**NEVER break the GitOps workflow.** All changes must go through git commits and ArgoCD sync.

## What NOT to Do ❌

### Manual kubectl Commands
- `kubectl apply -f file.yaml` 
- `kubectl patch deployment`
- `kubectl set image`
- `kubectl rollout restart`

**These are FORBIDDEN** - they bypass GitOps and create configuration drift.

### Manual Workarounds
- Copying files to remote servers and applying them
- "Quick fixes" to get things working faster
- Bypassing ArgoCD when it seems slow or broken

## What TO Do ✅

### 1. Trust the GitOps Process
- Commit changes to git
- Push to remote repository  
- Let ArgoCD sync automatically
- Wait for the process to complete

### 2. Debug ArgoCD Issues Properly
When ArgoCD isn't syncing:
- Check application status: `kubectl get applications -n argocd`
- Review sync errors: `kubectl get application <app> -n argocd -o yaml`
- Fix configuration issues in git, don't bypass with manual commands
- Use ArgoCD refresh/sync operations if needed

### 3. Proper Troubleshooting Workflow
1. **Identify the issue** - Why isn't ArgoCD syncing?
2. **Fix in git** - Update configurations, paths, etc.
3. **Commit and push** - Let GitOps handle deployment
4. **Verify sync** - Check ArgoCD application status
5. **Wait patiently** - Don't rush to manual fixes

## Recent Example: Monitoring Dashboards

### What Went Wrong
- Created new Grafana dashboards
- ArgoCD had path issues in kustomization.yaml
- Instead of fixing the GitOps configuration, applied dashboards manually
- Broke the GitOps principle

### What Should Have Been Done
1. **Identified the path issue** in kustomization.yaml
2. **Fixed the paths** to point to correct dashboard locations
3. **Committed the fix** to git
4. **Let ArgoCD sync** the corrected configuration
5. **Verified deployment** through GitOps

### The Fix
- Moved dashboard files to correct location: `k8s-kustomized/base/monitoring/dashboards/`
- Updated kustomization.yaml paths to use local references
- Updated Grafana deployment to mount new dashboard ConfigMaps
- Committed all changes and let ArgoCD sync
- **Result: Everything deployed correctly through GitOps**

## Key Learnings

### 1. GitOps is Not Optional
- It's not just a preference, it's a **strict requirement**
- Manual interventions create technical debt
- GitOps ensures reproducibility and auditability

### 2. Patience Over Speed
- It's better to wait for proper GitOps sync than rush with manual fixes
- Manual fixes often create more problems than they solve
- GitOps might seem slower but it's more reliable

### 3. Debug the Process, Don't Bypass It
- When GitOps fails, fix the GitOps configuration
- Don't work around the process, improve the process
- ArgoCD errors usually point to real configuration issues

### 4. Configuration Drift is Dangerous
- Manual changes create drift between git and cluster state
- Drift makes future deployments unpredictable
- GitOps prevents drift by ensuring git is the single source of truth

## Best Practices

### File Organization
- Keep related resources in the same directory
- Use relative paths in kustomization.yaml when possible
- Test kustomize builds locally before committing

### ArgoCD Management
- Monitor application sync status regularly
- Set up proper sync policies (auto-sync, self-heal)
- Use ArgoCD UI to understand sync failures

### Change Management
- Always commit configuration changes
- Use descriptive commit messages
- Test changes in development environments when possible

## Remember
**"The entire stack must be recoverable from repository alone without manual interventions."**

This is not just a goal - it's a requirement that must be maintained at all times.
