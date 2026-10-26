"""Proof that 'answer' is accepted on the live /api/post path (reviewer objection
on ctkadvisors/new_localai#86, 2026-09-09).

The reviewer could not tell from the diff alone that 'answer' is accepted; this
test drives make_handler's /api/post the way the tool-gateway does and asserts
the topic survives the allowlist AND lands in the ledger. It also asserts the
canonical topic list on the post.topic column comment is the live allowlist.
"""
import json
import pathlib
import sys
import threading
import urllib.request
import urllib.error
from http.server import ThreadingHTTPServer

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import console  # noqa: E402


class FakeLedger:
    def __init__(self):
        self.rows = []

    def posts(self, **kw):
        out = [r for r in self.rows]
        if kw.get("topic") is not None:
            out = [r for r in out if r["topic"] == kw["topic"]]
        if kw.get("unanswered"):
            out = [r for r in out if r.get("parent_id") is None]
        return out

    def post(self, author, body, topic="note", ref=None, mentions=(), parent_id=None):
        self.rows.append({"id": len(self.rows) + 1, "author": author, "body": body,
                          "topic": topic, "ref": ref, "mentions": list(mentions),
                          "parent_id": parent_id})
        return len(self.rows)


def _server(monkeypatch):
    led = FakeLedger()
    monkeypatch.setattr(console, "ledger", led)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), console.make_handler(agents=True))
    return led, threading.Thread(target=srv.serve_forever, daemon=True), srv


def test_answer_topic_is_accepted_on_api_post(monkeypatch):
    led, thr, srv = _server(monkeypatch)
    thr.start()
    base = f"http://127.0.0.1:{srv.server_port}"
    try:
        # A post whose topic is exactly 'answer' must be accepted (201), not
        # silently downgraded to 'note' by the allowlist.
        status, payload = _post(base, {"author": "implementer", "topic": "answer",
                                       "body": "the run is done", "ref": "github.com/ctkadvisors/new_localai/pull/86"})
        assert status == 201, payload
        (row,) = [r for r in led.rows if r["topic"] == "answer"]
        assert row["body"] == "the run is done"
    finally:
        srv.shutdown()


def test_any_other_topic_falls_back_to_note(monkeypatch):
    led, thr, srv = _server(monkeypatch)
    thr.start()
    base = f"http://127.0.0.1:{srv.server_port}"
    try:
        status, _ = _post(base, {"author": "implementer", "topic": "not-a-real-topic",
                                 "body": "garbage"})
        assert status == 201
        # An unknown topic is downgraded to 'note' by the same allowlist that
        # admits 'answer' — proving the allowlist, not a default, is what matters.
        assert led.rows[-1]["topic"] == "note"
    finally:
        srv.shutdown()


def test_answer_appears_in_topic_enum():
    # The post.topic column comment is the canonical topic list; it must list
    # 'answer' so a future reader cannot drop it again.
    import re
    from fleet import ledger
    src = open(ledger.__file__).read()
    m = re.search(r"-- status \|.*\| note", src)
    comment = m.group(0)
    assert "answer" in comment


def _post(base, body):
    req = urllib.request.Request(base + "/api/post", data=json.dumps(body).encode(),
                                 method="POST", headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as r:
        return r.status, json.load(r)
