"""reconcile: the fleet's one scheduler. Every five minutes, decide whether the
fleet is eligible to spend idle capacity on a self-improvement run, and if so
start exactly one.

Chris, 2026-09-04: "an 'idle watcher' (as opposed to a cron) that kicks off a
self-improvement loop" and "it should not be human dependent. it SHOULD be
self driving, but with [the console] for steering". Codex's review of the
first design shaped the rails here: one durable scheduler holding a lease, not
a thread in the webhook receiver; every signal carries a freshness stamp and
an unknown or stale signal means NOT eligible; the admission signal is the
resource the run consumes (the spark's GPU, where ornith15 lives - the minis'
/slots were watched for a night while the work ran elsewhere, Codex 2026-09-04);
a daily budget; stable run ids; and the
run is the existing staged pipeline (collect -> investigate -> adjudicate ->
implement -> test -> publish) whose PR is the proposal, so nothing merges
without the reviewer's rails.

Signals (all must be fresh, i.e. observed within FRESH_SECONDS):
  spark   llama-swap /metrics GPU util under SPARK_BUSY_UTIL percent      (capacity)
  jobs    no active mission / improve Jobs in kagent-system              (fleet busy)
  tasks   no AgentTask in flight                                          (agents busy)
  runners no pods in arc-runners                                          (CI busy)
  chat    no AgentTask created in the last QUIET_MINUTES               (Chris is around)
  events  no webhook activity in the last EVENT_QUIET_MINUTES (ledger kv) (repos moving)

Policy (ledger 'scheduler' table, all values overridable by env for the console's knobs):
  BUDGET_PER_DAY runs (default 1), MIN_GAP_MINUTES between runs (default 120),
  IDLE_MINUTES of continuous eligibility before launching (default 10).

Launch = create a Job from the improve-daily CronJob's template (no second copy
of the pipeline), name improve-<utc timestamp>, RUN_TRIGGER=idle on every
container, and a ledger run row + decision row. Everything else stays as is.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fleet import experience, github, ideas, ledger, net, telegram  # noqa: E402
import review  # noqa: E402  (merge_due: land announced PRs whose window has passed)
from ideate import random_file  # noqa: E402,F401  (the tests reach it here)

SA = "/var/run/secrets/kubernetes.io/serviceaccount"
NAMESPACE = os.environ.get("POD_NAMESPACE", "kagent-system")
RUNNER_NAMESPACE = os.environ.get("RUNNER_NAMESPACE", "arc-runners")
CRONJOB = os.environ.get("IMPROVE_CRONJOB", "improve-daily")
SPARK_METRICS_URL = os.environ.get("SPARK_METRICS_URL", "http://spark-llamaswap.ai-services.svc.cluster.local:9090/metrics")
SPARK_BUSY_AT = int(os.environ.get("SPARK_BUSY_AT", "3"))   # ornith15 requests in flight that count as contention
SPARK_BUSY_UTIL = float(os.environ.get("SPARK_BUSY_UTIL", "10"))
WORKBENCH_URL = os.environ.get("WORKBENCH_URL", "http://kagent-workbench.kagent-system.svc.cluster.local")
FRESH_SECONDS = int(os.environ.get("FRESH_SECONDS", "120"))
QUIET_MINUTES = int(os.environ.get("QUIET_MINUTES", "30"))
EVENT_QUIET_MINUTES = int(os.environ.get("EVENT_QUIET_MINUTES", "10"))
IDLE_MINUTES = int(os.environ.get("IDLE_MINUTES", "10"))
BUDGET_PER_DAY = int(os.environ.get("BUDGET_PER_DAY", "1"))
MIN_GAP_MINUTES = int(os.environ.get("MIN_GAP_MINUTES", "120"))
DRY_RUN = os.environ.get("DRY_RUN") == "1"
LAUNCHER = os.environ.get("LAUNCHER", "http://mission-launcher.kagent-system.svc.cluster.local:8080")


def k8s(method: str, path: str, body: dict | None = None) -> dict:
    host = os.environ.get("KUBERNETES_SERVICE_HOST", "kubernetes.default.svc")
    port = os.environ.get("KUBERNETES_SERVICE_PORT", "443")
    token = open(f"{SA}/token").read().strip()
    ctx = ssl.create_default_context(cafile=f"{SA}/ca.crt")
    req = urllib.request.Request(f"https://{host}:{port}{path}", data=json.dumps(body).encode() if body else None,
                                 headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}, method=method)
    with urllib.request.urlopen(req, timeout=20, context=ctx) as r:
        return json.load(r)


def get_json(url: str, timeout: int = 8):
    with urllib.request.urlopen(urllib.request.Request(url, headers={"Accept": "application/json"}), timeout=timeout) as r:
        return json.load(r)


# ---- signals: each returns (ok: bool, detail: str); an exception is "unknown" -> not eligible

SPARK_MODEL = os.environ.get("SPARK_MODEL", "ornith15")


def sig_spark() -> tuple[bool, str]:
    """What an improve run spends is ornith15's attention, so busy = requests
    running or waiting on it (vLLM's own gauge through llama-swap's /upstream
    proxy; ornith15 is resident, ttl 0, so the proxy answers). The GPU-util gauge
    is the fallback: on 2026-09-06 llama-swap reported 94% for two hours while
    nvidia-smi and both vLLM queues read zero, and the fleet sat idle on it."""
    base = SPARK_METRICS_URL.rsplit("/metrics", 1)[0]
    try:
        with urllib.request.urlopen(f"{base}/upstream/{SPARK_MODEL}/metrics", timeout=8) as r:
            text = r.read().decode()
        q = {}
        for l in text.splitlines():
            for k in ("vllm:num_requests_running", "vllm:num_requests_waiting"):
                if l.startswith(k + "{"):
                    q[k] = q.get(k, 0.0) + float(l.rsplit(" ", 1)[1])
        if q:
            n = int(q.get("vllm:num_requests_running", 0) + q.get("vllm:num_requests_waiting", 0))
            # One or two requests from outside the fleet (a qwen-coder MCP call, an OpenWebUI
            # chat) are not contention: n == 0 kept the fleet from ever idling while anyone
            # else used ornith15 (2026-09-15). The fleet's own runs count under `jobs`.
            return n < SPARK_BUSY_AT, f"{SPARK_MODEL} {n} request(s) in flight (busy at {SPARK_BUSY_AT})"
    except Exception as e:
        print(f"sig_spark: upstream {SPARK_MODEL} metrics unavailable ({type(e).__name__}); using GPU util")
    with urllib.request.urlopen(SPARK_METRICS_URL, timeout=8) as r:
        text = r.read().decode()
    utils = [float(l.rsplit(" ", 1)[1]) for l in text.splitlines() if l.startswith("llamaswap_gpu_util_percent")]
    if not utils:
        raise ValueError("no llamaswap_gpu_util_percent in metrics")
    util = max(utils)
    return util < SPARK_BUSY_UTIL, f"spark gpu {util:.0f}% util"


def sig_jobs() -> tuple[bool, str]:
    active = []
    for sel in ("app=mission", "app=improve-daily"):
        for j in k8s("GET", f"/apis/batch/v1/namespaces/{NAMESPACE}/jobs?labelSelector={sel}").get("items", []):
            if (j.get("status") or {}).get("active"):
                active.append(j["metadata"]["name"])
    return not active, f"active jobs: {active or 'none'}"


def sig_tasks() -> tuple[bool, str]:
    items = k8s("GET", "/apis/kagent.example.com/v1alpha1/agenttasks?limit=500").get("items", [])
    # The fleet's own asks of the concierge (payload.forumQuestion) are not
    # contention: the tick asks before it observes, so counting them reset the
    # idle clock every tick that had a question backlog (2026-09-11 17:45Z).
    live = [t["metadata"]["name"] for t in items
            if str((t.get("status") or {}).get("phase", "")).lower() not in ("succeeded", "failed", "completed", "cancelled", "canceled")
            and not ((t.get("spec") or {}).get("payload") or {}).get("forumQuestion")]
    return not live, f"agenttasks in flight: {len(live)}"


def sig_runners() -> tuple[bool, str]:
    pods = k8s("GET", f"/api/v1/namespaces/{RUNNER_NAMESPACE}/pods").get("items", [])
    return not pods, f"runner pods: {len(pods)}"


def sig_chat() -> tuple[bool, str]:
    """Is Chris talking to the fleet? Every Telegram or WhatsApp turn becomes an
    AgentTask, so the newest AgentTask's creation time is the last conversation.
    (The workbench sessions API was the first idea; its NetworkPolicy made it a
    timeout, and the AgentTask list is already in hand.)"""
    items = k8s("GET", "/apis/kagent.example.com/v1alpha1/agenttasks?limit=500").get("items", [])
    # Only channel turns (kct-*) are Chris talking; the fleet's own asks of the
    # concierge (manual-*) must not make the fleet wait on itself (2026-09-11).
    latest = max((parse_ts(t["metadata"].get("creationTimestamp")) for t in items if t["metadata"].get("name", "").startswith("kct-")), default=0.0)
    age_min = (time.time() - latest) / 60 if latest else 1e9
    return age_min >= QUIET_MINUTES, f"last agent task {age_min:.0f} min ago" if latest else "no agent tasks"


def sig_events() -> tuple[bool, str]:
    v = ledger.kv_get("last_event")
    ts = float((v or {}).get("at", 0)) if isinstance(v, dict) else 0.0
    age_min = (time.time() - ts) / 60 if ts else 1e9
    return age_min >= EVENT_QUIET_MINUTES, f"last webhook {age_min:.0f} min ago" if ts else "no events recorded"


def parse_ts(v) -> float:
    from datetime import datetime, timezone
    if isinstance(v, (int, float)):
        return float(v) / (1000 if v > 1e12 else 1)
    s = str(v).replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(s).timestamp()
    except ValueError:
        return 0.0


SIGNALS = {"spark": sig_spark, "jobs": sig_jobs, "tasks": sig_tasks, "runners": sig_runners, "chat": sig_chat, "events": sig_events}


def observe(signals=SIGNALS) -> tuple[bool, dict]:
    """Every signal must be fresh and green. Unknown counts as busy (Codex: fail closed)."""
    report, eligible = {}, True
    for name, fn in signals.items():
        try:
            ok, detail = fn()
        except Exception as e:
            ok, detail = False, f"unknown: {type(e).__name__}: {str(e)[:80]}"
        report[name] = {"ok": ok, "detail": detail, "at": time.time()}
        eligible = eligible and ok
    return eligible, report


# ---- policy

def budget_ok(now: float) -> tuple[bool, str]:
    day = time.strftime("%Y-%m-%d", time.gmtime(now))
    used = (ledger.kv_get(f"budget:{day}") or {}).get("runs", 0) if isinstance(ledger.kv_get(f"budget:{day}"), dict) else 0
    if used >= BUDGET_PER_DAY:
        return False, f"budget {used}/{BUDGET_PER_DAY} used today"
    last = ledger.kv_get("last_run") or {}
    gap_min = (now - float(last.get("at", 0))) / 60 if last else 1e9
    if gap_min < MIN_GAP_MINUTES:
        return False, f"last run {gap_min:.0f} min ago (< {MIN_GAP_MINUTES})"
    return True, f"budget {used}/{BUDGET_PER_DAY}, last run {gap_min:.0f} min ago"


def gap_ok(now: float) -> bool:
    """MIN_GAP_MINUTES since the last launch of any kind."""
    last = ledger.kv_get("last_run") or {}
    return not last or (now - float(last.get("at", 0))) / 60 >= MIN_GAP_MINUTES


def idle_streak(eligible: bool, now: float) -> float:
    """Minutes of continuous eligibility, persisted so a restart cannot forget it."""
    st = ledger.kv_get("idle_since") or {}
    if not eligible:
        ledger.kv_set("idle_since", {"at": 0})
        return 0.0
    since = float(st.get("at", 0)) if isinstance(st, dict) else 0.0
    if not since:
        ledger.kv_set("idle_since", {"at": now})
        return 0.0
    return (now - since) / 60


# ---- outcomes: did a merge help? Followed up at 24h and 7d per merged candidate.

WINDOWS = (("24h", 1), ("7d", 7))


def reverted(repo: str, pr_url: str | None, since) -> bool:
    """A commit on main since the merge whose message reverts this PR."""
    if not pr_url:
        return False
    n = pr_url.rstrip("/").rsplit("/", 1)[-1]
    since_iso = since.isoformat() if hasattr(since, "isoformat") else str(since)
    for c in github.api(f"/repos/{repo}/commits?sha=main&since={since_iso}&per_page=100"):
        msg = (c.get("commit", {}).get("message") or "").lower()
        if "revert" in msg and f"#{n}" in msg:
            return True
    return False


def observe_outcomes() -> list[str]:
    """One outcome row per merged candidate per window: recurred (the same
    candidate was attempted again after the merge) and rolled_back (a revert on
    main). A recurrence or a revert is what the collector shows the investigator
    next time; without it 'merged' would be the end of the story."""
    done = []
    for window, days in WINDOWS:
        for c in ledger.pending_outcomes(window, days):
            fp, since = c["fingerprint"], c["observed_at"]
            recurred = ledger.runs_since(fp, since) > 0
            try:
                rolled_back = reverted(c["repo"], c["pr_url"], since)
            except Exception as e:
                rolled_back = None
                print(f"outcomes: {fp} {window}: revert check unknown ({type(e).__name__})")
            ledger.record_outcome(fp, c["run_id"], window, recurred=recurred, rolled_back=rolled_back,
                                  note=f"{'recurred' if recurred else 'no recurrence'}; {'reverted' if rolled_back else 'not reverted' if rolled_back is False else 'revert unknown'}")
            ledger.set_state(fp, "rolled_back" if rolled_back else "observed")
            if rolled_back:
                from fleet import memory
                memory.remember("lesson", f"The merge of {c.get('pr_url')} was reverted on main within {days} day(s); "
                                "whatever it changed was wrong or unwanted. Read the revert before touching that area again.",
                                repo=c.get("repo"), ref=c.get("pr_url"), source="reconcile")
            done.append(f"{fp}@{window}")
    return done


# ---- launch

def render_improve_job(cronjob: dict, name: str, trigger: str = "idle", repo: str | None = None) -> dict:
    tpl = json.loads(json.dumps(cronjob["spec"]["jobTemplate"]))
    job = {"apiVersion": "batch/v1", "kind": "Job",
           "metadata": {"name": name, "namespace": NAMESPACE,
                        "labels": {**(tpl.get("metadata", {}).get("labels") or {}), "app": "improve-daily", "fleet.example.com/trigger": trigger},
                        "annotations": {"fleet.example.com/reconciler": trigger}},
           "spec": tpl["spec"]}
    spec = job["spec"]["template"]["spec"]
    for c in spec.get("initContainers", []) + spec.get("containers", []):
        c["env"] = ([e for e in c.get("env", []) if e["name"] not in ("RUN_TRIGGER", "RUN_ID")]
                    + [{"name": "RUN_TRIGGER", "value": trigger}, {"name": "RUN_ID", "value": name}])
    # the daily branch name collides with the cron's; give the idle run its own
    for c in spec.get("initContainers", []) + spec.get("containers", []):
        c["env"] = [e for e in c["env"] if e["name"] != "BRANCH"] + [{"name": "BRANCH", "value": f"agent/{name}"}]
    if repo:  # the run works the repo the evidence points at, not the template's default
        for c in spec.get("initContainers", []) + spec.get("containers", []):
            c["env"] = [e for e in c["env"] if e["name"] != "REPO"] + [{"name": "REPO", "value": repo}]
    return job


def choose_repo(gh=None) -> tuple[str, str]:
    """(repo, why) for the next improve run: the repo with the most open fleet
    problems (fleet:halt, fleet:repair issues), kid-gloves repos excluded, the
    template's default when nothing is open. Until 2026-09-06 every improve run
    went to kagent while the reviewer's amnesia sat in new_localai."""
    gh = gh or github
    default = os.environ.get("REPO", "ctkadvisors/kagent")
    counts: dict[str, int] = {}
    try:
        # fleet:halt is the pipeline stopping, not a defect in the repo: 11 self-filed
        # halts pinned all 25 runs of 2026-09-13 to new_localai.
        for lbl in ("fleet:repair",):
            res = gh.api(f"/search/issues?q=org:{ORG}+is:open+is:issue+label:%22{lbl}%22&per_page=50")
            for it in (res.get("items") if isinstance(res, dict) else res) or []:
                repo = "/".join(it.get("repository_url", "").rsplit("/", 2)[-2:])
                if repo:
                    counts[repo] = counts.get(repo, 0) + 1
    except Exception as e:
        return default, f"default {default}: could not read the board ({type(e).__name__})"
    ranked = sorted(((n, r) for r, n in counts.items() if not gh.kid_gloves(r)), reverse=True)
    if not ranked:
        repos = [r for r in IDEATION_REPOS if not gh.kid_gloves(r)] or [default]
        try:
            last = {r.get("repo"): str(r.get("started_at") or "") for r in reversed(ledger.recent_runs(50))}
        except Exception:
            last = {}
        repo = min(repos, key=lambda r: last.get(r, ""))
        return repo, f"{repo}: no open fleet problems anywhere; the repo improved least recently"
    n, repo = ranked[0]
    return repo, f"{repo} has {n} open fleet problem(s), the most of any repo"


EMPTY_RUNS = int(os.environ.get("EMPTY_RUNS", "2"))
EMPTY_HALT = "investigator found no candidates"


def empty_streak(repo: str, runs=None, ideas=None) -> str | None:
    """Why a speculative run on `repo` must not launch: its last EMPTY_RUNS
    improve runs found nothing and nobody has posted an idea since. Until
    2026-09-08 the budget went to kagent runs that found nothing, daily."""
    runs = ledger.recent_runs(40) if runs is None else runs
    mine = sorted((r for r in runs if r.get("pipeline") == "improve" and r.get("repo") == repo and r.get("outcome")),
                  key=lambda r: str(r.get("started_at") or ""), reverse=True)[:EMPTY_RUNS]
    if len(mine) < EMPTY_RUNS or not all((r.get("halt") or {}).get("reason") == EMPTY_HALT for r in mine):
        return None
    since = max(str(r.get("finished_at") or r.get("started_at") or "") for r in mine)
    ideas = ledger.posts(topic="idea", limit=5) if ideas is None else ideas
    if any(str(p.get("created_at") or "") > since for p in ideas):
        return None
    return f"the last {EMPTY_RUNS} improve runs on {repo} found nothing and no idea has been posted since"


RECONCILE_CRONJOB = os.environ.get("RECONCILE_CRONJOB", "fleet-reconcile")


def launch_from_template(name: str, command: list[str], env: dict[str, str] | None = None, deadline: int = 1800) -> str | None:
    """A Job built from this CronJob's own template (same image, ledger and judge
    env) with its own command and deadline: anything longer than the tick's 240 s
    (an ideation, the dream) runs this way (2026-09-10: two ticks killed mid-run).
    Labelled app: mission so the scheduler counts it as busy. Returns the name."""
    try:
        cj = k8s("GET", f"/apis/batch/v1/namespaces/{NAMESPACE}/cronjobs/{RECONCILE_CRONJOB}")
        tpl = json.loads(json.dumps(cj["spec"]["jobTemplate"]))
        spec = tpl["spec"]
        spec["activeDeadlineSeconds"], spec["ttlSecondsAfterFinished"] = deadline, 3600
        c = spec["template"]["spec"]["containers"][0]
        c["command"] = command
        c["env"] = [e for e in c.get("env", []) if e.get("name") not in (env or {})] + [{"name": k, "value": v} for k, v in (env or {}).items()]
        spec["template"]["metadata"]["labels"] = {**(spec["template"].get("metadata", {}).get("labels") or {}), "app": "mission"}
        job = {"apiVersion": "batch/v1", "kind": "Job", "metadata": {"name": name, "namespace": NAMESPACE, "labels": {"app": "mission"}}, "spec": spec}
        if not DRY_RUN:
            try:
                k8s("POST", f"/apis/batch/v1/namespaces/{NAMESPACE}/jobs", job)
            except urllib.error.HTTPError as e:
                if e.code != 409:
                    raise
                print(f"{name} already exists (a finished one is kept an hour): counting it as launched")
        print(f"launched {name}")
        return name
    except Exception as e:
        print(f"could not launch {name} ({type(e).__name__}: {str(e)[:80]})")
        return None


def thinker_running() -> str | None:
    """The name of an ideation or dream Job still active, or None. One judge-
    heavy Job at a time: at 18:10Z on 2026-09-10 two ideations and the dream
    launched together, shared qwen38, and both ideations died at their
    deadline while the dream took 27 minutes instead of a few."""
    try:
        jobs = k8s("GET", f"/apis/batch/v1/namespaces/{NAMESPACE}/jobs?labelSelector=app%3Dmission").get("items", [])
    except Exception:
        return None
    for j in jobs:
        n = j["metadata"]["name"]
        if (n.startswith("ideate-") or n.startswith("dream-")) and (j.get("status", {}).get("active") or 0) > 0:
            return n
    return None


IDEATE_PER_DAY = int(os.environ.get("IDEATE_PER_DAY", "3"))


def launch_ideation(repo: str, now: float) -> str | None:
    """Ideation Jobs per repo (scripts/ideate.py): once a day, and again, up to
    IDEATE_PER_DAY, when the archive holds no untried idea for the repo. The Job
    sets kv ideated:<repo> itself; kv ideate-launched:<repo> counts the tick's
    launches. Returns the Job name, None when not launched. (2026-09-15: both
    repos ideated before 05:00, every idea was spent by noon, the improve run
    found nothing and the fleet had nothing to launch until the next day.)"""
    day = time.strftime("%Y-%m-%d", time.gmtime(now))
    done = ledger.kv_get(f"ideate-launched:{repo}") or {}
    runs = int(done.get("count") or 1) if done.get("day") == day else 0
    if not runs and (ledger.kv_get(f"ideated:{repo}") or {}).get("day") == day:
        runs = 1
    if runs:
        try:
            untried = any(not r.get("run_id") for r in ideas.rows(repo, ("active",), 20))
        except Exception:
            untried = True  # unknown: keep the once-a-day behaviour
        if untried or runs >= IDEATE_PER_DAY:
            return None
    busy = thinker_running()
    if busy:
        print(f"ideation: {busy} is still thinking; {repo} waits for a later tick")
        bump("blocked", "thinker")
        return None
    name = f"ideate-{repo.split('/')[-1][:20]}-{time.strftime('%Y%m%d', time.gmtime(now))}".lower().replace("_", "-") + (f"-{runs + 1}" if runs else "")
    env = {"IDEATE_REPO": repo, **({"IDEATE_FORCE": "1"} if runs else {})}   # ideate.py keeps its own once-a-day guard
    if launch_from_template(name, ["python3", "/app/scripts/ideate.py"], env, deadline=3600):
        ledger.kv_set(f"ideate-launched:{repo}", {"day": day, "at": now, "name": name, "count": runs + 1})
        return name
    return None


def bump(kind: str, field: str, now: float | None = None) -> None:
    """Count what stood in the fleet's way today; the night line reads it."""
    key = f"{kind}:{_day(now or time.time())}"
    try:
        v = ledger.kv_get(key) or {}
        v[field] = int(v.get(field, 0)) + 1
        ledger.kv_set(key, v)
    except Exception:
        pass


def capacity_line(now: float, evidence: str) -> str:
    """Is the spark the ceiling? Timeouts among the day's halts, and the ticks
    the spark or the thinker blocked. Chris, 2026-09-11: the second-spark
    decision should write itself from these two numbers."""
    timeouts = sum(1 for l in evidence.splitlines() if "exceeded the" in l and "timeout" in l)
    b: dict = {}
    for d in (_day(now), _day(now - 86400)):
        for k, v in (ledger.kv_get(f"blocked:{d}") or {}).items():
            b[k] = b.get(k, 0) + int(v)
    return f"{timeouts} halt(s) were stage timeouts; ticks blocked by the spark: {b.get('spark', 0)}, by the thinker: {b.get('thinker', 0)}"


MARK = re.compile(r"[\w-]+(?:/[\w.-]+)+|[A-Za-z_]\w*\.[A-Za-z_][\w.]*|[a-z]+[A-Z]\w+|[A-Z][A-Z0-9]*_[A-Z0-9_]+")


def marks_of(text: str) -> set[str]:
    """The code names in a text (paths, dotted names, camelCase, UPPER_SNAKE): what
    makes two pieces of work the same work."""
    return {m for m in MARK.findall(text or "") if len(m) >= 6}


def overlaps(text: str, busy: set[str]) -> bool:
    """A code name shared with work in flight. Short names must match exactly, so
    a mention of index.ts does not collide with every PR that touches one."""
    return any(m == b or (len(m) >= 10 and (m in b or b in m)) for m in marks_of(text) for b in busy)


def inflight_marks(repo: str, now: float, gh=None) -> set[str]:
    """Code names (titles, touched files) of the repo's open fleet PRs and of those
    closed unmerged in the last 7 days. 2026-09-15: the day's second ideation
    re-proposed kagent#59 and #60 (both open) and the WORKBENCH_PORT fix the
    reviewer had closed twice (#48, #55); the top-scored idea would have launched
    a duplicate of #59."""
    gh = gh or github
    out: set[str] = set()
    try:
        prs = list(gh.api(f"/repos/{repo}/pulls?state=open&per_page=30")) + [
            p for p in gh.api(f"/repos/{repo}/pulls?state=closed&per_page=30")
            if not p.get("merged_at") and parse_ts(p.get("closed_at") or "") > now - 7 * 86400]
        for p in prs:
            if not str((p.get("head") or {}).get("ref", "")).startswith(review.AGENT_BRANCH_PREFIX or "agent/"):
                continue
            out |= marks_of(p.get("title") or "")
            out |= {f["filename"] for f in gh.api(f"/repos/{repo}/pulls/{p['number']}/files?per_page=100")}
    except Exception as e:  # unknown: launch as before
        print(f"inflight_marks: {repo}: {type(e).__name__}: {str(e)[:80]}")
    return out


def launch_idea(repo: str, now: float) -> str | None:
    """The best active idea in the archive that no run has attempted becomes a
    mission: the brief is the idea tag and the launcher expands it. Returns the
    mission name, or None when the archive holds nothing untried. (2026-09-11:
    17 active ideas sat untried while the tick asked Chris to post one.) An idea
    that is work already in flight or refused this week waits (inflight_marks)."""
    todo = [r for r in ideas.rows(repo, ("active",), 20) if not r.get("run_id")]
    if not todo or DRY_RUN:
        return None
    busy = inflight_marks(repo, now)
    for best in sorted(todo, key=lambda r: ideas.score_of(r.get("scores") or {}), reverse=True):
        if overlaps(" ".join(str(best.get(k) or "") for k in ("problem", "mechanism")), busy):
            print(f"launch_idea: {best['id']} is work already in flight or refused this week; skipped")
            continue
        spans = best.get("touches") or repo      # 2026-09-14: two missions went looking for a file kagent never had
        gone = ideas.missing_paths(best.get("mechanism") or "", spans.split(","))
        if not gone:
            break
        ideas.set_status(best["id"], "rejected", reason=f"names files not in {spans}: {', '.join(gone[:3])}")
    else:
        return None
    body = json.dumps({"brief": f"[idea:{best['id']}]", "repo": repo, "requestedBy": "reconcile:idea"}).encode()
    req = urllib.request.Request(LAUNCHER + "/missions", data=body, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)["name"]
    except Exception as e:
        print(f"launch_idea: {best['id']}: {type(e).__name__}: {str(e)[:120]}")
        return None


def launch_dream(now: float) -> str | None:
    """The night's consolidation as its own Job (reconcile.py --dream): the
    judge call with lessons, taste and the structural proposal takes minutes.
    Once a night after DREAM_HOUR."""
    if (ledger.kv_get("dream-launch") or {}).get("day") == _day(now) or time.gmtime(now).tm_hour < DREAM_HOUR:
        return None
    if thinker_running():
        bump("blocked", "thinker")
        return None                                     # the tick's guard is set only when it launches
    if not _once_today("dream-launch", now, DREAM_HOUR):
        return None
    return launch_from_template("dream-" + time.strftime("%Y%m%d", time.gmtime(now)), ["python3", "/app/scripts/reconcile.py", "--dream"], deadline=3600)


def ideate(repo: str, now: float) -> int:
    """Kept for the empty-board path: launches the ideation Job; the ideas
    arrive on the forum when it finishes, so the tick does not fall through."""
    return 1 if launch_ideation(repo, now) else 0


# Chris, 2026-09-09: "Give them (and yourself) the tools you want."
# Sleep: once a night the fleet reads its own day (runs, halts, objections, the
# forum, what shipped) and writes what it learned into memory itself, plus a
# taste note on what good work looked like. The ruler: the bench runs itself
# every night and a regression is a forum question, not a surprise a week later.
DREAM_HOUR = int(os.environ.get("DREAM_HOUR", "3"))          # UTC; first tick at or after this hour
BENCH_HOUR = int(os.environ.get("BENCH_HOUR", "3"))
BENCH_CRONJOB = os.environ.get("BENCH_CRONJOB", "fleet-bench")


def _day(now: float) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(now))


def _once_today(key: str, now: float, hour: int) -> bool:
    """True exactly once per UTC day, on the first tick at or after `hour`."""
    if time.gmtime(now).tm_hour < hour:
        return False
    day = _day(now)
    if (ledger.kv_get(key) or {}).get("day") == day:
        return False
    ledger.kv_set(key, {"day": day, "at": now})
    return True


def day_evidence(now: float) -> str:
    """What happened in the last 24 hours, for the dream and for a human."""
    since = now - 86400
    ts = lambda v: float(v) if isinstance(v, (int, float)) else parse_ts(v)
    runs = [r for r in ledger.recent_runs(40) if ts(r.get("started_at")) >= since]
    lines = ["RUNS (last 24h):"] + [f"- {r.get('id')} {r.get('repo')} {r.get('outcome')} {(r.get('halt') or {}).get('reason', '')[:120]} {r.get('pr_url') or ''}" for r in runs] or ["- none"]
    try:
        objections = [v for k, v in ledger.kv_like("objection:%") if now - float(v.get("at", 0)) < 86400]
        if objections:
            lines.append("REVIEWER OBJECTIONS (last 24h):")
            lines += [f"- {o.get('summary', '')[:160]}" for o in objections[:6]]
    except Exception:
        pass
    try:
        posts = [p for p in ledger.posts(limit=60) if ts(p.get("created_at")) >= since and p.get("author") != "node-runner"]
        lines.append("FORUM (last 24h, newest first):")
        lines += [f"- {p['author']} ({p['topic']}): {str(p['body'])[:200]}" for p in posts[:25]]
    except Exception:
        pass
    return "\n".join(lines)


def archive_lines(limit: int = 20) -> str:
    """The active and shipped ideas, one line each, for the dream's prompt."""
    try:
        return "\n".join(f"- idea:{r['id']} [{r['status']}] {str(r['problem'])[:140]}" for r in ideas.rows(None, ("active", "shipped"), limit))
    except Exception:
        return ""


def dream(now: float, force: bool = False) -> dict:
    """Once a night: the day's evidence -> up to three lessons and three taste
    notes, written to memory by the fleet itself (source dream) and posted as a
    digest. Returns counts; {} when it is not time. The dream Job (launch_dream)
    calls it with force=True; the tick's guard is the launch."""
    if not force and not _once_today("dream", now, DREAM_HOUR):
        return {}
    from fleet import memory
    evidence = day_evidence(now)
    known = memory.recall(None, "", limit=30)
    # REM (idea lineage spec 2026-09-10, step 7): one structural proposal a
    # night, and it must cite the experience ids it grew from; no connection,
    # no growth, so an uncited proposal is dropped.
    lived = experience.recent(1)
    prompt = ("You are the fleet's night consolidation. From the last 24 hours below, write what the fleet should carry forward. "
              "Rules: specific to this fleet and these repos, never generic advice; nothing that is already in WHAT WE HAVE LEARNED; "
              "a lesson names the mistake or the surprise and what to do instead; a taste note names one shipped pull request that "
              "was good work and says in one sentence why (scope, verification, honesty); when the forum shows the concierge creating the same "
              "specialist role more than once, one lesson says that role should become a permanent Agent by pull request. "
              "Then exactly one structural proposal, or null: a pattern in EXPERIENCES that wants to become a change in the fleet's own code "
              "(a rule learned three times wants to become a check; three halts at one stage want a guard), citing the experience ids it rests on. "
              "Reply with STRICT JSON only: "
              "{\"lessons\": [{\"text\": \"...\", \"repo\": \"<owner/repo or null>\"}], \"taste\": [{\"text\": \"...\", \"repo\": \"<owner/repo or null>\"}], "
              "\"proposal\": {\"problem\": \"...\", \"mechanism\": \"...\", \"novelty\": \"...\", \"assumptions\": \"...\", \"effect\": \"<measurable, done when>\", "
              "\"evidence\": [\"<experience id>\"]}} "
              "with at most 3 of each list; empty lists and a null proposal are fine when the day taught nothing new.\n\n" + evidence
              + "\n\nEXPERIENCES (cite these ids as evidence):\n" + (experience.render(lived) or "- none")
              + "\n\nIDEA ARCHIVE (already held or shipped; a proposal must not repeat one of these, the first dream re-proposed a shipped fix, 2026-09-10):\n"
              + (archive_lines() or "- none") + "\n\n" + known)
    out = {"lessons": 0, "taste": 0, "proposed": 0}
    try:
        got = review.parse_json(review.ask_judge(prompt, temperature=0.2))
    except Exception as e:
        print(f"dream: judge unavailable ({type(e).__name__}: {str(e)[:80]})")
        return out
    for it in (got.get("lessons") or [])[:3]:
        text = str(it.get("text", "")).strip()
        if len(text) > 20 and memory.remember("lesson", text, repo=it.get("repo") or None, source="dream"):
            out["lessons"] += 1
    for it in (got.get("taste") or [])[:3]:
        text = str(it.get("text", "")).strip()
        if len(text) > 20 and memory.remember("fact", "Taste: " + text, repo=it.get("repo") or None, source="dream"):
            out["taste"] += 1
    prop = got.get("proposal") if isinstance(got.get("proposal"), dict) else {}
    cited = [i for i in (prop.get("evidence") or []) if i in {e["id"] for e in lived}]
    proposed = ""
    if cited:
        try:
            ideas.add(prop, FLEET_REPO, "dream", evidence=cited)
            out["proposed"], proposed = 1, str(prop.get("problem", "")).strip()[:160]
        except Exception as e:  # the idea table is not the night's only work
            print(f"dream: proposal not stored ({type(e).__name__}: {str(e)[:80]})")
    shipped = sum(1 for l in evidence.splitlines() if " shipped " in l)
    halted = sum(1 for l in evidence.splitlines() if " halted " in l or " failed " in l)
    ledger.say("reconcile", f"Night consolidation: {shipped} shipped, {halted} halted or failed in the last 24 h; "
               f"wrote {out['lessons']} lesson(s) and {out['taste']} taste note(s) into memory myself"
               + (f"; proposed: {proposed}" if proposed else "") + ". Capacity: " + capacity_line(now, evidence) + ".", topic="status")
    # Chris, 2026-09-09: "i see lots of 'probe-egress OK' but no 'dreaming'". One
    # line a night, with what was learned, where he reads.
    try:
        st = ideas.stats()
        ideas_line = f"{st['by_status'].get('active', 0)} active, {st['by_status'].get('shipped', 0)} shipped, {st['links']} links"
    except Exception:
        ideas_line = ""
    if out["lessons"] or out["taste"] or proposed:
        try:
            texts = [str(it.get("text", "")).strip() for it in (got.get("lessons") or [])[:3]] + \
                    ["Taste: " + str(it.get("text", "")).strip() for it in (got.get("taste") or [])[:2]] + \
                    ([f"proposed: {proposed}"] if proposed else []) + ([f"ideas: {ideas_line}"] if ideas_line else [])
            telegram.send(f"🌙 Dreamt on the last 24 h ({shipped} shipped, {halted} halted): "
                          f"{out['lessons']} lesson(s), {out['taste']} taste note(s) into memory.\n"
                          + "\n".join(f"- {t[:200]}" for t in texts if len(t) > 20) + f"\n{telegram.CONSOLE_URL}")
        except Exception as e:
            print(f"dream: telegram failed ({type(e).__name__})")
    print(f"dream: {out}")
    return out


def nightly_bench(now: float) -> str | None:
    """Once a night, run the bench (scripts/bench.py via the fleet-bench template)
    so every harness change is measured against yesterday. Returns the job name."""
    if not _once_today("nightly-bench", now, BENCH_HOUR):
        return None
    name = "bench-" + time.strftime("%Y%m%d", time.gmtime(now))
    try:
        cj = k8s("GET", f"/apis/batch/v1/namespaces/{NAMESPACE}/cronjobs/{BENCH_CRONJOB}")
        tpl = json.loads(json.dumps(cj["spec"]["jobTemplate"]))
        job = {"apiVersion": "batch/v1", "kind": "Job",
               "metadata": {"name": name, "namespace": NAMESPACE, "labels": {**(tpl.get("metadata", {}).get("labels") or {}), "app": "mission"}},
               "spec": tpl["spec"]}
        if not DRY_RUN:
            k8s("POST", f"/apis/batch/v1/namespaces/{NAMESPACE}/jobs", job)
        print(f"bench: launched {name}")
        return name
    except Exception as e:
        print(f"bench: could not launch ({type(e).__name__}: {str(e)[:80]})")
        return None


def weekly_bench_target(now: float) -> str | None:
    """Once a week (idea lineage spec 2026-09-10, step 8), one improve run whose
    brief is "raise the bench". It goes through the mission launcher like a
    board retry (requestedBy `bench:` -> RUN_TRIGGER=bench), spends the day's
    budget like any run, and the week in the brief's first line makes each
    week its own candidate for the launcher's attempt cap. The held-out fixture
    is the reviewer's ruler, not the implementer's target; ties are rejected.
    Returns the mission name, None when this week's has launched or it could not."""
    week = time.strftime("%G-W%V", time.gmtime(now))
    if (ledger.kv_get("bench-target") or {}).get("week") == week:
        return None
    from bench import HELD_OUT, TASKS
    visible = ", ".join(n for n in TASKS if n not in HELD_OUT)
    brief = (f"Raise the bench (week {week}). services/fleet-scripts/scripts/bench.py runs fixed implement fixtures through the real "
             f"stage machinery (stage.sh implement, the dsh patch, the model on the spark) and records success and seconds per fixture; "
             f"the visible fixtures are {visible}. Make more of them pass, or pass faster, by improving the harness only: "
             "services/fleet-scripts/scripts/stage.sh, the dsh patches and stage prompts in "
             "k8s-kustomized/overlays/production/kagent/improve-daily.yaml (dsh-patch.yml, dsh-patch-judge.yml, implement.txt, test.txt), "
             "and the skills under services/fleet-scripts/skills. Do not change the fixtures or the scoring in bench.py. "
             f"One fixture is held-out ({', '.join(sorted(HELD_OUT))}): it is not your target, and the reviewer accepts this PR only if the "
             "held-out score strictly improves on the current one (a tie is rejected), so make a change that generalises rather than one "
             "tuned to the visible fixtures. When every visible fixture already passes, the target is speed: fewer rounds, fewer dsh "
             "calls, less prompt; the held-out fixture must stay passing and run at least 10% faster. Make ONE change and stop; "
             "say in the PR which visible fixture you aimed at, why, and what you expect the held-out fixture to do.")
    if DRY_RUN:
        print("bench-target: would launch (dry run)"); return None
    body = json.dumps({"brief": brief, "repo": FLEET_REPO, "requestedBy": "bench:weekly"}).encode()
    req = urllib.request.Request(LAUNCHER + "/missions", data=body, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            name = json.load(r)["name"]
    except Exception as e:  # 409 (still running) or the launcher down: the next tick tries again
        print(f"bench-target: {type(e).__name__}: {str(e)[:120]}"); return None
    ledger.kv_set("bench-target", {"week": week, "at": now, "name": name})
    ledger.say("reconcile", f"Launched {name} on {FLEET_REPO}: this week's \"raise the bench\" run ({visible} visible; "
               f"{', '.join(sorted(HELD_OUT))} held-out, and the reviewer rejects a tie there).", topic="status", ref=name)
    return name


IDEATION_REPOS = [r for r in os.environ.get("IDEATION_REPOS", "ctkadvisors/new_localai,ctkadvisors/kagent").split(",") if r]
IDEATE_HOUR = int(os.environ.get("IDEATE_HOUR", "4"))


def daily_ideation(now: float) -> list[str]:
    """Ideation is a daily practice, not a fallback: until 2026-09-10 the
    ideator ran only when a repo's board had been empty for a while, so the
    archive filled once and the search stopped. Once a day per repo after
    IDEATE_HOUR (ideate keeps its own once-a-day guard). Returns the repos
    that posted."""
    if time.gmtime(now).tm_hour < IDEATE_HOUR:
        return []
    posted = []
    for repo in IDEATION_REPOS:
        try:
            if launch_ideation(repo, now):
                posted.append(repo)
                break                                    # one thinker at a time; the next repo on a later tick
        except Exception as e:
            print(f"ideation: {repo} failed ({type(e).__name__}: {str(e)[:80]})")
    return posted


def bench_outcome(now: float) -> list[str]:
    """The honest gate for a 'raise the bench' PR: the first nightly --held-out
    bench after its merge against the last one before. A regression comments
    on the PR, tells Chris, fails the idea (-1 on its path) and asks the
    fleet to revert itself through a mission; an improvement reinforces the
    idea's path. Once per PR (kv bench-outcome:<pr_url>)."""
    done = []
    try:
        runs = ledger.merged_runs(trigger="bench")
        benches = sorted((k.split(":", 1)[1], v) for k, v in ledger.kv_like("bench:%") if re.fullmatch(r"\d{8}", k.split(":", 1)[1]))
    except Exception as e:
        print(f"bench-outcome: skipped ({type(e).__name__})"); return done
    from bench import verdict, held_out_passes
    for r in runs:
        pr_url, key = r.get("pr_url"), f"bench-outcome:{r.get('pr_url')}"
        if not pr_url or ledger.kv_get(key):
            continue
        merged_day = str(r.get("merged_at") or "")[:10].replace("-", "")
        # the nightly bench runs at ~03:00Z, before any merge of that day: same-day is "before"
        before = [v for d, v in benches if d <= merged_day]
        after = [v for d, v in benches if d > merged_day]
        if not before or not after:
            continue
        v = verdict(before[-1], after[0])
        a, b = held_out_passes(before[-1]), held_out_passes(after[0])
        ledger.kv_set(key, {"verdict": v, "held_out": [a, b], "at": now})
        note = f"held-out bench {a} -> {b} after the merge of {pr_url}: {v}"
        iid = None
        try:
            iid, _ = ideas.lookup(pr_url=pr_url)
        except Exception:
            pass
        if v == "regressed":
            try:
                n = pr_url.rsplit("/", 1)[-1]
                github.api(f"/repos/{r['repo']}/issues/{n}/comments", {"body": f"**Bench outcome**: {note}. The fleet is reverting this."})
            except Exception:
                pass
            telegram.send(f"\u26a0\ufe0f {note}. Reverting through a mission.\n{pr_url}")
            from fleet import memory
            memory.remember("lesson", f"The bench-target merge {pr_url} regressed the held-out bench ({a} -> {b}) and was reverted; "
                            "a harness change must generalise past the visible fixtures.", repo=r.get("repo"), ref=pr_url, source="reconcile")
            if iid:
                ideas.set_status(iid, "failed", reason=f"bench regressed after merge ({a} -> {b})")
                ideas.reinforce(f"pr:{pr_url}", -1.0)
            try:
                body = json.dumps({"brief": f"Revert {pr_url} on main: {note}. Use git revert on its merge commit, open the PR, and say in the PR body which held-out fixture regressed.",
                                   "repo": r["repo"], "requestedBy": "bench:revert"}).encode()
                req = urllib.request.Request(LAUNCHER + "/missions", data=body, headers={"Content-Type": "application/json"}, method="POST")
                with urllib.request.urlopen(req, timeout=30) as resp:
                    print(f"bench-outcome: revert mission {json.load(resp).get('name')}")
            except Exception as e:
                print(f"bench-outcome: revert launch failed ({type(e).__name__}: {str(e)[:80]})")
        elif v == "improved" and iid:
            ideas.reinforce(f"pr:{pr_url}", +1.0)
        ledger.say("reconcile", f"Bench outcome for {pr_url}: {note}.", topic="status", ref=pr_url)
        done.append(f"{pr_url}:{v}")
    return done


def bench_trend(now: float) -> str | None:
    """When tonight's bench has recorded itself, compare with the last one and
    say so; a drop in successes is a question to Chris and a lesson."""
    day = time.strftime("%Y%m%d", time.gmtime(now))
    cur = ledger.kv_get(f"bench:{day}")
    if not cur or (ledger.kv_get("bench-reported") or {}).get("day") == day:
        return None
    ledger.kv_set("bench-reported", {"day": day})
    prev = [(k, v) for k, v in ledger.kv_like("bench:%") if k != f"bench:{day}" and isinstance(v, dict) and "success" in v]
    prev.sort(key=lambda kv: float(kv[1].get("at", 0)))
    last = prev[-1][1] if prev else None
    line = f"Nightly bench {day}: {cur['success']}/{cur['n']} in {cur['seconds']}s, {cur.get('prompt_bytes', 0)} prompt bytes, {cur.get('rounds', '-')} rounds"
    if last:
        line += f" (last: {last['success']}/{last['n']} in {last['seconds']}s)"
    if last and cur["success"] < last["success"]:
        from fleet import memory
        memory.remember("lesson", f"The harness regressed on the bench {day}: {cur['success']}/{cur['n']} after {last['success']}/{last['n']}; the last merged change to stage.sh, the prompts or the skills is the suspect.", source="bench")
        ledger.say("reconcile", line + ". The harness regressed; the last change to stage.sh, the prompts or the skills is the suspect. Revert or explain?", topic="question", mentions=["chris"])
    else:
        ledger.say("reconcile", line + ".", topic="status")
    print("bench: " + line)
    return line


def retry_board(now: float) -> str | None:
    """Board first, speculation second. A human-labelled mission that halted
    (candidate.state=halted, its issue open and still labelled `mission`) is
    relaunched through the launcher, which owns the attempt cap and refuses an
    active run; the brief carries the comments left since. brutalist_todo #22
    and #23 sat halted for a day while the daily budget went to a kagent run
    that found nothing. Returns the mission name, or None when nothing waits."""
    import triage
    for c in ledger.halted_candidates():
        m = re.search(r"github\.com/([\w.-]+/[\w.-]+)/issues/(\d+)", c.get("issue_url") or "")
        if not m:
            continue
        repo, num = m.group(1), m.group(2)
        try:
            issue = github.api(f"/repos/{repo}/issues/{num}")
            if issue.get("state") != "open" or "mission" not in {l["name"] for l in issue.get("labels", [])}:
                continue
            # The implementer asked something and nobody answered: wait, do not
            # burn another run (mission 22 asked twice on 2026-09-06 and was
            # relaunched three times into the same wall).
            if ledger.open_questions(c["issue_url"]):
                print(f"retry_board: {repo}#{num} has an open question on the forum; waiting for the answer")
                continue
            if DRY_RUN:
                print(f"retry_board: would relaunch {repo}#{num} (dry run)")
                return None
            brief = triage.brief_for(issue, github.api(f"/repos/{repo}/issues/{num}/comments")) + context_for(c["fingerprint"], c["issue_url"])
            payload = {"brief": brief, "repo": repo, "requestedBy": "reconcile:board"}
            branch = open_pr_branch(c["fingerprint"], repo)
            if branch:  # a halted review round: continue the PR, do not open a second one
                payload["branch"] = branch
                payload["brief"] = (brief + f"\n\nThe PR for this work is already open on branch {branch} (checked out); continue it.")[:8000]
            body = json.dumps(payload).encode()
            req = urllib.request.Request(LAUNCHER + "/missions", data=body, headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)["name"]
        except urllib.error.HTTPError as e:  # 409 = still running or parked after MAX_ATTEMPTS
            print(f"retry_board: {repo}#{num}: HTTP {e.code} {e.read()[:160].decode(errors='replace')}")
        except Exception as e:
            print(f"retry_board: {repo}#{num}: {type(e).__name__}: {str(e)[:120]}")
    return None


def open_pr_branch(fp: str, repo: str, gh=None) -> str | None:
    """The head branch of this candidate's open PR, if any: a relaunch continues
    it instead of opening a second PR (the review round on brutalist_todo#24
    halted at 23:12 on 2026-09-06 and the board would have started over)."""
    gh = gh or github
    try:
        m = re.search(r"/pull/(\d+)$", ledger.last_pr_url(fp) or "")
        if not m:
            return None
        pr = gh.api(f"/repos/{repo}/pulls/{m.group(1)}")
        if pr.get("state") == "open" and not pr.get("merged"):
            return pr["head"]["ref"]
    except Exception as e:
        print(f"open_pr_branch: {type(e).__name__}: {str(e)[:80]}")
    return None


ASK_PER_TICK = int(os.environ.get("ASK_PER_TICK", "2"))  # <= the gateway's AIMD floor for ornith15; a third ask each tick lost to 429 and kept the cap from growing (2026-09-11 18:00Z)
ASK_TRIES = int(os.environ.get("ASK_TRIES", "3"))


def task_phase(name: str | None) -> str | None:
    """The phase of a workbench AgentTask by name, None when unknown. Through
    the list: the reconcile account may list agenttasks but not get one."""
    if not name:
        return None
    try:
        items = k8s("GET", "/apis/kagent.example.com/v1alpha1/agenttasks?limit=500").get("items", [])
        return next((t.get("status", {}).get("phase") for t in items if t["metadata"].get("name") == name), None)
    except Exception:
        return None


def relay_answers() -> int:
    """A concierge task that Completed without replying on the forum still
    decided: its final text becomes the reply, posted by the tick, not by the
    model. (#673, 2026-09-11: the concierge wrote the decision and then said
    "I could not post it, the tool guard refused"; the thread stayed open.)"""
    relayed = 0
    try:
        asked = [(k, v) for k, v in ledger.kv_like("asked:%") if isinstance(v, dict) and v.get("task") and not v.get("relayed")]
        if not asked:
            return 0
        items = k8s("GET", "/apis/kagent.example.com/v1alpha1/agenttasks?limit=500").get("items", [])
    except Exception as e:
        print(f"relay: {type(e).__name__}: {str(e)[:80]}")
        return 0
    by_name = {t["metadata"].get("name"): t for t in items}
    for key, v in asked:
        t = by_name.get(v["task"])
        if not t or t.get("status", {}).get("phase") != "Completed":
            continue
        qid = int(key.split(":", 1)[1])
        try:
            if any(p.get("parent_id") == qid for p in ledger.posts(limit=200)):
                ledger.kv_set(key, {**v, "relayed": True}); continue  # the concierge managed to post itself
            text = str((t.get("status", {}).get("result") or {}).get("content") or "").strip()
            if not text:  # "Yes" is an answer; a length cutoff dropped it (#197/#202, 2026-09-15)
                ledger.kv_set(key, {**v, "relayed": True}); continue
            ledger.post("concierge", text[:4000], topic="note", parent_id=qid)
            ledger.kv_set(key, {**v, "relayed": True})
            relayed += 1
        except Exception as e:
            print(f"relay: #{qid}: {type(e).__name__}: {str(e)[:80]}")
    return relayed


def ask_concierge(now: float, workbench: str | None = None) -> int:
    """Every unanswered forum question gets an answerer: the concierge, through
    a workbench AgentTask, with the thread and instructions to reply on the
    forum. Chris reads the forum and Telegram and overrides; he is never the
    gate. (Until 2026-09-11 a question that mentioned chris was skipped here,
    and every question the fleet writes mentions chris: 0 of 12 were routed.)"""
    workbench = workbench or WORKBENCH_URL
    asked = 0
    try:
        rows = [p for p in ledger.posts(limit=30, topic="question", unanswered=True)
                if now - parse_ts(p.get("created_at")) > 120]
    except Exception as e:
        print(f"ask: ledger unavailable ({type(e).__name__})")
        return 0
    for p in rows:
        if asked >= ASK_PER_TICK:
            break  # 14 at once on 2026-09-11: 7 hit HTTP 429, 4 ran out of iterations; the backlog drains a tick at a time
        key = f"asked:{p['id']}"
        try:
            prior = ledger.kv_get(key) or {}
            if prior and (prior.get("tries", 1) >= ASK_TRIES or task_phase(prior.get("task")) != "Failed"):
                continue  # running, answered, or given up; only a Failed task earns another try
            thread = ledger.posts(limit=10, ref=p["ref"]) if p.get("ref") else []
            prompt = (f"A forum question from {p['author']} (post #{p['id']}" + (f", about {p['ref']}" if p.get("ref") else "") + ") needs an answer:\n\n"
                      f"{str(p['body'])[:3000]}\n\n"
                      + ("Thread so far, oldest first:\n" + "\n".join(f"- {t['author']}: {str(t['body'])[:400]}" for t in reversed(thread)) + "\n\n" if thread else "")
                      + "Answer it on the forum: POST http://fleet-console.kagent-system.svc:8081/api/post with JSON "
                      f"{{\"author\":\"concierge\",\"topic\":\"note\",\"body\":\"<your answer>\",\"parent_id\":{p['id']}}}. "
                      "Decide as the front desk would: read the thread, the brain and the repo facts you can reach; be concrete about what to do and what not to do. "
                      "Decide. If the evidence is thin, make the call, state the assumption in the reply, and move on: Chris reads the forum and overrides when he wants to.")
            body = {"namespace": NAMESPACE, "targetAgent": "concierge", "originalUserMessage": prompt,
                    "payload": {"text": prompt, "forumQuestion": p["id"]},
                    "runConfig": {"maxIterations": 20, "timeoutSeconds": 900}}
            req = urllib.request.Request(workbench + "/api/tasks", data=json.dumps(body).encode(),
                                         headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=30) as r:
                created = json.load(r)
            name = created.get("name") or created.get("task", {}).get("name")
            ledger.kv_set(key, {"at": now, "task": name, "tries": int(prior.get("tries", 0)) + 1})
            ledger.say("reconcile", f"Asked the concierge to answer forum #{p['id']} from {p['author']} (task {name}).", topic="status",
                       ref=p.get("ref"), mentions=["concierge"])
            asked += 1
        except Exception as e:
            print(f"ask: post {p['id']}: {type(e).__name__}: {str(e)[:120]}")
    return asked


def watch_ships(now: float, gh=None) -> list[str]:
    """A merged fleet-scripts PR is live only once the ship workflow rebuilt the
    image and bumped the tag. On 2026-09-06 the ship failed on the runner after
    the reviewer's own merge of #25 and nobody noticed for 20 minutes. Re-run a
    failed ship once; if it fails again, ask Chris on the forum."""
    gh = gh or github
    acted = []
    try:
        runs = gh.api(f"/repos/{FLEET_REPO}/actions/workflows/fleet-scripts.yml/runs?branch=main&per_page=3").get("workflow_runs", [])
    except Exception as e:
        print(f"ships: cannot list runs ({type(e).__name__})")
        return acted
    for run in runs[:1]:  # only the newest matters: a later success supersedes
        if run.get("status") != "completed" or run.get("conclusion") in ("success", "skipped", None):
            break
        if now - parse_ts(run.get("updated_at")) > 6 * 3600:
            break
        key = f"ship-rerun:{run['id']}"
        try:
            prior = ledger.kv_get(key) or {}
            if prior.get("tries", 0) >= 1:
                if not prior.get("escalated"):
                    ledger.say("reconcile", f"The ship of {FLEET_REPO}@main ({run.get('head_sha', '')[:7]}) failed twice ({run.get('html_url')}); "
                               "the merged code is not live. I re-ran it once already.", topic="question", ref=run.get("html_url"), mentions=["chris"])
                    ledger.kv_set(key, {**prior, "escalated": True})
                break
            gh.api(f"/repos/{FLEET_REPO}/actions/runs/{run['id']}/rerun-failed-jobs", {}, method="POST")
            ledger.kv_set(key, {"tries": 1, "at": now})
            ledger.say("reconcile", f"The ship of {FLEET_REPO}@main ({run.get('head_sha', '')[:7]}) failed; re-running its failed jobs ({run.get('html_url')}).",
                       topic="status", ref=run.get("html_url"))
            acted.append(str(run["id"]))
        except Exception as e:
            print(f"ships: run {run.get('id')}: {type(e).__name__}: {str(e)[:120]}")
            try:
                ledger.kv_set(key, {"tries": 1, "at": now, "error": type(e).__name__})
                ledger.say("reconcile", f"The ship of {FLEET_REPO}@main failed and I could not re-run it ({type(e).__name__}; the App may lack actions:write). {run.get('html_url')}",
                           topic="question", ref=run.get("html_url"), mentions=["chris"])
            except Exception:
                pass
    return acted


def context_for(fp: str, ref: str | None) -> str:
    """What the next attempt must know: how the last one ended, and the forum
    thread on this subject (questions and their answers). Bot comments never
    ride along in the brief (triage.brief_for), so this is the memory."""
    out = []
    try:
        last = ledger.last_run(fp)
        if last and last.get("outcome") in ("halted", "failed"):
            h = last.get("halt") or {}
            out.append(f"Previous attempt {last['id']} {last['outcome']} at {h.get('stage', '?')}: {str(h.get('reason', ''))[:300]}. "
                       "Do not repeat it; if the cause is outside your control, stop and say so.")
    except Exception:
        pass
    try:
        thread = ledger.posts(limit=12, ref=ref) if ref else []
        if thread:
            out.append("Forum thread on this work, oldest first:\n" + "\n".join(
                f"- {p['author']} ({p['topic']}): {str(p['body'])[:600]}" for p in reversed(thread)))
    except Exception:
        pass
    return ("\n\n" + "\n\n".join(out)) if out else ""


def reap_failed_runs(now: float, gh=None) -> list[str]:
    """A run whose Job died before publish (a stage killed: OOM, deadline) left
    the ledger row open, nothing on the forum, nothing on the issue, and the
    board relaunched it into the same wall. Close it as `failed` with the stage
    and exit code, say so, and file the halt on the issue so the collector sees it."""
    gh = gh or github
    reaped = []
    try:
        open_runs = ledger.unfinished_runs()
    except Exception as e:
        print(f"reap: ledger unavailable ({type(e).__name__})")
        return reaped
    for r in open_runs:
        try:
            job = k8s("GET", f"/apis/batch/v1/namespaces/{NAMESPACE}/jobs/{r['id']}")
        except Exception as e:
            if "404" in str(e) and now - parse_ts(r.get("started_at")) > 3600:
                ledger.finish_run(r["id"], "failed", halt={"stage": "?", "reason": "Job gone without publishing"},
                                  pipeline=r["pipeline"], repo=r["repo"], trigger=r["trigger"], fp=r.get("fingerprint"))
                reaped.append(r["id"])
            continue
        st = job.get("status", {})
        if not st.get("failed") or st.get("active"):
            continue
        stage, code, why = "?", "?", ""
        try:
            pods = k8s("GET", f"/api/v1/namespaces/{NAMESPACE}/pods?labelSelector=job-name%3D{r['id']}").get("items", [])
            for p in pods:
                for c in (p.get("status", {}).get("initContainerStatuses") or []) + (p.get("status", {}).get("containerStatuses") or []):
                    t = (c.get("state") or {}).get("terminated") or {}
                    if t and t.get("exitCode", 0) != 0:
                        stage, code, why = c["name"], t.get("exitCode"), t.get("reason") or ""
                        break
        except Exception:
            pass
        reason = f"stage container killed, exit {code}" + (
            " (OOMKilled: out of memory; the stage never reached publish)" if why == "OOMKilled" or code == 137 else "")
        halt = {"stage": stage, "reason": reason, "exit_code": code, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))}
        ledger.finish_run(r["id"], "failed", halt=halt, pipeline=r["pipeline"], repo=r["repo"], trigger=r["trigger"], fp=r.get("fingerprint"))
        if r.get("fingerprint"):
            ledger.set_state(r["fingerprint"], "halted")
            # A death before publish is still an outcome for the idea (lineage spec
            # step 6, 2026-09-10); the candidate row carries the id from an earlier publish.
            try:
                iid = ideas.lookup(fp=r["fingerprint"])[0]
                if iid:
                    ideas.outcome(iid, r["id"], halt=halt)
            except Exception as e:
                print(f"reap: ideas write failed (non-fatal): {type(e).__name__}")
        issue_url = None
        try:
            issue_url = next((c.get("issue_url") for c in ledger.halted_candidates() if c["fingerprint"] == r.get("fingerprint")), None)
        except Exception:
            pass
        ledger.say("reconcile", f"{r['id']} on {r['repo']} died at {stage} ({reason}); recorded as failed. "
                   + ("The next attempt carries this." if issue_url else ""), topic="status", ref=issue_url or r["id"], mentions=["implementer"])
        if issue_url and "/issues/" in issue_url:
            try:
                gh.api("/repos/" + issue_url.split("github.com/", 1)[-1] + "/comments",
                       {"body": f"Attempt `{r['id']}` died at **{stage}** ({reason}) before it could report. Recorded by reconcile."})
            except Exception as e:
                print(f"reap: could not comment on {issue_url}: {type(e).__name__}")
        reaped.append(r["id"])
    return reaped


ESCALATE_MINUTES = int(os.environ.get("ESCALATE_MINUTES", "15"))


def relay_questions(now: float) -> int:
    """A forum question addressed to Chris reaches Telegram once, with where to
    answer, but only after the concierge (ask_concierge) has had ESCALATE_MINUTES
    and the thread is still open: #1197 paged him at 13:20 and the concierge
    answered it at 13:21 (2026-09-15). 15 min stays inside the forum plugin's
    20-min wait, so a page still lands while the stage can use the answer."""
    sent = 0
    try:
        rows = [p for p in ledger.posts(limit=30, topic="question", unanswered=True) if "chris" in (p.get("mentions") or [])]
    except Exception as e:
        print(f"relay: ledger unavailable ({type(e).__name__})")
        return 0
    for p in rows:
        key = f"relayed:{p['id']}"
        try:
            if ledger.kv_get(key):
                continue
            if p.get("created_at") and now - parse_ts(p["created_at"]) < ESCALATE_MINUTES * 60:
                continue  # the concierge's turn first
            label = telegram.ref_label(p.get("ref"))
            telegram.send(f"❓ {p['author']} asks" + (f" about {label}" if label else "") + f":\n{str(p['body'])[:900]}\n\n"
                          f"Answer here (the fleet waits for it): {telegram.post_link(p['id'])}"
                          + (f"\n{p['ref']}" if p.get("ref") and str(p["ref"]).startswith("http") else ""))
            ledger.kv_set(key, {"at": now})
            sent += 1
        except Exception as e:
            print(f"relay: post {p['id']}: {type(e).__name__}: {str(e)[:80]}")
    return sent


def retry_reviewed(now: float, gh=None) -> str | None:
    """Iterate on a PR the reviewer objected to or CI rejected: relaunch the
    mission on the PR's own branch with the objection and the failing checks in
    the brief. The launcher caps review rounds (REVIEW_ROUNDS). PR 24 sat for a
    day with confidence 82 and red CI because nothing ever re-ran the implementer."""
    gh = gh or github
    import triage
    try:
        rows = ledger.tested_candidates()
    except Exception as e:
        print(f"retry_reviewed: ledger unavailable ({type(e).__name__})")
        return None
    for c in rows:
        m = re.search(r"github\.com/([\w.-]+/[\w.-]+)/pull/(\d+)", c.get("pr_url") or "")
        if not m:
            continue
        repo, n = m.group(1), m.group(2)
        try:
            if gh.kid_gloves(repo):
                continue  # a human iterates there
            pr = gh.api(f"/repos/{repo}/pulls/{n}")
            if pr.get("state") != "open" or pr.get("merged"):
                continue
            objection = ledger.kv_get(f"objection:{repo}#{n}")
            runs = gh.api(f"/repos/{repo}/commits/{pr['head']['sha']}/check-runs").get("check_runs", [])
            # A cancelled check (a concurrency group killed it) is not a failing
            # check: nothing in the code is wrong, so no implementer round can fix
            # it. kagent#26 got two review rounds on 2026-09-07 that pushed
            # nothing for a "CRD drift check" that was only cancelled. Re-run it
            # once per head instead.
            cancelled = [x for x in runs if x.get("conclusion") == "cancelled"]
            red = [x["name"] for x in runs if x.get("status") == "completed" and x.get("conclusion") not in ("success", "skipped", "cancelled", None)]
            if cancelled:
                key = f"rerun:{repo}#{n}:{pr['head']['sha'][:12]}"
                if not ledger.kv_get(key):
                    ok = rerun_cancelled(repo, cancelled, gh)
                    ledger.kv_set(key, {"at": now, "ok": ok})
                    ledger.say("reconcile", f"Re-ran the cancelled check(s) {', '.join(x['name'] for x in cancelled)} on {pr['html_url']}"
                               + ("" if ok else " (the re-run request failed; the App may lack actions:write)")
                               + ". A cancelled run is not a failing run, so no review round for it.",
                               topic="status", ref=pr["html_url"], mentions=["reviewer"] if ok else ["chris"])
            if not objection and not red:
                continue
            if objection and str(objection.get("sha")) == pr["head"]["sha"] and parse_ts(c.get("started_at")) > float(objection.get("at", 0)):
                continue  # the last run already answered this head's objection; the reviewer has not re-judged yet
            if objection and str(objection.get("sha")) != pr["head"]["sha"] and not red:
                # A push newer than the objection: the reviewer judges it before another round.
                # kagent#59 got a third round at 17:05 on the 16:15 objection that the 16:47 push
                # had already answered (2026-09-15). A red check is fresh evidence and still relaunches.
                continue
            if parse_ts(c.get("started_at")) > now - MIN_GAP_MINUTES * 60:
                continue
            if c.get("issue_url") and ledger.open_questions(c["issue_url"]):
                continue
            feedback = ""
            if objection:
                feedback += f"\n\nREVIEW FEEDBACK on {pr['html_url']} (the reviewer will not merge until every point is addressed):\n{objection.get('feedback') or objection.get('summary', '')}"[:3500]
            if red:
                feedback += f"\n\nFAILING CHECKS on the PR head: {', '.join(red)}. Make them pass or say why they cannot."
            brief = ""
            if c.get("issue_url") and "/issues/" in c["issue_url"]:
                path = "/repos/" + c["issue_url"].split("github.com/", 1)[-1]
                brief = triage.brief_for(gh.api(path), gh.api(path + "/comments?per_page=100"))
            else:
                brief = f"Continue the work on {pr['html_url']} ({pr['title']}). The branch is checked out."
            brief = (brief + feedback + context_for(c["fingerprint"], c.get("issue_url") or pr["html_url"])
                     + "\n\nThis is a review round: work on the existing branch, do not start over, and reference the PR in the commit."
                     # kagent#55 was closed after two rounds for "recorded runtime smoke": each round's verify.sh ran
                     # scoped vitest and the smoke went to the forum, which the reviewer does not count (2026-09-15).
                     + " Any run the reviewer asks to see (a smoke run, exit codes, a command's output) goes in /workspace/p/verify.sh "
                     "(the pipeline's proof script, never a file committed to the repo): "
                     "the pipeline executes it and puts its real output on the PR. Output anywhere else is not evidence.")[:8000]
            if DRY_RUN:
                print(f"retry_reviewed: would relaunch {repo}#{n} (dry run)")
                return None
            body = json.dumps({"brief": brief, "repo": repo, "requestedBy": f"review:{pr['html_url']}", "branch": pr["head"]["ref"]}).encode()
            req = urllib.request.Request(LAUNCHER + "/missions", data=body, headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=30) as r:
                name = json.load(r)["name"]
            ledger.say("reconcile", f"Relaunched {name} on {repo} to address the reviewer's objection"
                       + (f" and failing checks ({', '.join(red)})" if red else "") + f" on {pr['html_url']}.",
                       topic="status", ref=pr["html_url"], mentions=["implementer", "reviewer"])
            return name
        except urllib.error.HTTPError as e:
            detail = e.read()[:160].decode(errors="replace")
            print(f"retry_reviewed: {repo}#{n}: HTTP {e.code} {detail}")
            if e.code == 409 and "iterated" in detail:
                close_after_rounds(repo, n, pr, objection, gh, red=red)
        except Exception as e:
            print(f"retry_reviewed: {repo}#{n}: {type(e).__name__}: {str(e)[:120]}")
    return None


def stop_missions_on(branch: str) -> list[str]:
    """Delete the active mission Jobs working `branch`. The PR they would push to is
    closed, and publish opens a new PR when it finds none open for the branch: the
    fleet closed kagent#59 at 17:15 while its third round was still implementing
    on that branch (2026-09-15). Returns the stopped Job names; never raises."""
    stopped = []
    try:
        for j in k8s("GET", f"/apis/batch/v1/namespaces/{NAMESPACE}/jobs?labelSelector=app%3Dmission").get("items", []):
            if not (j.get("status") or {}).get("active"):
                continue
            spec = ((j.get("spec") or {}).get("template") or {}).get("spec") or {}
            envs = [e for c in (spec.get("initContainers") or []) + (spec.get("containers") or []) for e in (c.get("env") or [])]
            if any(e.get("name") == "BRANCH" and e.get("value") == branch for e in envs):
                name = j["metadata"]["name"]
                k8s("DELETE", f"/apis/batch/v1/namespaces/{NAMESPACE}/jobs/{name}?propagationPolicy=Background")
                stopped.append(name)
    except Exception as e:
        print(f"stop_missions_on: {branch}: {type(e).__name__}: {str(e)[:80]}")
    return stopped


def close_after_rounds(repo: str, n: str, pr: dict, objection: dict | None, gh=None, red: list | None = None,
                       because: str = "two implementer rounds did not satisfy the reviewer") -> None:
    """The launcher refused a third review round. Nobody decides for the fleet:
    the PR is closed with the reason, the reason becomes a lesson, and the idea
    it came from is marked failed so the lineage learns. Chris reopens to
    override. (new_localai#131 and brutalist_todo#35 sat behind 'a human
    decides now' for a day on 2026-09-11 with nothing deciding.)"""
    gh = gh or github
    from fleet import memory
    # The reviewer settles a PR it scored >= ROUNDS_MERGE_MIN with no red check
    # (review.py: rounds exhausted + CI green -> veto-window merge). But it skips a
    # head it already judged, so returning here alone left kagent#49 (82) and
    # new_localai#197 (80) open for 20 h with nothing deciding (2026-09-15). Clear
    # its marker once per head; if its next verdict still leaves the PR here, close.
    if int((objection or {}).get("confidence") or 0) >= review.ROUNDS_MERGE_MIN and not red:
        sha = (pr.get("head") or {}).get("sha")
        asked = ledger.kv_get(f"settle:{repo}#{n}") or {}
        judged = ledger.kv_get(f"judged:{repo}#{n}") or {}
        if asked.get("sha") != sha or not asked:
            ledger.kv_set(f"settle:{repo}#{n}", {"sha": sha, "at": time.time()})
            ledger.kv_set(f"judged:{repo}#{n}", {**judged, "sha": "resettle"})  # already_judged() -> False
            print(f"close_after_rounds: {repo}#{n} at confidence {objection['confidence']}, no red check; asked the reviewer to settle it")
            return
        if float(judged.get("at") or 0) <= float(asked.get("at") or 0):
            return  # the reviewer has not re-judged since; next tick
        # re-judged after the rounds and it is still here: it did not merge, so close
    why = str((objection or {}).get("feedback") or (objection or {}).get("summary") or "the reviewer's objection stood")[:400]
    try:
        gh.api(f"/repos/{repo}/issues/{n}/comments", {"body": f"Closing: {because}. Reopen to override.\n\n{why}"})
        gh.api(f"/repos/{repo}/pulls/{n}", {"state": "closed"}, method="PATCH")
        stopped = stop_missions_on((pr.get("head") or {}).get("ref") or "") if (pr.get("head") or {}).get("ref") else []
        memory.remember("lesson", f"{repo}#{n} ({pr.get('title', '')}) was closed ({because}): {why}", repo, ref=pr.get("html_url"), source="reconcile")
        iid, _ = ideas.lookup(pr_url=pr.get("html_url"))
        if iid:
            ideas.set_status(iid, "failed", reason=f"closed ({because}): {why[:120]}", pr_url=pr.get("html_url"))
        ledger.say("reconcile", f"Closed {repo}#{n} ({because}): {why[:200]}"
                   + (f" Stopped the mission still working its branch: {', '.join(stopped)}." if stopped else ""),
                   topic="status", ref=pr.get("html_url"))
    except Exception as e:
        print(f"close_after_rounds: {repo}#{n}: {type(e).__name__}: {str(e)[:120]}")


STALE_HOURS = float(os.environ.get("STALE_HOURS", "48"))


def close_stalled(now: float, gh=None) -> int:
    """The backstop under every other rule: a fleet PR (agent/* branch) nothing has
    touched for STALE_HOURS gets a decision through close_after_rounds (a 70+ PR
    with no objection left is settled by the reviewer first, anything else closes).
    Every gap found so far (a head the reviewer would not re-judge, a round the
    launcher refused while the tick was busy) left PRs open for days; this closes
    the class, not the instance. Hourly. A running veto window is not stalled."""
    gh = gh or github
    if now - float((ledger.kv_get("stale-sweep") or {}).get("at") or 0) < 3600:
        return 0
    ledger.kv_set("stale-sweep", {"at": now})
    acted = 0
    for repo in gh.repos_from_env():
        try:
            for pr in gh.api(f"/repos/{repo}/pulls?state=open&per_page=50"):
                labels = {l["name"] for l in pr.get("labels") or []}
                if (pr.get("draft") or not pr["head"]["ref"].startswith(review.AGENT_BRANCH_PREFIX or "agent/")
                        or labels & {"fleet:announced", "fleet:merged"} or parse_ts(pr["updated_at"]) > now - STALE_HOURS * 3600):
                    continue
                # the reviewer never re-judges an escalated PR, so it cannot settle one: close it outright
                objection = None if "fleet:escalated" in labels else ledger.kv_get(f"objection:{repo}#{pr['number']}")
                close_after_rounds(repo, str(pr["number"]), pr, objection, gh, because=f"no decision in {STALE_HOURS:g} h")
                acted += 1
        except Exception as e:  # one repo must not stop the others
            print(f"close_stalled: {repo}: {type(e).__name__}: {str(e)[:120]}")
    return acted


def settle_exhausted(now: float, gh=None) -> int:
    """A PR whose review rounds are spent needs a decision, not an idle fleet:
    close_after_rounds (the reviewer settles a 70+ PR, anything else closes) for
    every open candidate PR with REVIEW_ROUNDS used and the reviewer's objection
    on its current head. It ran only inside retry_reviewed, behind the idle gate,
    and a busy afternoon (webhooks from pushes reset the idle clock) left kagent#58
    at 62 with both rounds spent (2026-09-15). Launching a round stays behind the
    gate; deciding does not."""
    gh = gh or github
    acted = 0
    try:
        rows = ledger.tested_candidates()
    except Exception as e:
        print(f"settle_exhausted: ledger unavailable ({type(e).__name__})")
        return 0
    for c in rows:
        m = re.search(r"github\.com/([\w.-]+/[\w.-]+)/pull/(\d+)", c.get("pr_url") or "")
        if not m:
            continue
        repo, n = m.group(1), m.group(2)
        try:
            objection = ledger.kv_get(f"objection:{repo}#{n}")
            if not objection or ledger.review_rounds(c["pr_url"]) < review.REVIEW_ROUNDS or gh.kid_gloves(repo):
                continue
            pr = gh.api(f"/repos/{repo}/pulls/{n}")
            if pr.get("state") != "open" or str(objection.get("sha")) != (pr.get("head") or {}).get("sha"):
                continue  # merged or closed, or a pushed round the reviewer has not judged yet
            close_after_rounds(repo, n, pr, objection, gh)
            acted += 1
        except Exception as e:  # one PR must not stop the others
            print(f"settle_exhausted: {repo}#{n}: {type(e).__name__}: {str(e)[:120]}")
    return acted


def rerun_cancelled(repo: str, cancelled: list[dict], gh=None) -> bool:
    """POST a re-run for every workflow run behind a cancelled check run (the run
    id is in the check's details_url). True when at least one was accepted."""
    gh = gh or github
    ok = False
    for run_id in sorted({m.group(1) for x in cancelled
                          for m in [re.search(r"/actions/runs/(\d+)", x.get("details_url") or x.get("html_url") or "")] if m}):
        try:
            gh.api(f"/repos/{repo}/actions/runs/{run_id}/rerun", {}, method="POST")
            ok = True
        except Exception as e:
            print(f"rerun {repo} run {run_id}: {type(e).__name__}: {str(e)[:120]}")
    return ok


def tidy_failed_jobs(now: float, max_age: float = 3600) -> str | None:
    """Failed fleet Jobs that reap_failed_runs has already recorded (or that
    belong to no run: pr-reviewer, digest) keep KubernetesJobFailed firing for
    as long as they exist; two pr-reviewer Jobs from 09-06 fired for 38 hours.
    When one is older than max_age, hand the namespace to the node runner's
    reap-failed-jobs (its allow-list, its forum post)."""
    try:
        jobs = k8s("GET", f"/apis/batch/v1/namespaces/{NAMESPACE}/jobs").get("items", [])
    except Exception as e:
        print(f"tidy_jobs: could not list ({type(e).__name__})")
        return None
    stale = [j["metadata"]["name"] for j in jobs
             if j.get("status", {}).get("failed") and not j.get("status", {}).get("active")
             and now - parse_ts(j["metadata"].get("creationTimestamp")) > max_age]
    if not stale:
        return None
    res = node_action("reap-failed-jobs", {"namespace": NAMESPACE})
    return f"{len(stale)} stale failed job(s): {res.get('result') if res else 'runner unreachable'}"


def launch(now: float, trigger: str = "idle", repo: str | None = None) -> str:
    name = "improve-" + time.strftime("%Y%m%d-%H%M%S", time.gmtime(now))
    cj = k8s("GET", f"/apis/batch/v1/namespaces/{NAMESPACE}/cronjobs/{CRONJOB}")
    job = render_improve_job(cj, name, trigger, repo)
    if not DRY_RUN:
        k8s("POST", f"/apis/batch/v1/namespaces/{NAMESPACE}/jobs", job)
    return name


# --- self-repair ----------------------------------------------------------
# Chris, 2026-09-06: "i want it to be self repairing and self sufficient". The
# six signals above say whether the fleet is idle; none said whether it was
# alive. The k3s-reconciler VM ate five hours of reviewer and reconcile pods
# with "exec format error" and nothing in the loop noticed. Now each tick
# reads its own namespace's failed pods, files a repair mission when a
# failure repeats, and pauses itself when failures pile up.
FLEET_REPO = os.environ.get("FLEET_REPO", "ctkadvisors/new_localai")
REPAIR_AFTER = int(os.environ.get("REPAIR_AFTER", "2"))     # same failure twice in an hour -> a repair mission
PAUSE_AFTER = int(os.environ.get("PAUSE_AFTER", "6"))       # this many own failures in an hour -> pause an hour
PAUSE_MINUTES = int(os.environ.get("PAUSE_MINUTES", "60"))
ORG = os.environ.get("GITHUB_ORG", "ctkadvisors")


STUCK_RUNNER_MINUTES = int(os.environ.get("STUCK_RUNNER_MINUTES", "20"))


def clear_stuck_runners(now: float, pods: list | None = None) -> list[str]:
    """A CI runner pod Pending for STUCK_RUNNER_MINUTES is a Kata sandbox
    start that hung (2026-09-09: three in one evening on elitemini2, each
    holding a runner slot for half an hour and paging Chris every five
    minutes). Deleting it is the cure: ARC replaces it in seconds. Returns
    the names deleted."""
    import datetime
    if pods is None:
        try:
            pods = k8s("GET", f"/api/v1/namespaces/{RUNNER_NAMESPACE}/pods").get("items", [])
        except Exception as e:
            print(f"runners: list skipped ({type(e).__name__})")
            return []
    gone: list[str] = []
    for p in pods:
        if (p.get("status") or {}).get("phase") != "Pending":
            continue
        try:
            born = datetime.datetime.strptime(p["metadata"]["creationTimestamp"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc).timestamp()
        except Exception:
            continue
        if now - born < STUCK_RUNNER_MINUTES * 60:
            continue
        name = p["metadata"]["name"]
        try:
            k8s("DELETE", f"/api/v1/namespaces/{RUNNER_NAMESPACE}/pods/{name}")
            gone.append(name)
        except Exception as e:
            print(f"runners: could not delete {name} ({type(e).__name__})")
    if gone:
        ledger.say("reconcile", f"Deleted CI runner pod(s) Pending for over {STUCK_RUNNER_MINUTES} min (a Kata sandbox start that hung): "
                   f"{', '.join(gone)}. ARC replaces them in seconds; the queued CI jobs continue.", topic="status")
    return gone


def own_failures(now: float, pods: list | None = None) -> list[dict]:
    """Failed pods in the fleet's namespace from the last hour: which job, on which
    node, with what reason, from the container statuses (no logs, no model)."""
    if pods is None:
        try:
            pods = k8s("GET", f"/api/v1/namespaces/{NAMESPACE}/pods?fieldSelector=status.phase%3DFailed").get("items", [])
        except Exception as e:
            print(f"self: could not list pods ({type(e).__name__})")
            return []
    out = []
    for p in pods:
        st = p.get("status", {})
        started = parse_ts(st.get("startTime") or p.get("metadata", {}).get("creationTimestamp"))
        if not started or now - started > 3600:
            continue
        reason = st.get("reason") or ""
        for c in (st.get("initContainerStatuses") or []) + (st.get("containerStatuses") or []):
            t = (c.get("state") or {}).get("terminated") or (c.get("lastState") or {}).get("terminated") or {}
            if t and t.get("exitCode", 0) != 0:
                msg = (t.get("message") or t.get("reason") or "").strip()
                if msg:
                    reason = msg.splitlines()[-1][:160]
                break
        name = p["metadata"]["name"]
        job = re.sub(r"(-\d{8,})?-[a-z0-9]{5}$", "", name)  # pr-reviewer-29811127-g94tf -> pr-reviewer
        out.append({"pod": name, "job": job, "node": p.get("spec", {}).get("nodeName"), "reason": reason or "failed", "at": started})
    return out


def repair(failures: list[dict], now: float, gh=None) -> list[str]:
    """One repair mission per repeating failure: a `mission` + `fleet:repair` issue on
    the fleet's own repo with the evidence as the brief. Board-first relaunches it,
    the launcher caps attempts, the reviewer judges the PR. Filed once a day per
    (job, reason)."""
    gh = gh or github
    groups: dict[tuple[str, str], list[dict]] = {}
    for f in failures:
        groups.setdefault((f["job"], f["reason"]), []).append(f)
    filed = []
    for (job, reason), fs in groups.items():
        if len(fs) < REPAIR_AFTER:
            continue
        fp = ledger.fingerprint("repair", job, reason)
        try:
            seen = ledger.kv_get(f"repair:{fp}")
            if seen and now - float(seen.get("at", 0)) < 86400:
                continue
        except Exception:
            continue  # no ledger, no memory of what was filed: do not spam issues
        nodes = sorted({f["node"] or "?" for f in fs})
        body = (f"<!-- fleet-fingerprint:{fp} -->\n**Self-repair.** `{job}` pods failed {len(fs)} times in the last hour "
                f"on node(s) {', '.join(nodes)}.\n\n**Reason:** `{reason}`\n\n**Pods:** " + ", ".join(f['pod'] for f in fs[:6]) +
                "\n\nFind the cause in the fleet's own manifests or scripts (services/fleet-scripts, "
                "k8s-kustomized/overlays/production/kagent) and fix it at the root. If the cause is outside the repo "
                "(a node, a credential, a host), say so in the PR or halt with what a human must do.")
        try:
            issue = gh.api(f"/repos/{FLEET_REPO}/issues", {"title": f"fleet repair: {job} fails with {reason[:60]}",
                                                            "body": body, "labels": ["mission", "fleet:repair"]})
            ledger.kv_set(f"repair:{fp}", {"at": now, "issue": issue.get("html_url")})
            ledger.say("reconcile", f"I saw {job} die {len(fs)}x in the last hour on {', '.join(nodes)} ({reason}). "
                       f"Filed {issue.get('html_url')} as a repair mission.", topic="repair", ref=issue.get("html_url"), mentions=["implementer"])
            filed.append(issue.get("html_url", fp))
        except Exception as e:
            print(f"repair: could not file for {job}: {type(e).__name__}: {str(e)[:120]}")
    return filed


def paused(now: float) -> str | None:
    try:
        p = ledger.kv_get("pause") or {}
        return p.get("why") if float(p.get("until", 0)) > now else None
    except Exception:
        return None


NODE_RUNNER = os.environ.get("NODE_RUNNER", "http://fleet-node-runner.kagent-system.svc.cluster.local:8080")


def ghost_nodes(now: float, nodes: list | None = None) -> list[str]:
    """Cordoned NotReady nodes that are not the fleet's architecture: the retired
    arm64 VM that rejoins after a power loss. Deleting the node object through
    the runner is safe (it is cordoned, nothing runs there, and a live VM would
    simply re-register, cordoned again by the next tick's pin)."""
    if nodes is None:
        try:
            nodes = k8s("GET", "/api/v1/nodes").get("items", [])
        except Exception as e:
            print(f"nodes: could not list ({type(e).__name__})")
            return []
    out = []
    for n in nodes:
        ready = next((c.get("status") for c in n.get("status", {}).get("conditions", []) if c.get("type") == "Ready"), "Unknown")
        arch = n.get("status", {}).get("nodeInfo", {}).get("architecture")
        if n.get("spec", {}).get("unschedulable") and ready != "True" and arch != "amd64":
            out.append(n["metadata"]["name"])
    return out


def node_action(action: str, args: dict, by: str = "reconcile") -> dict | None:
    """One allow-listed action through fleet-node-runner; None when it is unreachable."""
    try:
        req = urllib.request.Request(NODE_RUNNER + "/run", data=json.dumps({"action": action, "args": args, "by": by}).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        # The runner is on the other node and this pod is seconds old: the first
        # call is refused until the policy ipset carries our IP (fleet/net.py).
        # 15:45Z 2026-09-08: every other tick read "node runner unreachable".
        with net.urlopen_retry(req, timeout=150, tries=5) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode())
        except Exception:
            return {"ok": False, "result": f"HTTP {e.code}"}
    except Exception as e:
        print(f"node-runner: {action}: {type(e).__name__}: {str(e)[:80]}")
        return None


EGRESS_HOSTS = [h for h in os.environ.get("EGRESS_HOSTS", "elitemini2").split(",") if h]


def check_egress(now: float, hosts=None) -> dict:
    """Probe each node's path to GitHub through the runner; when it is gone,
    flush the gateway neighbour (the known Deco age-out) and probe again. The
    result is the `egress` kv the launcher's health relays. Still down after
    the fix: tell Chris once an hour, it is the router's, not ours."""
    state = {}
    for host in hosts or EGRESS_HOSTS:
        r = node_action("probe-egress", {"host": host})
        ok, healed = bool(r and r.get("ok")), False
        if r is not None and not ok:
            # 2026-09-14: 20 "flushed and it can again" a day were DNS blips
            # (the Deco's resolver drops cold queries from elitemini2); the
            # second probe passed because the name was cached by then, not
            # because of the flush. A blip is not news; probe again first.
            r = node_action("probe-egress", {"host": host})
            ok = bool(r and r.get("ok"))
        if r is not None and not ok:
            node_action("neigh-flush", {"host": host})
            r2 = node_action("probe-egress", {"host": host})
            ok = healed = bool(r2 and r2.get("ok"))
            r = r2 or r
        # r is None = the runner did not answer: unknown, not down (the first tick
        # after a rollout said "DOWN on elitemini2: node runner unreachable").
        state[host] = {"ok": None if r is None else ok, "healed": healed, "at": now,
                       "detail": str((r or {}).get("result", "node runner unreachable"))[:160]}
        # A pass after the flush is not the flush's doing: the second probe resolves
        # from the cache the first one warmed (2026-09-14: "flushed ... and it can
        # again" 22 times a day while elitemini2 kept dropping DNS replies). `healed`
        # stays in the kv; nothing is posted for a blip.
        if r is not None and not ok:
            last = ledger.kv_get(f"egress-said:{host}") or {}
            if now - float(last.get("at", 0)) > 3600:
                ledger.kv_set(f"egress-said:{host}", {"at": now})
                pid = ledger.say("reconcile", f"{host} cannot reach GitHub and a neighbour flush did not fix it: {state[host]['detail']}. "
                                 "CI and missions on it will time out until the router is sorted.", topic="question", mentions=["chris"])
                telegram.send(f"\u26a0\ufe0f {host} cannot reach GitHub ({state[host]['detail'][:80]}); flush did not help. "
                              + (telegram.post_link(pid) if pid else ""))
    try:
        ledger.kv_set("egress", state)
    except Exception:
        pass
    return state


def tidy_nodes(now: float) -> list[str]:
    """Each tick: ghost nodes go, once a day per name at most."""
    done = []
    for name in ghost_nodes(now):
        key = f"node-deleted:{name}"
        try:
            if ledger.kv_get(key) and now - float(ledger.kv_get(key).get("at", 0)) < 86400:
                continue
        except Exception:
            continue
        res = node_action("delete-node", {"name": name})
        if res is not None:
            ledger.kv_set(key, {"at": now, "ok": res.get("ok")})
            if res.get("ok"):
                done.append(name)
    return done


def canary(now: float) -> tuple[bool, str]:
    """Is the fleet's model still a model? improve-20260908-000000's implementer
    produced token salad for its whole budget while every signal read green
    and the halt paged Chris with the salad. One eight-token completion per
    tick; an answer without OK means: launch nothing, say so once an hour."""
    base = SPARK_METRICS_URL.rsplit("/metrics", 1)[0]
    body = json.dumps({"model": SPARK_MODEL, "max_tokens": 8, "chat_template_kwargs": {"enable_thinking": False},
                       "messages": [{"role": "user", "content": "Reply with the single word OK."}]}).encode()
    try:
        req = urllib.request.Request(f"{base}/v1/chat/completions", data=body, headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=60) as r:
            text = str(json.load(r)["choices"][0]["message"].get("content") or "")
    except Exception as e:
        return True, f"canary unavailable ({type(e).__name__}); not judging"  # the spark signal handles reachability
    ok = "ok" in text.lower()
    if not ok:
        try:
            last = ledger.kv_get("canary")
            if not last or now - float(last.get("at", 0)) > 3600:
                ledger.kv_set("canary", {"at": now, "reply": text[:200]})
                pid = ledger.say("reconcile", f"{SPARK_MODEL} answered the canary ('Reply with the single word OK.') with {text[:120]!r}. "
                                 "The model is degenerate; I launch nothing until it answers again.", topic="status", mentions=["chris", "concierge"])
                telegram.send(f"⚠️ {SPARK_MODEL} is answering gibberish ({text[:80]!r}); the fleet launches nothing until it recovers.\n"
                              + (telegram.post_link(pid) if pid else telegram.CONSOLE_URL))
        except Exception as e:
            print(f"canary: could not record ({type(e).__name__})")
    return ok, f"canary reply {text[:40]!r}"


LOG_BAD = re.compile(r"\b(error|Error|ERROR|Traceback|rejected|refused|ECONN\w*|ETIMEDOUT|HTTP [45]\d\d|exceeds|OOMKilled|CrashLoop\w*)\b")
LOG_SKIP = re.compile(r"CDPService|/health|readyz|livez")


def k8s_text(path: str) -> str:
    """A raw GET for what the API serves as text (pod logs)."""
    host = os.environ.get("KUBERNETES_SERVICE_HOST", "kubernetes.default.svc")
    port = os.environ.get("KUBERNETES_SERVICE_PORT", "443")
    token = open(f"{SA}/token").read().strip()
    ctx = ssl.create_default_context(cafile=f"{SA}/ca.crt")
    req = urllib.request.Request(f"https://{host}:{port}{path}", headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=20, context=ctx) as r:
        return r.read().decode(errors="replace")


def observe_pods(now: float, pods: list | None = None, logs=None) -> list[str]:
    """Each tick reads the last hour of its own namespace's long-running pods for
    error lines and stores each new kind of trouble as a global fact the ideator
    and every stage's recall can see. 2026-09-11..15: the Telegram adapter logged
    "inbound message rejected ... HTTP 400" for four days and nothing in the fleet
    read it; a Claude session did. The fleet reads its own logs now. One fact per
    deployment and line shape per day; stage pods keep their own logs."""
    if pods is None:
        try:
            pods = k8s("GET", f"/api/v1/namespaces/{NAMESPACE}/pods?fieldSelector=status.phase%3DRunning").get("items", [])
        except Exception as e:
            print(f"self: could not list running pods ({type(e).__name__})")
            return []
    logs = logs or (lambda name, c: k8s_text(f"/api/v1/namespaces/{NAMESPACE}/pods/{name}/log?container={c}&sinceSeconds=3600&tailLines=300"))
    noted: list[str] = []
    for p in pods:
        meta = p.get("metadata", {})
        name, labels = meta.get("name", ""), meta.get("labels") or {}
        if labels.get("job-name") or labels.get("app") in ("mission", "improve"):
            continue
        deploy = re.sub(r"(-[a-z0-9]{5,10}){1,2}$", "", name)
        for c in p.get("spec", {}).get("containers", []):
            try:
                text = logs(name, c["name"])
            except Exception:
                continue
            bad = [ln.strip() for ln in text.splitlines() if LOG_BAD.search(ln) and not LOG_SKIP.search(ln)]
            if not bad:
                continue
            shape = re.sub(r"\d+", "#", bad[0])[:120]
            key = f"podlog:{deploy}:{hashlib.sha1(shape.encode()).hexdigest()[:10]}"
            last = ledger.kv_get(key)
            if last and now - float(last.get("at", 0)) < 86400:
                continue
            ledger.kv_set(key, {"at": now, "line": bad[0][:200]})
            fact = f"{deploy} ({c['name']}) logged {len(bad)} error line(s) in the last hour, e.g.: {bad[0][:200]}"
            from fleet import memory
            memory.remember("fact", fact, source="observer")
            noted.append(fact)
    return noted


def self_check(now: float) -> str | None:
    """Record own health, file repairs, and pause the loop when failures pile up.
    Returns the pause reason when the tick should stop here."""
    try:
        gone = tidy_nodes(now)
        if gone:
            print(f"self: removed ghost node(s): {gone}")
    except Exception as e:
        print(f"self: node tidy skipped ({type(e).__name__})")
    try:
        eg = check_egress(now)
        bad = [h for h, v in eg.items() if v["ok"] is False]
        unknown = [h for h, v in eg.items() if v["ok"] is None]
        print(f"self: egress {'ok' if not bad and not unknown else ('DOWN on ' + ', '.join(bad) if bad else 'unknown on ' + ', '.join(unknown))}: " + "; ".join(f"{h}: {v['detail'][:60]}" for h, v in eg.items()))
    except Exception as e:
        print(f"self: egress check skipped ({type(e).__name__})")
    failures = own_failures(now)
    try:
        seen = observe_pods(now)
        if seen:
            print(f"self: noted {len(seen)} new log trouble(s): " + "; ".join(x[:90] for x in seen))
    except Exception as e:
        print(f"self: pod log scan skipped ({type(e).__name__})")
    cleared = clear_stuck_runners(now)
    if cleared:
        print(f"runners: deleted stuck {cleared}")
    try:
        ledger.kv_set("self_health", {"at": now, "failed_last_hour": len(failures), "failures": failures[:20]})
    except Exception:
        pass
    if failures:
        print(f"self: {len(failures)} failed pod(s) in the last hour: " + ", ".join(f"{f['job']}@{f['node']}: {f['reason'][:40]}" for f in failures[:5]))
        filed = repair(failures, now)
        if filed:
            print(f"self: repair missions filed: {filed}")
    why = paused(now)
    if why:
        return why
    if len(failures) >= PAUSE_AFTER:
        why = f"{len(failures)} of my own pods failed in the last hour; pausing launches for {PAUSE_MINUTES} min"
        try:
            ledger.kv_set("pause", {"until": now + PAUSE_MINUTES * 60, "why": why, "at": now})
            pid = ledger.say("reconcile", why + ". Resume from the console once the cause is handled.", topic="status", mentions=["chris", "concierge"])
            telegram.send(f"⏸ fleet paused itself: {why}.\n{telegram.post_link(pid) if pid else telegram.CONSOLE_URL}")
        except Exception as e:
            print(f"self: could not record the pause ({type(e).__name__})")
        return why
    return None


def main() -> int:
    if "--dream" in sys.argv:                      # the dream Job (launch_dream)
        print(f"dream: {dream(time.time(), force=True)}")
        return 0
    now = time.time()
    holder = f"reconcile-{os.environ.get('HOSTNAME', 'local')}"
    if not ledger.try_lease(holder, ttl_seconds=600):
        print("reconcile: another scheduler holds the lease; done")
        return 0
    try:
        merged = review.merge_due()
        if merged:
            print(f"reconcile: merged after their veto window: {merged}")
        try:
            observed = observe_outcomes()
            if observed:
                print(f"reconcile: outcomes recorded: {observed}")
        except Exception as e:
            print(f"reconcile: outcomes skipped ({type(e).__name__}: {str(e)[:80]})")
        why_paused = self_check(now)
        try:
            reaped = reap_failed_runs(now)
            if reaped:
                print(f"reconcile: reaped dead runs: {reaped}")
            tidied = tidy_failed_jobs(now)
            if tidied:
                print(f"reconcile: {tidied}")
            relayed = relay_questions(now)
            if relayed:
                print(f"reconcile: relayed {relayed} question(s) to Telegram")
            asked = ask_concierge(now)
            n = relay_answers()
            if n:
                print(f"reconcile: relayed {n} concierge answer(s) to the forum")
            stalled = close_stalled(now)
            if stalled:
                print(f"reconcile: decided {stalled} stalled PR(s)")
            spent = settle_exhausted(now)  # every tick: deciding a spent PR costs nothing, so it does not wait for idle
            if spent:
                print(f"reconcile: settled {spent} PR(s) with their review rounds spent")
            if asked:
                print(f"reconcile: asked the concierge to answer {asked} question(s)")
            dreamt = launch_dream(now)
            if dreamt:
                print(f"reconcile: launched the dream {dreamt}")
            bench_job = nightly_bench(now)
            if bench_job:
                print(f"reconcile: nightly bench {bench_job}")
            bench_trend(now)
            for line in bench_outcome(now):
                print(f"reconcile: bench outcome {line}")
            for repo in daily_ideation(now):
                print(f"reconcile: daily ideation posted for {repo}")
            ships = watch_ships(now)
            if ships:
                print(f"reconcile: re-ran failed ship(s): {ships}")
        except Exception as e:
            print(f"reconcile: reap/relay skipped ({type(e).__name__}: {str(e)[:80]})")
        if why_paused:
            print(f"reconcile: paused: {why_paused}")
            return 0
        sane, why_canary = canary(now)
        print(f"reconcile: {why_canary}")  # every tick, so the log proves the canary ran
        if not sane:
            print(f"reconcile: model degenerate: {why_canary}; launching nothing")
            return 0
        eligible, report = observe()
        if not (report.get("spark") or {}).get("ok", True):
            bump("blocked", "spark")
        streak = idle_streak(eligible, now)
        ok_budget, why_budget = budget_ok(now)
        summary = {k: ("ok" if v["ok"] else "busy") + " (" + v["detail"] + ")" for k, v in report.items()}
        ledger.kv_set("last_observation", {"at": now, "eligible": eligible, "idle_minutes": round(streak, 1),
                                           "budget": why_budget, "signals": summary})
        # the knobs this tick actually runs with; the console showed its own stale env (3/120) for days
        ledger.kv_set("knobs", {k: os.environ.get(k) for k in ("BUDGET_PER_DAY", "MIN_GAP_MINUTES", "IDLE_MINUTES", "QUIET_MINUTES",
                                                               "VETO_MINUTES_T1", "VETO_MINUTES_T2") if os.environ.get(k)})
        print(f"reconcile: eligible={eligible} idle={streak:.0f}m budget={why_budget} signals={json.dumps(summary)}")
        # The idle streak is stamped by the tick that became eligible and read
        # by a later tick, so after IDLE_MINUTES/5 ticks it reads 9.99 minutes,
        # printed as "10m", and the launch waited one more tick every time
        # (04:00Z 2026-09-08: eligible=True idle=10m, nothing launched).
        if not (eligible and streak + 0.5 >= IDLE_MINUTES and gap_ok(now)):
            return 0
        name = retry_board(now)  # the board does not spend the improve budget, only the gap
        if name:
            ledger.kv_set("last_run", {"at": now, "name": name})
            ledger.kv_set("idle_since", {"at": 0})
            ledger.record_decision("launch-mission", 1, "policy", f"board first: idle {streak:.0f} min; relaunched a halted mission", run_id=name)
            print(f"reconcile: relaunched {name} from the board")
            return 0
        name = retry_reviewed(now)  # then PRs the reviewer or CI sent back
        if name:
            ledger.kv_set("last_run", {"at": now, "name": name})
            ledger.kv_set("idle_since", {"at": 0})
            ledger.record_decision("launch-mission", 1, "policy", f"review round: idle {streak:.0f} min; iterating on reviewer feedback", run_id=name)
            print(f"reconcile: relaunched {name} for a review round")
            return 0
        if not ok_budget:
            return 0
        name = weekly_bench_target(now)  # one improve run a week is the bench's; it spends the day's budget like any run
        if name:
            day = time.strftime("%Y-%m-%d", time.gmtime(now))
            ledger.kv_set(f"budget:{day}", {"runs": int((ledger.kv_get(f"budget:{day}") or {}).get("runs", 0)) + 1})
            ledger.kv_set("last_run", {"at": now, "name": name})
            ledger.kv_set("idle_since", {"at": 0})
            ledger.record_decision("launch-mission", 1, "policy", f"idle {streak:.0f} min; {why_budget}; weekly bench target", run_id=name)
            print(f"reconcile: launched {name} to raise the bench")
            return 0
        repo, why_repo = choose_repo()
        why_empty = empty_streak(repo)
        if why_empty:
            name = launch_idea(repo, now)   # the archive first: an untried idea is a run, not a question
            if name:
                day = time.strftime("%Y-%m-%d", time.gmtime(now))
                ledger.kv_set(f"budget:{day}", {"runs": int((ledger.kv_get(f"budget:{day}") or {}).get("runs", 0)) + 1})
                ledger.kv_set("last_run", {"at": now, "name": name})
                ledger.kv_set("idle_since", {"at": 0})
                ledger.record_decision("launch-mission", 1, "policy", f"idle {streak:.0f} min; {why_budget}; {why_empty}; an untried idea from the archive", run_id=name)
                ledger.say("reconcile", f"Idle {streak:.0f} min, launched {name} on {repo} from the idea archive ({why_empty}).", topic="status", ref=name)
                print(f"reconcile: launched {name} from the idea archive")
                return 0
            try:
                posted = ideate(repo, now)
            except Exception as e:
                print(f"reconcile: ideate failed ({type(e).__name__}: {str(e)[:80]})"); posted = 0
            print(f"reconcile: not launching: {why_empty}; " + ("launched the ideation Job, its ideas run when they land" if posted else "no untried idea and no ideation this tick"))
            return 0
        name = launch(now, repo=repo)
        day = time.strftime("%Y-%m-%d", time.gmtime(now))
        used = (ledger.kv_get(f"budget:{day}") or {}).get("runs", 0)
        ledger.kv_set(f"budget:{day}", {"runs": int(used) + 1})
        ledger.kv_set("last_run", {"at": now, "name": name})
        ledger.kv_set("idle_since", {"at": 0})
        ledger.start_run(name, "improve", repo, "idle")
        ledger.record_decision("launch-improve", 1, "policy",
                               f"idle {streak:.0f} min; {why_budget}; signals all green; {why_repo}", run_id=name)
        ledger.say("reconcile", f"Idle {streak:.0f} min, launched {name} on {repo}: {why_repo}.", topic="status", ref=name)
        print(f"reconcile: launched {name}{' (dry run)' if DRY_RUN else ''}")
        return 0
    finally:
        ledger.release_lease(holder)


if __name__ == "__main__":
    sys.exit(main())
