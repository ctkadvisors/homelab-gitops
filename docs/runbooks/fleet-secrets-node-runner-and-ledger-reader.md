# Sealing the node runner's SSH identity and the ledger reader DSN

Two secrets only a human can create (2026-09-06). Until they exist the fleet
runs with `host_actions=false` on the node runner and stages see no ledger.

## 1. Node runner SSH identity (`fleet-node-runner-ssh`)

The runner ssh-es as the users in `NODE_HOSTS` (fleet-node-runner.yaml):
`chris@10.0.0.76` (elitemini), `chris@10.0.0.58` (elitemini2),
`homelab-user@10.0.0.56` (Mini-3, the Multipass host). Commands it may run
are the five in `scripts/noderun.py`; the eliteminis need passwordless sudo
for `ip neigh flush` and `systemctl restart` (they have it).

```bash
D=$(mktemp -d) && chmod 700 "$D"
ssh-keygen -q -t ed25519 -N "" -C "fleet-node-runner@kagent-system" -f "$D/id_ed25519"
PUB=$(cat "$D/id_ed25519.pub")
for h in elitemini elitemini2 mini-1-mdns; do
  ssh "$h" "mkdir -p ~/.ssh && chmod 700 ~/.ssh && echo '$PUB' >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys"
done
ssh-keyscan -t ed25519 10.0.0.76 10.0.0.58 10.0.0.56 > "$D/known_hosts"
ssh elitemini 'curl -s http://$(sudo kubectl get svc -n sealed-secrets sealed-secrets-controller -o jsonpath="{.spec.clusterIP}"):8080/v1/cert.pem' > "$D/cert.pem"
kubectl create secret generic fleet-node-runner-ssh -n kagent-system \
  --from-file=id_ed25519="$D/id_ed25519" --from-file=known_hosts="$D/known_hosts" \
  --dry-run=client -o yaml | kubeseal --cert "$D/cert.pem" --format yaml \
  > k8s-kustomized/overlays/production/kagent/fleet-node-runner-ssh-sealed.yaml
```

Add `fleet-node-runner-ssh-sealed.yaml` to `kustomization.yaml` resources,
commit, push. The runner picks the mounted key up on its next restart
(`kubectl -n kagent-system rollout restart deploy/fleet-node-runner`).
Verify: `curl fleet-node-runner:8080/healthz` shows `host_actions: true`.

## 2. Ledger reader DSN (`fleet-ledger-reader-dsn`)

The Postgres role `fleet_reader` (SELECT on every table in `fleet`, default
privileges included) already exists; its password is whatever you set here.

```bash
PW=$(openssl rand -hex 24)
ssh elitemini "sudo kubectl exec -n database deploy/postgresql -- psql -U postgres -d fleet -c \"ALTER ROLE fleet_reader WITH LOGIN PASSWORD '$PW'\""
kubectl create secret generic fleet-ledger-reader-dsn -n kagent-system \
  --from-literal=dsn="postgres://fleet_reader:$PW@postgresql.database.svc.cluster.local:5432/fleet" \
  --dry-run=client -o yaml | kubeseal --cert "$D/cert.pem" --format yaml \
  > k8s-kustomized/overlays/production/kagent/fleet-ledger-reader-dsn-sealed.yaml
```

Add it to `kustomization.yaml`, commit, push. Stages mount it at
`/secrets/ledger-ro/dsn` (`LEDGER_DSN_FILE`); nothing else changes.
