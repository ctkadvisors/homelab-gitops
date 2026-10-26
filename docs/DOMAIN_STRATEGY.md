# Domain Strategy Guide

## Overview

The Local AI Homelab uses a dual-domain strategy to separate public and private services based on access patterns and security requirements.

## Domain Types

### Internal Domains (*.homelab)

**Access Method**: Tailscale VPN only  
**Purpose**: Administrative interfaces, monitoring, and private development tools  
**Security**: Network-level isolation via VPN

**Services:**
- `argocd.homelab` - GitOps deployment management
- `grafana.homelab` - Monitoring dashboards and metrics
- `prometheus.homelab` - Metrics collection API
- `alertmanager.homelab` - Alert management interface
- `git.homelab` - Gitea repository hosting and container registry

**Usage:**
- Infrastructure administration
- Monitoring and observability
- Source code management
- Container registry access
- Private development tools

### External Domains (*.example.com)

**Access Method**: Public internet with SSL certificates  
**Purpose**: User-facing applications, APIs, and shared tools  
**Security**: Application-level authentication and authorization

**Services:**
- `chat.example.com` - OpenWebUI AI chat interface
- `n8n.example.com` - Workflow automation platform
- `platform.example.com` - Development platform dashboard
- `ollama.example.com` - AI inference API endpoints
- `mcpo.example.com` - MCPO Control Panel and tool management
- Various app domains - `{app-name}.example.com` for deployed applications

**Usage:**
- End-user applications
- Public API services
- Shared development tools
- Demonstration and sharing
- External integrations

## Access Patterns

### For Administrators
- **Internal access**: Connect via Tailscale, use *.homelab domains
- **External access**: Direct internet access to *.example.com domains
- **Dual access**: Many services available via both domain types

### For End Users
- **Primary access**: *.example.com domains via public internet
- **Internal access**: May access via Tailscale if granted access

### For APIs and Integrations
- **Public APIs**: Use *.example.com endpoints
- **Internal services**: Use cluster-internal service discovery
- **Cross-service communication**: Kubernetes service DNS

## Security Considerations

### Internal Domain Security
- Network isolation via Tailscale VPN
- No direct internet exposure
- Administrative access patterns
- Infrastructure management interfaces

### External Domain Security
- SSL/TLS termination via Let's Encrypt
- Application-level authentication where needed
- Rate limiting and DDoS protection via Traefik
- Public-facing but controlled access

## Configuration Examples

### Accessing Monitoring (Internal)
```bash
# Requires Tailscale connection
open https://grafana.homelab
curl https://prometheus.homelab/api/v1/query?query=up
```

### Accessing AI Services (External)
```bash
# Public internet access
open https://chat.example.com
curl https://ollama.example.com/api/generate -d '{"model":"llama2","prompt":"Hello"}'
```

### Development Workflow
```bash
# Push code (internal)
git push origin main  # to git.homelab

# Check deployment (internal)
open https://argocd.homelab

# Test application (external)
open https://my-app.example.com
```

## Best Practices

1. **Use appropriate domain for access pattern**
   - Internal/admin tasks → *.homelab
   - Public/user tasks → *.example.com

2. **Document access requirements**
   - Specify Tailscale requirement for internal services
   - Provide public URLs for shared resources

3. **Maintain domain consistency**
   - Keep internal services on *.homelab
   - Keep public services on *.example.com
   - Update documentation when services change domains

4. **Security awareness**
   - Internal domains require VPN access
   - External domains are internet-accessible
   - Choose appropriate domain based on sensitivity