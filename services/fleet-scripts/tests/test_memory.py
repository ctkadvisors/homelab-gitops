"""The fleet's memory: rules are always recalled, lessons by relevance, the same
thing learned twice weighs more, a halt distills to one usable line, and a
stage's LESSON: lines are harvested. No Postgres: rows are faked."""

import datetime
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fleet import memory  # noqa: E402


def row(kind, text, repo=None, weight=1, days_old=0.0, ref=None):
    return {"key": memory.key(kind, repo, text), "kind": kind, "repo": repo, "text": text, "ref": ref, "source": "t",
            "weight": weight, "created_at": datetime.datetime.fromtimestamp(time.time() - days_old * 86400, tz=datetime.timezone.utc)}


def test_rules_always_come_first_then_the_relevant_lessons():
    items = [
        row("lesson", "npm ignores resolutions; use overrides in package.json and regenerate the lockfile", "o/todo"),
        row("lesson", "the CRD drift check needs fifteen minutes on the kata runner", "o/kagent", days_old=20),
        row("feedback", "never route inference to the cloud"),
        row("fact", "elitemini2 egress uses source .90; a timeout to github or npm is the node, retry once", days_old=1),
        row("lesson", "lighthouse: the page must render on the server; icon buttons need aria-labels", "o/todo", weight=3),
    ]
    picked = memory.rank(items, "fix npm audit in package.json: resolutions did not take effect", limit=3)
    assert picked[0]["kind"] == "feedback"                       # the rule, whatever the context
    assert "overrides" in picked[1]["text"]                      # most words in common with the task
    assert len(picked) == 4                                      # the rule rides free; limit counts lessons
    text = memory.render(picked)
    assert text.startswith("WHAT WE HAVE LEARNED") and "[feedback, all repos]" in text and "[lesson, o/todo]" in text
    assert memory.render([]) == ""


def test_the_same_lesson_twice_is_one_key_and_a_halt_distills():
    assert memory.key("lesson", "o/r", "  Use overrides,  not resolutions ") == memory.key("lesson", "o/r", "  Use overrides,  not resolutions ")
    assert memory.key("lesson", "o/r", "a") != memory.key("lesson", None, "a")
    line = memory.distill_halt({"stage": "implement", "reason": "implementer wrote no 03-implementation.md",
                                "log_tail": "... I cannot run npm ci. What would unblock me: a writable cache and permission to install."},
                               "GitHub issue https://github.com/o/r/issues/22 — npm audit fails")
    assert line.startswith("A run halted at implement: implementer wrote no 03-implementation.md.")
    assert "Unblock: a writable cache and permission to install" in line and "Task: GitHub issue" in line


def test_lesson_lines_are_harvested_from_a_report():
    # a lesson is a paragraph: it ends at a blank line, a bullet, a heading or the next LESSON
    md = "## Scope\n- LESSON: npm audit --omit=dev is what the security workflow gates on\nLESSON: short\n* LESSON: the lockfile must be regenerated after overrides change\n\nnot a lesson"
    assert memory.lessons_in(md) == ["npm audit --omit=dev is what the security workflow gates on",
                                     "the lockfile must be regenerated after overrides change"]
    wrapped = "LESSON: this node's /bin/sh is dash, which rejects\n  set -o pipefail; write verify.sh for sh\n\nLESSON: on this repo pytest cannot run offline, so\nuse unittest\n- next bullet"
    assert memory.lessons_in(wrapped) == ["this node's /bin/sh is dash, which rejects set -o pipefail; write verify.sh for sh",
                                          "on this repo pytest cannot run offline, so use unittest"]


def test_remember_rejects_junk_and_survives_a_dead_ledger(monkeypatch):
    assert memory.remember("opinion", "x") is None and memory.remember("lesson", "   ") is None
    monkeypatch.setattr(memory.ledger, "connect", lambda: (_ for _ in ()).throw(RuntimeError("down")))
    assert memory.remember("lesson", "something real", repo="o/r") is None   # logged, not raised
    assert memory.recall("o/r", "anything") == ""                            # a role without memory still runs


def test_stats_counts_what_the_fleet_wrote_itself(monkeypatch):
    from contextlib import contextmanager
    class Cur:
        def execute(self, sql, args=()): self.last = sql
        def fetchall(self): return [("publish", "2026-09-09", "A run halted at adjudicate: dsh session failed.")] if "left(text" in self.last else [("claude", 26), ("implementer", 2), ("publish", 1)]
        def fetchone(self): return (1, 4) if "rep.n" in self.last else (3,)   # 4 halt lessons, 1 halt repeated after its lesson
    class Conn:
        def cursor(self): return Cur()
    @contextmanager
    def connect():
        yield Conn()
    monkeypatch.setattr(memory.ledger, "connect", connect)
    assert memory.stats() == {"rows": 29, "by_source": {"claude": 26, "implementer": 2, "publish": 1}, "fleet_written_recent": 3, "days": 7,
                              "halt_lessons": 4, "repeated_after_lesson": 1,
                              "recent": [{"source": "publish", "at": "2026-09-09", "text": "A run halted at adjudicate: dsh session failed."}]}


def test_used_lines_find_their_row_and_touch_it(monkeypatch):
    md = "## Scope\n- USED: A run that pushes to the fixture origin looks like no commit; judge by HEAD\nUSED: nothing matches this\n"
    assert memory.used_in(md) == ["A run that pushes to the fixture origin looks like no commit; judge by HEAD", "nothing matches this"]
    monkeypatch.setattr(memory, "rows", lambda repo=None, limit=400: [{"key": "k1", "text": "A run that pushes to the fixture origin looks like no commit. Judge by HEAD."}])
    assert memory.find("a run that PUSHES to the fixture origin looks like no commit", "o/r") == "k1"
    assert memory.find("nothing matches this") is None
    from contextlib import contextmanager
    seen = []
    class Cur:
        def execute(self, sql, args=()): seen.append((sql[:40], args))
    class Conn:
        def cursor(self): return Cur()
    @contextmanager
    def connect():
        yield Conn()
    monkeypatch.setattr(memory.ledger, "connect", connect)
    memory.touch("k1")
    assert seen == [("UPDATE lesson SET weight = weight + 1, u", ("k1",))]
