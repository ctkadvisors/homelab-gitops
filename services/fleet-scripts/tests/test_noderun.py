"""fleet-node-runner: the allow-list refuses what it should, and reconcile
only hands it ghost nodes."""

import os
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
os.environ.setdefault("MISSION_REPOS", "ctkadvisors/kagent")
import noderun  # noqa: E402
import reconcile  # noqa: E402
from fleet import ledger  # noqa: E402


def node(name, ready, unsched, arch="arm64"):
    return {"metadata": {"name": name}, "spec": {"unschedulable": unsched},
            "status": {"conditions": [{"type": "Ready", "status": ready}], "nodeInfo": {"architecture": arch}}}


def test_delete_node_only_removes_a_cordoned_notready_node(monkeypatch):
    calls = []
    store = {"k3s-reconciler": node("k3s-reconciler", "Unknown", True), "elitemini": node("elitemini", "True", False, "amd64"),
             "cordoned-live": node("cordoned-live", "True", True)}
    def k8s(method, path, body=None):
        calls.append((method, path))
        name = path.rsplit("/", 1)[-1]
        if method == "GET":
            return store[name]
        return {}
    monkeypatch.setattr(noderun, "k8s", k8s)
    assert "deleted node k3s-reconciler" in noderun.delete_node({"name": "k3s-reconciler"})
    assert ("DELETE", "/api/v1/nodes/k3s-reconciler") in calls
    for bad in ("elitemini", "cordoned-live"):
        try:
            noderun.delete_node({"name": bad}); assert False, bad
        except PermissionError:
            pass
    assert not any(m == "DELETE" and p.endswith(bad) for m, p in calls for bad in ("elitemini", "cordoned-live"))
    try:
        noderun.delete_node({"name": "../etc"}); assert False
    except ValueError:
        pass


def test_host_actions_refuse_without_identity_and_outside_the_lists(monkeypatch):
    monkeypatch.setattr(noderun, "SSH_KEY", "/nonexistent/key")
    monkeypatch.setattr(noderun, "HOSTS", {"mini-3": "u@10.0.0.1"})
    try:
        noderun.stop_vm({"host": "mini-3", "vm": "k3s-reconciler"}); assert False
    except RuntimeError as e:
        assert "host actions are off" in str(e)
    try:
        noderun.stop_vm({"host": "mini-3", "vm": "prod-db"}); assert False
    except ValueError:
        pass
    try:
        noderun.restart_unit({"host": "mini-3", "unit": "sshd"}); assert False
    except ValueError:
        pass


def test_run_records_every_outcome(monkeypatch):
    said, decided = [], []
    monkeypatch.setattr(ledger, "say", lambda *a, **k: said.append((a, k)))
    monkeypatch.setattr(ledger, "record_decision", lambda *a, **k: decided.append(a))
    monkeypatch.setattr(noderun, "reap_failed_pods", lambda args: "deleted 2 failed pod(s) in kagent-system")
    noderun.ACTIONS["reap-failed-pods"] = (noderun.reap_failed_pods, {})
    res = noderun.run("reap-failed-pods", {"namespace": "kagent-system"}, "reconcile")
    assert res["ok"] and decided[0][0] == "node:reap-failed-pods" and decided[0][1] == 3
    assert said[0][1]["topic"] == "status"
    res = noderun.run("stop-vm", {"host": "nowhere", "vm": "k3s-reconciler"}, "implementer")
    assert not res["ok"] and said[-1][1]["topic"] == "status" and said[-1][1]["mentions"] == []
    try:
        noderun.run("rm-rf", {}, "x"); assert False
    except KeyError:
        pass


def test_reconcile_only_hands_ghost_nodes_to_the_runner(monkeypatch):
    nodes = [node("k3s-reconciler", "Unknown", True), node("elitemini", "True", False, "amd64"),
             node("jetson2", "True", False), node("cordoned-amd64", "False", True, "amd64")]
    assert reconcile.ghost_nodes(time.time(), nodes) == ["k3s-reconciler"]
    kv = {}
    monkeypatch.setattr(ledger, "kv_get", lambda k: kv.get(k)); monkeypatch.setattr(ledger, "kv_set", lambda k, v: kv.__setitem__(k, v))
    monkeypatch.setattr(reconcile, "ghost_nodes", lambda now, nodes=None: ["k3s-reconciler"])
    acted = []
    monkeypatch.setattr(reconcile, "node_action", lambda action, args, by="reconcile": acted.append((action, args)) or {"ok": True})
    now = time.time()
    assert reconcile.tidy_nodes(now) == ["k3s-reconciler"] and acted == [("delete-node", {"name": "k3s-reconciler"})]
    assert reconcile.tidy_nodes(now + 60) == [] and len(acted) == 1  # once a day per name


def test_reap_failed_jobs_deletes_only_old_finished_failures(monkeypatch):
    stamp = lambda ago: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - ago))
    jobs = {"items": [
        {"metadata": {"name": "old-failed", "creationTimestamp": stamp(7200)}, "status": {"failed": 1}},
        {"metadata": {"name": "fresh-failed", "creationTimestamp": stamp(60)}, "status": {"failed": 1}},
        {"metadata": {"name": "retrying", "creationTimestamp": stamp(7200)}, "status": {"failed": 1, "active": 1}},
        {"metadata": {"name": "succeeded", "creationTimestamp": stamp(7200)}, "status": {"succeeded": 1}},
    ]}
    calls = []
    def k8s(method, path, body=None):
        calls.append((method, path, body))
        return jobs if method == "GET" else {}
    monkeypatch.setattr(noderun, "k8s", k8s)
    out = noderun.reap_failed_jobs({"namespace": "kagent-system"})
    assert out.startswith("deleted 1 failed job(s)") and "old-failed" in out
    assert [(p, b) for m, p, b in calls if m == "DELETE"] == [
        ("/apis/batch/v1/namespaces/kagent-system/jobs/old-failed", {"propagationPolicy": "Background"})]
    try:
        noderun.reap_failed_jobs({"namespace": "kube-system"}); assert False
    except ValueError:
        pass
    # reconcile hands over only when a stale failed Job exists in its namespace
    monkeypatch.setattr(reconcile, "k8s", k8s)
    acted = []
    monkeypatch.setattr(reconcile, "node_action", lambda action, args, by="reconcile": acted.append((action, args)) or {"ok": True, "result": "deleted 1"})
    assert "1 stale" in reconcile.tidy_failed_jobs(time.time()) and acted == [("reap-failed-jobs", {"namespace": "kagent-system"})]
    jobs["items"] = jobs["items"][1:]
    assert reconcile.tidy_failed_jobs(time.time()) is None and len(acted) == 1


def assert_no_space(argv):
    assert not any(" " in a for a in argv), argv   # ssh joins argv with spaces; a space splits an argument on the far side


def test_probe_egress_reads_the_status_code_and_refuses_unknown_hosts(monkeypatch):
    monkeypatch.setattr(noderun, "ssh", lambda host, *argv: (assert_no_space(argv), "200/0.412s\n")[1])
    assert noderun.probe_egress({"host": "elitemini2"}) == "elitemini2 -> api.github.com HTTP 200/0.412s"
    monkeypatch.setattr(noderun, "ssh", lambda host, *argv: "000/8.001s")
    try:
        noderun.probe_egress({"host": "elitemini2"}); assert False
    except RuntimeError as e:
        assert "000/8.001s" in str(e)
    # GitHub's 5xx is GitHub's, not the node's: reachable, no flush, no page.
    monkeypatch.setattr(noderun, "ssh", lambda host, *argv: "504/0.131s\n")
    assert noderun.probe_egress({"host": "elitemini2"}) == "elitemini2 -> api.github.com HTTP 504/0.131s"
    assert "probe-egress" in noderun.ACTIONS


def test_probes_never_post_and_only_a_failing_one_is_recorded(monkeypatch):
    said, decided = [], []
    monkeypatch.setattr(noderun.ledger, "say", lambda *a, **k: said.append(a) or 1)
    monkeypatch.setattr(noderun.ledger, "record_decision", lambda *a, **k: decided.append(a) or 1)
    monkeypatch.setattr(noderun, "ACTIONS", {"probe-egress": (lambda args: "HTTP 200/0.1s", {}), "neigh-flush": (lambda args: "flushed", {})})
    assert noderun.run("probe-egress", {"host": "h"}, "reconcile")["ok"] and said == [] and decided == []
    assert noderun.run("neigh-flush", {"host": "h"}, "reconcile")["ok"] and len(said) == 1        # a change is always recorded
    monkeypatch.setattr(noderun, "ACTIONS", {"probe-egress": (lambda args: (_ for _ in ()).throw(RuntimeError("timed out")), {})})
    r = noderun.run("probe-egress", {"host": "h"}, "reconcile")
    assert not r["ok"] and len(said) == 1 and decided[-1][0] == "node:probe-egress"   # recorded, not posted (2026-09-14)
