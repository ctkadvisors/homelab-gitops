---
name: node-runner
description: The only way to touch a node - an allow-list of named actions (reap failed pods or jobs, delete a cordoned NotReady node, flush the gateway neighbour, probe egress, restart a named unit). Use one only when the evidence says the node is the cause.
---
# Node runner (allow-listed actions)

```
curl -s http://fleet-node-runner.kagent-system.svc:8080/actions
curl -s -X POST http://fleet-node-runner.kagent-system.svc:8080/run -H 'content-type: application/json' \
  -d '{"action":"reap-failed-pods","args":{"namespace":"kagent-system"},"by":"implementer"}'
```
Every call is recorded in the ledger and posted on the forum, whether it worked or not. There are no
free-form commands; if the action you need is not listed, say so on the forum instead.
