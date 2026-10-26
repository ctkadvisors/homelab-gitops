"""Lineage, forks and links: the parts that decide what the fleet grows from."""
import os
import random
import sys
from contextlib import contextmanager

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from fleet import experience, ideas  # noqa: E402


class Cur:
    def __init__(self, log, answers):
        self.log, self.answers, self.description = log, answers, [("x",)]
    def execute(self, sql, args=()):
        self.log.append((" ".join(sql.split())[:60], tuple(args)))
    def fetchone(self):
        return self.answers.pop(0) if self.answers else None
    def fetchall(self):
        return self.answers.pop(0) if self.answers else []


def fake_connect(monkeypatch, answers=None):
    log = []
    class Conn:
        def cursor(self): return Cur(log, answers if answers is not None else [])
    @contextmanager
    def connect():
        yield Conn()
    monkeypatch.setattr(ideas.ledger, "connect", connect)
    monkeypatch.setattr(ideas, "_ready", True)
    return log


def test_quality_and_parent_weight_prefer_good_ideas_with_few_children():
    good = {"scores": {"non_obviousness": 80, "soundness": 70, "clarity": 70}, "children": 0, "status": "active"}
    same_but_busy = {**good, "children": 3}
    weak = {"scores": {"non_obviousness": 30, "soundness": 40, "clarity": 50}, "children": 0, "status": "active"}
    shipped = {**good, "status": "shipped"}
    assert ideas.score_of(good["scores"]) == 72.0
    assert ideas.parent_weight(good) > ideas.parent_weight(same_but_busy) > 0
    assert ideas.parent_weight(good) > ideas.parent_weight(weak) >= 0.05      # never zero: every line stays alive
    assert ideas.parent_weight(shipped) > ideas.parent_weight(good)
    picks = [ideas.sample_parent([good, weak], random.Random(i))["scores"]["non_obviousness"] for i in range(40)]
    assert picks.count(80) > picks.count(30) > 0                             # weighted, not winner-take-all
    assert ideas.sample_parent([]) is None


def test_add_forks_into_the_parents_lineage_and_links_evidence(monkeypatch):
    log = fake_connect(monkeypatch, answers=[("root123",)])
    iid = ideas.add({"problem": "halts repeat at adjudicate", "mechanism": "guard the judge call", "effect": "0 repeats"},
                    repo="o/r", source="ideator", parent="p1", evidence=["run:improve-1", "lesson:abc"], scores={"non_obviousness": 70})
    assert len(iid) == 12
    sqls = [s for s, _ in log]
    assert any(s.startswith("SELECT lineage FROM idea") for s in sqls)
    insert = next(a for s, a in log if s.startswith("INSERT INTO idea"))
    assert insert[1] == "root123" and insert[2] == "p1"                       # the fork inherits the parent's lineage
    assert insert[-1] == "o/r"                                                 # touches: the origin at least
    links = [a for s, a in log if s.startswith("INSERT INTO link")]
    assert ("idea:p1", f"idea:{iid}") in links and ("run:improve-1", f"idea:{iid}") in links and ("lesson:abc", f"idea:{iid}") in links
    import pytest
    with pytest.raises(ValueError):
        ideas.add({"problem": "", "mechanism": "x"}, None, "ideator")


def test_reinforce_touches_every_link_on_the_path(monkeypatch):
    edges = [("idea:i1", "run:r1", "attempt", 1.0), ("run:h0", "idea:i1", "evidence", 1.0), ("lesson:l0", "idea:i1", "evidence", 2.0)]
    log = fake_connect(monkeypatch, answers=[edges])
    assert ideas.reinforce("run:r1", +1.0) == 3
    updates = [a for s, a in log if s.startswith("UPDATE link")]
    assert len(updates) == 3 and all(a[0] == 1.0 for a in updates)


def test_experience_renders_typed_nodes(monkeypatch):
    monkeypatch.setattr(experience.ledger, "recent_runs", lambda n: [
        {"id": "improve-1", "repo": "o/r", "outcome": "halted", "started_at": "2026-09-10 03:00", "halt": {"stage": "adjudicate", "reason": "dsh session failed"}},
        {"id": "mission-2", "repo": "o/r", "outcome": "shipped", "started_at": "2026-09-10 04:00", "pr_url": "https://x/pull/9", "title": "t"}])
    monkeypatch.setattr(experience.ledger, "posts", lambda **k: [])
    monkeypatch.setattr(experience.ledger, "kv_like", lambda p: [("bench:20260910", {"rows": [{"success": True}, {"success": False}]})])
    from fleet import memory
    monkeypatch.setattr(memory, "rows", lambda limit=60: [{"key": "k1", "kind": "lesson", "repo": "o/r", "source": "dream", "text": "judge by HEAD", "created_at": "2026-09-10"}])
    items = experience.recent()
    ids = [i["id"] for i in items]
    assert ids == ["run:improve-1", "run:mission-2", "lesson:k1", "bench:20260910"]
    text = experience.render(items)
    assert "run:improve-1 [halt" in text and "[dream] judge by HEAD" in text and "1/2 fixtures passed" in text


def test_schema_statements_survive_the_semicolon_split():
    # ensure() splits SCHEMA on ";" like ledger.migrate: a semicolon inside a
    # comment broke the first live run (2026-09-10, "syntax error at end of input").
    stmts = [s.strip() for s in ideas.SCHEMA.split(";") if s.strip()]
    assert len(stmts) == 5 and all(s.startswith(("CREATE ", "ALTER ")) for s in stmts)


def test_brief_for_a_cross_cutting_idea_names_the_other_repos():
    idea = {"id": "abc", "repo": "ctkadvisors/kagent", "problem": "P", "mechanism": "M", "assumptions": "", "effect": "E",
            "touches": "ctkadvisors/kagent,ctkadvisors/new_localai"}
    b = ideas.brief_for(idea)
    assert b.startswith("[idea:abc] P How: M Touches: ctkadvisors/kagent, ctkadvisors/new_localai (this run is in ctkadvisors/kagent") and b.endswith("Done when: E")
    assert "Touches" not in ideas.brief_for({**idea, "touches": "ctkadvisors/kagent"})


def test_missing_paths_names_files_the_repo_never_had():
    """2026-09-14: kagent never had packages/agent-loop/src/stages/; two missions went looking for it."""
    tree = {"packages", "packages/agent-loop", "packages/agent-loop/src", "packages/agent-loop/src/index.ts", "scripts", "scripts/stage.sh"}
    assert ideas.missing_paths("In `packages/agent-loop/src/stages/implement.ts`, wrap the call.", ["o/k"], tree) == ["packages/agent-loop/src/stages/implement.ts"]
    # an existing file, a new file in an existing folder, and the pod's absolute paths all pass
    assert ideas.missing_paths("scripts/stage.sh, packages/agent-loop/src/new.test.ts and /workspace/p/verify.sh", ["o/k"], tree) == []
    assert ideas.missing_paths("anything/at/all.ts", ["o/k"], set()) == []      # no tree read: fail open
