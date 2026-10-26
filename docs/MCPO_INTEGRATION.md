# MCPO Integration Guide

## 🛠️ What is MCPO?

MCPO (MCP OpenAI Tool Server) is a proxy server that exposes MCP (Model Context Protocol) tools as standard OpenAPI endpoints. This allows you to use powerful MCP-based tools through familiar REST APIs.

## 🚀 Deployment

MCPO is automatically deployed as part of your k3s stack:

```bash
# Deploy complete stack (includes MCPO)
./scripts/deploy-complete-stack.sh

# Or deploy just applications (includes MCPO)
./scripts/deploy-apps.sh
```

## 🌐 Access Points

- **Public Access**: https://mcpo.example.com
- **Internal Access** (via Tailscale): https://mcpo.homelab  
- **OpenAPI Docs**: https://mcpo.example.com/docs
- **NodePort (testing)**: http://192.168.131.101:31800

## 🔧 Configuration

### Default Setup

MCPO is configured with:

- **MCP Server**: `mcp-server-time` (provides time-related tools)
- **API Key**: Auto-generated and stored in Kubernetes secret
- **Timezone**: America/New_York

### Customizing MCP Server

To use a different MCP server, edit `k8s/apps/mcpo.yaml`:

```yaml
args:
  - "--host"
  - "0.0.0.0"
  - "--port"
  - "8000"
  - "--api-key"
  - "$(MCPO_API_KEY)"
  - "--"
  - "uvx"
  - "your-mcp-server-command"
  - "--your-args"
```

## 🔗 OpenWebUI Integration

### Step 1: Access OpenWebUI Settings

1. Open https://chat.example.com
2. Go to ⚙️ **Settings**
3. Click on ➕ **Tools**

### Step 2: Add MCPO Tool Server

1. Enter URL: `https://mcpo.example.com` (or `https://mcpo.homelab` via Tailscale)
2. Click "Save"

### Step 3: Verify Connection

Look for the tool server indicator (🛠️) in the message input area.

## 📖 Available Tools

With the default `mcp-server-time` configuration, you get:

- **get_current_time**: Get current time in specified timezone
- **get_timezone_info**: Get timezone information
- **convert_time**: Convert time between timezones

View all available tools at: https://mcpo.example.com/docs

## 🔍 Troubleshooting

### Check MCPO Status

```bash
kubectl get pods -n ai-services -l app=mcpo
kubectl logs -f deployment/mcpo -n ai-services
```

### Test Direct Access

```bash
curl -k https://mcpo.local/
curl -k https://mcpo.local/docs
```

### Common Issues

1. **Service not accessible**: Check if Traefik is running and ingress is configured
2. **API key errors**: Verify the secret is created correctly
3. **MCP server fails**: Check logs for MCP server startup issues

## 🛡️ Security

- API key is auto-generated and stored securely in Kubernetes secrets
- HTTPS termination handled by Traefik
- Service runs with minimal privileges

## 📚 Further Reading

- [MCPO GitHub Repository](https://github.com/open-webui/mcpo)
- [OpenWebUI Tool Integration Docs](https://docs.openwebui.com/openapi-servers/open-webui/)
- [MCP Protocol Documentation](https://modelcontextprotocol.io/)
