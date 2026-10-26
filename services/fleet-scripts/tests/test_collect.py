"""Deterministic checks for the evidence collector (improve-daily's collect
stage, new_localai#5). Runs with the rest of the fleet-suite:
`python3 -m pytest services/fleet-scripts`."""

import datetime
import json
import pathlib
import sys
import urllib.error

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import collect  # noqa: E402
from fleet import github  # noqa: E402


class FakeGitHub:
    """The pieces of fleet/github that collect uses, driven by in-memory
    fixtures so the collector's four sources are exercised without the
    network and without touching a real App token."""

    def __init__(self, repos, issues, prs, comments):
        self._repos = repos
        self._issues = issues   # (repo, label) -> list of issue dicts
        self._prs = prs         # repo -> list of PR dicts
        self._comments = comments  # comments_url -> list of comment dicts

    def api(self, path, **kw):
        from urllib.parse import urlparse, parse_qs
        if path.startswith("/installation/repositories"):
            return {"total_count": len(self._repos),
                    "repositories": [{"full_name": r} for r in self._repos]}
        if path.startswith("/repos/"):
            rest = path[len("/repos/"):]
            repo, _, query = rest.partition("?")
            repo = "/".join(repo.split("/")[0:2])  # "o/r/issues?..." -> "o/r"
            if "/issues?" in rest:
                labels = parse_qs(query).get("labels", [None])[0]
                for key, items in self._issues.items():
                    if key == (repo, labels):
                        return items
                return []
            if "/pulls?" in rest:
                return self._prs.get(repo, [])
            for url, pr in self._prs.items():
                if url.startswith(f"/repos/{repo}/pulls/"):
                    return pr
            return {}
        # a PR's comments endpoint, queried with ?per_page=...
        base = path.split("?", 1)[0]
        if any(c == base for c in self._comments):
            return self._comments[base]
        return {}

    def push_url(self, repo):
        return f"https://x-access-token:t@github.com/{repo}.git"


def install(fake_github, monkeypatch):
    monkeypatch.setattr(github, "api", fake_github.api)
    monkeypatch.setattr(github, "installation_repos", lambda: list(fake_github._repos))
    monkeypatch.setattr(github, "repos_from_env", lambda var="REPOS": list(fake_github._repos))


def test_workbench_groups_by_error_and_counts(monkeypatch):
    class FakeResp:
        def __init__(self, body): self._b = body
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return json.dumps(self._b).encode()
    payload = {
        "items": [
            {"name": "t1", "error": "timeout", "targetAgent": "concierge",
             "createdAt": "2026-09-03T10:00:00Z", "completedAt": "2026-09-03T10:05:00Z"},
            {"name": "t2", "error": "timeout", "targetAgent": "concierge",
             "createdAt": "2026-09-03T11:00:00Z", "completedAt": "2026-09-03T11:05:00Z"},
            {"name": "t3", "error": "500", "targetAgent": "builder-shell",
             "createdAt": "2026-09-03T09:00:00Z", "completedAt": "2026-09-03T09:01:00Z"},
        ]
    }

    def fake_urlopen(url, timeout=None):
        expected_since = (datetime.datetime.now(datetime.timezone.utc)
                          - datetime.timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
        assert "phase=Failed" in url and url.endswith(f"since={expected_since}")
        return FakeResp(payload)

    monkeypatch.setattr(collect.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(collect, "WORKBENCH_URL", "http://workbench")
    items, note = collect.collect_workbench()
    assert note is None
    assert len(items) == 2
    # the two "timeout" failures rank above the lone 500
    assert items[0]["error"] == "timeout" and items[0]["count"] == 2
    assert items[0]["tasks"][0]["name"] == "t2"  # newest first
    assert items[1]["error"] == "500" and items[1]["count"] == 1


def test_workbench_unreachable_yields_nothing(monkeypatch):
    def boom(_url, timeout=None, **kw):
        raise urllib.error.URLError("refused")
    monkeypatch.setattr(collect.urllib.request, "urlopen", boom)
    monkeypatch.setattr(collect, "WORKBENCH_URL", "http://workbench")
    items, note = collect.collect_workbench()
    assert items == [] and "workbench unreachable" in note


def test_fleet_issues_across_repos_and_labels(monkeypatch):
    issues = {
        ("ctkadvisors/new_localai", "fleet:halt"): [
            {"number": 17, "title": "own halt", "html_url": "http://h17"},
        ],
        ("ctkadvisors/new_localai", "fleet:proposal"): [
            {"number": 21, "title": "a proposal", "html_url": "http://h21"},
        ],
    }
    gh = FakeGitHub(["ctkadvisors/new_localai"], issues, {}, {})
    install(gh, monkeypatch)
    items, note = collect.collect_fleet_issues()
    assert note is None
    nums = {(i["number"], i["source"]) for i in items}
    assert (17, "halt") in nums and (21, "proposal") in nums


def test_reviewer_feedback_only_agent_prs_with_feedback(monkeypatch):
    prs = {
        "ctkadvisors/new_localai": [
            {"number": 5, "head": {"ref": "agent/fix-timeout"},
             "comments_url": "http://c5"},
            {"number": 6, "head": {"ref": "feature/x"},  # not agent/* -> skipped
             "comments_url": "http://c6"},
        ],
    }
    comments = {
        "http://c5": [
            {"body": "please reproduce on the spark", "user": {"login": "a"}},
            {"body": "nice, merge it", "user": {"login": "b"}},  # no pointer -> skip
        ],
        "http://c6": [
            {"body": "needs docs", "user": {"login": "c"}},
        ],
    }
    gh = FakeGitHub(["ctkadvisors/new_localai"], {}, prs, comments)
    install(gh, monkeypatch)
    items, note = collect.collect_reviewer_feedback()
    assert note is None
    assert len(items) == 1 and items[0]["number"] == 5
    assert items[0]["head"] == "agent/fix-timeout"


def test_fleet_issues_no_prs_leaked(monkeypatch):
    # a PR is an object with a "pull_request" key in the issues endpoint; it
    # must never appear in the halt/proposal evidence.
    issues = {
        ("o/r", "fleet:halt"): [
            {"number": 1, "title": "real", "html_url": "http://r1"},
            {"number": 2, "pull_request": {"html_url": "http://pr2"}},
        ],
    }
    gh = FakeGitHub(["o/r"], issues, {}, {})
    install(gh, monkeypatch)
    items, _ = collect.collect_fleet_issues()
    assert [i["number"] for i in items] == [1]


def test_main_writes_the_evidence_file(tmp_path, monkeypatch):
    # No ledger (pg8000 not importable in this env) and unreachable workbench
    # must still leave a complete, valid evidence file. A halt issue is fed in
    # so there is something from one source to assert on.
    issues = {("o/r", "fleet:halt"): [{"number": 1, "title": "h", "html_url": "http://h"}]}
    gh = FakeGitHub(["o/r"], issues, {}, {})
    install(gh, monkeypatch)

    def boom(_url, timeout=None, **kw):
        raise urllib.error.URLError("refused")
    monkeypatch.setattr(collect.urllib.request, "urlopen", boom)
    monkeypatch.setattr(collect, "WORKBENCH_URL", "http://workbench")
    monkeypatch.setattr(collect, "PIPELINE_DIR", str(tmp_path))

    collect.main()
    ev = json.load(open(tmp_path / "00-evidence.json"))
    assert set(ev["sources"]) >= {"workbench", "fleet_issues", "ledger_runs", "reviewer_feedback"}
    assert ev["sources"]["fleet_issues"]["count"] == 1
    # recurrences is the flat, ordered list with a source on every item
    assert ev["recurrences"]
    for it in ev["recurrences"]:
        assert it["source"] in ev["sources"]


def test_ledger_runs_come_from_the_run_table(monkeypatch):
    # new_localai#10 shipped kv_like("run:%"), which reads the scheduler table;
    # runs live in `run`. The reviewer flagged it, a doc push made it forget.
    import fleet.ledger as ledger
    rows = [{"id": "mission-1", "pipeline": "mission", "repo": "o/r", "trigger": "triage", "outcome": "halted",
             "fingerprint": "abc", "title": "fix the thing", "state": "halted", "pr_url": None,
             "halt": {"stage": "implement", "reason": "dsh timeout", "log": "..."},
             "started_at": "2026-09-04 03:22:00+00:00", "finished_at": None}]
    monkeypatch.setattr(ledger, "recent_runs", lambda limit: rows)
    monkeypatch.setattr(ledger, "kv_like", lambda pat: (_ for _ in ()).throw(AssertionError("wrong table")))
    out, err = collect.collect_ledger_runs()
    assert err is None and len(out) == 1
    r = out[0]
    assert r["run_id"] == "mission-1" and r["title"] == "fix the thing" and r["state"] == "halted"
    assert r["halt"] == "implement: dsh timeout"          # the bundle's log is not evidence, the reason is
    assert r["started_at"] == "2026-09-04 03:22:00+00:00"


def test_forum_ideas_keep_their_idea_id(monkeypatch):
    # The ideator opens a post with [idea:<id>] (lineage spec, 2026-09-10): the
    # token must survive in the text the investigator reads, and the id rides
    # as its own field so publish can close the loop on the idea.
    import fleet.ledger as ledger
    rows = [{"id": 7, "topic": "idea", "author": "ideator", "body": "[idea:0123456789ab] Make the collector dedupe halts.", "ref": None, "created_at": "2026-09-10"},
            {"id": 8, "topic": "question", "author": "chris", "body": "why did mission 22 OOM?", "ref": None, "created_at": "2026-09-10"}]
    monkeypatch.setattr(ledger, "posts", lambda limit, topic, unanswered: [r for r in rows if r["topic"] == topic])
    items, note = collect.collect_forum()
    assert note is None and [i["idea"] for i in items] == ["0123456789ab", None]
    assert items[0]["text"].startswith("[idea:0123456789ab]")
