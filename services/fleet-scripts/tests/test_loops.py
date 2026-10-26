"""The fleet closes its own loops (2026-09-15): every fleet PR reaches merged or
closed without a person, a trusted human's PR is judged like the fleet's, a
one-word answer is still an answer, and a PR body is something a person reads."""

import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from fleet import ledger  # noqa: E402
import publish  # noqa: E402
import reconcile  # noqa: E402
import review  # noqa: E402
from test_reconcile import FakeLedger  # noqa: E402


def _closer(monkeypatch):
    fl = FakeLedger(); monkeypatch.setattr(reconcile, "ledger", fl)
    from fleet import ideas, memory
    monkeypatch.setattr(memory, "remember", lambda *a, **k: "k")
    monkeypatch.setattr(ideas, "lookup", lambda fp=None, pr_url=None: (None, None))
    return fl, []


def test_a_settling_pr_is_rejudged_once_then_closed(monkeypatch):
    fl, calls = _closer(monkeypatch)
    class GH:
        def api(self, path, data=None, method=None): calls.append((method or "POST", path)); return {}
    pr, obj = {"title": "t", "html_url": "u", "head": {"sha": "s1"}}, {"feedback": "wants smoke", "confidence": 82}
    fl.kv["judged:o/k#8"] = {"sha": "s1", "at": 100.0}
    reconcile.close_after_rounds("o/k", "8", pr, obj, GH())
    assert calls == [] and fl.kv["judged:o/k#8"]["sha"] == "resettle"      # the reviewer judges this head again
    reconcile.close_after_rounds("o/k", "8", pr, obj, GH())
    assert calls == []                                                      # not re-judged yet: wait
    fl.kv["judged:o/k#8"] = {"sha": "s1", "at": time.time() + 1}            # re-judged and still open: it did not merge
    reconcile.close_after_rounds("o/k", "8", pr, obj, GH())
    assert ("PATCH", "/repos/o/k/pulls/8") in calls


def test_close_stalled_decides_only_old_quiet_fleet_prs(monkeypatch):
    fl, calls = _closer(monkeypatch)
    old, new = "2026-09-10T00:00:00Z", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    pr = lambda n, ref, at, labels=(): {"number": n, "head": {"ref": ref, "sha": "x"}, "updated_at": at,
                                         "labels": [{"name": l} for l in labels], "title": str(n), "html_url": f"u{n}"}
    prs = [pr(1, "agent/a", old), pr(2, "agent/b", new), pr(3, "agent/c", old, ["fleet:announced"]), pr(4, "fix/d", old)]
    class GH:
        def repos_from_env(self): return ["o/k"]
        def api(self, path, data=None, method=None):
            calls.append((method or ("POST" if data is not None else "GET"), path))
            return prs if "pulls?state=open" in path else {}
    now = time.time()
    assert reconcile.close_stalled(now, GH()) == 1
    closed = [c[1] for c in calls if c[0] == "PATCH"]
    assert closed == ["/repos/o/k/pulls/1"]                                # fresh, in a veto window, or human: left alone
    assert reconcile.close_stalled(now + 60, GH()) == 0                    # hourly


def test_settle_exhausted_decides_without_waiting_for_idle(monkeypatch):
    fl, calls = _closer(monkeypatch)
    urls = {n: f"https://github.com/o/k/pull/{n}" for n in (58, 60, 61)}
    fl.tested_candidates = lambda: [{"pr_url": u} for u in urls.values()]
    fl.review_rounds = lambda url: {urls[58]: 2, urls[60]: 1, urls[61]: 2}[url]
    fl.kv["objection:o/k#58"] = {"sha": "h58", "confidence": 62, "feedback": "runtime smoke"}
    fl.kv["objection:o/k#60"] = {"sha": "h60", "confidence": 40, "feedback": "x"}     # a round left
    fl.kv["objection:o/k#61"] = {"sha": "old", "confidence": 40, "feedback": "x"}     # new push not judged yet
    class GH:
        def kid_gloves(self, repo): return False
        def api(self, path, data=None, method=None):
            calls.append((method or ("POST" if data is not None else "GET"), path))
            n = path.rsplit("/", 1)[-1]
            return {"state": "open", "head": {"sha": "h" + n}, "title": n, "html_url": "u" + n} if data is None else {}
    assert reconcile.settle_exhausted(time.time(), GH()) == 1
    assert [c[1] for c in calls if c[0] == "PATCH"] == ["/repos/o/k/pulls/58"]


def test_only_a_persons_github_activity_resets_the_idle_clock():
    import hooks
    person, bot = {"sender": {"login": "chrisknu"}}, {"sender": {"login": "example-fleet[bot]"}}
    assert hooks.counts_as_activity("push", person) and hooks.counts_as_activity("pull_request_review", person)
    assert not hooks.counts_as_activity("check_run", person) and not hooks.counts_as_activity("workflow_job", person)
    assert not hooks.counts_as_activity("push", bot)                     # the fleet's own push is its echo


def test_an_empty_archive_ideates_again_up_to_the_daily_cap(monkeypatch):
    fl, _ = _closer(monkeypatch)
    launched = []
    monkeypatch.setattr(reconcile, "thinker_running", lambda: None)
    monkeypatch.setattr(reconcile, "launch_from_template", lambda name, cmd, env, deadline=0: launched.append((name, env)) or name)
    rows = []
    monkeypatch.setattr(reconcile.ideas, "rows", lambda repo, states, n: rows)
    assert reconcile.launch_ideation("o/kagent", 1e9) == "ideate-kagent-20010909"            # the day's first
    assert "IDEATE_FORCE" not in launched[-1][1]
    rows.append({"id": "i1", "run_id": None})
    assert reconcile.launch_ideation("o/kagent", 1e9) is None                                   # an untried idea: no need
    rows[0]["run_id"] = "mission-1"
    assert reconcile.launch_ideation("o/kagent", 1e9) == "ideate-kagent-20010909-2"             # archive spent: again
    assert launched[-1][1].get("IDEATE_FORCE") == "1"                                           # past ideate.py's own daily guard
    assert reconcile.launch_ideation("o/kagent", 1e9) == "ideate-kagent-20010909-3"
    assert reconcile.launch_ideation("o/kagent", 1e9) is None                                   # IDEATE_PER_DAY = 3


def test_reviewer_can_judge_the_fleets_prs_before_humans(monkeypatch):
    judged = []
    prs = [{"number": 1, "head": {"ref": "fix/mine", "sha": "s"}, "user": {"login": "chrisknu"}, "labels": []},
           {"number": 2, "head": {"ref": "agent/mission-1", "sha": "s"}, "user": {"login": "example-fleet[bot]"}, "labels": []}]
    monkeypatch.setattr(review, "github", type("G", (), {"api": staticmethod(lambda path, *a, **k: prs)})())
    monkeypatch.setattr(review, "review_pr", lambda repo, api, pr, n: judged.append(n))
    monkeypatch.setattr(review, "TRUSTED", {"chrisknu", "example-fleet[bot]"})
    monkeypatch.setattr(review, "AGENT_BRANCH_PREFIX", "agent/")
    review.review_repo("o/r", True); assert judged == [2]
    review.review_repo("o/r", False); assert judged == [2, 1]
    review.review_repo("o/r"); assert judged == [2, 1, 1, 2]                    # default: both, in list order


def test_telegram_carries_only_what_needs_a_human(monkeypatch, tmp_path):
    from fleet import telegram
    sent = []
    (tmp_path / "token").write_text("t")
    monkeypatch.setattr(telegram, "TOKEN_FILE", str(tmp_path / "token"))
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "1")
    monkeypatch.delenv("TELEGRAM_INFO", raising=False)
    monkeypatch.setattr(telegram.urllib.request, "urlopen", lambda req, timeout=20: sent.append(req) or type("R", (), {"read": lambda self: b"{}"})())
    telegram.send("\U0001F528 kagent: PR opened https://x")                # routine: forum only
    telegram.send("✅ Merged o/r#1")
    assert sent == []
    telegram.send("❓ implement asks: which threshold?")
    telegram.send("⚠️ o/r#2 needs your call")
    assert len(sent) == 2
    monkeypatch.setenv("TELEGRAM_INFO", "1")
    telegram.send("\U0001F528 kagent: PR opened https://x")
    assert len(sent) == 3                                                   # the old behaviour, one env var away


def test_an_idea_for_work_already_in_flight_waits():
    now = time.time()
    closed_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - 3600))
    class GH:
        def api(self, path, data=None, method=None):
            if "state=open" in path:
                return [{"number": 59, "title": "feat(workbench-ui): add coverage-threshold regression gate", "head": {"ref": "agent/m-59"}},
                        {"number": 60, "title": "fix(agent-pod): report current context in get_my_context.tokenUtilization.used", "head": {"ref": "agent/m-60"}},
                        {"number": 61, "title": "docs: touch README.md", "head": {"ref": "fix/human"}}]          # a human's PR: not the fleet's work
            if "state=closed" in path:
                return [{"number": 55, "title": "fix(workbench-api): validate WORKBENCH_PORT before server boot", "head": {"ref": "agent/m-55"},
                         "merged_at": None, "closed_at": closed_at}]
            if path.endswith("/pulls/59/files?per_page=100"):
                return [{"filename": "packages/workbench-ui/vitest.config.ts"}]
            return []
    busy = reconcile.inflight_marks("o/k", now, GH())
    assert reconcile.overlaps("Remove the thresholds block in packages/workbench-ui/vitest.config.ts", busy)   # #59's file
    assert reconcile.overlaps("tokenUtilization.used still reports the cumulative sum", busy)                  # #60's title
    assert reconcile.overlaps("Validate WORKBENCH_PORT before boot", busy)                                     # closed twice this week
    assert not reconcile.overlaps("Add packages/workbench-api/src/sse.test.ts covering SseBroker fan-out", busy)
    assert not reconcile.overlaps("Rewrite README.md intro", busy)


def test_the_judge_plans_and_precheck_holds_its_bar(monkeypatch, tmp_path):
    import subprocess
    import plan
    import precheck
    repo = tmp_path / "repo"; repo.mkdir(); p = tmp_path / "p"; p.mkdir()
    git = lambda *a: subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True)
    git("init", "-q"); git("config", "user.email", "t@t"); git("config", "user.name", "t")
    (repo / "a.py").write_text("x = 1\n"); git("add", "."); git("commit", "-qm", "init")
    start = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    (repo / "a.py").write_text("x = 2\n"); git("commit", "-qam", "change")
    for m in (plan, precheck):
        monkeypatch.setattr(m, "P", str(p)); monkeypatch.setattr(m, "REPO_DIR", str(repo))
    monkeypatch.setenv("MISSION_BRIEF", "Continue PR 7.\n\nREVIEW FEEDBACK: 1. add a test. 2. fix the comment.")
    monkeypatch.setenv("STAGE_START_SHA", start)
    monkeypatch.setattr(review, "JUDGE_URL", "http://judge")
    # plan: the judge's steps become a numbered checklist
    monkeypatch.setattr(review, "ask_judge", lambda prompt, **k: '{"steps": [{"file": "a.py", "change": "x = 2", "proof": "pytest"}, {"file": "test_a.py", "change": "add a test", "proof": "pytest -q"}]}')
    assert plan.main() == 0 and (p / "plan.md").read_text().startswith("1. a.py: x = 2\n   proof: pytest\n2. test_a.py")
    # precheck: the reviewer's own judge, same bar
    monkeypatch.setattr(review, "judge", lambda pr, diff, **k: {"confidence": 90, "summary": "ok", "feedback": ""})
    assert precheck.main() == 0
    monkeypatch.setattr(review, "judge", lambda pr, diff, **k: {"confidence": 60, "summary": "half done", "feedback": "2. the comment still contradicts the code"})
    assert precheck.main() == 1 and '"confidence": 60' in (p / "precheck.json").read_text()
    def down(*a, **k): raise ConnectionError("spark down")
    monkeypatch.setattr(review, "judge", down)
    assert precheck.main() == 0                                  # fail open: the PR reviewer still judges it
    monkeypatch.setattr(review, "JUDGE_URL", "")
    assert precheck.main() == 0 and plan.main() == 0             # no judge configured: the stage runs as before


def test_no_review_round_on_an_objection_older_than_the_head(monkeypatch):
    import json
    kv = {"objection:o/r#59": {"sha": "old", "at": time.time() - 7200, "summary": "not a gate", "feedback": "add a red probe"}}
    monkeypatch.setattr(ledger, "kv_get", kv.get)
    monkeypatch.setattr(ledger, "tested_candidates", lambda: [{"fingerprint": "fp", "repo": "o/r", "issue_url": None,
                                                               "pr_url": "https://github.com/o/r/pull/59", "started_at": "2026-09-06T07:30:00Z"}])   # outside MIN_GAP
    monkeypatch.setattr(ledger, "open_questions", lambda ref: [])
    monkeypatch.setattr(ledger, "posts", lambda **k: [])
    monkeypatch.setattr(ledger, "last_run", lambda fp: None)
    monkeypatch.setattr(ledger, "say", lambda *a, **k: None)
    checks = {"conclusion": "success"}
    class GH:
        def kid_gloves(self, repo): return False
        def api(self, path, data=None, **k):
            if path.endswith("/pulls/59"):
                return {"state": "open", "merged": False, "title": "gate", "html_url": "https://github.com/o/r/pull/59", "head": {"sha": "new", "ref": "agent/m-59"}}
            if "/check-runs" in path:
                return {"check_runs": [{"name": "test", "status": "completed", **checks}]}
            return []
    launched = []
    class Resp:
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def read(self): return b'{"name": "mission-round"}'
    monkeypatch.setattr(reconcile.urllib.request, "urlopen", lambda req, timeout=30: launched.append(json.loads(req.data)) or Resp())
    assert reconcile.retry_reviewed(time.time(), GH()) is None and launched == []      # the 16:47 push is not judged yet: wait
    checks["conclusion"] = "failure"
    assert reconcile.retry_reviewed(time.time(), GH()) == "mission-round"              # a red check is fresh evidence
    kv["objection:o/r#59"]["sha"] = "new"; checks["conclusion"] = "success"
    assert reconcile.retry_reviewed(time.time(), GH()) == "mission-round"              # judged on this head: a round as before


def test_closing_a_pr_stops_the_mission_still_working_its_branch(monkeypatch):
    fl, calls = _closer(monkeypatch)
    job = lambda name, branch, active: {"metadata": {"name": name}, "status": {"active": 1} if active else {"succeeded": 1},
                                        "spec": {"template": {"spec": {"initContainers": [{"name": "clone", "env": [{"name": "BRANCH", "value": branch}]}]}}}}
    jobs = {"items": [job("mission-a", "agent/m-59", True), job("mission-b", "agent/m-60", True), job("mission-c", "agent/m-59", False)]}
    deleted = []
    def k8s(method, path, body=None):
        if method == "DELETE":
            deleted.append(path.rsplit("/", 1)[-1].split("?")[0]); return {}
        return jobs
    monkeypatch.setattr(reconcile, "k8s", k8s)
    class GH:
        def api(self, path, data=None, method=None): calls.append((method or "POST", path)); return {}
    pr = {"title": "gate", "html_url": "u59", "head": {"sha": "s", "ref": "agent/m-59"}}
    reconcile.close_after_rounds("o/k", "59", pr, {"feedback": "no red run", "confidence": 40}, GH())
    assert ("PATCH", "/repos/o/k/pulls/59") in calls
    assert deleted == ["mission-a"]                     # the active round on the closed branch; not #60's, not a finished one


def test_reviewer_judges_a_trusted_humans_branch_but_not_a_strangers(monkeypatch):
    judged = []
    prs = [{"number": 5, "head": {"ref": "fix/x", "sha": "s"}, "user": {"login": "chrisknu"}, "labels": []},
           {"number": 6, "head": {"ref": "fix/y", "sha": "s"}, "user": {"login": "someone"}, "labels": []}]
    monkeypatch.setattr(review, "github", type("G", (), {"api": staticmethod(lambda path, *a, **k: prs)})())
    monkeypatch.setattr(review, "review_pr", lambda repo, api, pr, n: judged.append(n))
    monkeypatch.setattr(review, "TRUSTED", {"chrisknu"})
    monkeypatch.setattr(review, "AGENT_BRANCH_PREFIX", "agent/")
    review.review_repo("o/r")
    assert judged == [5]


def test_a_one_word_answer_is_relayed(monkeypatch):
    kv, posted = {"asked:7": {"at": 1.0, "task": "t-a", "tries": 1}}, []
    monkeypatch.setattr(ledger, "kv_get", kv.get)
    monkeypatch.setattr(ledger, "kv_set", kv.__setitem__)
    monkeypatch.setattr(ledger, "kv_like", lambda pat: [(k, v) for k, v in kv.items() if k.startswith("asked:")])
    monkeypatch.setattr(ledger, "posts", lambda **k: [])
    monkeypatch.setattr(ledger, "post", lambda author, body, **k: posted.append(body) or 1)
    monkeypatch.setattr(reconcile, "k8s", lambda m, p, body=None: {"items": [
        {"metadata": {"name": "t-a"}, "status": {"phase": "Completed", "result": {"content": "Yes"}}}]})
    assert reconcile.relay_answers() == 1 and posted == ["Yes"]


def test_a_forum_post_by_chris_is_a_lesson_and_a_relayed_instruction_a_rule(monkeypatch):
    from contextlib import contextmanager
    from fleet import memory
    kept = []
    class Cur:
        def execute(self, sql, args=()): pass
        def fetchone(self): return (7,)
    @contextmanager
    def connect():
        yield type("C", (), {"cursor": lambda self: Cur()})()
    monkeypatch.setattr(ledger, "connect", connect)
    monkeypatch.setattr(memory, "remember", lambda kind, text, repo=None, ref=None, source="fleet": kept.append((kind, text)) or "k")
    ledger.post("chris", "Ok", topic="note")
    ledger.post("concierge", "Chris says: never merge on a red check.", topic="note")
    assert kept == [("lesson", "Ok"), ("feedback", "never merge on a red check.")]


def test_the_pr_body_is_short_and_leads_with_evidence(tmp_path, monkeypatch):
    monkeypatch.setattr(publish, "P", str(tmp_path))
    (tmp_path / "verify.sh").write_text("pnpm test")
    (tmp_path / "verify.out").write_text("x\n" * 5000 + "\x1b[32m✓\x1b[39m 50 passed\n")
    (tmp_path / "verify.rc").write_text("0")
    (tmp_path / "01-findings.json").write_text('{"candidates": [' + '"f",' * 3000 + '"f"]}')
    (tmp_path / "03-implementation.md").write_text("Guarded the port.")
    body = publish.pr_body()
    assert len(body) < 3000 and "01 findings" not in body and "\x1b[" not in body
    assert "50 passed" in body[:2000] and "Guarded the port." in body


def test_escalation_applies_the_judges_edits_inside_the_repo_only(monkeypatch, tmp_path):
    import io
    import subprocess
    import escalate
    repo = tmp_path / "repo"; repo.mkdir(); p = tmp_path / "p"; p.mkdir()
    git = lambda *a: subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True)
    git("init", "-q"); git("config", "user.email", "t@t"); git("config", "user.name", "t")
    (repo / "a.py").write_text("x = 1\ny = 1\n"); git("add", "."); git("commit", "-qm", "init")
    start = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    (repo / "a.py").write_text("x = 2\ny = 1\n"); git("commit", "-qam", "change")
    (p / "plan.md").write_text("1. a.py: x = 3\n   proof: pytest\n")
    (p / "precheck.out").write_text("pre-review confidence 60 (bar 85): half done\n1. x must be 3\n2. no test")
    monkeypatch.setattr(escalate, "P", str(p)); monkeypatch.setattr(escalate, "REPO_DIR", str(repo))
    monkeypatch.setenv("STAGE_START_SHA", start)
    monkeypatch.setattr(review, "JUDGE_URL", "http://judge")
    seen = {}
    reply = (f"FILE: a.py\n<<<<<<< SEARCH\nx = 2\n=======\nx = 3\n>>>>>>> REPLACE\n"
             f"FILE: test_a.py\n<<<<<<< SEARCH\n=======\nimport a\n>>>>>>> REPLACE\n"
             f"FILE: ../evil.py\n<<<<<<< SEARCH\n=======\nboom\n>>>>>>> REPLACE\n"
             f"FILE: .git/hooks/pre-commit\n<<<<<<< SEARCH\n=======\nboom\n>>>>>>> REPLACE\n"
             f"FILE: a.py\n<<<<<<< SEARCH\ny = 9\n=======\nnope\n>>>>>>> REPLACE\n"
             f"FILE: {p}/verify.sh\n<<<<<<< SEARCH\n=======\npython3 -c 'import a'\n>>>>>>> REPLACE\n")
    monkeypatch.setattr(review, "ask_judge", lambda prompt, **k: seen.update(prompt=prompt, **k) or reply)
    assert escalate.main(["rejected"]) == 0
    assert seen["thinking"] is False                              # 3e9c: a 20-min think hit the cap, nothing applied
    assert "2. no test" in seen["prompt"] and "x = 2\ny = 1" in seen["prompt"] and "1. a.py: x = 3" in seen["prompt"]
    assert (repo / "a.py").read_text() == "x = 3\ny = 1\n" and (repo / "test_a.py").read_text() == "import a\n"
    assert not (tmp_path / "evil.py").exists() and not (repo / ".git/hooks/pre-commit").exists()
    assert (p / "verify.sh").exists() and "Escalation" in (p / "03-implementation.md").read_text()
    log = subprocess.run(["git", "-C", str(repo), "log", "-1", "--format=%s", "--name-only"], capture_output=True, text=True).stdout
    assert "takes over" in log and "test_a.py" in log and "verify.sh" not in log
    monkeypatch.setattr(review, "ask_judge", lambda prompt, **k: "I would change x.")
    assert escalate.main(["rejected"]) == 1                       # no edit blocks: nothing committed
    monkeypatch.setattr(sys, "stdin", io.StringIO("Ber db Ber " * 200))
    assert escalate.main(["--degenerate"]) == 0
    monkeypatch.setattr(sys, "stdin", io.StringIO("stage implement: verify.sh passed (round 1), all 14 tests green " * 3))
    assert escalate.main(["--degenerate"]) == 1


def test_precheck_judges_the_whole_pr_not_the_round(monkeypatch, tmp_path):
    """kagent#62's round removed main.test.ts, which the PR itself had added; judged on the
    round's diff alone that read as deleting an existing test, and pre-review scored it 45."""
    import subprocess
    import precheck
    repo = tmp_path / "repo"; repo.mkdir(); p = tmp_path / "p"; p.mkdir()
    git = lambda *a: subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True, text=True).stdout.strip()
    git("init", "-q"); git("config", "user.email", "t@t"); git("config", "user.name", "t")
    (repo / "a.py").write_text("x = 1\n"); git("add", "."); git("commit", "-qm", "base")
    git("update-ref", "refs/remotes/origin/main", "HEAD"); git("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
    (repo / "main.test.ts").write_text("guard\n"); git("add", "."); git("commit", "-qm", "the PR adds an unscoped test")
    head = git("rev-parse", "HEAD")
    (repo / "main.test.ts").unlink(); (repo / "a.py").write_text("x = 2\n"); git("commit", "-qam", "round: drop it, fix a.py")
    monkeypatch.setattr(precheck, "P", str(p)); monkeypatch.setattr(precheck, "REPO_DIR", str(repo))
    monkeypatch.setenv("STAGE_START_SHA", head)
    monkeypatch.setattr(review, "JUDGE_URL", "http://judge")
    seen = {}
    monkeypatch.setattr(review, "judge", lambda pr, diff, **k: seen.setdefault("diff", diff) and {"confidence": 90, "summary": "ok"})
    assert precheck.main() == 0
    assert "a.py" in seen["diff"] and "main.test.ts" not in seen["diff"]
    git("update-ref", "-d", "refs/remotes/origin/HEAD")       # no default branch known: the round's own diff, as before
    assert precheck.pr_base() == head
