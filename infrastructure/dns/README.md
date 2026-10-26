# DNS Infrastructure

This directory contains DNS configuration for the Local AI infrastructure, specifically mDNS/Avahi services for local domain resolution.

## Overview

The DNS setup uses Avahi (mDNS) to provide automatic `.local` domain resolution across the network without requiring manual `/etc/hosts` file editing on each device.

## Files

- `avahi-chat-local.service` - Avahi service definition for `chat.local` domain

## Architecture

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Client Device │    │   RPi (Master)  │    │  Network Router │
│                 │    │                 │    │                 │
│ • Browser       │───▶│ • Avahi Daemon  │───▶│ • mDNS Relay    │
│ • mDNS Client   │    │ • Traefik       │    │ • DNS Forward   │
│                 │    │ • OpenWebUI     │    │                 │
└─────────────────┘    └─────────────────┘    └─────────────────┘
```

## Domain Mapping

| Domain | Target | Port | Service |
|--------|--------|------|---------|
| `chat.local` | RPi (192.168.131.101) | 443 | OpenWebUI via Traefik |
| `n8n.local` | RPi (192.168.131.101) | 443 | n8n via Traefik |
| `ollama.local` | RPi (192.168.131.101) | 443 | Ollama API via Traefik |

## Deployment

The DNS configuration is deployed automatically via the setup script:

```bash
./scripts/setup-dns.sh
```

## Manual Configuration

If you need to manually configure the Avahi service:

1. Copy the service file to the RPi:
   ```bash
   scp infrastructure/dns/avahi-chat-local.service chris@192.168.131.101:/tmp/
   ```

2. Install and configure on RPi:
   ```bash
   ssh chris@192.168.131.101
   sudo cp /tmp/avahi-chat-local.service /etc/avahi/services/
   sudo systemctl restart avahi-daemon
   ```

3. Verify resolution:
   ```bash
   ping chat.local
   curl -k https://chat.local
   ```

## Troubleshooting

### Domain Not Resolving

1. Check Avahi daemon status:
   ```bash
   ssh chris@192.168.131.101 'systemctl status avahi-daemon'
   ```

2. Verify service file:
   ```bash
   ssh chris@192.168.131.101 'ls -la /etc/avahi/services/'
   ```

3. Check mDNS traffic:
   ```bash
   avahi-browse -a
   ```

### SSL Certificate Warnings

The setup uses self-signed certificates, so browsers will show security warnings. This is expected for local development. You can:

1. Accept the warning and proceed (recommended for local use)
2. Add the certificate to your browser's trusted certificates
3. Set up proper CA certificates (advanced)

## Network Requirements

- **mDNS Support**: Most modern devices support mDNS automatically
- **Firewall**: Ensure UDP port 5353 is open for mDNS traffic
- **Network Topology**: Works best on flat networks (avoid complex VLANs)

## Compatibility

- ✅ **macOS**: Native mDNS support
- ✅ **Linux**: Avahi package required
- ✅ **Windows 10+**: Native mDNS support
- ✅ **iOS/Android**: Native mDNS support
- ⚠️ **Older Windows**: May require Bonjour Print Services
