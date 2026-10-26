# Observed Outcomes PR 1: Claims and the Metric Catalog. Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every fleet launch declares a claim (a catalog metric, a direction, a fleet-computed baseline) that rides on the candidate, the brief and the PR body; the reviewer objects to a fleet PR without one; the console shows claims and the catalog's current values.

**Architecture:** A new `fleet/metrics.py` owns the catalog and all measurement (pure functions over the ledger and GitHub). The ledger grows a `claim` jsonb on `candidate` and a `verdict` table the reviewer writes so acceptance metrics accrue from this PR on. Four launch paths (idea, human brief, review round, improve run) all end in `ledger.set_claim`; `publish` renders `### Claim`; `review` gates on it. Nothing measures "after" yet: that is PR 2.

**Tech Stack:** Python 3 stdlib, pg8000 via `fleet/ledger.py`, pytest with the repo's fake-ledger pattern, sh (`stage.sh`), the existing console's inline JS.

**Spec:** `docs/superpowers/specs/2026-09-16-observed-outcomes-design.md` (sections: Principles, Domain model, Metric catalog v1, Gates that change, Surfacing, Rollout item 1).

## Global Constraints

- Every rule that can be enforced in code is enforced in code; a model is asked only what code cannot answer (spec: Designed for small local models).
- New model prompts grow by at most one line (`CLAIM:` for the implementer, one sentence for the judge).
- The harness is model-agnostic: no rule may depend on the model's capability level (spec principle 7).
- Chris is not paged by anything in this PR.
- All tests run offline: no ledger, no GitHub, no spark. Follow `tests/test_reconcile.py`'s `FakeLedger` monkeypatch pattern.
- Run the whole suite before every commit: `cd services/fleet-scripts && python3 -m pytest -q tests` (184 passing at start).
- Commit messages follow the repo's style: `feat(fleet): ...` / `fix(fleet): ...`, body says why, ends with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- Work on branch `feat/observed-outcomes-pr1-claims` from `main`. Working directory for every command: `services/fleet-scripts` unless stated.
- The PR's own claim (spec Rollout 1): `first_pass_acceptance` on `ctkadvisors/new_localai` does not fall. Put it in the PR body under `### Claim`.

---

## File structure

| file | responsibility |
|---|---|
| `fleet/metrics.py` (new) | The catalog: `Metric` records, `CATALOG`, `measure()`, `claim_for()`, `default_claim()`, `parse_claim_line()`, `claim_line()`, `snapshot()`. Reads the ledger and GitHub; writes nothing. |
| `fleet/ledger.py` | Schema: `candidate.claim JSONB`, table `verdict`. Helpers: `set_claim`, `claim_of`, `claims`, `record_verdict`, `verdicts`, `runs_between`, `merged_between`. |
| `fleet/ideas.py` | `QUINTET` gains `metric`, `direction`; idea table columns; `brief_for` appends the `CLAIM:` line. |
| `scripts/ideate.py` | Quintet shape asks for `metric` and `direction`; an idea with no catalog metric is dropped like one with no evidence. |
| `scripts/launcher.py` | `admit()` stores the claim for every launcher-born mission; `validate()` appends a default `CLAIM:` line to a brief that has none. |
| `scripts/reconcile.py` | `launch()` gives an improve run a default claim (kv `claim:<run>` and env `CLAIM`). |
| `scripts/stage.sh` | Implement SUFFIX carries `CLAIM:` from env when the brief has none. |
| `scripts/publish.py` | `### Claim` section in the PR body; moves an improve run's kv claim onto its candidate. |
| `scripts/review.py` | Deterministic objection for a fleet PR without `### Claim`; writes a `verdict` row after every judgment. |
| `scripts/console.py` | `claims` and `catalog` in `/api/state`; one Claims panel in the page. |
| `tests/test_metrics.py` (new), plus additions to `test_ideate.py`, `test_launcher.py`, `test_publish.py`, `test_console.py`, `test_reconcile.py`, new `tests/test_review_claim.py` | One test per behavior, offline. |

---

### Task 1: Ledger schema and helpers for claims and verdicts

**Files:**
- Modify: `fleet/ledger.py` (SCHEMA string near line 30; helpers after `set_state` near line 182)
- Test: `tests/test_ledger_claims.py` (new)

**Interfaces:**
- Produces:
  - `set_claim(fp: str, claim: dict) -> None`
  - `claim_of(fp: str) -> dict | None`
  - `claims(limit: int = 30) -> list[dict]` rows: `fingerprint, repo, title, state, claim, updated_at`
  - `record_verdict(repo: str, pr_url: str, sha: str, confidence: int, first: bool, merged_bar: int) -> None`
  - `verdicts(repo: str | None, since, until) -> list[dict]` rows: `repo, pr_url, sha, confidence, first, merged_bar, at`
  - `runs_between(since, until, repo: str | None = None) -> list[dict]` rows: `id, repo, outcome, halt, timing, trigger, pr_url, started_at`
  - `merged_between(repo: str | None, since, until) -> list[dict]` rows: `fingerprint, run_id, pr_url, observed_at` (outcome rows with `obs_window='merge'`)

- [ ] **Step 1: Write the failing test**

The ledger needs Postgres, so this test checks the SQL text and the helper wiring with a fake cursor, the way nothing else in the repo does yet; keep it small.

```python
# tests/test_ledger_claims.py
"""Claims live on the candidate row; verdicts accrue in their own table."""
import json
import pathlib
import sys
from contextlib import contextmanager

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fleet import ledger  # noqa: E402


class Cur:
    def __init__(self, rows=()):
        self.sql, self.params, self.rows = [], [], list(rows)
        self.description = [("fingerprint",), ("repo",), ("title",), ("state",), ("claim",), ("updated_at",)]
    def execute(self, sql, params=None): self.sql.append(" ".join(sql.split())); self.params.append(params)
    def fetchall(self): return self.rows
    def fetchone(self): return self.rows[0] if self.rows else None


def fake_connect(cur):
    @contextmanager
    def connect():
        class C:
            def cursor(self): return cur
        yield C()
    return connect


def test_schema_adds_claim_column_and_verdict_table():
    assert "ALTER TABLE candidate ADD COLUMN IF NOT EXISTS claim JSONB" in ledger.SCHEMA
    assert "CREATE TABLE IF NOT EXISTS verdict" in ledger.SCHEMA


def test_set_claim_and_record_verdict_write_the_right_rows(monkeypatch):
    cur = Cur()
    monkeypatch.setattr(ledger, "connect", fake_connect(cur))
    ledger.set_claim("fpA", {"metric": "halt_rate_by_class", "direction": "down"})
    ledger.record_verdict("o/r", "https://github.com/o/r/pull/1", "abc", 72, True, 85)
    assert "UPDATE candidate SET claim=%s" in cur.sql[0] and json.loads(cur.params[0][0])["metric"] == "halt_rate_by_class"
    assert "INSERT INTO verdict" in cur.sql[1] and cur.params[1][3] == 72 and cur.params[1][4] is True


def test_claims_returns_dict_rows(monkeypatch):
    cur = Cur(rows=[("fpA", "o/r", "t", "tested", {"metric": "recurrence"}, None)])
    monkeypatch.setattr(ledger, "connect", fake_connect(cur))
    rows = ledger.claims(5)
    assert rows[0]["fingerprint"] == "fpA" and rows[0]["claim"]["metric"] == "recurrence"
    assert "WHERE c.claim IS NOT NULL" in cur.sql[0]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest -q tests/test_ledger_claims.py`
Expected: FAIL with `AttributeError: module 'fleet.ledger' has no attribute 'set_claim'` (and the SCHEMA assertion).

- [ ] **Step 3: Add the schema statements**

In `fleet/ledger.py`, inside the `SCHEMA` string, after the `lesson` table's statements (end of the string), append:

```sql
ALTER TABLE candidate ADD COLUMN IF NOT EXISTS claim JSONB;
CREATE TABLE IF NOT EXISTS verdict (
  id           BIGSERIAL PRIMARY KEY,
  repo         TEXT NOT NULL,
  pr_url       TEXT NOT NULL,
  sha          TEXT NOT NULL,
  confidence   SMALLINT NOT NULL,
  first        BOOLEAN NOT NULL,           -- the PR's first judgment (no prior objection)
  merged_bar   SMALLINT NOT NULL,          -- MERGE_MIN at the time, so first-pass acceptance is computed against the bar that applied
  at           TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS verdict_repo_at_idx ON verdict(repo, at DESC);
```

`migrate()` splits on `;` and runs each statement, so both are idempotent on every start.

- [ ] **Step 4: Add the helpers**

After `set_state` in `fleet/ledger.py`:

```python
def set_claim(fp: str, claim: dict) -> None:
    """The claim a launch made about this candidate (fleet/metrics.py builds it)."""
    with connect() as c:
        c.cursor().execute("UPDATE candidate SET claim=%s, updated_at=now() WHERE fingerprint=%s", (json.dumps(claim), fp))


def claim_of(fp: str) -> dict | None:
    with connect() as c:
        cur = c.cursor()
        cur.execute("SELECT claim FROM candidate WHERE fingerprint=%s", (fp,))
        row = cur.fetchone()
        return row[0] if row and row[0] else None


def claims(limit: int = 30) -> list[dict]:
    """Candidates that declared a claim, newest first: the console's Claims panel."""
    with connect() as c:
        cur = c.cursor()
        cur.execute("SELECT c.fingerprint, c.repo, c.title, c.state, c.claim, c.updated_at FROM candidate c "
                    "WHERE c.claim IS NOT NULL ORDER BY c.updated_at DESC LIMIT %s", (limit,))
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def record_verdict(repo: str, pr_url: str, sha: str, confidence: int, first: bool, merged_bar: int) -> None:
    """Every judgment the reviewer makes, so first_pass_acceptance and
    review_rounds_to_merge (fleet/metrics.py) are computed from history, not
    from the one objection kv that only remembers the latest sha."""
    with connect() as c:
        c.cursor().execute("INSERT INTO verdict (repo, pr_url, sha, confidence, first, merged_bar) VALUES (%s,%s,%s,%s,%s,%s)",
                           (repo, pr_url, sha, int(confidence), bool(first), int(merged_bar)))


def verdicts(repo: str | None, since, until) -> list[dict]:
    with connect() as c:
        cur = c.cursor()
        cur.execute("SELECT repo, pr_url, sha, confidence, first, merged_bar, at FROM verdict "
                    "WHERE (%s::text IS NULL OR repo=%s) AND at >= %s AND at < %s ORDER BY at", (repo, repo, since, until))
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def runs_between(since, until, repo: str | None = None) -> list[dict]:
    with connect() as c:
        cur = c.cursor()
        cur.execute("SELECT id, repo, outcome, halt, timing, trigger, pr_url, started_at FROM run "
                    "WHERE started_at >= %s AND started_at < %s AND (%s::text IS NULL OR repo=%s) ORDER BY started_at",
                    (since, until, repo, repo))
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def merged_between(repo: str | None, since, until) -> list[dict]:
    """Merges recorded by mark_pr('merged'): outcome rows with obs_window='merge'."""
    with connect() as c:
        cur = c.cursor()
        cur.execute("SELECT o.fingerprint, o.run_id, r.pr_url, o.observed_at FROM outcome o JOIN run r ON r.id=o.run_id "
                    "WHERE o.obs_window='merge' AND o.observed_at >= %s AND o.observed_at < %s AND (%s::text IS NULL OR r.repo=%s) "
                    "ORDER BY o.observed_at", (since, until, repo, repo))
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]
```

- [ ] **Step 5: Run tests**

Run: `python3 -m pytest -q tests/test_ledger_claims.py tests` 
Expected: all pass (187).

- [ ] **Step 6: Commit**

```bash
git add fleet/ledger.py tests/test_ledger_claims.py
git commit -m "feat(ledger): claim on the candidate, a verdict table the reviewer fills

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: The metric catalog, version 1

**Files:**
- Create: `fleet/metrics.py`
- Test: `tests/test_metrics.py` (new)

**Interfaces:**
- Consumes: `ledger.runs_between`, `ledger.verdicts`, `ledger.merged_between`, `ledger.posts`, `ledger.kv_like`, `ledger.runs_since`, `github.api` (all monkeypatched in tests).
- Produces:
  - `CATALOG: dict[str, Metric]`; `names() -> list[str]`
  - `Metric(name, kind, direction_good, samples_needed, min_effect, unit, measure)` where `measure(scope: dict, since: float, until: float) -> tuple[float | None, int]`
  - `measure(name: str, scope: dict, since: float, until: float) -> tuple[float | None, int]`
  - `claim_for(metric: str, direction: str, scope: dict, now: float, lookback_days: int = 7) -> dict` (the spec's Claim shape with `after=None, verdict=None, forced=False`)
  - `default_claim(repo: str, fp: str | None, now: float) -> dict`
  - `claim_line(claim: dict) -> str` renders `CLAIM: <metric> <direction> for <scope kind> <id>; baseline <value> (n=<n>)`
  - `parse_claim_line(text: str) -> tuple[str, str, dict] | None` reads `CLAIM: <metric> <direction> [for <kind> <id>]`
  - `snapshot(now: float) -> list[dict]` current value per fleet-scope metric for the console
  - `HALT_CLASSES` and `halt_class(reason: str) -> str`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_metrics.py
"""The catalog measures from ledger rows; a claim carries a fleet-computed baseline."""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fleet import metrics  # noqa: E402

T0 = 1_789_500_000.0
RUNS = [
    {"id": "r1", "repo": "o/r", "outcome": "halted", "halt": {"reason": "investigator found no candidates"}, "timing": None, "trigger": "idle", "pr_url": None, "started_at": T0 + 10},
    {"id": "r2", "repo": "o/r", "outcome": "halted", "halt": {"reason": "model output degenerate (token salad)"}, "timing": None, "trigger": "idle", "pr_url": None, "started_at": T0 + 20},
    {"id": "r3", "repo": "o/r", "outcome": "shipped", "halt": None, "timing": {"implement": {"seconds": 600}}, "trigger": "idle", "pr_url": "u3", "started_at": T0 + 30},
    {"id": "r4", "repo": "o/r", "outcome": "shipped", "halt": None, "timing": {"implement": {"seconds": 900}}, "trigger": "review", "pr_url": "u3", "started_at": T0 + 40},
]
VERDICTS = [
    {"repo": "o/r", "pr_url": "u3", "sha": "a", "confidence": 90, "first": True, "merged_bar": 85, "at": T0 + 50},
    {"repo": "o/r", "pr_url": "u4", "sha": "b", "confidence": 60, "first": True, "merged_bar": 85, "at": T0 + 60},
    {"repo": "o/r", "pr_url": "u4", "sha": "c", "confidence": 88, "first": False, "merged_bar": 85, "at": T0 + 70},
]
POSTS = [
    {"id": 1, "topic": "question", "author": "implementer", "created_at": T0 + 10, "answered_at": T0 + 300, "parent_id": None},
    {"id": 2, "topic": "question", "author": "reconcile", "created_at": T0 + 20, "answered_at": None, "parent_id": None},
    {"id": 3, "topic": "question", "author": "implementer", "created_at": T0 + 30, "answered_at": T0 + 2000, "parent_id": None},
]


class L:
    def runs_between(self, since, until, repo=None): return [r for r in RUNS if repo in (None, r["repo"])]
    def verdicts(self, repo, since, until): return [v for v in VERDICTS if repo in (None, v["repo"])]
    def merged_between(self, repo, since, until): return [{"fingerprint": "f3", "run_id": "r3", "pr_url": "u3", "observed_at": T0 + 80}]
    def posts(self, **kw): return POSTS
    def kv_like(self, pat): return [("bench:2026-09-15", {"rows": [{"success": True}, {"success": False}, {"success": True}]})]
    def runs_since(self, fp, since): return 1 if fp == "fpA" else 0


def test_catalog_names_and_shapes():
    assert {"recurrence", "halt_rate_by_class", "first_pass_acceptance", "review_rounds_to_merge", "implement_seconds",
            "bench_pass_rate", "concierge_answer_rate", "ci_green_rate"} <= set(metrics.names())
    for m in metrics.CATALOG.values():
        assert m.direction_good in ("up", "down") and m.samples_needed >= 1 and m.min_effect > 0


def test_measurements_from_ledger_rows(monkeypatch):
    monkeypatch.setattr(metrics, "ledger", L())
    assert metrics.measure("halt_rate_by_class", {"kind": "repo", "id": "o/r", "class": "any"}, T0, T0 + 100) == (0.5, 4)
    assert metrics.measure("halt_rate_by_class", {"kind": "repo", "id": "o/r", "class": "degenerate"}, T0, T0 + 100) == (0.25, 4)
    assert metrics.measure("implement_seconds", {"kind": "repo", "id": "o/r"}, T0, T0 + 100) == (750.0, 2)
    assert metrics.measure("first_pass_acceptance", {"kind": "repo", "id": "o/r"}, T0, T0 + 100) == (0.5, 2)
    assert metrics.measure("review_rounds_to_merge", {"kind": "repo", "id": "o/r"}, T0, T0 + 100) == (1.0, 1)
    assert metrics.measure("bench_pass_rate", {"kind": "fleet", "id": "fleet"}, T0, T0 + 100) == (2 / 3, 1)
    assert metrics.measure("concierge_answer_rate", {"kind": "fleet", "id": "fleet"}, T0, T0 + 100) == (1 / 3, 3)
    assert metrics.measure("recurrence", {"kind": "fingerprint", "id": "fpA"}, T0, T0 + 100) == (1.0, 1)
    assert metrics.measure("recurrence", {"kind": "fingerprint", "id": "fpB"}, T0, T0 + 100) == (0.0, 1)


def test_ci_green_rate_reads_workflow_runs(monkeypatch):
    monkeypatch.setattr(metrics, "ledger", L())
    runs = {"workflow_runs": [{"conclusion": "success", "run_attempt": 1}, {"conclusion": "failure", "run_attempt": 1},
                              {"conclusion": "success", "run_attempt": 2}]}
    monkeypatch.setattr(metrics.github, "api", lambda path, **kw: runs)
    assert metrics.measure("ci_green_rate", {"kind": "repo", "id": "o/r"}, T0, T0 + 100) == (1 / 3, 3)


def test_claim_for_carries_a_computed_baseline(monkeypatch):
    monkeypatch.setattr(metrics, "ledger", L())
    c = metrics.claim_for("implement_seconds", "down", {"kind": "repo", "id": "o/r"}, T0 + 100)
    assert c["metric"] == "implement_seconds" and c["direction"] == "down" and c["baseline"] == {"value": 750.0, "n": 2, "at": T0 + 100}
    assert c["samples_needed"] == 8 and c["after"] is None and c["verdict"] is None and c["forced"] is False
    line = metrics.claim_line(c)
    assert line.startswith("CLAIM: implement_seconds down for repo o/r; baseline 750 (n=2)")
    assert metrics.parse_claim_line("foo\n" + line + "\nbar") == ("implement_seconds", "down", {"kind": "repo", "id": "o/r"})
    assert metrics.parse_claim_line("CLAIM: nonsense up") is None
    assert metrics.parse_claim_line("no claim here") is None


def test_default_claim_is_recurrence_for_a_fingerprint_else_repo_acceptance(monkeypatch):
    monkeypatch.setattr(metrics, "ledger", L())
    assert metrics.default_claim("o/r", "fpZ", T0 + 100)["metric"] == "recurrence"
    assert metrics.default_claim("o/r", None, T0 + 100)["metric"] == "first_pass_acceptance"


def test_halt_class():
    assert metrics.halt_class("investigator found no candidates") == "no_candidates"
    assert metrics.halt_class("implementer made no commit") == "no_commit"
    assert metrics.halt_class("model output degenerate (token salad)") == "degenerate"
    assert metrics.halt_class("stage implement timed out after 3600s") == "timeout"
    assert metrics.halt_class("something else") == "other"


def test_snapshot_has_a_row_per_fleet_metric(monkeypatch):
    monkeypatch.setattr(metrics, "ledger", L())
    monkeypatch.setattr(metrics.github, "api", lambda path, **kw: {"workflow_runs": []})
    rows = metrics.snapshot(T0 + 100)
    names = {r["metric"] for r in rows}
    assert "halt_rate_by_class" in names and all({"metric", "value", "n", "direction_good", "samples_needed"} <= set(r) for r in rows)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest -q tests/test_metrics.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'fleet.metrics'`.

- [ ] **Step 3: Write `fleet/metrics.py`**

```python
"""The metric catalog: what the fleet can measure about itself, from data it
already holds. A claim names one metric, a direction and a fleet-computed
baseline; PR 2 measures the after and judges. Reads the ledger and GitHub,
writes nothing (spec: 2026-09-16-observed-outcomes-design.md, Metric catalog v1)."""
from __future__ import annotations

import re
import statistics
import time
from dataclasses import dataclass
from typing import Callable

from fleet import github, ledger

HALT_CLASSES = ("no_candidates", "no_commit", "degenerate", "timeout", "tool_error", "other")
_HALT_RULES = (
    ("no_candidates", re.compile(r"no candidates|no candidate passed", re.I)),
    ("no_commit", re.compile(r"no commit|wrote no 03-implementation", re.I)),
    ("degenerate", re.compile(r"degenerate|token salad", re.I)),
    ("timeout", re.compile(r"timed out|deadline|wall clock", re.I)),
    ("tool_error", re.compile(r"tool|dsh session failed|Connection refused|HTTP [45]\d\d", re.I)),
)


def halt_class(reason: str) -> str:
    for name, rx in _HALT_RULES:
        if rx.search(reason or ""):
            return name
    return "other"


@dataclass(frozen=True)
class Metric:
    name: str
    kind: str                 # deterministic | judged
    direction_good: str       # up | down
    samples_needed: int
    min_effect: float         # absolute for rates (0.05 = 5 points), relative for durations (0.15 = 15 %)
    unit: str                 # rate | seconds | rounds | count
    measure: Callable[[dict, float, float], tuple[float | None, int]]


def _ts(v) -> float:
    """Ledger timestamps arrive as datetimes from pg8000 and as floats in tests."""
    return v.timestamp() if hasattr(v, "timestamp") else float(v)


def _dt(ts: float):
    import datetime
    return datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc)


def _repo(scope: dict) -> str | None:
    return scope.get("id") if scope.get("kind") == "repo" else None


def m_recurrence(scope: dict, since: float, until: float) -> tuple[float | None, int]:
    """1.0 when the candidate was attempted again after `since`, else 0.0. Always one sample."""
    if scope.get("kind") != "fingerprint":
        return None, 0
    return (1.0 if ledger.runs_since(scope["id"], _dt(since)) > 0 else 0.0), 1


def m_halt_rate(scope: dict, since: float, until: float) -> tuple[float | None, int]:
    runs = [r for r in ledger.runs_between(_dt(since), _dt(until), _repo(scope)) if r.get("outcome") in ("shipped", "halted", "failed")]
    if not runs:
        return None, 0
    wanted = scope.get("class", "any")
    halted = [r for r in runs if r.get("outcome") in ("halted", "failed")
              and (wanted == "any" or halt_class(str((r.get("halt") or {}).get("reason", ""))) == wanted)]
    return len(halted) / len(runs), len(runs)


def m_implement_seconds(scope: dict, since: float, until: float) -> tuple[float | None, int]:
    secs = []
    for r in ledger.runs_between(_dt(since), _dt(until), _repo(scope)):
        t = (r.get("timing") or {}).get("implement") or {}
        if isinstance(t, dict) and t.get("seconds"):
            secs.append(float(t["seconds"]))
    return (statistics.median(secs), len(secs)) if secs else (None, 0)


def m_first_pass(scope: dict, since: float, until: float) -> tuple[float | None, int]:
    firsts = [v for v in ledger.verdicts(_repo(scope), _dt(since), _dt(until)) if v.get("first")]
    if not firsts:
        return None, 0
    return sum(1 for v in firsts if int(v["confidence"]) >= int(v["merged_bar"])) / len(firsts), len(firsts)


def m_rounds_to_merge(scope: dict, since: float, until: float) -> tuple[float | None, int]:
    merged = ledger.merged_between(_repo(scope), _dt(since), _dt(until))
    if not merged:
        return None, 0
    by_pr: dict[str, int] = {}
    for r in ledger.runs_between(_dt(since - 30 * 86400), _dt(until), _repo(scope)):
        if r.get("trigger") == "review" and r.get("pr_url"):
            by_pr[r["pr_url"]] = by_pr.get(r["pr_url"], 0) + 1
    rounds = [by_pr.get(m.get("pr_url") or "", 0) for m in merged]
    return sum(rounds) / len(rounds), len(rounds)


def m_bench_pass(scope: dict, since: float, until: float) -> tuple[float | None, int]:
    rows = sorted(ledger.kv_like("bench:%"), reverse=True)
    if not rows:
        return None, 0
    fixtures = (rows[0][1] or {}).get("rows") or []
    if not fixtures:
        return None, 0
    return sum(1 for f in fixtures if f.get("success")) / len(fixtures), 1


def m_concierge_answer(scope: dict, since: float, until: float) -> tuple[float | None, int]:
    qs = [p for p in ledger.posts(limit=200, topic="question") if since <= _ts(p["created_at"]) < until and p.get("parent_id") is None]
    if not qs:
        return None, 0
    ok = sum(1 for p in qs if p.get("answered_at") and _ts(p["answered_at"]) - _ts(p["created_at"]) <= 900)
    return ok / len(qs), len(qs)


def m_ci_green(scope: dict, since: float, until: float) -> tuple[float | None, int]:
    repo = _repo(scope)
    if not repo:
        return None, 0
    created = f">={time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(since))}"
    res = github.api(f"/repos/{repo}/actions/runs?per_page=100&created={created}&event=pull_request") or {}
    runs = [r for r in (res.get("workflow_runs") or []) if r.get("conclusion") in ("success", "failure")]
    if not runs:
        return None, 0
    return sum(1 for r in runs if r["conclusion"] == "success" and int(r.get("run_attempt") or 1) == 1) / len(runs), len(runs)


CATALOG: dict[str, Metric] = {m.name: m for m in (
    Metric("recurrence", "deterministic", "down", 1, 0.5, "rate", m_recurrence),
    Metric("halt_rate_by_class", "deterministic", "down", 10, 0.05, "rate", m_halt_rate),
    Metric("first_pass_acceptance", "deterministic", "up", 8, 0.05, "rate", m_first_pass),
    Metric("review_rounds_to_merge", "deterministic", "down", 5, 0.5, "rounds", m_rounds_to_merge),
    Metric("implement_seconds", "deterministic", "down", 8, 0.15, "seconds", m_implement_seconds),
    Metric("bench_pass_rate", "deterministic", "up", 1, 0.01, "rate", m_bench_pass),
    Metric("concierge_answer_rate", "deterministic", "up", 10, 0.10, "rate", m_concierge_answer),
    Metric("ci_green_rate", "deterministic", "up", 8, 0.10, "rate", m_ci_green),
)}
# tokens_per_stage and canary_uptime need capture that PR 3/4 add; idea_novelty (judged) is PR 4.


def names() -> list[str]:
    return list(CATALOG)


def measure(name: str, scope: dict, since: float, until: float) -> tuple[float | None, int]:
    m = CATALOG.get(name)
    if not m:
        return None, 0
    try:
        return m.measure(scope, since, until)
    except Exception as e:
        print(f"metrics: {name} unmeasurable ({type(e).__name__}: {str(e)[:80]})")
        return None, 0


def claim_for(metric: str, direction: str, scope: dict, now: float, lookback_days: int = 7) -> dict:
    m = CATALOG[metric]
    value, n = measure(metric, scope, now - lookback_days * 86400, now)
    return {"metric": metric, "direction": direction if direction in ("up", "down") else m.direction_good, "scope": scope,
            "baseline": {"value": value, "n": n, "at": now}, "samples_needed": m.samples_needed, "cap_days": 7,
            "min_effect": m.min_effect, "after": None, "verdict": None, "forced": False}


def default_claim(repo: str, fp: str | None, now: float) -> dict:
    """A human brief that names no metric (spec: recurrence on its fingerprint);
    an improve run before its candidate exists (repo first-pass acceptance)."""
    if fp:
        return claim_for("recurrence", "down", {"kind": "fingerprint", "id": fp, "repo": repo}, now)
    return claim_for("first_pass_acceptance", "up", {"kind": "repo", "id": repo}, now)


def _fmt(v) -> str:
    if v is None:
        return "unknown"
    return f"{v:.0f}" if float(v) >= 10 else f"{v:.2f}"


def claim_line(claim: dict) -> str:
    b, s = claim.get("baseline") or {}, claim.get("scope") or {}
    return (f"CLAIM: {claim['metric']} {claim['direction']} for {s.get('kind', 'fleet')} {s.get('id', 'fleet')}; "
            f"baseline {_fmt(b.get('value'))} (n={b.get('n', 0)})")


_CLAIM_RX = re.compile(r"^CLAIM:\s*([a-z_]+)\s+(up|down)(?:\s+for\s+(fingerprint|repo|fleet|canary)\s+(\S+?))?(?:;|\s*$)", re.M)


def parse_claim_line(text: str) -> tuple[str, str, dict] | None:
    m = _CLAIM_RX.search(text or "")
    if not m or m.group(1) not in CATALOG:
        return None
    scope = {"kind": m.group(3) or "fleet", "id": m.group(4) or "fleet"}
    return m.group(1), m.group(2), scope


def snapshot(now: float, repos: tuple[str, ...] = ()) -> list[dict]:
    """Current value of every metric at fleet scope (and per repo when given), for the console."""
    out = []
    scopes = [{"kind": "fleet", "id": "fleet"}] + [{"kind": "repo", "id": r} for r in repos]
    for m in CATALOG.values():
        if m.name == "recurrence":
            continue
        for scope in scopes:
            if m.name in ("bench_pass_rate", "concierge_answer_rate") and scope["kind"] != "fleet":
                continue
            if m.name == "ci_green_rate" and scope["kind"] != "repo":
                continue
            value, n = measure(m.name, scope, now - 7 * 86400, now)
            out.append({"metric": m.name, "scope": scope, "value": value, "n": n, "unit": m.unit,
                        "direction_good": m.direction_good, "samples_needed": m.samples_needed})
    return out
```

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest -q tests/test_metrics.py`
Expected: 7 passed. Then `python3 -m pytest -q tests` all pass.

- [ ] **Step 5: Commit**

```bash
git add fleet/metrics.py tests/test_metrics.py
git commit -m "feat(fleet): the metric catalog v1, claims with a fleet-computed baseline

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: Ideas carry a metric; the ideator must name one

**Files:**
- Modify: `fleet/ideas.py` (`QUINTET`, the idea table in `ensure()`, `add`, `brief_for`)
- Modify: `scripts/ideate.py` (`QUINTET_SHAPE`, `with_evidence`)
- Test: `tests/test_ideate.py` (add one test), `tests/test_ideas.py` (add one test)

**Interfaces:**
- Consumes: `metrics.names()`, `metrics.claim_line()`, `metrics.claim_for()`.
- Produces: idea rows with `metric` and `direction`; `ideas.brief_for(idea)` ending with a `CLAIM:` line; `ideate.with_evidence` also requires a catalog metric.

- [ ] **Step 1: Confirm the current shapes**

Run: `grep -n "^QUINTET\|metric\|direction\|CREATE TABLE IF NOT EXISTS idea" fleet/ideas.py | head`
Expected: `QUINTET = ("problem", "mechanism", "novelty", "assumptions", "effect", "where")` (or the same six in some order) and one `CREATE TABLE IF NOT EXISTS idea (...)` block with one column per quintet field. If the table stores the quintet as a jsonb instead of columns, adapt Step 3 to add the two keys inside that jsonb rather than as columns.

- [ ] **Step 2: Write the failing tests**

Append to `tests/test_ideas.py`:

```python
def test_brief_for_ends_with_a_claim_line(monkeypatch):
    from fleet import ideas, metrics
    monkeypatch.setattr(metrics, "measure", lambda name, scope, since, until: (0.4, 12))
    idea = {"id": "ab12cd34ef56", "repo": "o/r", "problem": "Runs halt at test with no log.", "mechanism": "tail the dsh log",
            "assumptions": "", "effect": "halts show a tail", "touches": "o/r", "metric": "halt_rate_by_class", "direction": "down"}
    b = ideas.brief_for(idea)
    assert b.startswith("[idea:ab12cd34ef56]") and "\nCLAIM: halt_rate_by_class down for repo o/r; baseline 0.40 (n=12)" in b


def test_brief_for_without_a_metric_falls_back_to_repo_acceptance(monkeypatch):
    from fleet import ideas, metrics
    monkeypatch.setattr(metrics, "measure", lambda name, scope, since, until: (None, 0))
    idea = {"id": "ab12cd34ef56", "repo": "o/r", "problem": "p", "mechanism": "m", "effect": "e", "touches": "o/r"}
    assert "CLAIM: first_pass_acceptance up for repo o/r" in ideas.brief_for(idea)
```

Append to `tests/test_ideate.py` (uses the file's existing `FakeIdeas`, `EXPERIENCES` and the pattern of the existing diverge tests; look at how they monkeypatch `review.ask_judge` and copy it):

```python
def test_ideas_without_a_catalog_metric_are_dropped(monkeypatch):
    known = {"run:improve-1"}
    good = {"problem": "p", "mechanism": "m", "evidence": ["run:improve-1"], "metric": "halt_rate_by_class", "direction": "down"}
    bad = {"problem": "p", "mechanism": "m", "evidence": ["run:improve-1"], "metric": "vibes", "direction": "up"}
    none = {"problem": "p", "mechanism": "m", "evidence": ["run:improve-1"]}
    assert ideate.with_evidence(good, known) is True
    assert ideate.with_evidence(bad, known) is False
    assert ideate.with_evidence(none, known) is False
    assert "\"metric\": \"<one of: " in ideate.QUINTET_SHAPE and "halt_rate_by_class" in ideate.QUINTET_SHAPE
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python3 -m pytest -q tests/test_ideas.py tests/test_ideate.py`
Expected: the three new tests FAIL (`KeyError`/`AssertionError`).

- [ ] **Step 4: Implement in `fleet/ideas.py`**

Add the two fields to `QUINTET`:

```python
QUINTET = ("problem", "mechanism", "novelty", "assumptions", "effect", "where", "metric", "direction")
```

In the idea table schema string used by `ensure()`, add after the existing quintet columns:

```sql
ALTER TABLE idea ADD COLUMN IF NOT EXISTS metric TEXT;
ALTER TABLE idea ADD COLUMN IF NOT EXISTS direction TEXT;
```

(If `ensure()` runs one `CREATE TABLE IF NOT EXISTS` only, add these two statements to the same list it executes, each as its own statement.) In `add()`, wherever the quintet fields are written, `metric` and `direction` ride along because they are read from `QUINTET`; check the INSERT column list is built from `QUINTET` and not hand-written; if hand-written, add the two columns and two placeholders.

Replace `brief_for`:

```python
def brief_for(idea: dict) -> str:
    """A mission brief from an archived idea, tagged so publish closes it, ending
    with the claim the run will be judged by (fleet/metrics.py)."""
    from fleet import metrics
    import time
    spans = [t for t in str(idea.get("touches") or "").split(",") if t]
    repo = str(idea.get("repo") or (spans[0] if spans else ""))
    metric, direction = idea.get("metric"), idea.get("direction")
    if metric in metrics.CATALOG:
        scope = {"kind": "repo", "id": repo} if metric != "recurrence" else {"kind": "fingerprint", "id": idea["id"], "repo": repo}
        claim = metrics.claim_for(metric, direction or metrics.CATALOG[metric].direction_good, scope, time.time())
    else:
        claim = metrics.default_claim(repo, None, time.time())
    return (f"[idea:{idea['id']}] {str(idea['problem']).strip()} How: {str(idea['mechanism']).strip()} "
            + (f"Assumptions: {str(idea['assumptions']).strip()} " if idea.get("assumptions") else "")
            + (f"Touches: {', '.join(spans)} (this run is in {idea.get('repo')}; say in the PR what the other repos still need). " if len(spans) > 1 else "")
            + f"Done when: {str(idea.get('effect') or '').strip()}\n" + metrics.claim_line(claim))
```

- [ ] **Step 5: Implement in `scripts/ideate.py`**

Change `QUINTET_SHAPE` to ask for the metric (the list is generated so a new catalog entry appears automatically):

```python
from fleet import metrics  # with the other fleet imports at the top

QUINTET_SHAPE = ("Reply with STRICT JSON only: {\"ideas\": [{\"problem\": \"<what is wrong, one sentence>\", \"mechanism\": \"<how the change works>\", "
                 "\"novelty\": \"<what makes it unlike the archive>\", \"assumptions\": \"<what must be true for it to work>\", "
                 "\"effect\": \"<the measurable effect, the check that proves it>\", \"where\": \"<files or area>\", "
                 "\"metric\": \"<one of: " + ", ".join(n for n in metrics.names() if n != "recurrence") + ">\", \"direction\": \"<up|down: the way the metric should move>\", "
                 "\"touches\": [\"<owner/name of every repo the change spans, this one first; an idea may be cross-cutting>\"], \"evidence\": [\"<experience id>\"]}]}")
```

Extend `with_evidence` so an idea without a catalog metric is dropped the way one without evidence is:

```python
def with_evidence(it: dict, known: set[str]) -> bool:
    it["evidence"] = [str(e) for e in (it.get("evidence") or []) if str(e) in known]
    if str(it.get("metric") or "") not in metrics.CATALOG or str(it.get("metric")) == "recurrence":
        return False                     # no catalog metric, no claim, no launch (spec principle 2)
    it["direction"] = it.get("direction") if it.get("direction") in ("up", "down") else metrics.CATALOG[it["metric"]].direction_good
    return bool(it["evidence"]) and bool(str(it.get("problem", "")).strip()) and bool(str(it.get("mechanism", "")).strip())
```

Note: the existing `diverge` prints "dropped an idea ... with no valid evidence id" on a false return; change that message to "dropped an idea from {name}: no valid evidence id or no catalog metric".

- [ ] **Step 6: Run tests**

Run: `python3 -m pytest -q tests`
Expected: all pass. If an existing ideate test's fake idea lacks a metric and now fails, add `"metric": "halt_rate_by_class", "direction": "down"` to that fixture: the rule is deliberate.

- [ ] **Step 7: Commit**

```bash
git add fleet/ideas.py scripts/ideate.py tests/test_ideas.py tests/test_ideate.py
git commit -m "feat(ideate): an idea names the catalog metric it will move; the brief ends with its claim

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: The launcher stores a claim for every mission it admits

**Files:**
- Modify: `scripts/launcher.py` (`validate`, `admit`)
- Test: `tests/test_launcher.py`

**Interfaces:**
- Consumes: `metrics.parse_claim_line`, `metrics.claim_for`, `metrics.default_claim`, `metrics.claim_line`, `ledger.set_claim`.
- Produces: `launcher.claim_for_brief(brief: str, repo: str, fp: str) -> dict`; every admitted mission has `candidate.claim` set; a brief with no `CLAIM:` line gets one appended.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_launcher.py` (the file already stubs `launcher.ledger`/`launcher.github` in other tests; follow the same monkeypatch style):

```python
def test_admit_stores_a_claim_and_a_bare_brief_gets_the_default(monkeypatch):
    from fleet import metrics
    calls = {}
    class L:
        def mission_candidate(self, repo, brief): return ("fp1", "t", None)
        def attempts(self, fp): return (0, None)
        def upsert_candidate(self, *a, **kw): pass
        def set_claim(self, fp, claim): calls["claim"] = (fp, claim)
    monkeypatch.setattr(launcher, "ledger", L())
    monkeypatch.setattr(metrics, "measure", lambda name, scope, since, until: (0.0, 1))
    fp, refusal = launcher.admit("ctkadvisors/kagent", "Fix the flaky test in x.\nCLAIM: implement_seconds down for repo ctkadvisors/kagent", human=True)
    assert refusal is None and calls["claim"][0] == "fp1" and calls["claim"][1]["metric"] == "implement_seconds"
    fp, refusal = launcher.admit("ctkadvisors/kagent", "Fix the flaky test in x with no claim at all", human=True)
    assert calls["claim"][1]["metric"] == "recurrence" and calls["claim"][1]["scope"]["id"] == "fp1"


def test_validate_appends_a_default_claim_line_when_the_brief_has_none(monkeypatch):
    from fleet import metrics
    monkeypatch.setattr(metrics, "measure", lambda name, scope, since, until: (0.5, 4))
    brief, repo = launcher.validate({"brief": "Fix the flaky test in x", "repo": "ctkadvisors/kagent"})
    assert brief.endswith("\nCLAIM: first_pass_acceptance up for repo ctkadvisors/kagent; baseline 0.50 (n=4)")
    brief2, _ = launcher.validate({"brief": brief, "repo": "ctkadvisors/kagent"})
    assert brief2.count("CLAIM:") == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest -q tests/test_launcher.py`
Expected: the two new tests FAIL (`set_claim` never called; no `CLAIM:` line).

- [ ] **Step 3: Implement**

In `scripts/launcher.py` add near the other fleet imports: `from fleet import metrics` (keep the existing imports).

At the end of `validate()`, before `return brief, repo`:

```python
    if metrics.parse_claim_line(brief) is None:
        # Every launch declares a claim (spec principle 2). A brief that names none
        # is judged by the repo's first-pass acceptance; admit() narrows it to the
        # candidate's own recurrence once the fingerprint exists.
        brief = brief.rstrip() + "\n" + metrics.claim_line(metrics.default_claim(repo, None, time.time()))
```

(`import time` at the top if the module lacks it.)

Add the helper above `admit`:

```python
def claim_for_brief(brief: str, repo: str, fp: str) -> dict:
    """The claim this mission will be judged by: the brief's CLAIM line when it
    names a catalog metric, else recurrence on the candidate itself."""
    parsed = metrics.parse_claim_line(brief)
    if parsed and parsed[0] != "first_pass_acceptance":
        metric, direction, scope = parsed
        if scope.get("kind") == "fingerprint":
            scope = {"kind": "fingerprint", "id": fp, "repo": repo}
        return metrics.claim_for(metric, direction, scope, time.time())
    return metrics.default_claim(repo, fp, time.time())
```

In `admit()`, the two non-refusal returns become claim-recording returns. Replace the review-round early return and the final lines:

```python
    if review:
        rounds = ledger.runs_by_trigger(fp, "review")
        if rounds >= REVIEW_ROUNDS:
            return fp, f"already iterated {rounds}x on review feedback; a human decides now"
        _store_claim(fp, repo, brief)
        return fp, None
    ...
    ledger.upsert_candidate(fp, repo, title, "human", issue_url=issue_url)
    _store_claim(fp, repo, brief)
    return fp, None
```

with

```python
def _store_claim(fp: str, repo: str, brief: str) -> None:
    try:
        ledger.set_claim(fp, claim_for_brief(brief, repo, fp))
    except Exception as e:  # a claim the ledger cannot store is a log line, never a refused launch
        print(f"[mission-launcher] claim not stored for {fp}: {type(e).__name__}: {str(e)[:80]}")
```

A review round keeps the PR's original claim if one exists: in `_store_claim`, first `existing = ledger.claim_of(fp)` inside a try; if `existing` is truthy and `metrics.parse_claim_line(brief)` is None, return without writing.

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest -q tests`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/launcher.py tests/test_launcher.py
git commit -m "feat(launcher): every admitted mission carries a claim; a bare brief gets the default

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: Improve runs get a default claim; the implement prompt carries it

**Files:**
- Modify: `scripts/reconcile.py` (`render_improve_job`, `launch`)
- Modify: `scripts/stage.sh` (implement SUFFIX, next to the PONYTAIL block)
- Test: `tests/test_reconcile.py`

**Interfaces:**
- Consumes: `metrics.default_claim`, `metrics.claim_line`, `ledger.kv_set`.
- Produces: kv `claim:<run name>` = the claim dict; env `CLAIM` on every container of the improve Job = the claim line; stage.sh appends `CLAIM: ...` to the implement SUFFIX when `MISSION_BRIEF` has no `CLAIM:` and `$CLAIM` is set.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_reconcile.py`:

```python
def test_launch_gives_an_improve_run_a_default_claim(monkeypatch):
    from fleet import metrics
    created, led = [], FakeLedger()
    tpl = {"spec": {"jobTemplate": {"metadata": {"labels": {}}, "spec": {"template": {"spec": {
        "initContainers": [{"name": "brief", "env": []}], "containers": [{"name": "implement", "env": []}]}}}}}}
    monkeypatch.setattr(reconcile, "k8s", lambda m, p, body=None: created.append((m, p, body)) or tpl)
    monkeypatch.setattr(reconcile, "ledger", led)
    monkeypatch.setattr(metrics, "measure", lambda name, scope, since, until: (0.25, 8))
    monkeypatch.setattr(reconcile, "DRY_RUN", False)
    name = reconcile.launch(1_789_500_000.0, "idle", "ctkadvisors/kagent")
    job = next(b for m, p, b in created if m == "POST")
    envs = {e["name"]: e["value"] for c in job["spec"]["template"]["spec"]["containers"] for e in c["env"]}
    assert envs["CLAIM"] == "CLAIM: first_pass_acceptance up for repo ctkadvisors/kagent; baseline 0.25 (n=8)"
    assert led.kv[f"claim:{name}"]["metric"] == "first_pass_acceptance"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest -q tests/test_reconcile.py -k default_claim`
Expected: FAIL with `KeyError: 'CLAIM'`.

- [ ] **Step 3: Implement in `scripts/reconcile.py`**

Add `metrics` to the fleet import line: `from fleet import experience, github, ideas, ledger, metrics, net, telegram`.

Change `render_improve_job`'s signature and env handling to accept a claim line:

```python
def render_improve_job(cronjob: dict, name: str, trigger: str = "idle", repo: str | None = None, claim_line: str | None = None) -> dict:
```

and after the `if repo:` block add:

```python
    if claim_line:  # the stage prompts read it (stage.sh CLAIM), publish stores it on the candidate
        for c in spec.get("initContainers", []) + spec.get("containers", []):
            c["env"] = [e for e in c["env"] if e["name"] != "CLAIM"] + [{"name": "CLAIM", "value": claim_line}]
```

Change `launch`:

```python
def launch(now: float, trigger: str = "idle", repo: str | None = None) -> str:
    name = "improve-" + time.strftime("%Y%m%d-%H%M%S", time.gmtime(now))
    cj = k8s("GET", f"/apis/batch/v1/namespaces/{NAMESPACE}/cronjobs/{CRONJOB}")
    target = repo or os.environ.get("REPO", "ctkadvisors/kagent")
    claim = metrics.default_claim(target, None, now)   # the candidate does not exist yet; publish narrows it
    try:
        ledger.kv_set(f"claim:{name}", claim)
    except Exception as e:
        print(f"launch: claim kv not written ({type(e).__name__})")
    job = render_improve_job(cj, name, trigger, repo, metrics.claim_line(claim))
    if not DRY_RUN:
        k8s("POST", f"/apis/batch/v1/namespaces/{NAMESPACE}/jobs", job)
    return name
```

- [ ] **Step 4: Implement in `scripts/stage.sh`**

Directly after the PONYTAIL block (`if [ "$S" = implement ]; then SUFFIX="$SUFFIX ... PONYTAIL ..."; fi`), add:

```sh
# The claim this run is judged by (spec 2026-09-16 observed outcomes). A mission's
# brief already ends with it; an improve run gets it from the Job's CLAIM env.
if [ "$S" = implement ] && [ -n "${CLAIM:-}" ] && ! printf '%s' "${MISSION_BRIEF:-}" | grep -q '^CLAIM:'; then SUFFIX="$SUFFIX
$CLAIM
(That line is how this change will be judged after it ships: the metric must move that way on the live fleet. Aim the change at it.)"; fi
```

Run `sh -n scripts/stage.sh` to check the syntax.

- [ ] **Step 5: Run tests**

Run: `python3 -m pytest -q tests && sh -n scripts/stage.sh`
Expected: all pass, no syntax error.

- [ ] **Step 6: Commit**

```bash
git add scripts/reconcile.py scripts/stage.sh tests/test_reconcile.py
git commit -m "feat(reconcile): an improve run launches with a default claim the implementer can read

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 6: publish renders the claim and pins it to the candidate

**Files:**
- Modify: `scripts/publish.py` (`build_trace`, the ledger block near line 227)
- Test: `tests/test_publish.py`

**Interfaces:**
- Consumes: `ledger.claim_of`, `ledger.kv_get(f"claim:{run_id}")`, `ledger.set_claim`, `metrics.claim_line`, env `CLAIM`.
- Produces: `publish.claim_section(fp: str | None) -> str` returning `### Claim\n<claim line>\n<one sentence>` or `""`; a candidate created from an improve run ends with `claim` set.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_publish.py`:

```python
def test_claim_section_prefers_the_candidate_then_the_run_kv_then_env(monkeypatch):
    class L:
        def __init__(self): self.claims = {}; self.kv = {}
        def claim_of(self, fp): return self.claims.get(fp)
        def kv_get(self, k): return self.kv.get(k)
        def set_claim(self, fp, c): self.claims[fp] = c
    led = L()
    monkeypatch.setattr(publish, "ledger", led)
    monkeypatch.setattr(publish, "run_id", lambda: "improve-1")
    monkeypatch.delenv("CLAIM", raising=False)
    assert publish.claim_section("fpX") == ""
    led.kv["claim:improve-1"] = {"metric": "first_pass_acceptance", "direction": "up", "scope": {"kind": "repo", "id": "o/r"}, "baseline": {"value": 0.5, "n": 4, "at": 1}}
    sec = publish.claim_section("fpX")
    assert sec.startswith("### Claim\nCLAIM: first_pass_acceptance up for repo o/r; baseline 0.50 (n=4)")
    assert led.claims["fpX"]["metric"] == "first_pass_acceptance"      # the kv claim is now the candidate's
    led.claims["fpY"] = {"metric": "recurrence", "direction": "down", "scope": {"kind": "fingerprint", "id": "fpY"}, "baseline": {"value": 0.0, "n": 1, "at": 1}}
    assert "CLAIM: recurrence down for fingerprint fpY" in publish.claim_section("fpY")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest -q tests/test_publish.py -k claim_section`
Expected: FAIL with `AttributeError: module 'publish' has no attribute 'claim_section'`.

- [ ] **Step 3: Implement**

In `scripts/publish.py`, import `metrics` alongside the other fleet imports, then add above `build_trace`:

```python
def claim_section(fp: str | None) -> str:
    """The claim this PR will be judged by, from the candidate, else the improve
    run's launch kv (moved onto the candidate here), else the Job's CLAIM env.
    The reviewer objects to a fleet PR without this section (review.py)."""
    claim = None
    try:
        claim = ledger.claim_of(fp) if fp else None
        if not claim:
            claim = ledger.kv_get(f"claim:{run_id()}")
            if claim and fp:
                ledger.set_claim(fp, claim)
    except Exception as e:
        print(f"claim: ledger unavailable ({type(e).__name__})")
    if claim:
        return ("### Claim\n" + metrics.claim_line(claim)
                + "\nJudged after deploy: the metric must move that way on the live fleet, with the samples the catalog needs.")
    if os.environ.get("CLAIM"):
        return "### Claim\n" + os.environ["CLAIM"] + "\nJudged after deploy: the metric must move that way on the live fleet."
    return ""
```

In `build_trace`, insert the section right after the "### Result: SHIP"/Halted line and before `pipeline_evidence()`:

```python
        claim_section(candidate(stopped and {} or v_cached())[0]) if False else CLAIM_SECTION,
```

That is awkward; do it the plain way instead: compute the fingerprint once in `main()` before the body is built and pass it. Concretely, in `main()` (near line 227) move `fp, title, issue_url = candidate(v)` above the body assembly, then `build_trace(stopped, fp)`; change `build_trace`'s signature to `def build_trace(stopped: dict | None, fp: str | None = None) -> str:` and its list to include `claim_section(fp)` after the Result line. Keep the ledger `try:` block as it is but drop the duplicate `candidate(v)` call inside it (reuse `fp, title, issue_url`).

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest -q tests`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/publish.py tests/test_publish.py
git commit -m "feat(publish): the PR body opens with the claim the change will be judged by

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 7: The reviewer objects to a fleet PR without a claim and records every verdict

**Files:**
- Modify: `scripts/review.py` (`review_pr`, `judge` prompt)
- Test: `tests/test_review_claim.py` (new)

**Interfaces:**
- Consumes: `ledger.record_verdict`, `MERGE_MIN`, `AGENT_BRANCH_PREFIX`.
- Produces: `review.missing_claim(pr: dict) -> dict | None` returning a verdict dict `{"confidence": 0, "summary": ..., "feedback": ..., "prior_addressed": False}` for a fleet PR whose body lacks `### Claim`; `review_pr` skips the judge in that case; every judged PR writes a verdict row.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_review_claim.py
"""A fleet PR without a claim is objected to by code, not by the judge; every
judgment lands in the verdict table."""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import review  # noqa: E402


def pr(body, branch="agent/mission-1", login="example-fleet[bot]"):
    return {"number": 5, "title": "t", "body": body, "html_url": "https://github.com/o/r/pull/5",
            "head": {"ref": branch, "sha": "abc", "repo": {"full_name": "o/r"}}, "user": {"login": login}, "labels": []}


def test_missing_claim_is_a_deterministic_objection_for_fleet_prs_only():
    v = review.missing_claim(pr("## Pipeline trace\n### Result: SHIP\n"))
    assert v and v["confidence"] == 0 and "### Claim" in v["feedback"] and v["prior_addressed"] is False
    assert review.missing_claim(pr("### Claim\nCLAIM: recurrence down for fingerprint f; baseline 0 (n=1)")) is None
    assert review.missing_claim(pr("no claim", branch="fix/human-branch", login="chrisknu")) is None


def test_review_pr_records_a_verdict_and_skips_the_judge_without_a_claim(monkeypatch):
    calls, verdicts = [], []
    class GH:
        def api(self, path, data=None, method=None, **kw):
            calls.append(path)
            if path.endswith("/files?per_page=100"): return [{"filename": "a.py", "changes": 3}]
            if "/check-runs" in path: return {"check_runs": [{"status": "completed", "conclusion": "success"}]}
            if path.endswith("/pulls/5") and kw.get("raw"): return "diff"
            return {}
        def kid_gloves(self, repo): return False
    class L:
        def posts(self, **kw): return []
        def review_rounds(self, u): return 0
        def kv_get(self, k): return None
        def kv_set(self, k, v): pass
        def kv_delete(self, k): pass
        def say(self, *a, **kw): return 1
        def record_verdict(self, *a): verdicts.append(a)
    monkeypatch.setattr(review, "github", GH()); monkeypatch.setattr(review, "ledger", L())
    monkeypatch.setattr(review, "judge", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("judge must not run")))
    monkeypatch.setattr(review, "checkout", lambda *a, **kw: None)
    monkeypatch.setattr(review, "objection", lambda repo, n: None)
    monkeypatch.setattr(review, "remember_objection", lambda *a, **kw: None)
    monkeypatch.setattr(review, "act", lambda *a, **kw: None, raising=False)
    review.review_pr("o/r", "/repos/o/r", pr("no claim here"), 5)
    assert verdicts and verdicts[0][:4] == ("o/r", "https://github.com/o/r/pull/5", "abc", 0) and verdicts[0][4] is True
```

If `review_pr`'s tail (labels, comments, merge) is not factored into a function named `act`, remove that monkeypatch line and instead stub the `github.api` calls it makes (they return `{}` above, which is enough for label and comment POSTs).

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest -q tests/test_review_claim.py`
Expected: FAIL with `AttributeError: module 'review' has no attribute 'missing_claim'`.

- [ ] **Step 3: Implement**

In `scripts/review.py` add above `review_pr`:

```python
def missing_claim(pr: dict) -> dict | None:
    """A fleet PR must say what it will be judged by (spec principle 2). Code
    objects; the judge is not spent on it. Humans' branches are exempt."""
    fleet_pr = pr["head"]["ref"].startswith(AGENT_BRANCH_PREFIX or "agent/") or pr["user"]["login"].endswith("[bot]")
    if not fleet_pr or "### Claim" in (pr.get("body") or ""):
        return None
    return {"confidence": 0, "prior_addressed": False,
            "summary": "no claim declared: the PR body has no '### Claim' section, so nothing says how this change will be judged after deploy",
            "feedback": "Add a '### Claim' section to the PR body (publish.py writes it from the candidate's claim; a mission brief ends "
                        "with a 'CLAIM: <metric> <up|down> for <scope>' line, see fleet/metrics.py names()). Re-run publish or edit the body."}
```

In `review_pr`, replace the judge call block:

```python
        prior = objection(repo, n)
        try:
            notes = ledger.posts(limit=8, ref=pr["html_url"])
        except Exception:
            notes = []
        v = missing_claim(pr)
        if v is None:
            cwd = checkout(repo, n, pr["head"]["sha"])
            try:
                v = judge(pr, diff, prior, cwd, notes, ci_state(runs) if runs else "")
            finally:
                if cwd:
                    shutil.rmtree(cwd, ignore_errors=True)
        conf, summary, feedback = int(v.get("confidence", 0)), v.get("summary", ""), v.get("feedback", "")
        if summary == "unparseable review":
            print(f"{repo}#{n}: unparseable verdict twice, next round; tail: {feedback[-200:]!r}")
            return
        raw = conf
        try:  # every judgment accrues: first_pass_acceptance and review_rounds_to_merge read this table
            ledger.record_verdict(repo, pr["html_url"], pr["head"]["sha"], raw, prior is None, MERGE_MIN)
        except Exception as e:
            print(f"{repo}#{n}: verdict not recorded ({type(e).__name__})")
```

In `judge`, add one sentence to the prompt right after the "Pipeline-run evidence" sentence:

```python
        "A '### Claim' section names the metric this change will be judged by after deploy: judge whether the diff can move that metric, "
        "and say so in feedback when it cannot. "
```

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest -q tests`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/review.py tests/test_review_claim.py
git commit -m "feat(review): no claim, no judge: a deterministic objection; every verdict is recorded

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 8: The console shows claims and the catalog

**Files:**
- Modify: `scripts/console.py` (`state`, `PAGE`)
- Test: `tests/test_console.py`

**Interfaces:**
- Consumes: `ledger.claims(30)`, `metrics.snapshot(now, repos)`.
- Produces: `state()["claims"]` (list of claim rows) and `state()["catalog"]` (list of snapshot rows); a `Claims` section in the page.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_console.py` (the file's `FakeLedger` is the one to extend; add `claims` to it):

```python
def test_state_carries_claims_and_the_catalog(monkeypatch):
    from fleet import metrics
    led = FakeLedger()
    led.claims = lambda limit=30: [{"fingerprint": "f1", "repo": "o/r", "title": "t", "state": "tested",
                                    "claim": {"metric": "implement_seconds", "direction": "down", "baseline": {"value": 700, "n": 8, "at": 1},
                                              "samples_needed": 8, "after": None, "verdict": None}, "updated_at": None}]
    monkeypatch.setattr(metrics, "snapshot", lambda now, repos=(): [{"metric": "halt_rate_by_class", "scope": {"kind": "fleet", "id": "fleet"},
                                                                     "value": 0.3, "n": 12, "unit": "rate", "direction_good": "down", "samples_needed": 10}])
    s = console.state(gh=FakeGH(), led=led)
    assert s["claims"][0]["claim"]["metric"] == "implement_seconds"
    assert s["catalog"][0]["metric"] == "halt_rate_by_class" and s["catalog"][0]["value"] == 0.3
    assert "id=claims" in console.PAGE and "s.catalog" in console.PAGE
```

Check how `state(gh, led)` uses `led`: if it reads the module-level `ledger` instead of `led`, monkeypatch `console.ledger` to `led` in the test, as the existing console tests do.

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest -q tests/test_console.py -k claims`
Expected: FAIL with `KeyError: 'claims'`.

- [ ] **Step 3: Implement**

In `scripts/console.py`, import `metrics` with the fleet imports. In `state()`, after the `candidates`/`objections` block, add:

```python
    try:
        out["claims"] = [{k: jsonable(v) for k, v in r.items()} for r in ledger.claims(30)]
        repos = tuple(sorted({r["repo"] for r in out["claims"] if r.get("repo")}))[:4]
        out["catalog"] = metrics.snapshot(time.time(), repos)
    except Exception as e:
        out["errors"]["claims"] = str(e)[:200]
```

In `PAGE`, add a section after the Candidates section:

```html
<section style="grid-column:1/-1"><h2>Claims (what each change says it will move, and the catalog it is measured by)</h2><div id=claims></div><div id=catalog></div></section>
```

and in `render(s)`, after the `#cands` line:

```js
 $('#claims').innerHTML=(s.claims||[]).length?(s.claims||[]).map(c=>{const k=c.claim||{},b=k.baseline||{},a=k.after||{};const v=k.verdict||(c.state==='tested'?'awaiting merge':c.state);
   return `<div class=row><span>${esc(c.repo)} · ${esc(c.title)}<br><small>${esc(k.metric)} ${esc(k.direction)} · baseline ${b.value==null?'unknown':Number(b.value).toFixed(2)} (n=${b.n||0}) · after ${a.value==null?'–':Number(a.value).toFixed(2)} (n=${a.n||0}/${k.samples_needed||'?'})</small></span><span class=${v==='improved'?'ok':v==='missed'||v==='regressed'?'bad':''}>${esc(v)}</span></div>`}).join(''):'<small>no claims yet</small>';
 $('#catalog').innerHTML='<h3>Catalog, last 7 days</h3>'+(s.catalog||[]).map(m=>`<div class=row><span class=k>${esc(m.metric)} <small>${esc(m.scope.kind)} ${esc(m.scope.id)}</small></span><span>${m.value==null?'unmeasurable':Number(m.value).toFixed(m.unit==='rate'?2:0)} <small>n=${m.n} · ${esc(m.direction_good)} is good · needs ${m.samples_needed}</small></span></div>`).join('');
```

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest -q tests`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/console.py tests/test_console.py
git commit -m "feat(console): a Claims panel with the catalog's current values

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 9: Ship PR 1 and record its own claim

**Files:**
- None new. The PR itself.

- [ ] **Step 1: Full suite and shell syntax**

Run: `python3 -m pytest -q tests && sh -n scripts/stage.sh`
Expected: all pass (about 200 tests).

- [ ] **Step 2: Compute this PR's baseline by hand**

The verdict table is empty before this PR, so `first_pass_acceptance` has no ledger baseline yet. Use the last seven days of reviewer forum posts as the baseline and say so: 

Run (from the Mac, console port-forwarded on 18080): 
```bash
curl -s localhost:18080/api/state | python3 -c "
import json,sys,re;s=json.load(sys.stdin)
first={}
for p in sorted(s['forum'], key=lambda p:p['id']):
    if p['author']!='reviewer': continue
    m=re.search(r'(new_localai)#(\d+).*?confidence (\d+)', p['body'])
    if m and m.group(2) not in first: first[m.group(2)]=int(m.group(3))
ok=sum(1 for v in first.values() if v>=85); print(f'first-pass acceptance new_localai last posts: {ok}/{len(first)}')"
```
Expected: a line like `first-pass acceptance new_localai last posts: 0/6`.

- [ ] **Step 3: Open the PR**

```bash
git push -u origin feat/observed-outcomes-pr1-claims
gh pr create --title "feat(fleet): claims and the metric catalog (observed outcomes, PR 1 of 4)" --body "$(cat <<'EOF'
Spec: docs/superpowers/specs/2026-09-16-observed-outcomes-design.md, rollout item 1.

Every launch now declares a claim: a catalog metric, a direction and a fleet-computed baseline, stored on the candidate, ending the brief, rendered as `### Claim` in the PR body. The reviewer objects by code to a fleet PR without one and records every verdict in a new `verdict` table so first-pass acceptance accrues from here on. The console shows claims and the catalog. Nothing measures "after" yet; that is PR 2.

### Claim
CLAIM: first_pass_acceptance up for repo ctkadvisors/new_localai; baseline <value from Step 2> (n=<n>)
Judged after deploy: first-pass acceptance on new_localai does not fall once claims are required (a falling rate would mean the gate rejects work the judge would have accepted).

Tests: pytest tests (all), sh -n stage.sh.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 4: Watch CI, merge when green, confirm the ship**

```bash
gh pr checks --watch
gh pr merge --squash --delete-branch
gh run list --branch main --limit 1
kubectl get cronjob -n kagent-system fleet-reconcile -o jsonpath='{.spec.jobTemplate.spec.template.spec.containers[0].image}{"\n"}'
```
Expected: the image tag on the CronJob is the new ship tag. Then confirm on the console that `/api/state` has `claims` and `catalog` keys, and that the next fleet launch's forum post carries a brief ending in `CLAIM:`.

- [ ] **Step 5: Record the handoff**

Append to the memory handoff note the ship tag, the baseline from Step 2, and that PR 2 (deployed detection and judging) is next, with the note that `tokens_per_stage`, `canary_uptime` and `idea_novelty` are intentionally absent from the catalog until PRs 3 and 4.

---

## Self-review against the spec

- Principle 2 (every launch declares): Tasks 3, 4, 5 cover idea, human brief, review round (via admit with `review=True`), improve run. Covered.
- Gates that change: ideate (Task 3), launch paths (4, 5), publish (6), review (7). Covered.
- Surfacing, console part: Task 8. Digest and forum posts per verdict are PR 2 (they need verdicts). Deferred by design, stated in the plan header.
- Catalog v1: eight of ten deterministic metrics; `tokens_per_stage` and `canary_uptime` need capture (PR 3/4), stated in Task 2's code comment and Task 9. `idea_novelty` is PR 4.
- Small-models constraint: the only prompt growth is one `CLAIM:` line (stage.sh, Task 5) and one sentence in the judge (Task 7). `QUINTET_SHAPE` gains two JSON fields. Covered.
- Model-agnostic: no rule branches on the model. Covered.
- Type consistency: `claim_for(metric, direction, scope, now)`, `default_claim(repo, fp, now)`, `claim_line(claim)`, `parse_claim_line(text)`, `snapshot(now, repos)`, `ledger.set_claim(fp, claim)`, `ledger.claim_of(fp)`, `ledger.claims(limit)`, `ledger.record_verdict(repo, pr_url, sha, confidence, first, merged_bar)` are used with the same names and argument orders in Tasks 3 to 8.
