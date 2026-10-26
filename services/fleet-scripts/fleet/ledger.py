"""The fleet ledger: the structured record of what the fleet considered,
did, and what came of it. Postgres (the shared in-cluster instance,
database `fleet`), pure-Python driver so the alpine image stays small.

Chris, 2026-09-04: "where is our ideation/task log?" There was none - verdicts
lived in PR comments, Telegram and pod-local JSON. GitHub issues are the
human-visible queue (a label is a decision); this is the store behind them:
fingerprints so an idea is filed once, runs with their stage timings and halt
bundles, decisions with their veto windows, outcomes observed after deploy.
Codex's review (docs/superpowers/specs/2026-09-04-idle-improvement-codex-
review.md) asked for exactly this, outside the graph. The brain mirrors it;
it never owns it.

Connection: LEDGER_DSN env, or /secrets/ledger/dsn. Every function is a
single short transaction; callers treat failures as non-fatal and log them,
the way brain.add_episode is treated - the ledger must never take a run down.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from contextlib import contextmanager

DSN_FILE = os.environ.get("LEDGER_DSN_FILE", "/secrets/ledger/dsn")

SCHEMA = """
CREATE TABLE IF NOT EXISTS candidate (
  fingerprint  TEXT PRIMARY KEY,
  repo         TEXT NOT NULL,
  title        TEXT NOT NULL,
  source       TEXT NOT NULL,            -- halt | reviewer | digest | auditor | human | improve | tool-gap
  risk_tier    SMALLINT NOT NULL DEFAULT 1,
  evidence     JSONB NOT NULL DEFAULT '{}'::jsonb,
  target_metric TEXT,
  state        TEXT NOT NULL DEFAULT 'proposed',  -- proposed selected attempted tested reviewed merged deployed observed rejected duplicate halted rolled_back no_effect declined
  issue_url    TEXT,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS run (
  id           TEXT PRIMARY KEY,           -- the Job name
  pipeline     TEXT NOT NULL,              -- improve | mission
  repo         TEXT NOT NULL,
  fingerprint  TEXT REFERENCES candidate(fingerprint),
  trigger      TEXT NOT NULL,              -- idle | cron | concierge | triage | human
  started_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  finished_at  TIMESTAMPTZ,
  outcome      TEXT,                       -- shipped | halted | quiet
  halt         JSONB,                      -- the stop bundle
  timing       JSONB,                      -- per-stage seconds
  pr_url       TEXT,
  cost         JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE TABLE IF NOT EXISTS decision (
  id           BIGSERIAL PRIMARY KEY,
  run_id       TEXT REFERENCES run(id),
  fingerprint  TEXT REFERENCES candidate(fingerprint),
  action       TEXT NOT NULL,              -- implement | merge | deploy | tool-activate | rails-change
  risk_tier    SMALLINT NOT NULL,
  decided_by   TEXT NOT NULL,              -- policy | human:<login>
  veto_until   TIMESTAMPTZ,                -- null = no window (tier 0) or already past
  vetoed_by    TEXT,
  vetoed_at    TIMESTAMPTZ,
  rationale    TEXT,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS outcome (
  id           BIGSERIAL PRIMARY KEY,
  fingerprint  TEXT REFERENCES candidate(fingerprint),
  run_id       TEXT REFERENCES run(id),
  observed_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  obs_window   TEXT NOT NULL,              -- merge | 24h | 7d   (`window` is reserved in Postgres)
  metric       TEXT,
  before_value DOUBLE PRECISION,
  after_value  DOUBLE PRECISION,
  recurred     BOOLEAN,
  rolled_back  BOOLEAN,
  note         TEXT
);
CREATE TABLE IF NOT EXISTS scheduler (
  key          TEXT PRIMARY KEY,           -- 'lease' | 'budget:<date>' | 'last_run'
  value        JSONB NOT NULL,
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS post (
  id           BIGSERIAL PRIMARY KEY,     -- the forum: the fleet's sanctioned message board
  topic        TEXT NOT NULL DEFAULT 'note',  -- status | idea | question | repair | answer | note
  author       TEXT NOT NULL,             -- reconcile | reviewer | implementer | concierge | chris | ...
  body         TEXT NOT NULL,
  ref          TEXT,                      -- a PR, issue or run the post is about
  mentions     TEXT[] NOT NULL DEFAULT '{}',  -- roles asked to read it
  parent_id    BIGINT REFERENCES post(id),
  answered_at  TIMESTAMPTZ,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS post_created_idx ON post(created_at DESC);
CREATE TABLE IF NOT EXISTS lesson (
  key          TEXT PRIMARY KEY,           -- fingerprint(kind, repo, text): the same thing learned twice weighs more
  kind         TEXT NOT NULL,              -- feedback | lesson | fact   (fleet/memory.py)
  repo         TEXT,                       -- NULL = every repo
  text         TEXT NOT NULL,
  ref          TEXT,                       -- the PR, issue, run or post it came from
  source       TEXT NOT NULL,              -- chris | publish | review | reconcile | implementer | claude
  weight       INT NOT NULL DEFAULT 1,
  retired_at   TIMESTAMPTZ,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS lesson_repo_idx ON lesson(repo, kind);
CREATE INDEX IF NOT EXISTS candidate_state_idx ON candidate(state);
CREATE INDEX IF NOT EXISTS run_started_idx ON run(started_at DESC);
"""


def fingerprint(*parts: str) -> str:
    return hashlib.sha1("|".join(p.strip().lower() for p in parts).encode()).hexdigest()[:12]


def mission_candidate(repo: str, brief: str) -> tuple[str, str, str | None]:
    """(fingerprint, title, issue_url) of a mission: its issue when triage wrote the
    brief ('GitHub issue <url> — <title>'), else the brief's text. The launcher
    and publish agree on this, so seven launches of one issue are one candidate."""
    import re
    m = re.match(r"GitHub issue (\S+) — ([^\n]*)", brief)
    if m:
        return fingerprint(repo, "issue", m.group(1)), m.group(2).strip()[:300], m.group(1)
    return fingerprint(repo, brief[:200]), brief.splitlines()[0][:300], None


def dsn() -> str:
    return os.environ.get("LEDGER_DSN") or open(DSN_FILE).read().strip()


@contextmanager
def connect():
    import sys
    vendor = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "vendor")
    if os.path.isdir(vendor) and vendor not in sys.path:
        sys.path.insert(0, vendor)  # pg8000 ships in the image under /app/vendor (see Dockerfile)
    import pg8000.dbapi  # imported lazily: tests and stages that never touch the ledger need no driver
    from urllib.parse import urlparse, unquote
    u = urlparse(dsn())
    conn = pg8000.dbapi.connect(user=unquote(u.username or ""), password=unquote(u.password or ""),
                                host=u.hostname, port=u.port or 5432, database=(u.path or "/fleet").lstrip("/"))
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def migrate() -> None:
    with connect() as c:
        cur = c.cursor()
        for stmt in [s for s in SCHEMA.split(";") if s.strip()]:
            cur.execute(stmt)


def upsert_candidate(fp: str, repo: str, title: str, source: str, risk_tier: int = 1,
                     evidence: dict | None = None, target_metric: str | None = None, issue_url: str | None = None) -> None:
    with connect() as c:
        c.cursor().execute(
            "INSERT INTO candidate (fingerprint, repo, title, source, risk_tier, evidence, target_metric, issue_url) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (fingerprint) DO UPDATE SET "
            "evidence = candidate.evidence || EXCLUDED.evidence, issue_url = COALESCE(EXCLUDED.issue_url, candidate.issue_url), updated_at = now()",
            (fp, repo, title[:300], source, risk_tier, json.dumps(evidence or {}), target_metric, issue_url))


def park(fp: str) -> None:
    """Decline a candidate that keeps failing; a merged or observed one is left as it is."""
    with connect() as c:
        c.cursor().execute("UPDATE candidate SET state='declined', updated_at=now() WHERE fingerprint=%s "
                           "AND state NOT IN ('merged','observed','rolled_back','deployed')", (fp,))


def set_state(fp: str, state: str) -> None:
    with connect() as c:
        c.cursor().execute("UPDATE candidate SET state=%s, updated_at=now() WHERE fingerprint=%s", (state, fp))


def start_run(run_id: str, pipeline: str, repo: str, trigger: str, fp: str | None = None) -> None:
    with connect() as c:
        c.cursor().execute(
            "INSERT INTO run (id, pipeline, repo, fingerprint, trigger) VALUES (%s,%s,%s,%s,%s) ON CONFLICT (id) DO NOTHING",
            (run_id, pipeline, repo, fp, trigger))


def finish_run(run_id: str, outcome: str, halt: dict | None = None, timing: dict | None = None,
               pr_url: str | None = None, pipeline: str = "mission", repo: str = "", trigger: str = "unknown",
               fp: str | None = None, cost: dict | None = None) -> None:
    with connect() as c:
        cur = c.cursor()
        cur.execute("INSERT INTO run (id, pipeline, repo, trigger, fingerprint) VALUES (%s,%s,%s,%s,%s) ON CONFLICT (id) DO NOTHING",
                    (run_id, pipeline, repo, trigger, fp))
        cur.execute("UPDATE run SET finished_at=now(), outcome=%s, halt=%s, timing=%s, pr_url=%s, "
                    "fingerprint=COALESCE(%s, fingerprint), cost=%s WHERE id=%s",
                    (outcome, json.dumps(halt) if halt else None, json.dumps(timing) if timing else None, pr_url, fp,
                     json.dumps(cost or {}), run_id))


def mark_pr(pr_url: str, state: str) -> None:
    """Move the candidate behind a PR (by the run that opened it) to a new state.
    'merged' also opens the outcome trail: an outcome row for the merge window,
    which observe_outcomes (reconcile) follows up at 24h and 7d."""
    with connect() as c:
        cur = c.cursor()
        cur.execute("UPDATE candidate SET state=%s, updated_at=now() "
                    "WHERE fingerprint IN (SELECT fingerprint FROM run WHERE pr_url=%s)", (state, pr_url))
        if state == "merged":
            cur.execute("INSERT INTO outcome (fingerprint, run_id, obs_window, note) "
                        "SELECT fingerprint, id, 'merge', %s FROM run WHERE pr_url=%s ORDER BY started_at DESC LIMIT 1",
                        (f"merged {pr_url}", pr_url))


def attempts(fp: str, active_within_seconds: int = 3 * 3600) -> tuple[int, str | None]:
    """(attempts so far for this candidate, the id of one still running or None).
    A review round (trigger 'review') is progress on an open PR, not another
    try at a halt, so it does not count toward MAX_ATTEMPTS: brutalist_todo#23
    was parked at 02:55 on 2026-09-07 after one halt and two review rounds."""
    with connect() as c:
        cur = c.cursor()
        cur.execute("SELECT count(*) FILTER (WHERE trigger <> 'review'), "
                    "max(id) FILTER (WHERE finished_at IS NULL AND started_at > now() - make_interval(secs => %s)) "
                    "FROM run WHERE fingerprint=%s", (active_within_seconds, fp))
        n, running = cur.fetchone()
        return int(n), running


def pending_outcomes(window: str, days: int) -> list[dict]:
    """Merged candidates whose merge is older than `days` and have no `window` outcome yet."""
    with connect() as c:
        cur = c.cursor()
        cur.execute(
            "SELECT c.fingerprint, o.run_id, o.observed_at, r.repo, r.pr_url FROM candidate c "
            "JOIN outcome o ON o.fingerprint=c.fingerprint AND o.obs_window='merge' "
            "JOIN run r ON r.id=o.run_id "
            "WHERE c.state IN ('merged','observed') AND o.observed_at < now() - make_interval(days => %s) "
            "AND NOT EXISTS (SELECT 1 FROM outcome x WHERE x.fingerprint=c.fingerprint AND x.obs_window=%s)",
            (days, window))
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def runs_since(fp: str, since) -> int:
    """Attempts at the same candidate after a moment: the recurrence signal."""
    with connect() as c:
        cur = c.cursor()
        cur.execute("SELECT count(*) FROM run WHERE fingerprint=%s AND started_at > %s", (fp, since))
        return int(cur.fetchone()[0])


def record_decision(action: str, risk_tier: int, decided_by: str, rationale: str, run_id: str | None = None,
                    fp: str | None = None, veto_seconds: int | None = None) -> int:
    try:
        return _insert_decision(action, risk_tier, decided_by, rationale, run_id, fp, veto_seconds)
    except Exception as e:
        # 23503: the run row is not there (the launcher's start_run failed and it
        # said 201 anyway). A decision is telemetry; it must never kill the tick
        # that already launched the run (fleet-reconcile-29821830-cv87k, 2026-09-13
        # 14:30Z, mission-...-de90). Keep the decision, name the orphan.
        if run_id and "23503" in str(e):
            return _insert_decision(action, risk_tier, decided_by, f"{rationale} (run {run_id} has no ledger row)", None, fp, veto_seconds)
        raise


def _insert_decision(action, risk_tier, decided_by, rationale, run_id, fp, veto_seconds) -> int:
    with connect() as c:
        cur = c.cursor()
        # veto_until computed here: pg8000 cannot type a NULL parameter inside
        # CASE/make_interval ("could not determine data type"), so the window
        # end is a plain timestamptz or NULL.
        from datetime import datetime, timedelta, timezone
        veto_until = (datetime.now(timezone.utc) + timedelta(seconds=veto_seconds)) if veto_seconds else None
        cur.execute(
            "INSERT INTO decision (run_id, fingerprint, action, risk_tier, decided_by, rationale, veto_until) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id",
            (run_id, fp, action, risk_tier, decided_by, rationale[:2000], veto_until))
        return int(cur.fetchone()[0])


def vetoed(decision_id: int) -> bool:
    with connect() as c:
        cur = c.cursor()
        cur.execute("SELECT vetoed_at IS NOT NULL FROM decision WHERE id=%s", (decision_id,))
        row = cur.fetchone()
        return bool(row and row[0])


def veto(decision_id: int, who: str) -> None:
    with connect() as c:
        c.cursor().execute("UPDATE decision SET vetoed_by=%s, vetoed_at=now() WHERE id=%s AND vetoed_at IS NULL", (who, decision_id))


def record_outcome(fp: str | None, run_id: str | None, window: str, metric: str | None = None,
                   before: float | None = None, after: float | None = None, recurred: bool | None = None,
                   rolled_back: bool | None = None, note: str = "") -> None:
    with connect() as c:
        c.cursor().execute(
            "INSERT INTO outcome (fingerprint, run_id, obs_window, metric, before_value, after_value, recurred, rolled_back, note) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)", (fp, run_id, window, metric, before, after, recurred, rolled_back, note[:1000]))


def halted_candidates() -> list[dict]:
    """Human-requested candidates whose last attempt halted and that were not
    parked: the board the scheduler retries before it speculates. Oldest first."""
    with connect() as c:
        cur = c.cursor()
        cur.execute("SELECT fingerprint, repo, title, issue_url FROM candidate "
                    "WHERE state='halted' AND source='human' AND issue_url IS NOT NULL ORDER BY updated_at")
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def merged_runs(trigger: str, limit: int = 20) -> list[dict]:
    """Runs of one trigger whose PR was merged (candidate state merged/observed),
    newest first, with the candidate's updated_at as the merge time."""
    with connect() as c:
        cur = c.cursor()
        cur.execute("SELECT r.id, r.repo, r.pr_url, c.updated_at FROM run r JOIN candidate c ON c.fingerprint = r.fingerprint "
                    "WHERE r.trigger = %s AND r.pr_url IS NOT NULL AND c.state IN ('merged','observed','deployed') "
                    "ORDER BY c.updated_at DESC LIMIT %s", (trigger, limit))
        return [{"id": r[0], "repo": r[1], "pr_url": r[2], "merged_at": str(r[3])} for r in cur.fetchall()]


def run_for_pr(pr_url: str) -> dict | None:
    """The newest run that opened this PR (id, trigger, repo), or None."""
    with connect() as c:
        cur = c.cursor()
        cur.execute("SELECT id, trigger, repo FROM run WHERE pr_url=%s ORDER BY started_at DESC LIMIT 1", (pr_url,))
        r = cur.fetchone()
        return {"id": r[0], "trigger": r[1], "repo": r[2]} if r else None


def recent_runs(limit: int = 10) -> list[dict]:
    """The newest runs, one per candidate (its latest attempt), with the candidate's
    title and state. Runs without a fingerprint count as their own candidate."""
    with connect() as c:
        cur = c.cursor()
        cur.execute(
            "SELECT DISTINCT ON (COALESCE(r.fingerprint, r.id)) r.id, r.pipeline, r.repo, r.trigger, r.outcome, "
            "r.fingerprint, r.started_at, r.finished_at, r.pr_url, r.halt, r.cost, c.title, c.state, "
            "(SELECT jsonb_build_object('window', o.obs_window, 'recurred', o.recurred, 'rolled_back', o.rolled_back) "
            " FROM outcome o WHERE o.fingerprint = r.fingerprint ORDER BY o.observed_at DESC LIMIT 1) AS observed "
            "FROM run r LEFT JOIN candidate c ON c.fingerprint = r.fingerprint "
            "ORDER BY COALESCE(r.fingerprint, r.id), r.started_at DESC")
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, row)) for row in cur.fetchall()]
    rows.sort(key=lambda r: r["started_at"], reverse=True)
    return rows[:limit]


def kv_get(key: str):
    with connect() as c:
        cur = c.cursor()
        cur.execute("SELECT value FROM scheduler WHERE key=%s", (key,))
        row = cur.fetchone()
        return row[0] if row else None


def kv_set(key: str, value) -> None:
    with connect() as c:
        c.cursor().execute("INSERT INTO scheduler (key, value) VALUES (%s,%s) ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, updated_at=now()",
                           (key, json.dumps(value)))


def try_lease(holder: str, ttl_seconds: int = 3600) -> bool:
    """One scheduler at a time: take the lease if free or expired. Atomic in one statement."""
    now = time.time()
    with connect() as c:
        cur = c.cursor()
        cur.execute(
            "INSERT INTO scheduler (key, value) VALUES ('lease', %s) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now() "
            "WHERE (scheduler.value->>'expires')::double precision < %s OR scheduler.value->>'holder' = %s RETURNING value->>'holder'",
            (json.dumps({"holder": holder, "expires": now + ttl_seconds}), now, holder))
        row = cur.fetchone()
        return bool(row and row[0] == holder)


def release_lease(holder: str) -> None:
    with connect() as c:
        c.cursor().execute("UPDATE scheduler SET value = jsonb_build_object('holder','', 'expires', 0), updated_at=now() "
                           "WHERE key='lease' AND value->>'holder'=%s", (holder,))


def kv_like(pattern: str) -> list[tuple[str, dict]]:
    with connect() as c:
        cur = c.cursor()
        cur.execute("SELECT key, value FROM scheduler WHERE key LIKE %s ORDER BY updated_at", (pattern,))
        return [(k, v if isinstance(v, dict) else json.loads(v)) for k, v in cur.fetchall()]


def kv_delete(key: str) -> None:
    with connect() as c:
        c.cursor().execute("DELETE FROM scheduler WHERE key=%s", (key,))


def get_run(run_id: str) -> dict | None:
    """One run's own verdict: outcome (shipped/halted), halt, pr_url. None when
    the ledger never heard of it."""
    with connect() as c:
        cur = c.cursor()
        cur.execute("SELECT id, pipeline, repo, trigger, outcome, halt, pr_url, started_at, finished_at FROM run WHERE id=%s", (run_id,))
        row = cur.fetchone()
        if not row:
            return None
        r = dict(zip([d[0] for d in cur.description], row))
        if isinstance(r.get("halt"), str):
            try:
                r["halt"] = json.loads(r["halt"])
            except ValueError:
                r["halt"] = {"reason": r["halt"]}
        return r


# --- the forum -----------------------------------------------------------
# Chris, 2026-09-06: "the agents need an internal forum to communicate ...
# they're little people and need people skills". OpenAI's Hugging Face report
# showed agents building their own message board when denied one; this is the
# sanctioned one: external memory, requests for help, hand-offs, disagreement,
# all on the console where a human can read it. fleet/voice.txt is how to talk.

def voice() -> str:
    try:
        return open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "voice.txt")).read().strip()
    except OSError:
        return ""


def post(author: str, body: str, topic: str = "note", ref: str | None = None,
         mentions=(), parent_id: int | None = None) -> int:
    with connect() as c:
        cur = c.cursor()
        if parent_id and not ref:  # a reply belongs to the thread's subject
            cur.execute("SELECT ref FROM post WHERE id=%s", (parent_id,))
            row = cur.fetchone()
            ref = row[0] if row else None
        # %s::text[]: a reply usually mentions nobody, and pg8000 cannot type an
        # empty array on its own (ProgrammingError on every reply, 2026-09-06 22:05Z).
        cur.execute("INSERT INTO post (topic, author, body, ref, mentions, parent_id) VALUES (%s,%s,%s,%s,%s::text[],%s) RETURNING id",
                    (topic[:32], author[:64], body[:4000], ref, list(mentions or ()), parent_id))
        new_id = int(cur.fetchone()[0])  # read RETURNING before any further statement: the UPDATE below has no rows
        if parent_id:
            cur.execute("UPDATE post SET answered_at=now() WHERE id=%s AND answered_at IS NULL", (parent_id,))
    said = body if author == "chris" else (body[len("Chris says:"):].strip() if author == "concierge" and body.startswith("Chris says:") else None)
    if said and topic in ("note", "idea", "question", "answer"):
        # Whatever Chris says on the forum is kept (fleet/memory.py): a reply on a PR
        # thread is scoped to that repo, anything else is global. The concierge relays
        # his Telegram instructions as "Chris says: ..." (2026-09-09); those stay rules
        # (always recalled). A post he types on the forum is kept as a lesson, recalled
        # when relevant: "Ok" (x10) and a vented question rode every stage prompt as
        # rules until 2026-09-15.
        from . import memory  # lazy: memory imports this module
        import re as _re
        m = _re.search(r"github\.com/([\w.-]+/[\w.-]+)/", ref or "")
        memory.remember("feedback" if author == "concierge" else "lesson", said, repo=m.group(1) if m else None, ref=ref, source="chris")
    return new_id


def say(author: str, body: str, **kw) -> int | None:
    """post() that never takes a run down: the forum being unreachable is a log line."""
    try:
        return post(author, body, **kw)
    except Exception as e:
        print(f"forum: could not post as {author}: {type(e).__name__}: {str(e)[:80]}")
        return None


def posts(limit: int = 50, topic: str | None = None, ref: str | None = None, unanswered: bool = False) -> list[dict]:
    where, args = [], []
    if topic:
        where.append("topic=%s"); args.append(topic)
    if ref:
        where.append("ref=%s"); args.append(ref)
    if unanswered:
        where.append("answered_at IS NULL AND parent_id IS NULL")
    sql = "SELECT id, topic, author, body, ref, mentions, parent_id, answered_at, created_at FROM post"
    sql += (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY created_at DESC LIMIT %s"
    with connect() as c:
        cur = c.cursor()
        cur.execute(sql, (*args, limit))
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def thread(ids: list[int]) -> list[dict]:
    """The posts with these ids and every reply to them: the rest of the
    threads a page of recent posts only shows a piece of."""
    if not ids:
        return []
    with connect() as c:
        cur = c.cursor()
        cur.execute("SELECT id, topic, author, body, ref, mentions, parent_id, answered_at, created_at FROM post "
                    "WHERE id = ANY(%s) OR parent_id = ANY(%s)", (list(ids), list(ids)))
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def inbox(role: str, limit: int = 10) -> list[dict]:
    """Unanswered posts addressed to a role, oldest first: what it reads before it acts."""
    with connect() as c:
        cur = c.cursor()
        cur.execute("SELECT id, topic, author, body, ref, mentions, created_at FROM post "
                    "WHERE %s = ANY(mentions) AND answered_at IS NULL AND author <> %s ORDER BY created_at LIMIT %s",
                    (role, role, limit))
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def answered(post_id: int) -> None:
    with connect() as c:
        c.cursor().execute("UPDATE post SET answered_at=now() WHERE id=%s", (post_id,))


def open_questions(ref: str) -> list[dict]:
    """Unanswered `question` posts about a subject (an issue or PR URL): the
    implementer asked, nobody replied yet. Board-first waits on these."""
    with connect() as c:
        cur = c.cursor()
        cur.execute("SELECT id, author, body, mentions, created_at FROM post WHERE topic='question' AND ref=%s "
                    "AND parent_id IS NULL AND answered_at IS NULL ORDER BY created_at", (ref,))
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def last_run(fp: str) -> dict | None:
    """The candidate's newest run: outcome, halt, pr_url, started_at."""
    with connect() as c:
        cur = c.cursor()
        cur.execute("SELECT id, trigger, outcome, halt, pr_url, started_at, finished_at FROM run WHERE fingerprint=%s "
                    "ORDER BY started_at DESC LIMIT 1", (fp,))
        row = cur.fetchone()
        if not row:
            return None
        r = dict(zip([d[0] for d in cur.description], row))
        if isinstance(r.get("halt"), str):
            try:
                r["halt"] = json.loads(r["halt"])
            except ValueError:
                r["halt"] = {"reason": r["halt"]}
        return r


def last_pr_url(fp: str) -> str | None:
    """The newest PR this candidate opened, whatever its latest run did. A halted
    review round has no pr_url of its own; the PR it worked on is still open
    (2026-09-07 04:55: mission 23 relaunched on a fresh branch for that reason)."""
    with connect() as c:
        cur = c.cursor()
        cur.execute("SELECT pr_url FROM run WHERE fingerprint=%s AND pr_url IS NOT NULL ORDER BY started_at DESC LIMIT 1", (fp,))
        row = cur.fetchone()
        return row[0] if row else None


def review_rounds(pr_url: str) -> int:
    """Review rounds (trigger 'review') that ran on this PR."""
    with connect() as c:
        cur = c.cursor()
        cur.execute("SELECT count(*) FROM run WHERE pr_url=%s AND trigger='review'", (pr_url,))
        return int(cur.fetchone()[0])


def runs_by_trigger(fp: str, trigger: str) -> int:
    with connect() as c:
        cur = c.cursor()
        cur.execute("SELECT count(*) FROM run WHERE fingerprint=%s AND trigger=%s", (fp, trigger))
        return int(cur.fetchone()[0])


def tested_candidates() -> list[dict]:
    """Candidates with a PR open (state tested) and their newest run: what the
    reviewer may have objected to and nobody has iterated on."""
    with connect() as c:
        cur = c.cursor()
        cur.execute(
            "SELECT c.fingerprint, c.repo, c.issue_url, c.source, r.id AS run_id, r.pr_url, r.started_at, r.trigger "
            "FROM candidate c JOIN LATERAL (SELECT id, pr_url, started_at, trigger FROM run WHERE fingerprint=c.fingerprint "
            "ORDER BY started_at DESC LIMIT 1) r ON true WHERE c.state='tested' AND r.pr_url IS NOT NULL ORDER BY r.started_at")
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def unfinished_runs() -> list[dict]:
    """Runs that started and never finished: a Job the pipeline never got to
    publish (killed stage, OOM, deadline). reconcile reaps these."""
    with connect() as c:
        cur = c.cursor()
        cur.execute("SELECT id, pipeline, repo, fingerprint, trigger, started_at FROM run WHERE finished_at IS NULL ORDER BY started_at")
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]
