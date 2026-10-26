"""The one runnable check: template rendering and brief validation.

    python3 -m pytest services/mission-launcher   # or: python3 test_launcher.py
"""

import json
import os
import sys

os.environ["MISSION_REPOS"] = "ctkadvisors/kagent,ctkadvisors/new_localai"  # no GitHub in tests
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts"))
import launcher  # noqa: E402

TEMPLATE = {
    "apiVersion": "batch/v1",
    "kind": "Job",
    "metadata": {"name": "PLACEHOLDER", "namespace": "kagent-system"},
    "spec": {"template": {"spec": {
        "initContainers": [{"name": "brief", "env": [{"name": "REPO", "value": "old"}]}, {"name": "implement"}],
        "containers": [{"name": "publish", "env": [{"name": "BRAIN_URL", "value": "http://brain"}]}],
    }}},
}


def test_render_sets_name_branch_and_env_on_every_container():
    job = launcher.render_job(TEMPLATE, "mission-20260902-010203", "fix the flaky test in x", "ctkadvisors/kagent", "concierge")
    assert job["metadata"]["name"] == "mission-20260902-010203"
    assert job["metadata"]["labels"]["app"] == "mission"
    spec = job["spec"]["template"]["spec"]
    for c in spec["initContainers"] + spec["containers"]:
        env = {e["name"]: e["value"] for e in c["env"]}
        assert env["REPO"] == "ctkadvisors/kagent"
        assert env["BRANCH"] == "agent/mission-20260902-010203"
        assert env["MISSION_BRIEF"] == "fix the flaky test in x"
        assert env["PIPELINE"] == "Mission"
        assert env["RUN_TRIGGER"] == "concierge"
        assert env["RUN_ID"] == job["metadata"]["name"]  # the ledger row, even when BRANCH is another run's
    assert {e["name"]: e["value"] for e in launcher.render_job(TEMPLATE, "m", "fix the flaky test in x", "o/r", "triage:https://x/issues/5")
            ["spec"]["template"]["spec"]["containers"][0]["env"]}["RUN_TRIGGER"] == "triage"
    # publish keeps its own env, and the old REPO on brief was replaced not duplicated
    assert {e["name"] for e in spec["containers"][0]["env"]} >= {"BRAIN_URL", "REPO"}
    assert [e["name"] for e in spec["initContainers"][0]["env"]].count("REPO") == 1
    # template untouched
    assert TEMPLATE["metadata"]["name"] == "PLACEHOLDER"


def test_validate_rejects_short_brief_and_unknown_repo():
    for bad in ({"brief": "hi"}, {"brief": "x" * 9000}, {"brief": "do the thing please", "repo": "evil/repo"}):
        try:
            launcher.validate(bad)
        except ValueError:
            continue
        raise AssertionError(f"accepted {json.dumps(bad)[:40]}")
    brief, repo = launcher.validate({"brief": "fix the typo in README"})
    assert repo == launcher.DEFAULT_REPO and brief.startswith("fix")
    assert launcher.validate({"brief": "fix the typo in README", "repo": "ctkadvisors/new_localai"})[1] == "ctkadvisors/new_localai"


def test_job_summary_phases():
    base = {"metadata": {"name": "m"}, "spec": {"template": {"spec": {"containers": []}}}}
    assert launcher.job_summary({**base, "status": {"active": 1}})["phase"] == "running"
    assert launcher.job_summary({**base, "status": {"failed": 1}})["phase"] == "failed"
    assert launcher.job_summary({**base, "status": {}})["phase"] == "pending"
    # A finished Job is not a success until the ledger says shipped.
    done = launcher.job_summary({**base, "status": {"succeeded": 1}})
    assert done["phase"] == "completed" and "not a success" in done["note"]


def test_job_summary_tells_the_ledgers_truth():
    base = {"metadata": {"name": "mission-20260905-160823"}, "spec": {"template": {"spec": {"containers": []}}},
            "status": {"succeeded": 1}}
    halted = launcher.job_summary(base, {"outcome": "halted", "halt": {"stage": "implement", "reason": "implementer made no commit"}})
    assert halted["phase"] == "halted" and halted["halt"]["stage"] == "implement"
    shipped = launcher.job_summary(base, {"outcome": "shipped", "pr_url": "https://github.com/ctkadvisors/kagent/pull/24"})
    assert shipped["phase"] == "shipped" and shipped["pr_url"].endswith("/24")


def test_fleet_serves_repos_and_the_reviewers_policy(monkeypatch):
    monkeypatch.setattr(launcher.ledger, "kv_get", lambda k: {"merges_on_its_own": True} if k == "review_policy" else None)
    f = launcher.fleet()
    assert f["repos"] == ["ctkadvisors/kagent", "ctkadvisors/new_localai"]
    assert f["review"]["merges_on_its_own"] is True
    monkeypatch.setattr(launcher.ledger, "kv_get", lambda k: (_ for _ in ()).throw(RuntimeError("down")))
    assert "ledger unavailable" in launcher.fleet()["review"]["note"]


def test_health_is_computed_from_the_ledger_not_narrated(monkeypatch):
    kv = {"last_observation": {"at": 1788822600.0, "eligible": False, "budget": "3/3", "signals": {"spark": "ok"}},
          "self_health": {"failed_last_hour": 0}, "pause": {"until": 0, "why": "old"}, "canary": {"at": 1.0}}
    monkeypatch.setattr(launcher.ledger, "kv_get", lambda k: kv.get(k))
    monkeypatch.setattr(launcher.ledger, "unfinished_runs", lambda: [{"id": "mission-x"}])
    monkeypatch.setattr(launcher.ledger, "recent_runs", lambda n: [{"id": "improve-1", "repo": "o/r", "outcome": "halted", "halt": {"reason": "no candidates"}, "pr_url": None}])
    monkeypatch.setattr(launcher, "api", lambda m, p, b=None: {"items": [{"metadata": {"name": "dead"}, "status": {"failed": 1}}, {"metadata": {"name": "live"}, "status": {"active": 1}}]})
    h = launcher.health()
    assert h["scheduler"]["eligible"] is False and h["scheduler"]["signals"] == {"spark": "ok"}
    assert h["own_failed_pods_last_hour"] == 0 and h["paused"] is None and h["model_degenerate_seen_at"] is None
    assert h["runs_in_flight"] == ["mission-x"] and h["last_runs"][0]["halt"] == "no candidates"
    assert h["failed_jobs"] == ["dead"]
    assert h["summary"] == "Fleet health: 1 failed Job(s): dead. Of the last 1 runs, 0 shipped, 1 halted (no candidates). 1 run(s) in flight: mission-x."
    clean = {"paused": None, "model_degenerate_seen_at": None, "own_failed_pods_last_hour": 0, "failed_jobs": [], "runs_in_flight": [],
             "last_runs": [{"outcome": "shipped"}, {"outcome": "shipped"}, {"outcome": "halted", "halt": "implementer wrote no 03-implementation.md"}]}
    assert launcher.summarize(clean) == ("Fleet health: nothing is broken. Of the last 3 runs, 2 shipped, "
                                         "1 halted (implementer wrote no 03-implementation.md).")
    clean["memory"] = {"rows": 29, "fleet_written_recent": 3, "days": 7}
    assert launcher.summarize(clean).endswith(" Memory: 29 rows, 3 written by the fleet itself in the last 7 days.")
    clean["memory"].update({"halt_lessons": 4, "repeated_after_lesson": 0})
    assert launcher.summarize(clean).endswith("in the last 7 days; 4 halt lesson(s), 0 repeated after.")
    monkeypatch.setattr(launcher.ledger, "kv_get", lambda k: (_ for _ in ()).throw(RuntimeError("down")))
    assert "ledger unavailable" in launcher.health()["note"]


def test_health_carries_idea_stats_and_the_summary_counts_them(monkeypatch):
    # 2026-09-10 idea lineage: yield and shipped rate are measures, computed, never narrated.
    from fleet import ideas
    kv = {"last_observation": {}, "self_health": {}, "pause": {}, "canary": {}}
    monkeypatch.setattr(launcher.ledger, "kv_get", lambda k: kv.get(k))
    monkeypatch.setattr(launcher.ledger, "unfinished_runs", lambda: [])
    monkeypatch.setattr(launcher.ledger, "recent_runs", lambda n: [])
    monkeypatch.setattr(launcher, "api", lambda m, p, b=None: {"items": []})
    stats = {"by_status": {"active": 4, "historical": 2, "shipped": 1, "failed": 1, "attempted": 2}, "recent": 3, "days": 7, "links": 11,
             "evidence_cited": 3, "shipped_rate": 0.25}
    monkeypatch.setattr(ideas, "stats", lambda days=7: stats)
    h = launcher.health()
    assert h["ideas"] is stats
    assert h["summary"].endswith(" Ideas: 4 active, 3 new in 7 days, 1 shipped of 4 attempted; 11 links.")
    monkeypatch.setattr(ideas, "stats", lambda days=7: (_ for _ in ()).throw(RuntimeError("no db")))
    h = launcher.health()
    assert h["ideas"] == {"note": "unavailable (RuntimeError)"} and "Ideas:" not in h["summary"]


def test_fleet_carries_the_active_archive_trimmed(monkeypatch):
    from fleet import ideas, memory
    monkeypatch.setattr(launcher.ledger, "kv_get", lambda k: None)
    monkeypatch.setattr(launcher.github, "repos_from_env", lambda: ["o/r"], raising=False)
    monkeypatch.setattr(memory, "recall", lambda repo, ctx, limit=12: "")
    seen = []
    row = {"id": "abc", "lineage": "abc", "parent": None, "problem": "p", "mechanism": "m", "effect": "e", "status": "active",
           "source": "ideator", "scores": {"soundness": 70}, "children": 0, "created_at": "x", "repo": None}
    monkeypatch.setattr(ideas, "rows", lambda repo, statuses, limit: seen.append((repo, statuses, limit)) or [row])
    out = launcher.fleet("hi")
    assert seen == [(None, ("active",), 10)]
    assert out["ideas"] == {"active": [{"id": "abc", "lineage": "abc", "parent": None, "problem": "p", "effect": "e", "status": "active",
                                        "source": "ideator", "scores": {"soundness": 70}}]}


def test_admit_refuses_a_running_or_spent_candidate(monkeypatch):
    # new_localai#5 launched seven times in one night: the dedupe was a GitHub
    # comment posted after the launch, and it failed six times. The ledger decides now.
    calls = []
    class L:
        def __init__(self, n, running): self.n, self.running = n, running
        mission_candidate = staticmethod(lambda repo, brief: ("fp5", "collect evidence", "https://github.com/o/r/issues/5"))
        def attempts(self, fp): return self.n, self.running
        def park(self, fp): calls.append(("state", fp, "declined"))
        def upsert_candidate(self, *a, **k): calls.append(("candidate", a[0]))
    class GH:
        def api(self, path, data=None, method=None, **kw): calls.append((method or "POST", path, data)); return {}
    monkeypatch.setattr(launcher, "github", GH())
    monkeypatch.setattr(launcher, "ledger", L(0, None))
    assert launcher.admit("o/r", "GitHub issue https://github.com/o/r/issues/5 — collect evidence\n\nbody") == ("fp5", None)
    assert ("candidate", "fp5") in calls
    monkeypatch.setattr(launcher, "ledger", L(1, "mission-20260904-1"))
    assert "already running" in launcher.admit("o/r", "x" * 20)[1]
    calls.clear()
    monkeypatch.setattr(launcher, "ledger", L(3, None))
    assert "parked" in launcher.admit("o/r", "x" * 20)[1]
    assert ("state", "fp5", "declined") in calls
    assert ("DELETE", "/repos/o/r/issues/5/labels/mission", None) in calls
    assert any(c[1] == "/repos/o/r/issues/5/labels" and "fleet:declined" in c[2]["labels"] for c in calls)


def test_admit_lets_a_human_retry_past_the_cap(monkeypatch):
    class L:
        mission_candidate = staticmethod(lambda repo, brief: ("fp5", "t", None))
        def attempts(self, fp): return 7, None
        def park(self, fp): raise AssertionError("a human retry must not park")
        def upsert_candidate(self, *a, **k): pass
    monkeypatch.setattr(launcher, "ledger", L())
    assert launcher.admit("o/r", "x" * 20, human=True) == ("fp5", None)


def test_health_relays_egress_from_the_scheduler(monkeypatch):
    kv = {"egress": {"elitemini2": {"ok": False, "detail": "curl: (28) timed out", "at": 1.0}}}
    monkeypatch.setattr(launcher.ledger, "kv_get", lambda k: kv.get(k))
    monkeypatch.setattr(launcher.ledger, "unfinished_runs", lambda: [])
    monkeypatch.setattr(launcher.ledger, "recent_runs", lambda n: [])
    monkeypatch.setattr(launcher, "api", lambda m, p, b=None: {"items": []})
    h = launcher.health()
    assert h["egress"] == {"elitemini2": {"ok": False, "detail": "curl: (28) timed out"}}
    assert h["summary"] == "Fleet health: elitemini2 cannot reach GitHub (curl: (28) timed out). No runs recorded."
    kv["egress"] = {"elitemini2": {"ok": None, "detail": "node runner unreachable"}}
    assert launcher.health()["summary"].startswith("Fleet health: the egress check for elitemini2 did not run (node runner unreachable).")


def test_remember_posts_a_rule_as_chris_and_rejects_junk(monkeypatch):
    import pytest
    posted = []
    monkeypatch.setattr(launcher.ledger, "post", lambda author, body, **kw: posted.append((author, body, kw)) or 7)
    out = launcher.remember({"text": "  never delete a fleet job\n on an unchecked clock ", "ref": "telegram"})
    assert out == {"ok": True, "post": 7, "text": "never delete a fleet job on an unchecked clock"}
    assert posted == [("chris", "never delete a fleet job on an unchecked clock", {"topic": "note", "ref": "telegram"})]
    with pytest.raises(ValueError):
        launcher.remember({"text": "ok"})


def test_fleet_recalls_memory_for_the_message(monkeypatch):
    from fleet import memory
    seen = []
    monkeypatch.setattr(launcher.ledger, "kv_get", lambda k: None)
    monkeypatch.setattr(launcher.github, "repos_from_env", lambda: ["o/r"], raising=False)
    monkeypatch.setattr(memory, "recall", lambda repo, ctx, limit=12: seen.append(ctx) or "RULES")
    out = launcher.fleet("what does refresh first mean")
    assert out["memory"] == "RULES" and seen == ["what does refresh first mean"]


def test_a_brief_that_is_an_idea_tag_expands_from_the_archive(monkeypatch):
    from fleet import ideas
    monkeypatch.setattr(launcher, "allowed_repos", lambda: ["o/r", "o/other"])
    monkeypatch.setattr(ideas, "get", lambda iid: {"id": iid, "repo": "o/other", "problem": "Runs halt at test with no log", "mechanism": "capture stderr",
                                                    "assumptions": "the stage writes to stderr", "effect": "the halt issue carries the log"} if iid == "ea8179ef1b6d" else None)
    brief, repo = launcher.validate({"brief": "[idea:ea8179ef1b6d]", "repo": "o/r"})
    assert repo == "o/other" and brief.startswith("[idea:ea8179ef1b6d] Runs halt at test with no log How: capture stderr Assumptions:") and brief.endswith("Done when: the halt issue carries the log")
    import pytest
    with pytest.raises(ValueError):
        launcher.validate({"brief": "[idea:000000000000]", "repo": "o/r"})
