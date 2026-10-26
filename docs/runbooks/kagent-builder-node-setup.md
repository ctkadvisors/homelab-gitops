# kagent-builder node provisioning (elitemini2, jetson2)

Manual, one-time, **not GitOps-managed** — same posture as
`spark-llamaswap.yaml`'s Endpoints object. This sets up the dedicated,
low-privilege `kagent-builder` OS account that `homelab-builder`'s
`shell.exec` tool SSHes into on each target node.

## Status

- **jetson2** (`10.0.0.75`): done, 2026-07-06.
- **elitemini2** (`10.0.0.74` per `config/network.yaml`): **not done** —
  node was unreachable over SSH during provisioning (pings fine, port 22
  refused after a reboot; possibly booted into Windows with OpenSSH not
  running, or Ubuntu not fully up). Revisit and run the same steps below
  against it once it's confirmed reachable. Until then, `shell.exec`'s
  `HOST_IPS` map in `shell-runner.ts` still lists `elitemini2`, but no
  requests targeting it will succeed (SSH connection refused) until this
  is completed.

Note: there is a separate, pre-existing `elitemini2`/`elite2` alias in
`~/.ssh/config` on the operator's Mac that actually points to
`10.0.0.66` (a Mac mini, part of the Exo cluster) — a historical
naming collision unrelated to the actual `elitemini2` k3s compute-worker.
Always use the explicit IP (`10.0.0.74`) from `config/network.yaml`
for this node, not the `elitemini2` SSH alias.

## 1. Generate the dedicated keypair (once, not per-node)

Run on your own machine, **not** on either target node:

```bash
ssh-keygen -t ed25519 -f ~/kagent-builder-ed25519 -N "" -C "kagent-builder@homelab"
```

Never reuse your personal SSH key for this account.

## 2. Create the `kagent-builder` user on the target node

```bash
ssh <node> "sudo useradd --create-home --shell /bin/bash --comment 'kagent homelab-builder agent' kagent-builder"
ssh <node> "sudo -u kagent-builder mkdir -p /home/kagent-builder/.ssh && sudo -u kagent-builder chmod 700 /home/kagent-builder/.ssh"
cat ~/kagent-builder-ed25519.pub | ssh <node> "sudo tee -a /home/kagent-builder/.ssh/authorized_keys > /dev/null"
ssh <node> "sudo chown kagent-builder:kagent-builder /home/kagent-builder/.ssh/authorized_keys && sudo chmod 600 /home/kagent-builder/.ssh/authorized_keys"
```

Verify no sudo access:

```bash
ssh <node> "sudo -l -U kagent-builder"
```
Expected: "User kagent-builder is not allowed to run sudo on `<node>`."

Verify the key works and privilege escalation is blocked:

```bash
ssh -i ~/kagent-builder-ed25519 -o StrictHostKeyChecking=accept-new -o BatchMode=yes kagent-builder@<node-ip> "whoami; sudo whoami"
```
Expected: `whoami` prints `kagent-builder`; `sudo whoami` fails (no
password source / not in sudoers).

**Note (jetson2 specifically):** `sudo` on jetson2 required an interactive
password for the operator's own account, which can't be supplied through
a non-interactive session. A one-time `NOPASSWD` sudoers entry for the
operator's own user was added first (`/etc/sudoers.d/chris-nopasswd`,
validated with `visudo -c`) to unblock the rest of this provisioning —
this is a pre-existing convenience setting on that node, not something
`kagent-builder` itself has.

## 3. Node-side resource cap (the actual killswitch)

`shell.exec`'s compute happens over SSH on the node itself, not inside a
k8s pod — pod resource limits don't cover it. This systemd slice cap is
the boundary that matters:

```bash
ssh <node> "id -u kagent-builder"   # get the numeric UID, e.g. 2010
ssh <node> "sudo mkdir -p /etc/systemd/system/user-<UID>.slice.d"
cat <<'EOF' | ssh <node> "sudo tee /etc/systemd/system/user-<UID>.slice.d/10-kagent-builder-cap.conf > /dev/null"
[Slice]
CPUQuota=200%
MemoryMax=4G
MemoryHigh=3G
EOF
ssh <node> "sudo systemctl daemon-reload"
```

Verify (only meaningful once `kagent-builder` has had an active session —
the slice is created on first login via `pam_systemd`):

```bash
ssh <node> "systemctl show user-<UID>.slice --property=CPUQuotaPerSecUSec,MemoryMax"
```
Expected: `CPUQuotaPerSecUSec=2s` (200% = 2 cores), `MemoryMax=4294967296`
(4G).

## jetson2 — actual values (for reference)

- `kagent-builder` UID/GID: `2010`
- Cgroup slice: `/etc/systemd/system/user-2010.slice.d/10-kagent-builder-cap.conf`
- Verified live: `CPUQuotaPerSecUSec=2s`, `MemoryMax=4294967296`

## Private key handling

The private key (`~/kagent-builder-ed25519`) gets sealed into
`Secret/kagent-builder-ssh-key` in `kagent-system` (see
`k8s-kustomized/overlays/production/kagent/homelab-builder-secrets.yaml`)
— delete the local copy once that's committed, or keep it somewhere
outside any git working tree.
