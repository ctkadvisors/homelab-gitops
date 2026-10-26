"""The console's state assembly degrades per block, and its three steering
routes do exactly one thing each against fakes."""

import json
import pathlib
import sys
import threading
import urllib.request
from http.server import ThreadingHTTPServer

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import console  # noqa: E402


class FakeGH:
    def __init__(self):
        self.calls = []
    def installation_repos(self): return ["ctkadvisors/a"]
    def api(self, path, data=None, method=None, **kw):
        self.calls.append((method or ("POST" if data is not None else "GET"), path, data))
        if path.startswith("/search/issues?"):
            return {"items": [{"number": 7, "title": "fleet halt: x", "html_url": "u", "repository_url": "https://api.github.com/repos/ctkadvisors/a",
                               "labels": [{"name": "fleet:halt"}], "updated_at": "2026-09-04T00:00:00Z", "user": {"login": "bot"}}]} if "fleet%3Ahalt" in path or "fleet:halt" in path else {"items": []}
        return {}


class FakeLedger:
    def __init__(self): self.kv = {"last_observation": {"eligible": False, "signals": {"minis": "busy (1/2)"}}}; self.vetoes = []
    def kv_get(self, k): return self.kv.get(k)
    def veto(self, did, who): self.vetoes.append((did, who))
    def connect(self): raise RuntimeError("no db in tests")


def test_state_degrades_per_block(monkeypatch):
    monkeypatch.setattr(console, "ledger", FakeLedger())
    s = console.state(gh=FakeGH())
    assert s["observation"]["eligible"] is False
    assert "ledger" in s["errors"] and "no db" in s["errors"]["ledger"]     # runs/decisions block failed alone
    assert s["board"][0]["number"] == 7 and s["board"][0]["labels"] == ["fleet:halt"] and s["board"][0]["repo"] == "ctkadvisors/a"
    assert "knobs" in s


def test_steering_routes(monkeypatch):
    led = FakeLedger(); gh = FakeGH(); monkeypatch.setattr(console, "ledger", led)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), console.make_handler(gh))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_port}"
    def post(path, body):
        req = urllib.request.Request(base + path, data=json.dumps(body).encode(), method="POST", headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as r: return r.status, json.load(r)
    assert post("/api/veto/42", {"who": "chris"}) == (200, {"vetoed": 42}) and led.vetoes == [(42, "human:chris")]
    assert post("/api/label/ctkadvisors/a/7", {"label": "mission"})[1] == {"labelled": "mission"}
    assert ("POST", "/repos/ctkadvisors/a/issues/7/labels", {"labels": ["mission"]}) in gh.calls
    assert post("/api/label/ctkadvisors/a/7", {"label": "fleet:declined"})[1] == {"labelled": "fleet:declined"}
    assert ("DELETE", "/repos/ctkadvisors/a/issues/7/labels/mission", None) in gh.calls
    try:
        post("/api/label/ctkadvisors/a/7", {"label": "fleet:merged"}); assert False
    except urllib.error.HTTPError as e:
        assert e.code == 400
    assert post("/api/ask/ctkadvisors/a/7", {"q": "why?"})[1] == {"asked": True}
    with urllib.request.urlopen(base + "/", timeout=5) as r:
        html = r.read()
        assert r.status == 200 and b"fleet console" in html
        assert b"sendReply(" in html and b"flex-wrap:wrap" in html  # inline reply + rows wrap on a phone
        assert b".remove();load()" in html  # the reply box goes away before the refresh, or load() would skip it (typed text)
    srv.shutdown()


def test_retry_and_feedback(monkeypatch):
    # "there is no mechanism for me to give feedback (or see WHY it was halted), or retry"
    import io
    calls, kv = [], {}
    rows = {"mission-1": {"pipeline": "mission", "repo": "o/r", "fingerprint": "fp", "issue_url": "https://github.com/o/r/issues/5", "pr_url": None},
            "mission-2": {"pipeline": "mission", "repo": "o/r", "fingerprint": "fq", "issue_url": "https://github.com/o/r/issues/6", "pr_url": "https://github.com/o/r/pull/9"}}
    monkeypatch.setattr(console, "q", lambda sql, args=(): [rows[args[0]]] if args and args[0] in rows else [])
    class L:
        def kv_set(self, k, v): kv[k] = v
    monkeypatch.setattr(console, "ledger", L())
    class GH:
        def api(self, path, data=None, method=None, **kw):
            calls.append((path, data))
            if path.endswith("/issues/5"): return {"html_url": "https://github.com/o/r/issues/5", "title": "t", "body": "b", "number": 5}
            if path.endswith("/comments?per_page=100"): return [{"user": {"login": "chris"}, "body": "do it with X"}, {"user": {"login": "example-fleet[bot]"}, "body": "mission started: m"}]
            return {}
    launched = []
    def fake_urlopen(req, timeout=0):
        launched.append(json.loads(req.data)); return io.BytesIO(b'{"name": "mission-3"}')
    monkeypatch.setattr(console.urllib.request, "urlopen", fake_urlopen)
    assert console.retry("mission-1", "chris", GH()) == {"started": "mission-3"}
    assert launched[0]["requestedBy"] == "console:chris" and "do it with X" in launched[0]["brief"] and "mission started" not in launched[0]["brief"]
    assert any(p.endswith("/issues/5/comments") and "mission started:" in d["body"] for p, d in calls)
    assert console.feedback("mission-2", "wrong table", "chris", GH()) == {"posted": "https://github.com/o/r/pull/9", "objection": True}
    assert kv["objection:o/r#9"]["summary"] == "wrong table"
    assert console.feedback("mission-1", "try the other path", "chris", GH())["objection"] is False
    try:
        console.retry("nope", "chris", GH()); assert False
    except LookupError:
        pass


def test_forum_port_lets_agents_read_and_post_only(monkeypatch):
    """The tool-gateway reaches FORUM_PORT alone: agents read and post, never steer,
    never post as chris (2026-09-06 security review of the forum)."""
    class L(FakeLedger):
        rows = []
        def posts(self, **kw): return list(self.rows)
        def post(self, author, body, topic="note", ref=None, mentions=(), parent_id=None):
            self.rows.append({"id": len(self.rows) + 1, "author": author, "body": body, "topic": topic, "ref": ref, "mentions": list(mentions)}); return len(self.rows)
        def kv_set(self, k, v): pass
    led = L(); monkeypatch.setattr(console, "ledger", led)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), console.make_handler(FakeGH(), agents=True))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_port}"
    def post(path, body):
        req = urllib.request.Request(base + path, data=json.dumps(body).encode(), method="POST", headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as r: return r.status, json.load(r)
    assert post("/api/post", {"author": "concierge", "topic": "question", "body": "who owns the digest?", "mentions": ["reconcile"]}) == (201, {"id": 1})
    with urllib.request.urlopen(base + "/api/forum", timeout=5) as r:
        assert json.load(r)["posts"][0]["author"] == "concierge"
    with urllib.request.urlopen(base + "/api/forum?limit=1", timeout=5) as r:   # a query string is not a different route (00:28Z 2026-09-09: 403)
        assert r.status == 200
    for path, body in (("/api/veto/1", {}), ("/api/resume", {}), ("/api/retry/improve", {}), ("/api/post", {"author": "chris", "body": "as chris"})):
        try:
            post(path, body); assert False, path
        except urllib.error.HTTPError as e:
            assert e.code == 403, path
    try:
        urllib.request.urlopen(base + "/api/state", timeout=5); assert False
    except urllib.error.HTTPError as e:
        assert e.code == 403
    srv.shutdown()


def test_ideas_routes_read_the_archive_and_its_paths(monkeypatch):
    """2026-09-10 idea lineage: the page lists the active archive and what each idea grew from."""
    calls = []
    class Ideas:
        STATUSES = ("active", "historical", "rejected", "attempted", "shipped", "failed")
        def rows(self, repo, statuses, limit):
            calls.append(("rows", repo, statuses, limit)); return [{"id": "ab12", "lineage": "ab12", "parent": None, "problem": "p", "status": statuses[0], "scores": {}}]
        def path_to(self, node, hops):
            calls.append(("path", node, hops)); return [("halt:x", "idea:ab12", "evidence", 1.0), ("idea:00", "idea:ab12", "fork", 2.0)]
    monkeypatch.setattr(console, "ideas", Ideas())
    srv = ThreadingHTTPServer(("127.0.0.1", 0), console.make_handler(FakeGH()))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_port}"
    def get(path):
        with urllib.request.urlopen(base + path, timeout=5) as r: return r.status, json.load(r)
    assert get("/api/ideas")[1]["ideas"][0]["id"] == "ab12" and calls[-1] == ("rows", None, ("active",), 20)
    assert get("/api/ideas?status=shipped&limit=3")[1]["ideas"][0]["status"] == "shipped" and calls[-1] == ("rows", None, ("shipped",), 3)
    assert get("/api/ideas/ab12/path") == (200, {"links": [["halt:x", "idea:ab12", "evidence", 1.0], ["idea:00", "idea:ab12", "fork", 2.0]]})
    assert calls[-1] == ("path", "idea:ab12", 3)
    try:
        get("/api/ideas?status=bogus"); assert False
    except urllib.error.HTTPError as e:
        assert e.code == 400
    with urllib.request.urlopen(base + "/", timeout=5) as r:
        assert b'id=ideas' in r.read()
    srv.shutdown()
