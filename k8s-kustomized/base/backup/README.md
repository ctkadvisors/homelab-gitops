# Off-box backup to valhalla (Synology NAS)

Nightly CronJob shipping the cluster's unrecoverable state to the NAS:
k3s SQLite datastore, sealed-secrets master key, local-path PVC data
(gitea et al.). Ships **suspended** — two manual steps arm it:

## 1. Prepare the NAS (DSM, once)

- Control Panel → Terminal & SNMP → **Enable SSH service**
- Create shared folder `homelab-backup`, dir `elitemini/`
- (Recommended) Snapshot Replication on that share — it is the
  retention/versioning layer; the job itself keeps a single mirror.
- (Required, learned 2026-09-08) Give valhalla a static address in DSM (it drifted .54 -> .67 and the backups refused-on-22 for a day; the Deco app cannot reserve) so
  DHCP can't move it; else update `NAS_DEST` in cronjob.yaml when it drifts.

## 2. Install the SSH key and arm the job

```bash
ssh-keygen -t ed25519 -N "" -C "k3s-nas-backup" -f /tmp/nas-backup-key
ssh-copy-id -i /tmp/nas-backup-key.pub homelab-user@10.0.0.67
kubectl -n backup create secret generic nas-ssh --from-file=key=/tmp/nas-backup-key
rm /tmp/nas-backup-key*
# then flip `suspend: true` -> `false` in cronjob.yaml, commit, push
```

Smoke test without waiting for 03:30:

```bash
kubectl -n backup create job --from=cronjob/nas-backup nas-backup-manual
kubectl -n backup logs -f job/nas-backup-manual
```

## Restore sketch

- New k3s server: stop k3s, drop `state.db` into
  `/var/lib/rancher/k3s/server/db/`, start k3s.
- Sealed secrets: `kubectl apply -f sealed-secrets-key.yaml`, restart the
  sealed-secrets controller, existing SealedSecrets decrypt again.
- PVC data: copy the relevant dirs back under `/var/lib/rancher/k3s/storage/`.
