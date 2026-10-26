"""fleet-hooks: the GitHub App's webhook receiver.

Chris, 2026-09-03: "flip to a subscription". pr-reviewer polled every 15
minutes and triage every 30; now GitHub pushes the event and the same
code runs for just the repo it names, seconds later. The CronJobs stay as
an hourly fallback for anything a webhook drops.

Routing:
  pull_request opened/synchronize/reopened/ready_for_review -> review that repo
  check_suite / workflow_run completed                       -> review that repo
  issues opened/labeled/reopened carrying the mission label  -> triage that repo

Events for one repo are coalesced: a burst of check_suite completions
becomes one review run after DEBOUNCE_SECONDS of quiet, and runs for the
same (kind, repo) never overlap. Signature is HMAC-SHA256 of the raw body
with the App webhook secret (X-Hub-Signature-256); unsigned or badly
signed posts get 401 and are never parsed.

On start, if WEBHOOK_URL is set and the App key is mounted, the receiver
registers its own URL and secret on the App (PATCH /app/hook/config), so
the secret never has to be pasted anywhere by a human.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import os
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
from fleet import brain, github, ideas, ledger  # noqa: E402
import review  # noqa: E402
import triage  # noqa: E402

SECRET_FILE = os.environ.get("WEBHOOK_SECRET_FILE", "/secrets/webhook/secret")
DEBOUNCE = float(os.environ.get("DEBOUNCE_SECONDS", "20"))
# Source gate. Only Cloudflare can reach the tunnel, so CF-Connecting-IP is
# the real client; anything outside GitHub's published `hooks` ranges is
# dropped with 403 before the body is read. Chris, 2026-09-03: "its still an
# open hook into my homelab" - after this it answers only GitHub.
CLIENT_IP_HEADER = os.environ.get("CLIENT_IP_HEADER", "CF-Connecting-IP")
GITHUB_META = os.environ.get("GITHUB_META_URL", "https://api.github.com/meta")
META_REFRESH = float(os.environ.get("META_REFRESH_SECONDS", "3600"))
REVIEW_ACTIONS = {"opened", "synchronize", "reopened", "ready_for_review"}
TRIAGE_ACTIONS = {"opened", "labeled", "reopened"}
RUNNERS = {"review": review.review_repo, "triage": triage.triage_repo}


def verify(secret: bytes, body: bytes, header: str | None) -> bool:
    if not header or not header.startswith("sha256="):
        return False
    digest = hmac.new(secret, body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(digest, header[len("sha256="):])


def push_episode(payload: dict) -> tuple[str, str] | None:
    """(name, body) for a push: the commit messages, which already carry the
    why. Chris, 2026-09-04: "ensure all of this is getting captured correctly
    in our brain" - work done outside the fleet (a Claude Code session, a
    laptop push) only reaches the graph if something writes it, and the push
    is the one event every change produces. Deleted branches and pushes with
    no commits write nothing."""
    commits = payload.get("commits") or []
    if payload.get("deleted") or not commits:
        return None
    repo = payload["repository"]["full_name"]
    branch = (payload.get("ref") or "").replace("refs/heads/", "")
    who = (payload.get("pusher") or {}).get("name") or (payload.get("sender") or {}).get("login") or "someone"
    lines = []
    for c in commits[-20:]:
        files = sorted({*c.get("added", []), *c.get("modified", []), *c.get("removed", [])})
        lines.append(f"- {c.get('id', '')[:7]} {c.get('message', '').strip()}"
                     + (f"\n  files: {', '.join(files[:12])}" + (" ..." if len(files) > 12 else "") if files else ""))
    body = (f"{who} pushed {len(commits)} commit(s) to {repo} branch {branch} at "
            f"{payload.get('head_commit', {}).get('timestamp') or ''}.\n" + "\n".join(lines))[:8000]
    return f"push: {repo}@{branch} {commits[-1].get('id', '')[:7]}", body


def record_merge(event: str, payload: dict) -> str | None:
    """A fleet PR merged by anyone (a human, the App token) is still an outcome
    the ledger must see: brutalist_todo#32 was merged by hand on 2026-09-08 and
    its candidate sat at `tested` with no outcome row until it was marked by
    hand. The reviewer's own merges call mark_pr themselves; this covers the
    rest. Returns the PR URL when it recorded one."""
    if event != "pull_request" or payload.get("action") != "closed":
        return None
    pr = payload.get("pull_request") or {}
    if not pr.get("merged") or not str((pr.get("head") or {}).get("ref", "")).startswith(review.AGENT_BRANCH_PREFIX or "agent/"):
        return None
    url = pr.get("html_url")
    try:
        ledger.mark_pr(url, "merged")
        ledger.say("reconcile", f"Recorded the merge of {url} by {(pr.get('merged_by') or {}).get('login', '?')}; the 24h/7d outcome checks start now.",
                   topic="status", ref=url)
        # The reviewer's escalation of this PR is answered by the merge itself; left
        # open it sat in "Needs you" for a day (#304, #368 on 2026-09-09).
        for q in ledger.posts(limit=5, topic="question", ref=url, unanswered=True):
            if q.get("author") == "reviewer":
                ledger.say("reconcile", f"Answered by the merge: a human merged {url}. Nothing more to decide here.",
                           topic="answer", ref=url, parent_id=q["id"])
    except Exception as e:
        print(f"hooks: could not record the merge of {url}: {type(e).__name__}", flush=True)
        return None
    # The merge is the idea's strongest outcome (lineage spec step 6, 2026-09-10):
    # publish stamped the PR on the idea when it shipped; the path earns another +1.
    try:
        iid, rid = ideas.lookup(pr_url=url)
        if iid:
            ideas.set_status(iid, "shipped", pr_url=url, run_id=rid)
            ideas.reinforce(f"pr:{url}", 1.0)
    except Exception as e:
        print(f"hooks: ideas write failed (non-fatal): {type(e).__name__}", flush=True)
    return url


def route(event: str, payload: dict) -> tuple[str, str] | None:
    """(kind, repo) for events the fleet acts on, else None."""
    repo = (payload.get("repository") or {}).get("full_name")
    action = payload.get("action")
    if not repo:
        return None
    if event == "pull_request" and action in REVIEW_ACTIONS:
        return "review", repo
    if event in ("check_suite", "workflow_run") and action == "completed":
        return "review", repo
    if event == "issues" and action in TRIAGE_ACTIONS:
        labels = {l.get("name") for l in (payload.get("issue") or {}).get("labels", [])}
        if triage.LABEL in labels:
            return "triage", repo
    return None


class SourceGate:
    """Allow only GitHub's webhook source ranges (api.github.com/meta `hooks`).
    Fails closed: with no ranges loaded every request is refused (503)."""

    def __init__(self, nets: list | None = None):
        self.nets = [ipaddress.ip_network(n) for n in (nets or [])]
        self.loaded_at = time.time() if nets else 0.0

    def refresh(self, opener=urllib.request.urlopen) -> int:
        req = urllib.request.Request(GITHUB_META, headers={"Accept": "application/vnd.github+json",
                                                           "User-Agent": "fleet-hooks"})
        with opener(req, timeout=20) as r:
            hooks = json.load(r).get("hooks", [])
        self.nets = [ipaddress.ip_network(n) for n in hooks]
        self.loaded_at = time.time()
        return len(self.nets)

    def allows(self, ip: str | None) -> bool:
        if not self.nets or not ip:
            return False
        try:
            addr = ipaddress.ip_address(ip.strip())
        except ValueError:
            return False
        return any(addr in n for n in self.nets)

    def keep_fresh(self) -> None:
        """Background refresh; a failed refresh keeps the last good ranges."""
        while True:
            time.sleep(META_REFRESH)
            try:
                print(f"hooks: github hook ranges refreshed: {self.refresh()}", flush=True)
            except Exception as e:
                print(f"hooks: github meta refresh failed, keeping {len(self.nets)} ranges: {e}", flush=True)


class Coalescer:
    """One run per (kind, repo) after a quiet period; never two at once."""

    def __init__(self, runners: dict, debounce: float = DEBOUNCE):
        self.runners, self.debounce = runners, debounce
        self._timers: dict[tuple[str, str], threading.Timer] = {}
        self._busy: dict[tuple[str, str], threading.Lock] = {}
        self._lock = threading.Lock()
        self.runs = 0

    def schedule(self, kind: str, repo: str) -> None:
        key = (kind, repo)
        with self._lock:
            if key in self._timers:
                self._timers[key].cancel()
            t = threading.Timer(self.debounce, self._run, args=(key,))
            t.daemon = True
            self._timers[key] = t
            t.start()

    def _run(self, key: tuple[str, str]) -> None:
        with self._lock:
            self._timers.pop(key, None)
            busy = self._busy.setdefault(key, threading.Lock())
        if not busy.acquire(blocking=False):
            self.schedule(*key)  # a run is in flight; go again after it
            return
        try:
            kind, repo = key
            t0 = time.time()
            print(f"hooks: {kind} {repo} start", flush=True)
            self.runners[kind](repo)
            print(f"hooks: {kind} {repo} done in {time.time() - t0:.0f}s", flush=True)
        except Exception as e:  # one repo must not take the receiver down
            print(f"hooks: {key[0]} {key[1]} failed: {e}", flush=True)
        finally:
            self.runs += 1
            busy.release()


# CI and bot traffic is the fleet's own echo, not the repos moving: every push fires
# check_run/workflow_job events for minutes, and they kept 'events' busy so the fleet
# never went idle after its own work (2026-09-15). A person's push, PR or review counts.
QUIET_EVENTS = {"check_run", "check_suite", "workflow_run", "workflow_job", "status", "deployment_status"}


def counts_as_activity(event: str, payload: dict) -> bool:
    login = str((payload.get("sender") or {}).get("login") or "")
    return event not in QUIET_EVENTS and not login.endswith("[bot]")


def stamp_activity(event: str) -> None:
    """The reconciler's 'events' signal: the repos moved. Best effort; no ledger, no stamp."""
    try:
        ledger.kv_set("last_event", {"at": time.time(), "event": event})
    except Exception:
        pass


def scribe(name: str, body: str) -> None:
    brain.add_episode(name, body, "GitHub push webhook via fleet-hooks", client="fleet-hooks")


def make_handler(secret: bytes, coalescer: Coalescer, gate: SourceGate | None = None, scribe=scribe):
    class Handler(BaseHTTPRequestHandler):
        def client_ip(self) -> str:
            return self.headers.get(CLIENT_IP_HEADER) or self.client_address[0]

        def _reply(self, status: int, body: dict | None = None) -> None:
            data = json.dumps(body or {}).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            self._reply(200, {"ok": True, "runs": coalescer.runs}) if self.path == "/healthz" else self._reply(404)

        def do_POST(self):
            if self.path != "/hooks":
                return self._reply(404)
            if gate is not None:
                if not gate.nets:
                    return self._reply(503, {"error": "source ranges not loaded"})
                if not gate.allows(self.client_ip()):
                    return self._reply(403, {"error": "not a github hook source"})
            body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            if not verify(secret, body, self.headers.get("X-Hub-Signature-256")):
                return self._reply(401, {"error": "bad signature"})
            event = self.headers.get("X-GitHub-Event", "")
            try:
                payload = json.loads(body or b"{}")
            except ValueError:
                return self._reply(400, {"error": "not json"})
            if counts_as_activity(event, payload):
                stamp_activity(event)
            if event == "push":
                ep = push_episode(payload)
                if not ep:
                    return self._reply(204)
                try:
                    scribe(*ep)
                except Exception as e:  # the brain being down must not fail the hook
                    print(f"hooks: brain write failed for {ep[0]}: {e}", flush=True)
                    return self._reply(202, {"scribed": False, "name": ep[0]})
                print(f"hooks: scribed {ep[0]}", flush=True)
                return self._reply(202, {"scribed": True, "name": ep[0]})
            merged = record_merge(event, payload)
            if merged:
                print(f"hooks: recorded merge {merged}", flush=True)
            hit = route(event, payload)
            if not hit:
                return self._reply(204 if not merged else 202)
            coalescer.schedule(*hit)
            self._reply(202, {"queued": hit[0], "repo": hit[1]})

        def log_message(self, fmt, *args):  # one line per hit is enough; see do_POST
            pass

    return Handler


def main() -> None:
    secret = open(SECRET_FILE, "rb").read().strip()
    url = os.environ.get("WEBHOOK_URL")
    if url and os.path.exists(f"{github.APP_DIR}/private_key.pem"):
        try:
            github.set_app_webhook(url, secret.decode())
            print(f"hooks: App webhook registered -> {url}", flush=True)
        except Exception as e:
            print(f"hooks: could not register App webhook: {e}", flush=True)
    review.publish_policy()  # the ledger copy the launcher serves to the concierge
    gate = SourceGate()
    for attempt in range(5):
        try:
            print(f"hooks: github hook ranges loaded: {gate.refresh()}", flush=True)
            break
        except Exception as e:
            print(f"hooks: github meta fetch failed ({e}); retry {attempt + 1}/5", flush=True)
            time.sleep(10)
    threading.Thread(target=gate.keep_fresh, daemon=True).start()
    port = int(os.environ.get("PORT", "8080"))
    print(f"hooks: listening on :{port}, debounce {DEBOUNCE}s, client ip from {CLIENT_IP_HEADER}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", port), make_handler(secret, Coalescer(RUNNERS), gate)).serve_forever()


if __name__ == "__main__":
    main()
