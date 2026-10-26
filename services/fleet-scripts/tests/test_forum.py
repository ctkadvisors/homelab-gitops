"""The runnable checks for 2026-09-06: the forum, kid gloves, self-repair and
repo choice. No Postgres, no GitHub: the ledger and the API are monkeypatched.
`python3 -m pytest services/fleet-scripts/tests/test_forum.py`."""

import os
import pathlib
import sys
import json
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
os.environ.setdefault("MISSION_REPOS", "ctkadvisors/kagent,ctkadvisors/new_localai")
from fleet import github, ledger  # noqa: E402
import collect  # noqa: E402
import reconcile  # noqa: E402
import review  # noqa: E402


def test_voice_is_shared_and_says_the_essentials():
    v = ledger.voice()
    assert "did not do" in v and "I don't know" in v and "GO" in v and "decline" in v


def test_kid_gloves_reads_the_repo_topic_and_fails_closed(monkeypatch):
    github._topics.clear()
    monkeypatch.setattr(github, "api", lambda path, *a, **k: {"names": ["fleet-kid-gloves"]} if "harknote" in path else {"names": []})
    assert github.kid_gloves("ctkadvisors/harknote") is True
    assert github.kid_gloves("ctkadvisors/kagent") is False
    github._topics.clear()

    def boom(path, *a, **k):
        raise RuntimeError("github down")
    monkeypatch.setattr(github, "api", boom)
    assert github.kid_gloves("ctkadvisors/kagent") is True  # unreadable with no history = never merge
    github._topics["ctkadvisors/kagent"] = (0.0, [])          # stale but known: keep the last answer
    assert github.kid_gloves("ctkadvisors/kagent") is False
    github._topics["ctkadvisors/harknote"] = (0.0, ["fleet-kid-gloves"])
    assert github.kid_gloves("ctkadvisors/harknote") is True
    github._topics.clear()


def test_policy_tier3_has_a_window_and_kid_gloves_are_named():
    p = review.policy()
    assert p["veto_minutes_by_tier"]["3"] == review.VETO_MINUTES[3] > 0
    assert "fleet-kid-gloves" in p["kid_gloves"] and "merge in kid-gloves repos" in p["cannot"]


class FakeGH:
    def __init__(self, issues, gloves=()):
        self.issues, self.gloves, self.created = issues, set(gloves), []

    def api(self, path, data=None, method=None, **k):
        if "/search/issues" in path:
            lbl = path.split("label:%22")[1].split("%22")[0]
            return {"items": [{"repository_url": f"https://api.github.com/repos/{r}"} for r, l in self.issues if l == lbl]}
        if path.endswith("/issues") and data:
            self.created.append(data)
            return {"html_url": f"https://github.com/{path.split('/')[2]}/{path.split('/')[3]}/issues/{len(self.created)}"}
        return {}

    def kid_gloves(self, repo):
        return repo in self.gloves


def test_choose_repo_follows_open_problems_and_skips_kid_gloves(monkeypatch):
    monkeypatch.setenv("REPO", "ctkadvisors/kagent")
    gh = FakeGH([("ctkadvisors/harknote", "fleet:halt"), ("ctkadvisors/harknote", "fleet:halt"),
                 ("ctkadvisors/new_localai", "fleet:repair")], gloves={"ctkadvisors/harknote"})
    repo, why = reconcile.choose_repo(gh)
    assert repo == "ctkadvisors/new_localai" and "1 open fleet problem" in why
    monkeypatch.setattr(reconcile, "IDEATION_REPOS", ["ctkadvisors/kagent", "ctkadvisors/new_localai"])
    repo, why = reconcile.choose_repo(FakeGH([]))
    assert repo == "ctkadvisors/kagent" and "no open fleet problems" in why   # no ledger: first eligible repo


def pod(name, node, started, reason=None, message=None):
    return {"metadata": {"name": name}, "spec": {"nodeName": node},
            "status": {"phase": "Failed", "startTime": started,
                       "containerStatuses": [{"state": {"terminated": {"exitCode": 1, "reason": reason, "message": message}}}]}}


def test_own_failures_names_the_job_node_and_reason():
    now = time.time()
    fresh = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - 600))
    stale = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - 7200))
    out = reconcile.own_failures(now, [
        pod("pr-reviewer-29811127-g94tf", "k3s-reconciler", fresh, "Error", "exec /bin/sh: exec format error"),
        pod("fleet-reconcile-29811175-6fdpx", "k3s-reconciler", fresh, "Error", "exec /usr/local/bin/python3: exec format error"),
        pod("triage-29811157-zhdw7", "elitemini2", stale, "Error"),
    ])
    assert [f["job"] for f in out] == ["pr-reviewer", "fleet-reconcile"]
    assert out[0]["node"] == "k3s-reconciler" and "exec format error" in out[0]["reason"]


def test_repair_files_once_per_repeating_failure(monkeypatch):
    kv = {}
    said = []
    monkeypatch.setattr(ledger, "kv_get", lambda k: kv.get(k))
    monkeypatch.setattr(ledger, "kv_set", lambda k, v: kv.__setitem__(k, v))
    monkeypatch.setattr(ledger, "say", lambda *a, **k: said.append((a, k)))
    now = time.time()
    fails = [{"pod": f"pr-reviewer-2981112{i}-abcde", "job": "pr-reviewer", "node": "k3s-reconciler",
              "reason": "exec format error", "at": now} for i in range(3)]
    once = [{"pod": "triage-1-abcde", "job": "triage", "node": "elitemini2", "reason": "timeout", "at": now}]
    gh = FakeGH([])
    filed = reconcile.repair(fails + once, now, gh)
    assert len(filed) == 1 and gh.created[0]["labels"] == ["mission", "fleet:repair"]
    assert "pr-reviewer" in gh.created[0]["title"] and "k3s-reconciler" in gh.created[0]["body"]
    assert said and "implementer" in said[0][1]["mentions"]
    assert reconcile.repair(fails, now + 60, gh) == []  # same failure an hour later: already filed today


def test_self_check_pauses_when_failures_pile_up(monkeypatch):
    kv = {}
    monkeypatch.setattr(ledger, "kv_get", lambda k: kv.get(k))
    monkeypatch.setattr(ledger, "kv_set", lambda k, v: kv.__setitem__(k, v))
    monkeypatch.setattr(ledger, "say", lambda *a, **k: None)
    monkeypatch.setattr(reconcile.telegram, "send", lambda *a, **k: None)
    monkeypatch.setattr(reconcile, "repair", lambda *a, **k: [])
    now = time.time()
    many = [{"pod": f"x-{i}-abcde", "job": "x", "node": "n", "reason": f"r{i}", "at": now} for i in range(reconcile.PAUSE_AFTER)]
    monkeypatch.setattr(reconcile, "own_failures", lambda now, pods=None: many)
    assert "pausing" in reconcile.self_check(now)
    assert kv["pause"]["until"] > now and kv["self_health"]["failed_last_hour"] == reconcile.PAUSE_AFTER
    monkeypatch.setattr(reconcile, "own_failures", lambda now, pods=None: [])
    assert reconcile.self_check(now + 10) is not None  # still paused
    assert reconcile.self_check(now + reconcile.PAUSE_MINUTES * 60 + 1) is None


def test_collect_forum_turns_ideas_into_evidence(monkeypatch):
    rows = {"idea": [{"id": 7, "topic": "idea", "author": "chris", "body": "make the digest shorter", "ref": None, "created_at": "2026-09-06T05:00:00Z"}],
            "question": []}
    monkeypatch.setattr(ledger, "posts", lambda limit=50, topic=None, ref=None, unanswered=False: rows.get(topic, []))
    items, note = collect.collect_forum()
    assert note is None and items[0]["post"] == 7 and items[0]["by"] == "chris" and items[0]["count"] == 1


def test_kid_gloves_pr_is_escalated_never_merged(monkeypatch):
    calls, said = [], []
    pr = {"number": 5, "title": "t", "body": "", "html_url": "https://github.com/ctkadvisors/harknote/pull/5",
          "head": {"sha": "abc", "ref": "agent/x", "repo": {"full_name": "ctkadvisors/harknote"}}, "user": {"login": "chrisknu"}, "labels": []}

    def api(path, data=None, method=None, **k):
        calls.append((path, method))
        if path.endswith("/files?per_page=100"):
            return [{"filename": "README.md", "changes": 1}]
        if "/check-runs" in path:
            return {"check_runs": [{"status": "completed", "conclusion": "success"}]}
        if path.endswith("/pulls/5"):
            return "diff"
        return {}
    monkeypatch.setattr(review.github, "api", api)
    monkeypatch.setattr(review.github, "kid_gloves", lambda repo: True)
    monkeypatch.setattr(review, "checkout", lambda *a: None)
    monkeypatch.setattr(review, "objection", lambda *a: None)
    monkeypatch.setattr(review, "judge", lambda *a, **k: {"confidence": 99, "summary": "fine", "feedback": ""})
    monkeypatch.setattr(review.ledger, "posts", lambda **k: [])
    monkeypatch.setattr(review.ledger, "say", lambda *a, **k: said.append(k))
    monkeypatch.setattr(review, "forget_objection", lambda *a: None)
    monkeypatch.setattr(review.telegram, "send", lambda *a, **k: None)
    review.review_pr("ctkadvisors/harknote", "/repos/ctkadvisors/harknote", pr, 5)
    assert not any(p.endswith("/merge") for p, _ in calls)
    assert any("fleet:escalated" in str(c) for c in calls) or said[-1]["topic"] == "question"
    assert said[-1]["mentions"] == ["concierge"]   # the concierge decides; a human merges a kid-gloves repo


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-q"]))


# --- 2026-09-06 evening: reap, relay, review rounds --------------------------

class KV:
    def __init__(self): self.kv = {}
    def kv_get(self, k): return self.kv.get(k)
    def kv_set(self, k, v): self.kv[k] = v


def test_reap_closes_a_killed_run_and_tells_the_forum(monkeypatch):
    kv = KV(); finished, said, comments = [], [], []
    monkeypatch.setattr(ledger, "unfinished_runs", lambda: [{"id": "mission-1", "pipeline": "mission", "repo": "o/r", "fingerprint": "fp1", "trigger": "reconcile", "started_at": "2026-09-06T09:30:00Z"}])
    monkeypatch.setattr(ledger, "finish_run", lambda rid, outcome, **kw: finished.append((rid, outcome, kw.get("halt"))))
    monkeypatch.setattr(ledger, "set_state", lambda fp, st: None)
    monkeypatch.setattr(ledger, "halted_candidates", lambda: [{"fingerprint": "fp1", "issue_url": "https://github.com/o/r/issues/22"}])
    monkeypatch.setattr(ledger, "say", lambda *a, **k: said.append((a, k)))
    def k8s(method, path, body=None):
        if "/jobs/mission-1" in path:
            return {"status": {"failed": 1}}
        if "/pods" in path:
            return {"items": [{"status": {"initContainerStatuses": [{"name": "clone", "state": {"terminated": {"exitCode": 0}}},
                                                                  {"name": "implement", "state": {"terminated": {"exitCode": 137}}}]}}]}
        raise AssertionError(path)
    monkeypatch.setattr(reconcile, "k8s", k8s)
    class GH:
        def api(self, path, data=None, **k): comments.append((path, data)); return {}
    assert reconcile.repair.__name__  # module loaded
    assert reconcile.reap_failed_runs(time.time(), GH()) == ["mission-1"]
    assert finished[0][1] == "failed" and finished[0][2]["stage"] == "implement" and "137" in finished[0][2]["reason"] and "OOM" in finished[0][2]["reason"]
    assert said[0][0][0] == "reconcile" and "implementer" in said[0][1]["mentions"]
    assert comments and comments[0][0].endswith("/issues/22/comments")


def test_relay_sends_a_question_for_chris_once(monkeypatch):
    kv = KV(); sent = []
    monkeypatch.setattr(ledger, "kv_get", kv.kv_get); monkeypatch.setattr(ledger, "kv_set", kv.kv_set)
    monkeypatch.setattr(ledger, "posts", lambda **k: [{"id": 6, "author": "implementer", "body": "in scope?", "ref": "https://github.com/o/r/issues/22", "mentions": ["reconcile", "chris"]},
                                                       {"id": 7, "author": "implement", "body": "fresh: concierge first", "ref": None, "mentions": ["chris", "concierge"],
                                                        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())},
                                                       {"id": 8, "author": "implementer", "body": "for reconcile only", "ref": None, "mentions": ["reconcile"]}])
    monkeypatch.setattr(reconcile.telegram, "send", lambda t: sent.append(t))
    assert reconcile.relay_questions(time.time()) == 1 and "in scope?" in sent[0] and "fleet.example.com" in sent[0]
    assert reconcile.relay_questions(time.time()) == 0  # not twice


def test_context_for_carries_the_last_failure_and_the_thread(monkeypatch):
    monkeypatch.setattr(ledger, "last_run", lambda fp: {"id": "mission-1", "outcome": "failed", "halt": {"stage": "implement", "reason": "exit 137"}})
    monkeypatch.setattr(ledger, "posts", lambda **k: [{"author": "chris", "topic": "note", "body": "keep next pinned"},
                                                       {"author": "implementer", "topic": "question", "body": "bump next?"}])
    ctx = reconcile.context_for("fp1", "https://github.com/o/r/issues/22")
    assert "Previous attempt mission-1 failed at implement: exit 137" in ctx
    assert ctx.index("bump next?") < ctx.index("keep next pinned")  # oldest first


def test_retry_board_waits_on_an_open_question(monkeypatch):
    monkeypatch.setattr(ledger, "halted_candidates", lambda: [{"fingerprint": "fp1", "repo": "o/r", "issue_url": "https://github.com/o/r/issues/22"}])
    monkeypatch.setattr(ledger, "open_questions", lambda ref: [{"id": 6}])
    monkeypatch.setattr(reconcile.github, "api", lambda path, *a, **k: {"state": "open", "labels": [{"name": "mission"}]})
    assert reconcile.retry_board(time.time()) is None


def test_retry_reviewed_relaunches_on_the_pr_branch_with_the_objection(monkeypatch):
    kv = KV(); kv.kv["objection:o/r#24"] = {"sha": "abc", "at": time.time() - 7200, "summary": "font swap", "feedback": "use display:optional"}
    monkeypatch.setattr(ledger, "kv_get", kv.kv_get)
    monkeypatch.setattr(ledger, "tested_candidates", lambda: [{"fingerprint": "fp2", "repo": "o/r", "issue_url": "https://github.com/o/r/issues/23",
                                                               "pr_url": "https://github.com/o/r/pull/24", "started_at": "2026-09-06T07:30:00Z", "trigger": "reconcile"}])
    monkeypatch.setattr(ledger, "open_questions", lambda ref: [])
    monkeypatch.setattr(ledger, "last_run", lambda fp: None)
    monkeypatch.setattr(ledger, "posts", lambda **k: [])
    said = []
    monkeypatch.setattr(ledger, "say", lambda *a, **k: said.append(k))
    class GH:
        def kid_gloves(self, repo): return False
        def api(self, path, data=None, **k):
            if path.endswith("/pulls/24"): return {"state": "open", "merged": False, "title": "perf", "html_url": "https://github.com/o/r/pull/24", "head": {"sha": "abc", "ref": "agent/mission-20260906-073003"}}
            if "/check-runs" in path: return {"check_runs": [{"name": "lighthouse", "status": "completed", "conclusion": "failure"}]}
            if path.endswith("/issues/23"): return {"html_url": "https://github.com/o/r/issues/23", "title": "Lighthouse", "body": "fix it", "number": 23}
            if path.endswith("/comments?per_page=100"): return []
            raise AssertionError(path)
    launched = []
    class Resp:
        def __init__(self, b): self.b = b
        def read(self): return self.b
        def __enter__(self): return self
        def __exit__(self, *a): pass
    def urlopen(req, timeout=30):
        launched.append(json.loads(req.data)); return Resp(b'{"name": "mission-review-1"}')
    monkeypatch.setattr(reconcile.urllib.request, "urlopen", urlopen)
    assert reconcile.retry_reviewed(time.time(), GH()) == "mission-review-1"
    sent = launched[0]
    assert sent["branch"] == "agent/mission-20260906-073003" and sent["requestedBy"].startswith("review:")
    assert "use display:optional" in sent["brief"] and "lighthouse" in sent["brief"] and "review round" in sent["brief"]
    assert said[-1]["mentions"] == ["implementer", "reviewer"]


def test_launcher_review_rounds_are_capped_and_branch_validated(monkeypatch):
    import launcher
    assert launcher.branch_of({}) is None and launcher.branch_of({"branch": "agent/mission-1"}) == "agent/mission-1"
    try:
        launcher.branch_of({"branch": "main"}); assert False
    except ValueError:
        pass
    monkeypatch.setattr(launcher.ledger, "mission_candidate", lambda repo, brief: ("fp", "t", None))
    monkeypatch.setattr(launcher.ledger, "attempts", lambda fp: (5, None))
    monkeypatch.setattr(launcher.ledger, "runs_by_trigger", lambda fp, t: 1)
    assert launcher.admit("o/r", "brief text here", review=True) == ("fp", None)       # past MAX_ATTEMPTS, review rounds have their own cap
    monkeypatch.setattr(launcher.ledger, "runs_by_trigger", lambda fp, t: launcher.REVIEW_ROUNDS)
    assert "iterated" in launcher.admit("o/r", "brief text here", review=True)[1]


def test_open_pr_comments_on_an_existing_pr_instead_of_opening_a_second(monkeypatch, tmp_path):
    import publish, subprocess
    monkeypatch.setattr(publish, "REPO_DIR", str(tmp_path)); monkeypatch.setattr(publish, "BRANCH", "agent/mission-x"); monkeypatch.setattr(publish, "REPO", "o/r")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: type("R", (), {"stdout": "feat: thing\n"})())
    calls = []
    class GH:
        def push_url(self, repo): return "https://x@github.com/o/r.git"
        def api(self, path, data=None, **k):
            calls.append((path, data))
            if "pulls?state=open&head=o:agent/mission-x" in path: return [{"number": 24, "html_url": "https://github.com/o/r/pull/24"}]
            return {"html_url": "https://github.com/o/r/pull/99"}
    assert publish.open_pr("trace", GH()) == "https://github.com/o/r/pull/24"
    assert calls[-1][0].endswith("/issues/24/comments") and not any(p == "/repos/o/r/pulls" for p, _ in calls)
    assert ("/repos/o/r/pulls/24", {"body": "trace"}) in calls    # the reviewer reads the body: a round replaces it


def test_telegram_deep_links_and_ref_labels():
    from fleet import telegram
    assert telegram.post_link(6).endswith("/#post-6") and telegram.post_link(6).startswith("https://")
    assert telegram.ref_label("https://github.com/ctkadvisors/brutalist_todo/issues/22") == "brutalist_todo#22"
    assert telegram.ref_label("https://github.com/o/r/pull/24") == "r#24" and telegram.ref_label("mission-1") == "mission-1" and telegram.ref_label(None) == ""


def test_relay_message_names_the_subject_and_links_the_post(monkeypatch):
    kv = KV(); sent = []
    monkeypatch.setattr(ledger, "kv_get", kv.kv_get); monkeypatch.setattr(ledger, "kv_set", kv.kv_set)
    monkeypatch.setattr(ledger, "posts", lambda **k: [{"id": 6, "author": "implementer", "body": "in scope?", "ref": "https://github.com/ctkadvisors/brutalist_todo/issues/22", "mentions": ["chris"]}])
    monkeypatch.setattr(reconcile.telegram, "send", lambda t: sent.append(t))
    reconcile.relay_questions(time.time())
    assert "about brutalist_todo#22" in sent[0] and "/#post-6" in sent[0] and "issues/22" in sent[0]


def test_console_page_has_needs_you_and_deep_link_handling():
    import console
    assert 'id=needs' in console.PAGE and 'function jumpToHash' in console.PAGE and 'id="post-${x.id}"' in console.PAGE and 'hashchange' in console.PAGE


def test_docs_only_pr_without_workflows_merges_at_tier_0(monkeypatch):
    calls, said = [], []
    pr = {"number": 21, "title": "docs: note", "body": "", "html_url": "https://github.com/o/r/pull/21",
          "head": {"sha": "abc", "ref": "agent/docs", "repo": {"full_name": "o/r"}}, "user": {"login": "chrisknu"}, "labels": []}

    def api(path, data=None, method=None, **k):
        calls.append((path, method))
        if path.endswith("/files?per_page=100"):
            return [{"filename": "CLAUDE.md", "changes": 9}]
        if "/check-runs" in path:
            return {"check_runs": []}          # no workflow touches prose
        if path.endswith("/pulls/21"):
            return "diff"
        return {}
    monkeypatch.setattr(review.github, "api", api)
    monkeypatch.setattr(review.github, "kid_gloves", lambda repo: False)
    monkeypatch.setattr(review, "checkout", lambda *a: None)
    monkeypatch.setattr(review, "objection", lambda *a: None)
    monkeypatch.setattr(review, "judge", lambda *a, **k: {"confidence": 90, "summary": "fine", "feedback": ""})
    monkeypatch.setattr(review, "merge_gate", lambda repo, n, tier, why: (True, "tier 0: no veto window"))
    monkeypatch.setattr(review, "mark_merged", lambda *a: None)
    monkeypatch.setattr(review.ledger, "posts", lambda **k: [])
    monkeypatch.setattr(review.ledger, "say", lambda *a, **k: said.append(k))
    monkeypatch.setattr(review, "forget_objection", lambda *a: None)
    monkeypatch.setattr(review.telegram, "send", lambda *a, **k: None)
    review.review_pr("o/r", "/repos/o/r", pr, 21)
    assert any(p.endswith("/pulls/21/merge") and m == "PUT" for p, m in calls)


# --- 2026-09-06 late: continue the PR, ask the concierge, watch ships, read failing checks

def test_open_pr_branch_returns_the_open_prs_head(monkeypatch):
    # the newest run may be a halted review round with no pr_url: the PR still counts
    monkeypatch.setattr(ledger, "last_pr_url", lambda fp: "https://github.com/o/r/pull/24")
    class GH:
        def api(self, path, **k): return {"state": "open", "merged": False, "head": {"ref": "agent/mission-1"}}
    assert reconcile.open_pr_branch("fp", "o/r", GH()) == "agent/mission-1"
    class Closed:
        def api(self, path, **k): return {"state": "closed", "merged": True, "head": {"ref": "x"}}
    assert reconcile.open_pr_branch("fp", "o/r", Closed()) is None
    monkeypatch.setattr(ledger, "last_pr_url", lambda fp: None)
    assert reconcile.open_pr_branch("fp", "o/r", GH()) is None


def test_ask_concierge_files_a_task_once_per_role_question(monkeypatch):
    kv = KV(); said = []; tasks = []
    monkeypatch.setattr(ledger, "kv_get", kv.kv_get); monkeypatch.setattr(ledger, "kv_set", kv.kv_set)
    monkeypatch.setattr(ledger, "say", lambda *a, **k: said.append(k))
    old = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 600))
    posts = [{"id": 29, "author": "implementer", "body": "widen scope?", "ref": "https://github.com/o/r/pull/24", "mentions": ["reconcile"], "created_at": old},
             {"id": 6, "author": "implementer", "body": "for chris", "ref": None, "mentions": ["chris"], "created_at": old}]
    monkeypatch.setattr(ledger, "posts", lambda limit=50, topic=None, ref=None, unanswered=False: posts if topic == "question" else [])
    class Resp:
        def __init__(self, b): self.b = b
        def read(self): return self.b
        def __enter__(self): return self
        def __exit__(self, *a): pass
    def urlopen(req, timeout=30):
        tasks.append(json.loads(req.data)); return Resp(b'{"name": "kct-x"}')
    monkeypatch.setattr(reconcile.urllib.request, "urlopen", urlopen)
    assert reconcile.ask_concierge(time.time(), "http://wb") == 2  # the one for chris too: the concierge decides, Chris overrides
    assert tasks[0]["targetAgent"] == "concierge" and "parent_id\":29" in tasks[0]["originalUserMessage"] and "widen scope?" in tasks[0]["originalUserMessage"]
    assert "for chris" in tasks[1]["originalUserMessage"]
    assert said[0]["mentions"] == ["concierge"]
    assert reconcile.ask_concierge(time.time(), "http://wb") == 0  # not twice
    monkeypatch.setattr(reconcile, "k8s", lambda m, p, body=None: {"items": [{"metadata": {"name": "kct-x"}, "status": {"phase": "Failed"}}]})  # via the list: get is not allowed
    assert reconcile.ask_concierge(time.time(), "http://wb") == 2  # a Failed task earns another try (11 of 14 failed on 2026-09-11)
    assert kv.kv_get("asked:29")["tries"] == 2
    assert reconcile.ask_concierge(time.time(), "http://wb") == 2 and reconcile.ask_concierge(time.time(), "http://wb") == 0  # three tries, then it rests
    monkeypatch.setattr(reconcile, "ASK_PER_TICK", 1)
    kv.kv_set("asked:29", None); kv.kv_set("asked:6", None)
    assert reconcile.ask_concierge(time.time(), "http://wb") == 1  # paced


def test_watch_ships_reruns_once_then_asks_chris(monkeypatch):
    kv = KV(); said = []; calls = []
    monkeypatch.setattr(ledger, "kv_get", kv.kv_get); monkeypatch.setattr(ledger, "kv_set", kv.kv_set)
    monkeypatch.setattr(ledger, "say", lambda *a, **k: said.append(k))
    now = time.time()
    run = {"id": 5, "status": "completed", "conclusion": "failure", "head_sha": "abcdef0", "html_url": "https://github.com/o/r/actions/runs/5",
           "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - 300))}
    class GH:
        def api(self, path, data=None, method=None, **k):
            calls.append((path, method))
            if "/workflows/" in path: return {"workflow_runs": [run]}
            return {}
    assert reconcile.watch_ships(now, GH()) == ["5"]
    assert any(p.endswith("/actions/runs/5/rerun-failed-jobs") and m == "POST" for p, m in calls)
    assert reconcile.watch_ships(now + 60, GH()) == [] and said[-1]["mentions"] == ["chris"]
    assert reconcile.watch_ships(now + 120, GH()) == [] and len(said) == 2  # escalated once


def test_failing_checks_reads_the_job_log_lines(monkeypatch):
    import launcher
    class GH:
        def api(self, path, **k):
            return {"check_runs": [{"name": "lighthouse", "status": "completed", "conclusion": "failure", "details_url": "https://github.com/o/r/actions/runs/1/job/77"},
                                   {"name": "build", "status": "completed", "conclusion": "success", "details_url": "x"}]}
    monkeypatch.setattr(launcher.github, "job_log", lambda repo, jid, gh: "2026-09-06T21:08:19.6Z Checking assertions\n2026-09-06T21:08:19.7Z   \x1b[31m✘\x1b[0m  button-name failure for minScore assertion\n2026-09-06T21:08:19.8Z         expected: >=0.9\n2026-09-06T21:08:19.9Z            found: 0\n")
    out = launcher.failing_checks("o/r", "fde21cc", GH())
    assert [f["name"] for f in out["failing"]] == ["lighthouse"]
    assert out["failing"][0]["lines"] == ["✘  button-name failure for minScore assertion", "expected: >=0.9", "found: 0"]


def test_chat_signal_ignores_the_fleets_own_concierge_asks(monkeypatch):
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 60))
    old = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 3600))
    monkeypatch.setattr(reconcile, "k8s", lambda m, p, body=None: {"items": [
        {"metadata": {"name": "manual-abc", "creationTimestamp": now}},    # reconcile asked the concierge a minute ago
        {"metadata": {"name": "kct-telegram-work-1", "creationTimestamp": old}}]})
    quiet, why = reconcile.sig_chat()
    assert quiet and why.startswith("last agent task 60 min ago")


def test_tasks_signal_ignores_the_fleets_own_concierge_asks(monkeypatch):
    monkeypatch.setattr(reconcile, "k8s", lambda m, p, body=None: {"items": [
        {"metadata": {"name": "manual-ask"}, "spec": {"payload": {"forumQuestion": 29}}, "status": {"phase": "Running"}},
        {"metadata": {"name": "kct-telegram-work-1"}, "spec": {"payload": {"text": "hi"}}, "status": {"phase": "Completed"}}]})
    assert reconcile.sig_tasks() == (True, "agenttasks in flight: 0")
    monkeypatch.setattr(reconcile, "k8s", lambda m, p, body=None: {"items": [
        {"metadata": {"name": "kct-telegram-work-2"}, "spec": {"payload": {"text": "hi"}}, "status": {"phase": "Running"}}]})
    assert reconcile.sig_tasks() == (False, "agenttasks in flight: 1")


def test_relay_answers_posts_a_completed_tasks_text_into_the_thread(monkeypatch):
    kv = KV(); posted = []
    kv.kv_set("asked:673", {"at": 1.0, "task": "manual-a", "tries": 2})
    kv.kv_set("asked:600", {"at": 1.0, "task": "manual-b", "tries": 1})
    monkeypatch.setattr(ledger, "kv_get", kv.kv_get); monkeypatch.setattr(ledger, "kv_set", kv.kv_set)
    monkeypatch.setattr(ledger, "kv_like", lambda pat: [(k, v) for k, v in kv.kv.items() if k.startswith("asked:")])
    monkeypatch.setattr(ledger, "posts", lambda limit=50, topic=None, ref=None, unanswered=False: [{"id": 9, "parent_id": 600}])  # 600 already answered
    monkeypatch.setattr(ledger, "post", lambda author, body, topic="note", ref=None, mentions=None, parent_id=None: posted.append((author, topic, parent_id, body)) or 1)
    monkeypatch.setattr(reconcile, "k8s", lambda m, p, body=None: {"items": [
        {"metadata": {"name": "manual-a"}, "status": {"phase": "Completed", "result": {"content": "Confirm scope: M1 only, record run_id and url on the ledger entry when a ship fails. I could not post it."}}},
        {"metadata": {"name": "manual-b"}, "status": {"phase": "Completed", "result": {"content": "already posted this one"}}}]})
    assert reconcile.relay_answers() == 1
    assert posted == [("concierge", "note", 673, posted[0][3])] and posted[0][3].startswith("Confirm scope: M1 only")
    assert kv.kv_get("asked:673")["relayed"] and kv.kv_get("asked:600")["relayed"]
    assert reconcile.relay_answers() == 0  # once
