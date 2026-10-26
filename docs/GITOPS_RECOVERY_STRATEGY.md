# GitOps Recovery Strategy & Backup Procedures

## 🚨 Emergency Recovery Protocol

### **DEFCON 1: Complete Infrastructure Failure**

```bash
# 1. Identify last known working commit
git log --oneline --grep="WORKING\|SUCCESS\|STABLE" -10

# 2. Force ArgoCD to known good state
kubectl patch application homelab-apps -n argocd --type merge \
  -p '{"spec":{"source":{"targetRevision":"KNOWN_GOOD_COMMIT"}}}'

# 3. Delete failed application and recreate
kubectl delete application homelab-apps -n argocd
kubectl apply -f argocd/homelab-apps.yaml

# 4. Monitor recovery
watch kubectl get applications -n argocd
```

### **DEFCON 2: Partial Service Failure**

```bash
# 1. Check ArgoCD sync status
kubectl get applications -n argocd

# 2. Force sync specific resources
kubectl patch application homelab-apps -n argocd --type merge \
  -p '{"operation":{"sync":{"syncStrategy":{"force":true}}}}'

# 3. Restart failed pods
kubectl delete pods -n NAMESPACE -l app=FAILED_SERVICE
```

### **DEFCON 3: Configuration Drift**

```bash
# 1. Compare cluster state vs Git
kubectl diff -f k8s-kustomized/overlays/production/

# 2. Identify manual changes
kubectl get events --sort-by='.lastTimestamp' | grep -v "Normal"

# 3. Commit missing configurations
git add . && git commit -m "Fix configuration drift"
```

## 🔄 Backup Strategy

### **1. Git Repository Backup**
```bash
# Daily automated backup
#!/bin/bash
DATE=$(date +%Y%m%d)
git clone --mirror https://github.com/ctkadvisors/new_localai.git backup-$DATE
tar -czf homelab-backup-$DATE.tar.gz backup-$DATE/
```

### **2. Cluster State Backup**
```bash
# Export all resources
kubectl get all --all-namespaces -o yaml > cluster-state-$(date +%Y%m%d).yaml

# Export specific critical resources
kubectl get configmaps,secrets,persistentvolumes -A -o yaml > cluster-config-$(date +%Y%m%d).yaml
```

### **3. DNS Configuration Backup**
```bash
# Backup RPi DNS config
ssh rpi "sudo cp /etc/dnsmasq.d/localai.conf /backup/dns-$(date +%Y%m%d).conf"
```

## 📋 Recovery Procedures

### **Scenario 1: ArgoCD Corruption**
```bash
# 1. Reinstall ArgoCD
kubectl delete namespace argocd
kubectl create namespace argocd
kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml

# 2. Restore applications
kubectl apply -f argocd/homelab-apps.yaml
```

### **Scenario 2: MetalLB Failure**
```bash
# 1. Delete and recreate MetalLB
kubectl delete namespace metallb-system
kubectl apply -f k8s-kustomized/base/networking/metallb.yaml

# 2. Apply RBAC fix
kubectl apply -f k8s-kustomized/base/networking/metallb-rbac-fix.yaml
```

### **Scenario 3: DNS Failure**
```bash
# 1. Restore DNS config from backup
ssh rpi "sudo cp /backup/dns-YYYYMMDD.conf /etc/dnsmasq.d/localai.conf"
ssh rpi "sudo systemctl restart dnsmasq"

# 2. Or apply from Kubernetes
kubectl apply -f k8s-kustomized/base/networking/dns-config.yaml
```

## 🎯 GitOps Best Practices

### **DO:**
- ✅ Always commit manual fixes immediately
- ✅ Test changes in staging before production
- ✅ Use descriptive commit messages with impact
- ✅ Tag stable releases for easy rollback
- ✅ Monitor ArgoCD sync status continuously
- ✅ Document all emergency procedures

### **DON'T:**
- ❌ Apply manual kubectl changes without committing
- ❌ SSH into nodes for permanent configuration changes
- ❌ Ignore ArgoCD OutOfSync warnings
- ❌ Delete resources without understanding dependencies
- ❌ Skip testing after major changes

## 🔍 Monitoring & Alerting

### **Critical Metrics to Monitor:**
- ArgoCD application sync status
- Pod restart counts and failure rates
- DNS resolution success rates
- LoadBalancer IP accessibility
- Certificate expiration dates

### **Alert Conditions:**
- ArgoCD application OutOfSync > 5 minutes
- Pod CrashLoopBackOff > 3 restarts
- DNS resolution failures > 10%
- LoadBalancer IP unreachable
- Disk space < 20% on any node

## 📚 Recovery Runbooks

### **Quick Reference Commands:**
```bash
# Check overall health
kubectl get nodes,pods --all-namespaces | grep -v Running

# Force ArgoCD sync
kubectl patch application homelab-apps -n argocd --type merge \
  -p '{"operation":{"sync":{"syncStrategy":{"force":true}}}}'

# Restart all failed pods
kubectl get pods --all-namespaces --field-selector=status.phase!=Running \
  -o jsonpath='{range .items[*]}{.metadata.namespace}{" "}{.metadata.name}{"\n"}{end}' | \
  xargs -n2 kubectl delete pod -n

# Check DNS resolution
nslookup dashboard.homelab 192.168.131.101

# Test LoadBalancer connectivity
curl -I http://192.168.131.200
```

## 🏷️ Commit Tagging Strategy

### **Tag Format:**
- `stable-YYYYMMDD-HH` - Verified working state
- `emergency-fix-YYYYMMDD` - Critical hotfixes
- `rollback-safe-YYYYMMDD` - Known rollback points

### **Example:**
```bash
# Tag current working state
git tag -a stable-20250608-04 -m "All services operational, MetalLB fixed"
git push origin stable-20250608-04

# Use for emergency rollback
kubectl patch application homelab-apps -n argocd --type merge \
  -p '{"spec":{"source":{"targetRevision":"stable-20250608-04"}}}'
```

---

**Remember: In GitOps, Git is the single source of truth. 
If it's not in Git, it doesn't exist in production.**
