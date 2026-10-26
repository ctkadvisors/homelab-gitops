# Kata Containers — microVM isolation for agent pods

Status: **LIVE 2026-09-01.** kata-deploy runs as the `kata-deploy` ArgoCD
Application (`base/argocd/applications/kata-deploy.yaml`, upstream chart
pinned to 4.1.0, manual sync). elitemini2 is installed and labeled
`katacontainers.io/kata-runtime=true`; RuntimeClasses `kata-qemu` /
`kata-clh` are chart-created. kagent agent pods run with
`runtimeClasses.default: kata-qemu` (see the kagent overlay
application.yaml). Smoke-test proof: guest kernel 6.18.35 vs host
6.8.0-138.

`runtimeclass.yaml` in this dir is a STAGED REFERENCE ONLY — the chart
owns the live RuntimeClasses; do not wire this dir into any overlay.

## How the install actually works (hard-won, 2026-09-01)

The old raw-YAML kata-deploy manifests are GONE upstream — it's a Helm
chart now (`tools/packaging/kata-deploy/helm-chart/kata-deploy`), managed
here declaratively via ArgoCD. Job deployment mode: a dispatcher hook
creates one node-pinned install Job per node in `job.nodes`, which stages
artifacts, writes containerd drop-ins, restarts the CRI, and labels the
node when Ready. Gotchas that cost real time:

1. **`defaultShim` must be an enabled shim.** Chart default is
   `qemu-runtime-rs` (Rust runtime, Kata 4.0+); with
   `shims.disableAll: true` + only qemu/clh enabled, host-check fails
   until `defaultShim: {amd64: qemu}` is set.
2. **k3s (containerd 2.x) needs a template that imports the drop-in
   dir.** kata-deploy writes handlers to
   `/var/lib/rancher/k3s/agent/etc/containerd/config-v3.toml.d/` but k3s
   only imports it if the operator-owned template says so. One-time,
   per-node, as root:

   ```
   printf 'imports = ["/var/lib/rancher/k3s/agent/etc/containerd/config-v3.toml.d/*.toml"]\n{{ template "base" . }}\n' \
     | sudo tee /var/lib/rancher/k3s/agent/etc/containerd/config-v3.toml.tmpl
   sudo systemctl restart k3s-agent   # or fold into a reboot
   ```

   (k3s renders to `config.toml` regardless; the `imports` line must be
   first — TOML top-level keys can't follow tables.)
3. **elitemini2 is 10.0.0.58** (static since 2026-08-12) —
   `config/network.yaml` is the source of truth; ssh alias `elitemini2`
   logs in as user `chris`.

## Adding another node

Add the node name to `job.nodes` in the kata-deploy Application, do the
containerd template step above on that node, then
`argocd app sync kata-deploy` (dispatcher is idempotent; installed nodes
are skipped).

## Smoke test

```bash
kubectl apply -f - <<'EOF'
apiVersion: v1
kind: Pod
metadata: { name: kata-smoke, namespace: default }
spec:
  runtimeClassName: kata-qemu
  nodeSelector: { kubernetes.io/hostname: elitemini2 }
  containers:
    - name: u
      image: busybox:1.36
      command: ["sh","-c","uname -r; echo kata-ok; sleep 30"]
  restartPolicy: Never
EOF
kubectl logs kata-smoke   # different kernel than host = inside the microVM
kubectl delete pod kata-smoke
```

## Revert

Set `runtimeClasses.default/strict: ''` in the kagent overlay (agents
back to runc) — that's the fast path. Removing kata from the node is
`helm`-side: delete the ArgoCD app (its pre-delete cleanup hook runs the
uninstall pipeline per labeled node).
