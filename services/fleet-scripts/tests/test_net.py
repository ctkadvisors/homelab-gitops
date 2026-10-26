"""fleet/net.py: connection errors retry, HTTP errors do not."""

import io
import pathlib
import sys
import urllib.error

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fleet import net  # noqa: E402


def test_urlopen_retry_waits_out_a_refused_first_second(monkeypatch):
    calls = []
    def fake(req, timeout=30):
        calls.append(req)
        if len(calls) < 3:
            raise urllib.error.URLError(ConnectionRefusedError(111, "Connection refused"))
        return io.BytesIO(b'{"status":"ok"}')
    monkeypatch.setattr(net.urllib.request, "urlopen", fake)
    monkeypatch.setattr(net.time, "sleep", lambda s: None)
    assert net.urlopen_retry("http://x/healthz", tries=5, wait=0).read() == b'{"status":"ok"}'
    assert len(calls) == 3


def test_urlopen_retry_gives_up_and_never_retries_http_errors(monkeypatch):
    monkeypatch.setattr(net.time, "sleep", lambda s: None)
    def refused(req, timeout=30):
        raise urllib.error.URLError("refused")
    monkeypatch.setattr(net.urllib.request, "urlopen", refused)
    try:
        net.urlopen_retry("http://x", tries=3, wait=0); assert False
    except urllib.error.URLError:
        pass
    n = []
    def http_500(req, timeout=30):
        n.append(1); raise urllib.error.HTTPError("http://x", 500, "boom", {}, None)
    monkeypatch.setattr(net.urllib.request, "urlopen", http_500)
    try:
        net.urlopen_retry("http://x", tries=3, wait=0); assert False
    except urllib.error.HTTPError:
        assert len(n) == 1


def test_post_reads_returning_id_before_marking_the_parent_answered(monkeypatch):
    """2026-09-06 22:30Z: every reply 503'd with 'attempting to use unexecuted
    cursor' because the RETURNING row was read after the UPDATE."""
    from contextlib import contextmanager
    from fleet import ledger
    log = []
    class Cur:
        def execute(self, sql, args=()):
            log.append(sql.split()[0]); self.last = sql
        def fetchone(self):
            if self.last.startswith("SELECT ref"):
                return ("https://github.com/o/r/issues/1",)
            if self.last.startswith("INSERT"):
                return (42,)
            raise AssertionError("fetchone after " + self.last.split()[0])
    class Conn:
        def cursor(self): return Cur()
    @contextmanager
    def connect():
        yield Conn()
    monkeypatch.setattr(ledger, "connect", connect)
    assert ledger.post("chris", "answer", parent_id=7) == 42
    assert log[:3] == ["SELECT", "INSERT", "UPDATE"]   # a 4th INSERT: what chris says becomes memory (fleet/memory.py)


def test_the_concierge_relays_chris_into_memory(monkeypatch):
    """The agent face refuses author chris; the concierge posts 'Chris says: ...' instead."""
    from contextlib import contextmanager
    from fleet import ledger, memory
    kept = []
    class Cur:
        def execute(self, sql, args=()): self.last = sql
        def fetchone(self): return (7,)
    class Conn:
        def cursor(self): return Cur()
    @contextmanager
    def connect():
        yield Conn()
    monkeypatch.setattr(ledger, "connect", connect)
    monkeypatch.setattr(memory, "remember", lambda kind, text, repo=None, ref=None, source="fleet": kept.append((kind, text, source)) or "k")
    ledger.post("concierge", "Chris says: when you cite memory, say who wrote it, by source.", topic="note")
    ledger.post("concierge", "Created specialist fleet-poet for a poem.", topic="note")
    assert kept == [("feedback", "when you cite memory, say who wrote it, by source.", "chris")]
