"""fleet-hooks: signature check, event routing, coalescing, and one signed
POST through the real server."""

import hashlib
import hmac
import json
import pathlib
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import hooks  # noqa: E402

SECRET = b"s3cret"


def sign(body: bytes) -> str:
    return "sha256=" + hmac.new(SECRET, body, hashlib.sha256).hexdigest()


def test_verify_accepts_only_a_matching_signature():
    body = b'{"x":1}'
    assert hooks.verify(SECRET, body, sign(body))
    assert not hooks.verify(SECRET, body, sign(b'{"x":2}'))
    assert not hooks.verify(SECRET, body, None)
    assert not hooks.verify(SECRET, body, "sha1=abc")


def test_route_maps_events_to_review_or_triage():
    repo = {"repository": {"full_name": "ctkadvisors/x"}}
    assert hooks.route("pull_request", {**repo, "action": "opened"}) == ("review", "ctkadvisors/x")
    assert hooks.route("pull_request", {**repo, "action": "closed"}) is None
    assert hooks.route("check_suite", {**repo, "action": "completed"}) == ("review", "ctkadvisors/x")
    assert hooks.route("workflow_run", {**repo, "action": "requested"}) is None
    issue = {**repo, "action": "labeled", "issue": {"labels": [{"name": hooks.triage.LABEL}]}}
    assert hooks.route("issues", issue) == ("triage", "ctkadvisors/x")
    assert hooks.route("issues", {**repo, "action": "labeled", "issue": {"labels": [{"name": "bug"}]}}) is None
    assert hooks.route("push", {**repo}) is None
    assert hooks.route("pull_request", {"action": "opened"}) is None  # no repo


def test_merged_agent_prs_are_recorded_whoever_merged_them(monkeypatch):
    marked, said = [], []
    monkeypatch.setattr(hooks.ledger, "mark_pr", lambda url, state: marked.append((url, state)))
    kws = []
    monkeypatch.setattr(hooks.ledger, "say", lambda *a, **k: (said.append(a), kws.append(k)) and 1)
    monkeypatch.setattr(hooks.ledger, "posts", lambda **k: [{"id": 9, "author": "reviewer"}] if k.get("unanswered") else [])
    pr = {"html_url": "https://github.com/o/r/pull/32", "merged": True, "merged_by": {"login": "app/example-fleet"}, "head": {"ref": "agent/mission-1"}}
    assert hooks.record_merge("pull_request", {"action": "closed", "pull_request": pr}) == pr["html_url"]
    assert marked == [(pr["html_url"], "merged")] and "Recorded the merge" in said[0][1]
    assert "Answered by the merge" in said[1][1] and kws[1]["parent_id"] == 9   # the reviewer's open escalation
    assert hooks.record_merge("pull_request", {"action": "closed", "pull_request": {**pr, "merged": False}}) is None   # closed unmerged
    assert hooks.record_merge("pull_request", {"action": "closed", "pull_request": {**pr, "head": {"ref": "feature/x"}}}) is None  # not a fleet branch
    assert hooks.record_merge("pull_request", {"action": "opened", "pull_request": pr}) is None
    assert len(marked) == 1


def test_coalescer_runs_once_per_burst_and_never_overlaps():
    seen = []
    gate = threading.Event()

    def slow(repo):
        seen.append(repo)
        gate.wait(2)

    c = hooks.Coalescer({"review": slow}, debounce=0.05)
    for _ in range(5):
        c.schedule("review", "a/b")
    time.sleep(0.2)
    assert seen == ["a/b"]  # five events, one run
    c.schedule("review", "a/b")  # arrives mid-run: must queue, not overlap
    time.sleep(0.2)
    assert seen == ["a/b"]
    gate.set()
    time.sleep(0.4)
    assert seen == ["a/b", "a/b"]


def test_source_gate_allows_only_github_ranges_and_fails_closed():
    empty = hooks.SourceGate()
    assert not empty.allows("140.82.112.1")
    g = hooks.SourceGate(["140.82.112.0/20", "2a0a:a440::/29"])
    assert g.allows("140.82.115.9")
    assert g.allows("2a0a:a440::1")
    assert not g.allows("1.2.3.4")
    assert not g.allows("garbage")
    assert not g.allows(None)

    class R:  # a fake api.github.com/meta
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def read(self): return json.dumps({"hooks": ["192.30.252.0/22"]}).encode()
    assert g.refresh(opener=lambda req, timeout: R()) == 1
    assert g.allows("192.30.253.1") and not g.allows("140.82.115.9")


def test_push_episode_is_the_commit_messages_and_skips_empty_or_deleted():
    push = {"ref": "refs/heads/main", "repository": {"full_name": "ctkadvisors/x"}, "pusher": {"name": "chrisknu"},
            "head_commit": {"timestamp": "2026-09-04T02:00:00Z"},
            "commits": [{"id": "abc1234def", "message": "fix(arc): pin the runner image by digest\n\nbecause tags move",
                         "modified": ["overlays/production/arc/arc-runners-application.yaml"]}]}
    name, body = hooks.push_episode(push)
    assert name == "push: ctkadvisors/x@main abc1234"
    assert "chrisknu pushed 1 commit(s) to ctkadvisors/x branch main" in body
    assert "abc1234 fix(arc): pin the runner image by digest" in body and "because tags move" in body
    assert "files: overlays/production/arc/arc-runners-application.yaml" in body
    assert hooks.push_episode({**push, "commits": []}) is None
    assert hooks.push_episode({**push, "deleted": True}) is None


def test_server_rejects_bad_signature_and_queues_good_events():
    ran = []
    scribed = []
    c = hooks.Coalescer({"review": ran.append, "triage": ran.append}, debounce=0.05)
    gate = hooks.SourceGate(["140.82.112.0/20"])  # GitHub, as seen through CF-Connecting-IP
    srv = ThreadingHTTPServer(("127.0.0.1", 0), hooks.make_handler(SECRET, c, gate, scribe=lambda n, b: scribed.append(n)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_port}"
    body = json.dumps({"action": "opened", "repository": {"full_name": "ctkadvisors/y"}}).encode()

    def post(sig, event="pull_request", ip="140.82.115.9"):
        req = urllib.request.Request(base + "/hooks", data=body, method="POST",
                                     headers={"X-Hub-Signature-256": sig, "X-GitHub-Event": event,
                                              "Content-Type": "application/json", "CF-Connecting-IP": ip})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    assert post(sign(body), ip="8.8.8.8")[0] == 403  # right signature, wrong source: still out
    assert post("sha256=nope")[0] == 401
    status, out = post(sign(body))
    assert status == 202 and json.loads(out) == {"queued": "review", "repo": "ctkadvisors/y"}
    assert post(sign(body), event="push")[0] == 204  # a push with no commits writes nothing
    push = json.dumps({"ref": "refs/heads/main", "repository": {"full_name": "ctkadvisors/y"},
                       "commits": [{"id": "0123456789", "message": "docs: note"}]}).encode()
    req = urllib.request.Request(base + "/hooks", data=push, method="POST",
                                 headers={"X-Hub-Signature-256": sign(push), "X-GitHub-Event": "push",
                                          "Content-Type": "application/json", "CF-Connecting-IP": "140.82.115.9"})
    with urllib.request.urlopen(req, timeout=5) as r:
        assert r.status == 202 and json.loads(r.read())["scribed"] is True
    assert scribed == ["push: ctkadvisors/y@main 0123456"]
    time.sleep(0.3)
    assert ran == ["ctkadvisors/y"]
    with urllib.request.urlopen(base + "/healthz", timeout=5) as r:
        assert json.load(r)["runs"] == 1
    srv.shutdown()


def test_a_human_merge_marks_the_idea_shipped_and_reinforces(monkeypatch):
    for name in ("mark_pr", "say"):
        monkeypatch.setattr(hooks.ledger, name, lambda *a, **k: 1)
    monkeypatch.setattr(hooks.ledger, "posts", lambda **k: [])
    calls = []
    for name in ("set_status", "reinforce"):
        monkeypatch.setattr(hooks.ideas, name, lambda *a, _n=name, **k: calls.append((_n, a, k)))
    url = "https://github.com/o/r/pull/32"
    monkeypatch.setattr(hooks.ideas, "lookup", lambda **k: ("0123456789ab", "mission-1") if k.get("pr_url") == url else (None, None))
    pr = {"html_url": url, "merged": True, "merged_by": {"login": "chris"}, "head": {"ref": "agent/mission-1"}}
    assert hooks.record_merge("pull_request", {"action": "closed", "pull_request": pr}) == url
    assert calls == [("set_status", ("0123456789ab", "shipped"), {"pr_url": url, "run_id": "mission-1"}), ("reinforce", (f"pr:{url}", 1.0), {})]
    monkeypatch.setattr(hooks.ideas, "lookup", lambda **k: (_ for _ in ()).throw(RuntimeError("no ideas table")))
    assert hooks.record_merge("pull_request", {"action": "closed", "pull_request": pr}) == url   # a missing table never breaks the merge record
