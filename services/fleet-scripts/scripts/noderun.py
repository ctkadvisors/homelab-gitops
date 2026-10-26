"""fleet-node-runner: the one place the fleet may touch a node, through an
allow-list. Chris, 2026-09-06: "read everything, write through PRs, touch
nodes only through a runner with an allow-list". Every action is named,
its arguments validated, its result posted on the forum and recorded as a
decision. Nothing here takes free-form commands.

  POST /run  {"action": "<name>", "args": {...}, "by": "reconcile|implementer|..."}
  GET  /actions   the allow-list with argument shapes
  GET  /healthz

Cluster actions use the ServiceAccount (nodes delete, pods delete in the
fleet's namespaces). Host actions use the SSH identity in /secrets/ssh
(sealed; absent = host actions refuse with 503) against hosts from
NODE_HOSTS ("name=user@ip,...") and only the commands written here.
"""

from __future__ import annotations

import calendar
import json
import os
import re
import ssl
import subprocess
import sys
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fleet import ledger  # noqa: E402

SA = "/var/run/secrets/kubernetes.io/serviceaccount"
SSH_KEY = os.environ.get("SSH_KEY_FILE", "/secrets/ssh/id_ed25519")
KNOWN_HOSTS = os.environ.get("SSH_KNOWN_HOSTS", "/secrets/ssh/known_hosts")
FLEET_NAMESPACES = [n for n in os.environ.get("FLEET_NAMESPACES", "kagent-system,ai-services").split(",") if n]
HOSTS = dict(kv.split("=", 1) for kv in os.environ.get("NODE_HOSTS", "").split(",") if "=" in kv)
VMS = [v for v in os.environ.get("VM_NAMES", "k3s-reconciler").split(",") if v]
UNITS = [u for u in os.environ.get("UNITS", "k3s,k3s-agent,deco-keepalive").split(",") if u]
NAME = re.compile(r"^[a-z0-9]([a-z0-9.-]{0,61}[a-z0-9])?$")


def k8s(method: str, path: str, body: dict | None = None) -> dict:
    host = os.environ.get("KUBERNETES_SERVICE_HOST", "kubernetes.default.svc")
    port = os.environ.get("KUBERNETES_SERVICE_PORT", "443")
    token = open(f"{SA}/token").read().strip()
    ctx = ssl.create_default_context(cafile=f"{SA}/ca.crt")
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"https://{host}:{port}{path}", data=data, method=method,
                                 headers={"Authorization": f"Bearer {token}", **({"Content-Type": "application/json"} if data else {})})
    with urllib.request.urlopen(req, timeout=20, context=ctx) as r:
        return json.load(r)


def ssh(host: str, *argv: str) -> str:
    if not os.path.exists(SSH_KEY):
        raise RuntimeError("no SSH identity sealed at /secrets/ssh; host actions are off")
    target = HOSTS.get(host)
    if not target:
        raise ValueError(f"unknown host {host!r}; known: {sorted(HOSTS)}")
    cmd = ["ssh", "-i", SSH_KEY, "-o", f"UserKnownHostsFile={KNOWN_HOSTS}", "-o", "StrictHostKeyChecking=yes",
           "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", target, "--", *argv]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if out.returncode != 0:
        raise RuntimeError(f"ssh {host}: exit {out.returncode}: {(out.stderr or out.stdout)[-300:]}")
    return out.stdout[-2000:]


# --- the allow-list ---------------------------------------------------------

def delete_node(args: dict) -> str:
    """Remove a node object that is cordoned AND NotReady (a ghost: the arm64 VM
    that rejoined after the power loss). A Ready or schedulable node is refused."""
    name = str(args.get("name", ""))
    if not NAME.match(name):
        raise ValueError("name")
    node = k8s("GET", f"/api/v1/nodes/{name}")
    ready = next((c.get("status") for c in node.get("status", {}).get("conditions", []) if c.get("type") == "Ready"), "Unknown")
    if not node.get("spec", {}).get("unschedulable") or ready == "True":
        raise PermissionError(f"{name} is {'schedulable' if not node.get('spec', {}).get('unschedulable') else 'Ready'}; only a cordoned NotReady node may be deleted")
    k8s("DELETE", f"/api/v1/nodes/{name}")
    return f"deleted node {name} (was cordoned, Ready={ready}, arch={node.get('status', {}).get('nodeInfo', {}).get('architecture')})"


def reap_failed_pods(args: dict) -> str:
    """Delete pods in phase Failed in the fleet's namespaces (they hold no state)."""
    ns = str(args.get("namespace", ""))
    if ns not in FLEET_NAMESPACES:
        raise ValueError(f"namespace must be one of {FLEET_NAMESPACES}")
    items = k8s("GET", f"/api/v1/namespaces/{ns}/pods?fieldSelector=status.phase%3DFailed").get("items", [])
    for p in items:
        k8s("DELETE", f"/api/v1/namespaces/{ns}/pods/{p['metadata']['name']}")
    return f"deleted {len(items)} failed pod(s) in {ns}"


def reap_failed_jobs(args: dict) -> str:
    """Delete finished Jobs that failed more than an hour ago in the fleet's
    namespaces. The ledger and the forum hold the record; the Job object only
    keeps KubernetesJobFailed firing (two pr-reviewer Jobs from 2026-09-06 did
    for 38 hours). Pods go with them (background propagation)."""
    ns = str(args.get("namespace", ""))
    if ns not in FLEET_NAMESPACES:
        raise ValueError(f"namespace must be one of {FLEET_NAMESPACES}")
    cutoff = time.time() - 3600
    names = []
    for j in k8s("GET", f"/apis/batch/v1/namespaces/{ns}/jobs").get("items", []):
        st = j.get("status", {})
        if not st.get("failed") or st.get("active"):
            continue
        created = j["metadata"].get("creationTimestamp", "")
        try:
            if calendar.timegm(time.strptime(created, "%Y-%m-%dT%H:%M:%SZ")) > cutoff:
                continue
        except ValueError:
            continue
        k8s("DELETE", f"/apis/batch/v1/namespaces/{ns}/jobs/{j['metadata']['name']}", {"propagationPolicy": "Background"})
        names.append(j["metadata"]["name"])
    return f"deleted {len(names)} failed job(s) in {ns}" + (f": {', '.join(names[:8])}" if names else "")


def stop_vm(args: dict) -> str:
    """multipass stop <vm> on the host that runs it (the retired k3s-reconciler VM autostarts after a power loss)."""
    host, vm = str(args.get("host", "")), str(args.get("vm", ""))
    if vm not in VMS:
        raise ValueError(f"vm must be one of {VMS}")
    return ssh(host, "/usr/local/bin/multipass", "stop", vm) or f"stopped {vm} on {host}"


def neigh_flush(args: dict) -> str:
    """Flush the node's ARP entry for the gateway (the Deco age-out fix from CLAUDE.md)."""
    host = str(args.get("host", ""))
    return ssh(host, "sudo", "-n", "ip", "neigh", "flush", "dev", "enp2s0", "to", "10.0.0.1") or f"flushed gateway neighbour on {host}"


def probe_egress(args: dict) -> str:
    """Can the node reach GitHub? Read-only. The Deco ages wired clients out and
    the node keeps its ssh while every CI job on it times out (2026-09-08)."""
    host = str(args.get("host", ""))
    # No space inside the -w format: ssh joins argv with spaces and the remote
    # shell would hand curl a second "URL" (15:35Z: the probe printed GitHub's body).
    out = ssh(host, "curl", "-sS", "-m", "8", "-o", "/dev/null", "-w", "%{http_code}/%{time_total}s", "https://api.github.com/").strip()
    # Any HTTP answer means the path is up. A 5xx in 0.13 s is GitHub's edge
    # having a day (githubstatus listed incidents at 09:47Z and 19:11Z on
    # 2026-09-15; both paged Chris as "the router"); only "000" = curl never
    # got an answer is the node's egress.
    if not out or out.split("/")[0] == "000":
        raise RuntimeError(f"{host} -> api.github.com: {out or 'no answer'}")
    return f"{host} -> api.github.com HTTP {out}"


def restart_unit(args: dict) -> str:
    """systemctl restart of one of a few named units."""
    host, unit = str(args.get("host", "")), str(args.get("unit", ""))
    if unit not in UNITS:
        raise ValueError(f"unit must be one of {UNITS}")
    return ssh(host, "sudo", "-n", "systemctl", "restart", unit) or f"restarted {unit} on {host}"


ACTIONS = {
    "delete-node": (delete_node, {"name": "node name; must be cordoned and NotReady"}),
    "reap-failed-pods": (reap_failed_pods, {"namespace": f"one of {FLEET_NAMESPACES}"}),
    "reap-failed-jobs": (reap_failed_jobs, {"namespace": f"one of {FLEET_NAMESPACES}"}),
    "stop-vm": (stop_vm, {"host": f"one of {sorted(HOSTS)}", "vm": f"one of {VMS}"}),
    "neigh-flush": (neigh_flush, {"host": f"one of {sorted(HOSTS)}"}),
    "probe-egress": (probe_egress, {"host": f"one of {sorted(HOSTS)}"}),
    "restart-unit": (restart_unit, {"host": f"one of {sorted(HOSTS)}", "unit": f"one of {UNITS}"}),
}


def run(action: str, args: dict, by: str) -> dict:
    """Do one allow-listed action; the record goes to the ledger and the forum
    whether it worked or not."""
    if action not in ACTIONS:
        raise KeyError(action)
    fn, _ = ACTIONS[action]
    try:
        result = fn(args or {})
        ok = True
    except Exception as e:
        result, ok = f"{type(e).__name__}: {str(e)[:300]}", False
    # A read-only probe that passed is not news: 97 "probe-egress OK" posts in
    # eight hours buried everything else on the forum (Chris, 2026-09-09). Probes
    # record only when they fail; actions that change a node always do. A failed
    # probe is not posted either: 82 of 200 forum posts on 2026-09-14 were
    # elitemini2's probe failures and they pushed Chris's reply off the page;
    # reconcile.check_egress says it once an hour when it stays down.
    probe = action.startswith("probe-")
    try:
        if not (ok and probe):
            ledger.record_decision(f"node:{action}", 3, by[:60], f"{json.dumps(args)[:300]} -> {result[:600]}")
        if not probe:
            ledger.say("node-runner", f"{by} ran {action} {json.dumps(args)}: {'OK' if ok else 'FAILED'}. {result[:500]}",
                       topic="status", mentions=[])  # reconcile escalates what self-heal cannot fix; a failed probe is not a question
    except Exception as e:
        print(f"noderun: record failed ({type(e).__name__})", flush=True)
    return {"ok": ok, "action": action, "args": args, "result": result}


class Handler(BaseHTTPRequestHandler):
    def _json(self, status: int, body: dict) -> None:
        raw = json.dumps(body).encode()
        self.send_response(status); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw)

    def log_message(self, fmt, *args):
        print("[node-runner]", fmt % args, flush=True)

    def do_GET(self):
        if self.path == "/healthz":
            return self._json(200, {"ok": True, "host_actions": os.path.exists(SSH_KEY)})
        if self.path == "/actions":
            return self._json(200, {"actions": {k: v[1] for k, v in ACTIONS.items()}, "hosts": sorted(HOSTS), "host_actions": os.path.exists(SSH_KEY)})
        self._json(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/run":
            return self._json(404, {"error": "not found"})
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        except ValueError:
            return self._json(400, {"error": "not json"})
        action = str(body.get("action", ""))
        if action not in ACTIONS:
            return self._json(400, {"error": f"unknown action; see GET /actions", "actions": sorted(ACTIONS)})
        args = body.get("args") if isinstance(body.get("args"), dict) else {}
        res = run(action, args, str(body.get("by") or "unknown"))
        self._json(200 if res["ok"] else 409, res)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    print(f"[node-runner] listening :{port}; hosts={sorted(HOSTS)} host_actions={os.path.exists(SSH_KEY)}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
