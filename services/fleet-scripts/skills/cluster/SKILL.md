---
name: cluster
description: Look at the live cluster, read-only (pods, jobs, cronjobs, deployments, events, nodes in the fleet's namespaces) before theorising about a failure.
---
# Cluster, read-only

`/fleet/bin/kubectl` has in-cluster auth (ServiceAccount fleet-stage). Allowed: `get`, `describe`, `logs`
on pods, jobs, cronjobs, deployments, events and networkpolicies in `kagent-system`, `ai-services`,
`database`, `monitoring`, `arc-runners`, plus `get nodes`. Nothing else works and nothing here changes
cluster state: a change is a pull request to `k8s-kustomized/`.

```
/fleet/bin/kubectl get pods -n kagent-system
/fleet/bin/kubectl logs -n kagent-system <pod> --tail=200
/fleet/bin/kubectl describe job -n kagent-system <job>
/fleet/bin/kubectl get events -n kagent-system --sort-by=.lastTimestamp | tail -30
```

Look at the thing that failed before you theorise. A pod that died with exit 137 hit its memory limit.
