# Power-Outage Recovery Runbook (written 2026-08-12)

## Why this exists

Power was lost on 2026-08-11. The DGX Spark and both Jetsons came back on their
own; **elitemini (K3s control plane) and elitemini2 (worker) did not power back
on** — their BIOS is not set to restore power after AC loss, and wake-on-LAN is
not armed (magic packets to elitemini2's known MAC were ignored). Everything on
the cluster — Traefik at 10.0.0.200, mlflow.example.com, and the
qwen-coder MCP (`qwen-coder.example.com/mcp`) — was down until someone pressed
the power buttons.

The qwen-coder MCP cannot fail over by design: the Deployment is pinned to the
control-plane node (`nodeSelector: node-type: control-plane`) because only
elitemini has tailnet reachability to the Spark, and its PVC is `local-path`
(node-local). Control plane down ⇒ MCP down. The Spark itself was fine the
whole time (`coder` verified serving at http://100.64.0.69:9090/v1).

Diagnostic gotcha that cost time: with the cluster down, ARP for .200 still
answered — jetson2's MetalLB speaker keeps announcing the LB IP even with the
control plane gone (jetson2 eno1 = `3c:6d:66:1e:b3:f0`). ARP-alive ≠ service-alive.

## Recovery (physical, in order)

1. Press power on **elitemini** (control plane). This alone restores Traefik,
   MetalLB, mlflow, and qwen-coder MCP.
2. Press power on **elitemini2** (worker: n8n, platform-api/dashboard, openwebui).
3. Verify from the Mac:
   ```sh
   nc -z -G 3 10.0.0.76 6443 && echo API up
   KUBECONFIG=~/.kube/config-homelab kubectl get nodes -o wide
   KUBECONFIG=~/.kube/config-homelab kubectl -n ai-services get pods -l app=qwen-coder
   curl -s -o /dev/null -w '%{http_code}\n' https://mlflow.example.com
   claude mcp list   # qwen-coder should connect
   ```
   Note: elitemini2's IP drifts via DHCP (.74 → .66 → .64…) — trust
   `kubectl get nodes -o wide`, not old configs.

## Hardening status (updated 2026-08-12 after recovery)

Done on 2026-08-12, right after the boxes came back:

- **NIC-level WoL armed and persisted on both eliteminis** — `ethtool` installed,
  `Wake-on: g` verified, persisted via NetworkManager:
  `nmcli connection modify "Wired connection 1" 802-3-ethernet.wake-on-lan magic`.
- **MACs recorded** in `config/network.yaml`:
  - elitemini enp2s0: `58:47:ca:7e:5b:f1`
  - elitemini2 enp2s0: `58:47:ca:7e:5d:27`
  - (reference: jetson2 eno1 `3c:6d:66:1e:b3:f0`, DGX Spark at .69)
- `systemctl is-enabled k3s` on elitemini: enabled.
- elitemini2 drifted again during this reboot: now **10.0.0.58**.

Also done 2026-08-12 — **DHCP drift fixed with host-side static IPs**:

- Both eliteminis pinned via NetworkManager (`nmcli con mod "Wired connection 1"
  ipv4.method manual ipv4.addresses <ip>/22 ipv4.gateway 10.0.0.1
  ipv4.dns "10.0.0.1,8.8.8.8" ipv4.ignore-auto-dns yes`):
  elitemini = .76, elitemini2 = .58. Same IPs they already held, so no k3s
  re-registration. This also replaced elitemini's stale 192.168.131.101 DNS.
- Why not a Deco reservation: **address reservation is app-only** on the Deco
  BE11000. Verified 2026-08-12 — the local web UI (10.0.0.1) is read-only
  (Status/System), and the local encrypted luci API 404s/errors every
  reservation-shaped form (`admin/dhcps?form=reservation` etc.). The Deco app
  does it via TP-Link's cloud.
- **Superseded 2026-09-15 for elitemini2:** static without a lease made the Deco
  blackhole .58 for 7-27 s every minute. It now has an app reservation
  (More > Advanced > Address Reservation, MAC typed in by hand:
  `58-47-CA-7E-5D-27` -> `10.0.0.58`) and runs `ipv4.method auto`, with
  .58 kept as a static fallback. The app's own "elitemini2" entry is the Wi-Fi
  card's MAC (...7F-64), not the wired NIC. elitemini is also on DHCP now (.76).

Still owed (need physical/BIOS access):

1. **BIOS on both eliteminis: "Restore on AC Power Loss" = Power On.**
   This is the actual durable fix; everything else is a workaround.
2. **BIOS: enable Wake-on-LAN** (often "Power On By PCI-E/Onboard LAN") —
   the OS side is already armed, but S5 wake won't work until BIOS allows it.

To wake a box once BIOS WoL is on (from any LAN host, e.g. jetson1):

```sh
python3 -c '
import socket
mac = "58:47:ca:7e:5b:f1"  # elitemini; elitemini2 = 58:47:ca:7e:5d:27
d = bytes.fromhex("ff"*6 + mac.replace(":","")*16)
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
s.sendto(d, ("192.168.71.255", 9))'
```

## Reference: what survives an outage today

| Box | Auto-recovers? | Why |
|---|---|---|
| DGX Spark (.69 / TS 100.64.0.69) | yes | boots on AC restore; llama-swap is a systemd user service with linger |
| jetson1 (.73), jetson2 (.75) | yes | boot on AC restore |
| elitemini (.76), elitemini2 | **no** | BIOS power-loss policy + no WoL — fix per above |
