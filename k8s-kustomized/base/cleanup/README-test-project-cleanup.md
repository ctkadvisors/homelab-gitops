# Test Project Namespaces Cleanup

## Overview

This directory contains GitOps-compliant cleanup manifests for removing failed and obsolete test project namespaces from the homelab cluster.

## Current Situation

The cluster currently has **9 test project namespaces** consuming resources with various states:

### Failed Namespaces (Priority 1 - Remove Immediately)

1. **platform-test-app**
   - Status: CrashLoopBackOff (10,122 restarts)
   - Error: `exec /usr/local/bin/docker-entrypoint.sh: exec format error`
   - Age: 35 days
   - Resources: 1 pod, 1 service, 1 deployment, 1 replicaset, 1 secret, 1 configmap

2. **project-supatest2**
   - Status: CreateContainerConfigError
   - Error: `secret "supatest2-secrets" not found`
   - Age: 35 days
   - Resources: 1 pod, 1 service, 1 deployment, 1 replicaset, 1 job, 2 secrets, 2 configmaps, 1 ingress

3. **project-supatest3**
   - Status: Partial failure (1 pod CrashLoopBackOff)
   - Error: `invalid URI query parameter: "search_path"` (database connection)
   - Age: 35 days  
   - Resources: 2 pods, 2 services, 2 deployments, 2 replicasets, 1 job, 3 secrets, 2 configmaps, 3 ingress

### Working But Obsolete Namespaces (Priority 2 - Remove When Safe)

4. **project-autotest**
   - Status: Running (1/1 pods healthy)
   - Reason: Test project no longer needed
   - Resources: 1 pod, 1 service, 1 deployment, 1 replicaset, 2 secrets, 2 configmaps, 1 ingress

5. **project-supatest**
   - Status: Running (1/1 pods healthy)
   - Reason: Test project no longer needed
   - Resources: 1 pod, 1 service, 1 deployment, 2 replicasets, 2 secrets, 2 configmaps, 1 ingress

6. **project-teeets**
   - Status: Running (1/1 pods healthy)
   - Reason: Test project no longer needed
   - Resources: 1 pod, 1 service, 1 deployment, 1 replicaset, 2 secrets, 2 configmaps, 1 ingress

7. **project-testproject**
   - Status: Running (1/1 pods healthy)
   - Reason: Test project no longer needed
   - Resources: 1 pod, 1 service, 1 deployment, 1 replicaset, 2 secrets, 2 configmaps, 1 ingress

### Preserved Namespaces

- **platform**: Main production platform namespace ✅ KEEP
- **platform-builds**: Build system namespace ✅ KEEP
- **project-test-v0-workflow-e2e**: No pods found, may be empty ⚠️ INVESTIGATE

## Cleanup Strategy

### Phase 1: Immediate Cleanup (Failed Namespaces)
Remove the 3 failing namespaces that are consuming resources without providing value:
- platform-test-app
- project-supatest2  
- project-supatest3

### Phase 2: Planned Cleanup (Working Test Namespaces)
Remove the 4 working test namespaces after confirming they're not needed:
- project-autotest
- project-supatest
- project-teeets
- project-testproject

## GitOps Cleanup Process

### 1. Pre-cleanup Verification
```bash
# Verify current state
kubectl get namespaces | grep -E 'project-|platform-'
kubectl get pods -A | grep -E 'CrashLoopBackOff|CreateContainerConfigError'

# Check resource usage
kubectl top pods -A | grep -E 'project-|platform-'
```

### 2. Safe Cleanup Execution
```bash
# Apply the cleanup manifest (this removes the namespaces and all resources)
kubectl delete -f k8s-kustomized/base/cleanup/test-project-namespaces-cleanup.yaml

# Alternative: Remove namespaces one by one for safety
kubectl delete namespace platform-test-app
kubectl delete namespace project-supatest2
kubectl delete namespace project-supatest3
# ... (continue for others after verification)
```

### 3. Post-cleanup Verification
```bash
# Verify namespaces are gone
kubectl get namespaces | grep -E 'project-|platform-'

# Check for any remaining resources
kubectl get pods -A | grep -E 'CrashLoopBackOff|CreateContainerConfigError'

# Verify cluster health
kubectl get nodes -o wide
kubectl top nodes
```

## Resource Impact Analysis

### Before Cleanup
- **Total Test Namespaces**: 7 (excluding investigation needed)
- **Failed Pods**: 3 (constantly restarting, consuming CPU/memory)
- **Working Test Pods**: 4 (consuming resources unnecessarily)
- **Ingress Routes**: 7 external domains pointing to test services
- **Secrets**: ~14 test secrets
- **ConfigMaps**: ~14 test configmaps

### After Cleanup  
- **Eliminated**: All test project resource consumption
- **Freed Resources**: CPU, memory, storage, and networking resources
- **Reduced Noise**: No more CrashLoopBackOff alerts/logs
- **Cleaner DNS**: Remove unused *.example.com test domains

## Safety Checks

### Before Executing Cleanup
1. ✅ Verify no production traffic to test domains
2. ✅ Confirm test projects are not referenced by other services
3. ✅ Backup any important test data (if needed)
4. ✅ Document current state for rollback (this README serves as documentation)

### During Cleanup
1. ✅ Remove one namespace at a time for safety
2. ✅ Monitor cluster health between deletions
3. ✅ Verify no production services are affected

### After Cleanup
1. ✅ Confirm all targeted resources are removed
2. ✅ Verify cluster stability and performance improvement
3. ✅ Update monitoring/alerting to remove references to deleted namespaces

## Rollback Plan

If cleanup causes issues, the namespaces can be recreated from:
1. Git history of this repository (if they were previously defined in code)
2. Container images are still available in registries
3. Database schemas may need recreation

However, since these are all test projects with known issues, rollback should not be necessary.

## Monitoring Improvements

After cleanup, expect:
- ✅ Reduced CrashLoopBackOff alerts
- ✅ Lower cluster resource utilization
- ✅ Cleaner namespace list
- ✅ Reduced log noise from failing applications
- ✅ More available resources for production workloads