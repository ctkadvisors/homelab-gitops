"""mission-launcher: turn a brief into a dsh staged-pipeline Job.

The concierge (or anything with the http.mission_launch tool) POSTs
{"brief": "...", "repo": "ctkadvisors/kagent"} and gets back a Job name.
The Job is the improve-daily pipeline minus its investigate/adjudicate
stages: a `brief` stage writes the candidate the human already chose,
then implement -> test -> publish run unchanged (publish opens the PR,
writes the brain episode, pings Telegram).

Deterministic, no model, no git or brain credentials here: the only
authority this process holds is "create a Job from the template". The
template lives in a ConfigMap so the Job shape is GitOps-owned.

Stdlib only. Runs in-cluster with a ServiceAccount that may create/get/list
batch Jobs in its own namespace.
"""

from __future__ import annotations

import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fleet import github, ledger  # noqa: E402

SA = "/var/run/secrets/kubernetes.io/serviceaccount"
MAX_BRIEF = 8000
# One candidate, MAX_ATTEMPTS runs, then it is parked. new_localai#5 launched seven
# times in a night because the only dedupe was a GitHub comment posted after the
# launch, and that comment failed six times. The ledger is the record now, and the
# launcher refuses before it spends the spark: fail closed when the ledger is down.
MAX_ATTEMPTS = int(os.environ.get("MAX_ATTEMPTS", "3"))
NAMESPACE = os.environ.get("POD_NAMESPACE") or "kagent-system"
TEMPLATE_PATH = os.environ.get("MISSION_TEMPLATE", "/config/job-template.json")
DEFAULT_REPO = os.environ.get("DEFAULT_REPO", "ctkadvisors/kagent")
_repos: dict[str, object] = {"names": [], "at": 0.0}


def allowed_repos() -> list[str]:
    """The repos the GitHub App is installed on, refreshed every 10 minutes.
    MISSION_REPOS overrides for tests or a deliberate narrowing."""
    fixed = [r for r in os.environ.get("MISSION_REPOS", "").split(",") if r]
    if fixed:
        return fixed
    if time.time() - float(_repos["at"]) > 600 or not _repos["names"]:
        _repos["names"] = github.installation_repos()
        _repos["at"] = time.time()
    return list(_repos["names"])  # type: ignore[arg-type]


def k8s_api():
    """Base URL, headers and TLS context for the in-cluster API server."""
    host = os.environ.get("KUBERNETES_SERVICE_HOST", "kubernetes.default.svc")
    port = os.environ.get("KUBERNETES_SERVICE_PORT", "443")
    token = open(f"{SA}/token").read().strip()
    ctx = ssl.create_default_context(cafile=f"{SA}/ca.crt")
    return f"https://{host}:{port}", {"Authorization": f"Bearer {token}"}, ctx


def api(method: str, path: str, body: dict | None = None) -> dict:
    base, headers, ctx = k8s_api()
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers = {**headers, "Content-Type": "application/json"}
    req = urllib.request.Request(base + path, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=20, context=ctx) as r:
        return json.load(r)


def render_job(template: dict, name: str, brief: str, repo: str, requested_by: str, branch: str | None = None) -> dict:
    """Fill the Job template: name, and the env every stage container reads.
    `branch` continues an existing PR branch (a review round); default is a new
    agent/<name> branch."""
    job = json.loads(json.dumps(template))  # deep copy
    job["metadata"]["name"] = name
    job["metadata"].setdefault("labels", {})["app"] = "mission"
    job["metadata"].setdefault("annotations", {})["mission.example.com/requested-by"] = requested_by[:200]
    env = [
        {"name": "REPO", "value": repo},
        {"name": "RUN_ID", "value": name},  # the ledger row; a review round's BRANCH is another run's
        {"name": "BRANCH", "value": branch or f"agent/{name}"},
        {"name": "PIPELINE", "value": "Mission"},
        {"name": "MISSION_BRIEF", "value": brief},
        {"name": "RUN_TRIGGER", "value": requested_by.split(":", 1)[0] if ":" in requested_by else "concierge"},
    ]
    spec = job["spec"]["template"]["spec"]
    for c in spec.get("initContainers", []) + spec.get("containers", []):
        c["env"] = [e for e in c.get("env", []) if e["name"] not in {x["name"] for x in env}] + env
    return job


def validate(payload: dict) -> tuple[str, str]:
    brief = str(payload.get("brief", "")).strip()
    repo = str(payload.get("repo", DEFAULT_REPO)).strip()
    # A brief that is only an idea tag ("[idea:ea8179ef1b6d]") is the archive's
    # idea: the launcher writes the brief from the quintet and takes the idea's
    # repo, so Chris can say "run that one" and the concierge passes the id
    # (2026-09-10). The tag stays in the brief, so publish closes the idea.
    m = re.fullmatch(r"\[idea:([0-9a-f]{12})\]", brief)
    if m:
        from fleet import ideas
        idea = ideas.get(m.group(1))
        if not idea:
            raise ValueError(f"no idea {m.group(1)} in the archive")
        brief = ideas.brief_for(idea)
        repo = str(idea.get("repo") or repo)
    if len(brief) < 12:
        raise ValueError("brief is too short to act on")
    if len(brief) > MAX_BRIEF:
        raise ValueError(f"brief exceeds {MAX_BRIEF} chars")
    allowed = allowed_repos()
    if repo not in allowed:
        raise ValueError(f"repo {repo!r} is not one the fleet's GitHub App is installed on ({len(allowed)} repos)")
    return brief, repo


def branch_of(payload: dict) -> str | None:
    """An existing agent/* branch to continue (a review round), or None."""
    b = str(payload.get("branch") or "").strip()
    if not b:
        return None
    if not re.fullmatch(r"agent/[\w.-]{1,80}", b):
        raise ValueError("branch must be an agent/* branch")
    return b


REVIEW_ROUNDS = int(os.environ.get("REVIEW_ROUNDS", "2"))


def admit(repo: str, brief: str, human: bool = False, review: bool = False) -> tuple[str, str | None]:
    """The ledger's say on launching this brief: (fingerprint, refusal or None).
    A running attempt is always refused. MAX_ATTEMPTS spent -> refused and the
    issue parked (fleet:declined, mission label off), unless a human asked:
    the console's retry is a decision, not the fleet looping. A review round
    (iterating on the reviewer's objection, same branch) has its own cap,
    REVIEW_ROUNDS, so feedback loops cannot spin."""
    fp, title, issue_url = ledger.mission_candidate(repo, brief)
    n, running = ledger.attempts(fp)
    if running:
        return fp, f"already running as {running}"
    if review:
        rounds = ledger.runs_by_trigger(fp, "review")
        if rounds >= REVIEW_ROUNDS:
            return fp, f"already iterated {rounds}x on review feedback; a human decides now"
        return fp, None
    if n >= MAX_ATTEMPTS and not human:
        ledger.park(fp)  # never clobbers merged/observed: the ledger's history outranks a relaunch
        if issue_url and "/issues/" in issue_url:
            path = "/repos/" + issue_url.split("github.com/", 1)[-1]
            try:
                github.api(path + "/comments", {"body": f"Parked after {n} attempts (fleet:declined). "
                           "Each halt is on its own `fleet:halt` issue; fix the cause, then label `mission` again to retry."})
                github.api(path + "/labels", {"labels": ["fleet:declined"]})
                github.api(path + "/labels/mission", method="DELETE")
            except Exception as e:
                print(f"[mission-launcher] could not park {issue_url}: {e}")
        return fp, f"parked after {n} attempts"
    ledger.upsert_candidate(fp, repo, title, "human", issue_url=issue_url)
    return fp, None


FAIL_LINE = re.compile(r"✘|failure for|expected:|found:|##\[error\]|FAILED|Error:|error TS|npm ERR|Traceback|AssertionError|✖")


def failing_checks(repo: str, sha: str, gh=None) -> dict:
    """The failing check runs on a commit and the telling lines of their job logs,
    for a stage that cannot see GitHub (2026-09-06 23:11: the implementer on
    brutalist_todo#24 asked which Lighthouse audits still fail because it had no
    token; the App can read Actions logs). Never more than ~80 lines per job."""
    gh = gh or github
    out = {"repo": repo, "sha": sha, "failing": []}
    runs = gh.api(f"/repos/{repo}/commits/{sha}/check-runs").get("check_runs", [])
    for c in runs:
        if c.get("status") != "completed" or c.get("conclusion") in ("success", "skipped", "neutral", None):
            continue
        item = {"name": c.get("name"), "conclusion": c.get("conclusion"), "url": c.get("details_url"), "lines": []}
        m = re.search(r"/job/(\d+)", c.get("details_url") or "")
        if m:
            try:
                text = github.job_log(repo, m.group(1), gh)
                lines = [re.sub(r"\x1b\[[0-9;]*m", "", ln).split("Z ", 1)[-1] for ln in text.splitlines()]
                picked = [ln.strip() for ln in lines if FAIL_LINE.search(ln)]
                item["lines"] = picked[-80:] if picked else [ln.strip() for ln in lines if ln.strip()][-40:]
            except Exception as e:
                item["lines"] = [f"(log unavailable: {type(e).__name__})"]
        out["failing"].append(item)
    return out


def job_summary(job: dict, run: dict | None = None) -> dict:
    """The Job's phase, overridden by the ledger's verdict when there is one. A
    halted mission still completes its Job (a halt is a stop file, exit 0), so
    Job phase alone read "succeeded" for mission-20260905-160823, which halted
    at implement, and the concierge told Chris twice that it had shipped."""
    st = job.get("status", {})
    phase = "succeeded" if st.get("succeeded") else "failed" if st.get("failed") else "running" if st.get("active") else "pending"
    out = {
        "name": job["metadata"]["name"],
        "phase": phase,
        "startedAt": st.get("startTime"),
        "completedAt": st.get("completionTime"),
        "repo": next((e["value"] for c in job["spec"]["template"]["spec"].get("containers", []) for e in c.get("env", []) if e["name"] == "REPO"), None),
    }
    if run and run.get("outcome"):
        out["phase"] = run["outcome"]  # shipped | halted: the pipeline's own word
        out["pr_url"] = run.get("pr_url")
        halt = run.get("halt") or {}
        if halt:
            out["halt"] = {"stage": halt.get("stage"), "reason": halt.get("reason")}
    elif phase == "succeeded":
        out["phase"] = "completed"
        out["note"] = "the Job finished but the ledger has no outcome for it; not a success until a PR URL is known"
    return out


def run_row(name: str) -> dict | None:
    try:
        return ledger.get_run(name)
    except Exception as e:
        print(f"[mission-launcher] ledger lookup for {name} failed: {type(e).__name__}")
        return None


def fleet(context: str = "") -> dict:
    """What the fleet can do, from the systems that do it: the repos the GitHub
    App is installed on, and the merge policy the reviewer publishes to the ledger
    each round (review.policy()). Served on GET /missions so the concierge answers
    "can it merge?" from this, not from its prompt: on 2026-09-05 it told Chris the
    fleet cannot merge, the day after it had merged two PRs."""
    out = {"repos": allowed_repos()}
    try:
        out["review"] = ledger.kv_get("review_policy") or {"note": "the reviewer has not published its policy yet"}
    except Exception as e:
        out["review"] = {"note": f"ledger unavailable ({type(e).__name__})"}
    out["health"] = health()
    try:
        from fleet import memory
        out["memory"] = memory.recall(None, context, limit=16)
    except Exception as e:
        out["memory"] = f"(memory unavailable: {type(e).__name__})"
    try:  # 2026-09-10: the active archive, trimmed, so the concierge can list ideas (adapter unchanged)
        from fleet import ideas
        keep = ("id", "lineage", "parent", "problem", "effect", "status", "source", "scores")
        out["ideas"] = {"active": [{k: r.get(k) for k in keep} for r in ideas.rows(None, ("active",), 10)]}
    except Exception as e:
        out["ideas"] = {"note": f"unavailable ({type(e).__name__})"}
    return out


def health() -> dict:
    """The fleet's own health, computed, for the concierge to relay verbatim.
    2026-09-07: it told Chris 'code runner's down' three times and 'the
    cluster's fine' once, all from how its tool calls felt. This is what the
    scheduler actually observed: its last tick's signals, its own failed pods,
    whether it paused itself, whether the model answered the canary, and what
    the last runs did. No model in the path."""
    h: dict = {"computed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    try:
        obs = ledger.kv_get("last_observation") or {}
        h["scheduler"] = {"observed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(float(obs.get("at", 0)))) if obs.get("at") else None,
                          "eligible": obs.get("eligible"), "budget": obs.get("budget"), "signals": obs.get("signals")}
        sh = ledger.kv_get("self_health") or {}
        h["own_failed_pods_last_hour"] = sh.get("failed_last_hour")
        pause = ledger.kv_get("pause") or {}
        h["paused"] = pause.get("why") if pause and float(pause.get("until", 0)) > time.time() else None
        can = ledger.kv_get("canary") or {}
        h["model_degenerate_seen_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(float(can["at"]))) if can.get("at") and time.time() - float(can["at"]) < 3600 else None
        h["egress"] = {k: {"ok": v.get("ok"), "detail": v.get("detail")} for k, v in (ledger.kv_get("egress") or {}).items()}
        try:
            from fleet import memory
            h["memory"] = memory.stats()
        except Exception as e:
            h["memory"] = {"note": f"unavailable ({type(e).__name__})"}
        try:  # 2026-09-10 idea lineage: yield and shipped rate are measures, computed like memory
            from fleet import ideas
            h["ideas"] = ideas.stats()
        except Exception as e:
            h["ideas"] = {"note": f"unavailable ({type(e).__name__})"}
        h["runs_in_flight"] = [r["id"] for r in ledger.unfinished_runs()]
        h["last_runs"] = [{"id": r.get("id"), "repo": r.get("repo"), "outcome": r.get("outcome"),
                           "halt": (r.get("halt") or {}).get("reason"), "pr_url": r.get("pr_url")} for r in ledger.recent_runs(5)]
    except Exception as e:
        h["note"] = f"ledger unavailable ({type(e).__name__})"
    try:
        jobs = api("GET", f"/apis/batch/v1/namespaces/{NAMESPACE}/jobs").get("items", [])
        h["failed_jobs"] = [j["metadata"]["name"] for j in jobs if j.get("status", {}).get("failed") and not j.get("status", {}).get("active")]
    except Exception as e:
        h["failed_jobs"] = f"unknown ({type(e).__name__})"
    h["summary"] = summarize(h)
    return h


def summarize(h: dict) -> str:
    """One sentence, computed, for the concierge to say first and verbatim. The
    model kept inventing trends ('a couple earlier ones', 'on repeat') from a
    list of five runs with one halt in it (2026-09-08 02:04Z), so the counting
    happens here, not in its head."""
    problems = []
    if h.get("paused"):
        problems.append(f"the fleet paused itself ({h['paused']})")
    if h.get("model_degenerate_seen_at"):
        problems.append(f"the model failed its canary at {h['model_degenerate_seen_at']}")
    if h.get("own_failed_pods_last_hour"):
        problems.append(f"{h['own_failed_pods_last_hour']} fleet pod(s) failed in the last hour")
    fj = h.get("failed_jobs")
    if isinstance(fj, list) and fj:
        problems.append(f"{len(fj)} failed Job(s): {', '.join(fj[:3])}")
    elif isinstance(fj, str):
        problems.append(f"failed Jobs {fj}")
    for host, v in (h.get("egress") or {}).items():
        if v.get("ok") is False:
            problems.append(f"{host} cannot reach GitHub ({str(v.get('detail'))[:60]})")
        elif v.get("ok") is None:
            problems.append(f"the egress check for {host} did not run ({str(v.get('detail'))[:60]})")
    if h.get("note"):
        problems.append(h["note"])
    runs = h.get("last_runs") or []
    shipped = sum(1 for r in runs if r.get("outcome") == "shipped")
    halts: dict[str, int] = {}
    for r in runs:
        if r.get("outcome") in ("halted", "failed"):
            k = (r.get("halt") or r.get("outcome") or "?").split(" (")[0][:60]  # the clause, not a cut-off parenthesis
            halts[k] = halts.get(k, 0) + 1
    runs_txt = (f"Of the last {len(runs)} runs, {shipped} shipped" + (", " + ", ".join(f"{n} halted ({k})" for k, n in halts.items()) if halts else "") + ".") if runs else "No runs recorded."
    flight = h.get("runs_in_flight") or []
    flight_txt = f" {len(flight)} run(s) in flight: {', '.join(flight[:3])}." if flight else ""
    head = "Fleet health: nothing is broken." if not problems else "Fleet health: " + "; ".join(problems) + "."
    mem = h.get("memory") or {}
    mem_txt = (f" Memory: {mem['rows']} rows, {mem['fleet_written_recent']} written by the fleet itself in the last {mem['days']} days"
               + (f"; {mem['halt_lessons']} halt lesson(s), {mem['repeated_after_lesson']} repeated after." if isinstance(mem.get("halt_lessons"), int) else ".")
               if isinstance(mem.get("rows"), int) else "")
    idea_txt = ""
    st = h.get("ideas") or {}
    if isinstance(st.get("by_status"), dict):  # 2026-09-10: counts are the archive's, not the week's; only `recent` is windowed
        bs = st["by_status"]
        attempted = sum(bs.get(k, 0) for k in ("attempted", "shipped", "failed"))
        idea_txt = (f" Ideas: {bs.get('active', 0)} active, {st.get('recent', 0)} new in {st.get('days', 7)} days, "
                    f"{bs.get('shipped', 0)} shipped of {attempted} attempted; {st.get('links', 0)} links.")
    return f"{head} {runs_txt}{flight_txt}{mem_txt}{idea_txt}"


class Handler(BaseHTTPRequestHandler):
    def _remember(self) -> None:
        try:
            n = int(self.headers.get("Content-Length") or 0)
            out = remember(json.loads(self.rfile.read(n) or b"{}"))
        except (ValueError, json.JSONDecodeError) as e:
            return self._json(400, {"error": str(e)})
        except Exception as e:
            return self._json(503, {"error": f"ledger unavailable: {type(e).__name__}"})
        self._json(201, out)

    def _json(self, status: int, body: dict) -> None:
        raw = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, fmt, *args):  # one line per request, no client noise
        print("[mission-launcher]", self.command, self.path, fmt % args)

    def do_GET(self):
        if self.path == "/healthz":
            return self._json(200, {"ok": True})
        m = re.fullmatch(r"/missions/([a-z0-9-]{1,63})", self.path)
        if m:
            try:
                job = api("GET", f"/apis/batch/v1/namespaces/{NAMESPACE}/jobs/{m.group(1)}")
                return self._json(200, job_summary(job, run_row(m.group(1))))
            except urllib.error.HTTPError as e:
                return self._json(e.code, {"error": f"job lookup failed: HTTP {e.code}"})
        m = re.fullmatch(r"/checks/([\w.-]+/[\w.-]+)/([0-9a-f]{7,40})", self.path)
        if m:
            try:
                return self._json(200, failing_checks(m.group(1), m.group(2)))
            except urllib.error.HTTPError as e:
                return self._json(e.code, {"error": f"github: HTTP {e.code}"})
            except Exception as e:
                return self._json(502, {"error": f"{type(e).__name__}: {str(e)[:200]}"})
        if self.path == "/missions" or self.path.startswith("/missions?"):
            # ?q=<the message>: the memory in `fleet.memory` is recalled for that
            # text (rules always, then the lessons that overlap it), so the
            # adapter's [fleet now] block carries what matters to this message.
            import urllib.parse
            q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query).get("q", [""])[0][:500]
            jobs = api("GET", f"/apis/batch/v1/namespaces/{NAMESPACE}/jobs?labelSelector=app%3Dmission")
            items = [job_summary(j, run_row(j["metadata"]["name"])) for j in jobs.get("items", [])[-20:]]
            return self._json(200, {"items": items, "fleet": fleet(q)})
        self._json(404, {"error": "not found"})

    def do_POST(self):
        if self.path == "/remember":
            return self._remember()
        if self.path != "/missions":
            return self._json(404, {"error": "not found"})
        try:
            n = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(n) or b"{}")
            brief, repo = validate(payload)
            branch = branch_of(payload)
        except (ValueError, json.JSONDecodeError) as e:
            return self._json(400, {"error": str(e)})
        requested_by = str(payload.get("requestedBy", "concierge"))
        try:
            fp, refusal = admit(repo, brief, human=requested_by.startswith("console:"), review=requested_by.startswith("review:"))
        except Exception as e:
            return self._json(503, {"error": f"ledger unavailable, not launching blind: {type(e).__name__}"})
        if refusal:
            return self._json(409, {"error": refusal, "fingerprint": fp})
        # two launches in one second collided on the name and the second came
        # back as 'job create failed: HTTP 502' (2026-09-10 17:56Z)
        name = f"mission-{time.strftime('%Y%m%d-%H%M%S')}-{os.urandom(2).hex()}"
        template = json.load(open(TEMPLATE_PATH))
        job = render_job(template, name, brief, repo, requested_by, branch)
        try:
            created = api("POST", f"/apis/batch/v1/namespaces/{NAMESPACE}/jobs", job)
        except urllib.error.HTTPError as e:
            return self._json(502, {"error": f"job create failed: HTTP {e.code} {e.read()[:300].decode(errors='replace')}"})
        try:
            ledger.start_run(name, "mission", repo, requested_by.split(":", 1)[0] if ":" in requested_by else "concierge", fp)
        except Exception as e:
            print(f"[mission-launcher] ledger start_run failed (job is running): {e}", flush=True)  # stdout is a pipe: unflushed, this never showed
        self._json(201, {"name": created["metadata"]["name"], "repo": repo, "branch": branch or f"agent/{name}",
                         "status": "Mission started. The publish stage reports the PR (or the halt reason) to Telegram and the brain when it finishes, usually within 30 minutes."})


def remember(payload: dict) -> dict:
    """A rule from Chris, straight into the fleet's memory: the Telegram adapter
    posts a message that starts with 'rule:' here before the model sees it
    (2026-09-09: asked to keep a rule, the concierge wrote it to the brain and
    said the whole fleet had it). Posted on the forum as chris; ledger.post
    turns an author-chris post into a feedback row every stage recalls."""
    text = " ".join(str(payload.get("text", "")).split())
    if len(text) < 8 or len(text) > 2000:
        raise ValueError("text: 8..2000 characters")
    pid = ledger.post("chris", text, topic="note", ref=str(payload.get("ref") or "") or None)
    return {"ok": True, "post": pid, "text": text}


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    print(f"[mission-launcher] listening :{port} ns={NAMESPACE} repos={'MISSION_REPOS' if os.environ.get('MISSION_REPOS') else 'GitHub App installation'}")
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
