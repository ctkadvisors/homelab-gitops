"""publish never pages token salad: a degenerate model tail is named, not shown."""

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import publish  # noqa: E402

SALAD = ("高地Poly sp sp sp-rad务美国马-健康-务 sp-公司** sp sp sp --/公司/ sp sp客 poly poly sp- poly-chi sp法律公司-公司美国 "
         "Poly.公司 /美国 /\" sp unct- sp-/中国 - Ki poly- poly- \" sp sp客- poly sp sp sp sp 美国 Poly- poly- sp Poly + sp sp")
REPEATS = " ".join(["sp"] * 60 + ["poly"] * 20)
PROSE = ("validate implement: STOP — implementer wrote no 03-implementation.md. The model explained that the brief asked "
         "for a change in a file that does not exist in this repository, listed the three files it inspected, and stopped.")


def test_degenerate_tails_are_named_not_shown():
    assert publish.degenerate(SALAD) and publish.degenerate(REPEATS)
    assert not publish.degenerate(PROSE) and not publish.degenerate("short")
    assert "token salad" in publish.clean_tail(SALAD) and publish.clean_tail(PROSE) == PROSE


def test_a_ship_closes_halt_issues_filed_before_the_run(monkeypatch):
    calls = []
    issues = [{"number": 75, "created_at": "2026-09-09T01:54:15Z", "comments_url": "c75"},
              {"number": 80, "created_at": "2026-09-09T16:50:00Z", "comments_url": "c80"},   # filed after this run began
              {"number": 81, "created_at": "2026-09-09T01:00:00Z", "comments_url": "c81", "pull_request": {"url": "p"}}]
    monkeypatch.setattr(publish.github, "api", lambda path, data=None, method=None, **k: calls.append((path, method)) or issues)
    timing = {"investigate": {"status": "ok", "seconds": 300, "at": "2026-09-09T16:45:00Z"}, "implement": {"status": "ok", "seconds": 60, "at": "2026-09-09T16:55:00Z"}}
    assert publish.run_started_at(timing) == "2026-09-09T16:40:00Z"
    assert publish.close_stale_halts("https://github.com/o/r/pull/1", publish.run_started_at(timing)) == [75]
    assert ("c75", None) in calls and any(p.endswith("/issues/75") and m == "PATCH" for p, m in calls)
    assert publish.close_stale_halts("u", publish.run_started_at(None)) == []   # unknown start closes nothing


def fake_ideas(monkeypatch):
    """publish.ideas without a DB: the primitives record their calls; outcome() stays real."""
    calls = []
    for name in ("set_status", "link", "reinforce"):
        monkeypatch.setattr(publish.ideas, name, lambda *a, _n=name, **k: calls.append((_n, a, k)))
    return calls


def quiet_publish(tmp_path, monkeypatch, pr_url):
    """main() with every side channel stubbed: the pipeline dir, ledger, brain, forum, Telegram, GitHub."""
    import json
    monkeypatch.setattr(publish, "P", str(tmp_path))
    monkeypatch.setenv("RUN_ID", "improve-1")
    json.dump({"candidates": [{"id": "C1", "claim": "dedupe halts", "evidence": "[idea:0123456789ab] forum post 7"}]}, open(tmp_path / "01-findings.json", "w"))
    json.dump({"selected": "C1", "selection_reasoning": "verified"}, open(tmp_path / "02-verdict.json", "w"))
    monkeypatch.setattr(publish, "review_round_unchanged", lambda: False)
    monkeypatch.setattr(publish, "open_pr", lambda trace, gh=None: pr_url)
    monkeypatch.setattr(publish, "close_stale_halts", lambda *a: [])
    monkeypatch.setattr(publish, "file_halt_issue", lambda *a: "repeat")
    for name in ("upsert_candidate", "finish_run", "set_state", "say"):
        monkeypatch.setattr(publish.ledger, name, lambda *a, **k: None)
    monkeypatch.setattr(publish.brain, "add_episode", lambda *a, **k: None)
    monkeypatch.setattr(publish.telegram, "send", lambda *a, **k: None)
    return fake_ideas(monkeypatch)


def test_a_ship_closes_the_idea_shipped_and_reinforces_the_path(tmp_path, monkeypatch):
    pr = "https://github.com/o/r/pull/9"
    calls = quiet_publish(tmp_path, monkeypatch, pr)
    evidence = []
    monkeypatch.setattr(publish.ledger, "upsert_candidate", lambda *a, **k: evidence.append(k.get("evidence")))
    publish.main()
    assert evidence == [{"idea_id": "0123456789ab"}]                       # the candidate row carries the id
    assert ("set_status", ("0123456789ab", "attempted"), {"run_id": "improve-1"}) in calls
    assert ("link", ("idea:0123456789ab", "run:improve-1", "attempt"), {}) in calls
    assert ("set_status", ("0123456789ab", "shipped"), {"pr_url": pr, "run_id": "improve-1"}) in calls
    assert ("link", ("run:improve-1", f"pr:{pr}", "outcome"), {}) in calls
    assert calls[-1] == ("reinforce", (f"pr:{pr}", 1.0), {})


def test_a_halt_closes_the_idea_failed_with_the_reason(tmp_path, monkeypatch):
    import json
    calls = quiet_publish(tmp_path, monkeypatch, None)
    json.dump({"stage": "implement", "reason": "dsh timeout after 3600s" + "x" * 200, "exit_code": 124}, open(tmp_path / "stop", "w"))
    publish.main()
    failed = [c for c in calls if c[0] == "set_status" and c[1][1] == "failed"]
    assert failed and failed[0][2]["run_id"] == "improve-1"
    assert failed[0][2]["reason"].startswith("implement: dsh timeout") and len(failed[0][2]["reason"]) == len("implement: ") + 120
    assert ("link", ("idea:0123456789ab", "run:improve-1", "attempt"), {}) in calls
    assert calls[-1] == ("reinforce", ("run:improve-1", -0.5), {})
    assert not any(c[0] == "link" and c[1][2] == "outcome" for c in calls)


def test_a_review_round_leaves_the_idea_alone(tmp_path, monkeypatch):
    calls = quiet_publish(tmp_path, monkeypatch, "https://github.com/o/r/pull/9")
    monkeypatch.setenv("RUN_TRIGGER", "review")
    publish.main()
    assert calls == []


def test_used_lessons_are_linked_to_the_run_and_weigh_more(monkeypatch, tmp_path):
    from fleet import memory
    touched, linked = [], []
    monkeypatch.setattr(memory, "find", lambda used, repo=None: "k1" if used.startswith("judge by HEAD") else None)
    monkeypatch.setattr(memory, "touch", lambda k: touched.append(k))
    monkeypatch.setattr(publish.ideas, "link", lambda src, dst, kind, weight=1.0: linked.append((src, dst, kind)))
    monkeypatch.setattr(publish, "run_id", lambda: "improve-9")
    report = "USED: judge by HEAD not by the diff\nUSED: something unknown\nLESSON: fixtures need a bare origin\n"
    for used in memory.used_in(report)[:8]:
        k = memory.find(used, "o/r")
        if k:
            memory.touch(k); publish.ideas.link(f"lesson:{k}", f"run:{publish.run_id()}", "informed")
    assert touched == ["k1"] and linked == [("lesson:k1", "run:improve-9", "informed")]


def test_candidate_fingerprint_is_the_finding_not_its_slot(tmp_path, monkeypatch):
    """Every investigator names its first candidate C1; two different findings must not share a fingerprint."""
    import json
    monkeypatch.setattr(publish, "P", str(tmp_path))
    monkeypatch.setattr(publish, "BRIEF", "")
    json.dump({"candidates": [{"id": "C1", "file": "a.py", "claim": "guard the prefix"}]}, open(tmp_path / "01-findings.json", "w"))
    fp1, title1, _ = publish.candidate({"selected": "C1"})
    json.dump({"candidates": [{"id": "C1", "file": "b.sh", "claim": "parenthesize find"}]}, open(tmp_path / "01-findings.json", "w"))
    fp2, title2, _ = publish.candidate({"selected": "C1"})
    assert fp1 != fp2 and title1 == "a.py: guard the prefix" and title2 == "b.sh: parenthesize find"
    (tmp_path / "01-findings.json").unlink()
    assert publish.candidate({"selected": "C1"})[1] == "C1"          # no findings file: the slot, as before
    assert publish.candidate({}) == (None, None, None)


def test_pipeline_run_evidence_leads_the_trace(tmp_path, monkeypatch):
    monkeypatch.setattr(publish, "P", str(tmp_path))
    monkeypatch.setattr(publish, "BRIEF", "")
    assert "Pipeline-run evidence" not in publish.build_trace(None)
    (tmp_path / "verify.sh").write_text("npx jest x.test.ts")
    (tmp_path / "verify.out").write_text("junk\n" * 1000 + "Tests: 9 passed\n")
    (tmp_path / "verify.rc").write_text("0\n")
    trace = publish.build_trace(None)
    head = trace[:2000]                                              # what the reviewer reads
    assert "Pipeline-run evidence" in head and "exit 0" in head and "Tests: 9 passed" in head and "npx jest" in head
    assert trace.index("Pipeline-run evidence") < trace.index("### 01 findings")


def test_a_halt_files_its_issue_and_does_not_page(tmp_path, monkeypatch):
    import json
    calls = quiet_publish(tmp_path, monkeypatch, None)
    paged = []
    monkeypatch.setattr(publish.telegram, "send", lambda *a, **k: paged.append(a))
    monkeypatch.setattr(publish, "file_halt_issue", lambda *a: "new")
    json.dump({"stage": "test", "reason": "artifact 04-test-report.json missing", "exit_code": 0, "log_tail": "No request has been provided yet."},
              open(tmp_path / "stop", "w"))
    publish.main()
    assert paged == []
