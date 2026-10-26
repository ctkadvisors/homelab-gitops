# Tailscale Security Strategy

This document outlines the recommended security approach using Tailscale for your homelab access.

## The Perfect Hybrid Setup

### **For You (Daily Use): Tailscale**
- ✅ **Zero friction** - Connect once, works everywhere
- ✅ **No login prompts** - Direct access to services
- ✅ **Full network access** - Reach everything in your homelab
- ✅ **Perfect for APIs** - Scripts, mobile apps work seamlessly
- ✅ **Always secure** - Encrypted WireGuard tunnel

### **For Others (Selective Sharing): Cloudflare Tunnel**
- ✅ **Controlled sharing** - Share specific services only
- ✅ **No VPN setup** - Works in any browser
- ✅ **Authentication** - Add login when needed
- ✅ **Granular control** - Different access levels per service

## Architecture Overview

```
Your Devices (Tailscale) → Direct Access → Homelab Services
    ↓
No authentication needed, full network access

External Users → Cloudflare Tunnel → Selected Services
    ↓
Authentication required, limited access
```

## Implementation Plan

### Phase 1: Tailscale Integration (This Weekend)

1. **Set up Tailscale in K8s**:
   ```bash
   ./scripts/setup-tailscale-k8s.sh
   ```

2. **Enable subnet routing** in Tailscale admin console
3. **Test access** from your devices

### Phase 2: Hybrid Configuration (Next Week)

1. **Keep Cloudflare Tunnel** for selective sharing
2. **Configure service-specific access**
3. **Document access patterns**

## Access Patterns

### **Your Daily Workflow (Tailscale)**
```bash
# Connect to Tailscale (once per device)
tailscale up

# Access services directly - no additional auth
https://chat.homelab
https://n8n.homelab
https://platform.homelab
https://grafana.homelab
https://argocd.homelab

# APIs work seamlessly
curl https://ollama.homelab/api/generate
curl https://api.homelab/rest/v1/...
```

### **Sharing with Others (Cloudflare)**
```bash
# Share specific services with authentication
https://chat.ctkadvisors.net      # → Requires login
https://platform.ctkadvisors.net  # → Requires login

# Keep admin tools private (Tailscale only)
https://argocd.homelab     # → Only via Tailscale
https://grafana.homelab    # → Only via Tailscale
```

## Security Benefits

### **Network Segmentation**
- **Tailscale network**: Your trusted devices only
- **Public internet**: Limited access via Cloudflare
- **Local network**: Full access when at home

### **Zero Trust Principles**
- **Device authentication**: Only your registered devices
- **Encrypted tunnels**: All traffic encrypted end-to-end
- **Minimal exposure**: Only necessary services exposed publicly

### **Defense in Depth**
1. **Tailscale ACLs**: Control which devices can access what
2. **Kubernetes Network Policies**: Restrict pod-to-pod communication
3. **Service-level auth**: Individual service authentication where needed
4. **Cloudflare protection**: DDoS and bot protection for public services

## Tailscale Configuration

### **Device Setup**
```bash
# Install Tailscale on your devices
# macOS
brew install tailscale

# iOS/Android
# Install from App Store/Play Store

# Connect to your tailnet
tailscale up
```

### **ACL Configuration (Optional)**
```json
{
  "acls": [
    {
      "action": "accept",
      "src": ["chris@yourdomain.com"],
      "dst": ["tag:k8s-router:*"]
    }
  ],
  "tagOwners": {
    "tag:k8s-router": ["chris@yourdomain.com"]
  }
}
```

## Service Access Matrix

| Service | Tailscale Access | Cloudflare Access | Reasoning |
|---------|------------------|-------------------|-----------|
| **chat.homelab** | ✅ Direct | ✅ With auth | Personal use + sharing |
| **n8n.homelab** | ✅ Direct | ✅ With auth | Automation + demos |
| **platform.homelab** | ✅ Direct | ✅ With auth | Development + sharing |
| **dashboard.homelab** | ✅ Direct | ✅ With auth | Overview + sharing |
| **grafana.homelab** | ✅ Direct | ❌ Private | Sensitive monitoring |
| **argocd.homelab** | ✅ Direct | ❌ Private | Critical infrastructure |
| **git.homelab** | ✅ Direct | ❌ Private | Source code access |
| **ollama.homelab** | ✅ Direct | ⚠️ API only | API endpoint |
| **api.homelab** | ✅ Direct | ⚠️ API only | Supabase API |

## Management Commands

### **Tailscale Status**
```bash
# Check K8s Tailscale status
kubectl logs -n tailscale deployment/tailscale-subnet-router

# Check your device status
tailscale status

# Check subnet routes
tailscale status --json | jq '.Self.PrimaryRoutes'
```

### **Troubleshooting**
```bash
# Restart Tailscale in K8s
kubectl rollout restart deployment/tailscale-subnet-router -n tailscale

# Check connectivity from K8s
kubectl exec -n tailscale deployment/tailscale-subnet-router -- tailscale ping <your-device-ip>

# Test service access
curl -k https://chat.homelab
```

## Cost Analysis

| Solution | Monthly Cost | Setup Time | Maintenance |
|----------|--------------|------------|-------------|
| **Tailscale** | $0 (up to 3 users) | 30 min | Minimal |
| **Cloudflare Tunnel** | $0 | 30 min | Minimal |
| **Combined** | $0 | 1 hour | Minimal |

## Security Monitoring

### **Tailscale Logs**
- Device connections/disconnections
- Route advertisements
- ACL violations (if configured)

### **Access Patterns**
- Monitor which devices access which services
- Set up alerts for unusual access patterns
- Regular review of connected devices

## Emergency Procedures

### **If Tailscale Goes Down**
1. **Local access**: Services still work on local network
2. **Cloudflare backup**: Public services still accessible
3. **Direct IP access**: Can reach services via 192.168.131.200

### **If You're Locked Out**
1. **SSH to EliteMini**: `ssh elitemini`
2. **Restart Tailscale**: `kubectl rollout restart deployment/tailscale-subnet-router -n tailscale`
3. **Check logs**: `kubectl logs -n tailscale deployment/tailscale-subnet-router`

## Migration from Current Setup

### **Step 1: Add Tailscale**
```bash
# Deploy Tailscale to K8s
./scripts/setup-tailscale-k8s.sh

# Test access from your devices
curl -k https://chat.homelab
```

### **Step 2: Update Workflows**
- Start using `.homelab` URLs via Tailscale
- Keep `.ctkadvisors.net` URLs for sharing
- Update bookmarks and scripts

### **Step 3: Optimize**
- Remove public access from admin services
- Configure Tailscale ACLs if needed
- Set up monitoring and alerts

## Recommended Next Steps

1. **This Weekend**: Run `./scripts/setup-tailscale-k8s.sh`
2. **Test thoroughly**: Verify all services work via Tailscale
3. **Update workflows**: Switch to Tailscale for daily use
4. **Configure sharing**: Set up Cloudflare Access for public services
5. **Document**: Update team docs with new access patterns

This gives you the best of both worlds: frictionless access for you, controlled sharing for others, and enterprise-grade security throughout.
