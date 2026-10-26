"""What the fleet has learned, written by the fleet, read before it acts.

Chris, 2026-09-08: "act as the parent/mentor, lay the foundation for it to
become a mini-you." Until now a halt produced a bundle, a review produced an
objection, a rollback produced an outcome row, and none of it changed what the
next run did: every run started as a stranger. This is the fleet's memory in
the shape Claude's own works: one fact per row, a kind, a scope, why it
matters, recalled by relevance and handed to every role before it acts.

Kinds:
  feedback  a rule from Chris (or the mentor) about how to work; always recalled
  lesson    what a halt, an objection or a rollback taught; recalled by relevance
  fact      something true about a repo or the environment; recalled by relevance

Writers: publish (halts, the implementer's LESSON lines), review (objections),
reconcile (rollbacks), the forum (anything Chris posts), the seed (the mentor's
hand-down). Readers: every stage prompt (stage.sh), the reviewer's judge
prompt, the concierge (fleet.memory on GET /missions).

The ledger owns the rows (table `lesson`); the brain mirrors them like
everything else. Recall is a small ranked query, not a model call: the point
is that remembering costs nothing and never lies.
"""

from __future__ import annotations

import re
import time

from . import ledger

KINDS = ("feedback", "lesson", "fact")
STOP = set("the a an and or of to in on for with is are was were be by at as it this that from not no do does "
           "did into over after before when while which who what how why its their our your they them we you i".split())


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9][a-z0-9_.:/#-]{2,}", (text or "").lower()) if w not in STOP}


def key(kind: str, repo: str | None, text: str) -> str:
    return ledger.fingerprint(kind, repo or "*", text[:200])


def remember(kind: str, text: str, repo: str | None = None, ref: str | None = None, source: str = "fleet") -> str | None:
    """Store one thing; the same thing again raises its weight instead of a
    duplicate row. Never takes a run down: a failure is a log line."""
    if kind not in KINDS or not (text or "").strip():
        return None
    text = " ".join(text.split())[:600]
    k = key(kind, repo, text)
    try:
        with ledger.connect() as c:
            cur = c.cursor()
            cur.execute(
                "INSERT INTO lesson (key, kind, repo, text, ref, source) VALUES (%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (key) DO UPDATE SET weight = lesson.weight + 1, ref = COALESCE(EXCLUDED.ref, lesson.ref), "
                "retired_at = NULL, updated_at = now()",
                (k, kind, repo, text, ref, source[:32]))
        return k
    except Exception as e:
        print(f"memory: could not remember ({type(e).__name__}: {str(e)[:80]})")
        return None


def retire(k: str) -> None:
    with ledger.connect() as c:
        c.cursor().execute("UPDATE lesson SET retired_at = now() WHERE key=%s", (k,))


def stats(days: int = 7) -> dict:
    """How much the fleet has written itself (new_localai#67): rows by source
    and rows from fleet roles in the last `days`. The seed is source claude."""
    with ledger.connect() as c:
        cur = c.cursor()
        cur.execute("SELECT source, count(*) FROM lesson WHERE retired_at IS NULL GROUP BY source")
        by_source = {r[0]: int(r[1]) for r in cur.fetchall()}
        cur.execute("SELECT count(*) FROM lesson WHERE retired_at IS NULL AND source NOT IN ('claude','chris') "
                    "AND created_at > now() - (%s * interval '1 day')", (days,))
        fleet_recent = int(cur.fetchone()[0])
        # Did a lesson change a later run (new_localai#67)? For every halt a run
        # distilled into a lesson: how many later runs on that repo halted at the
        # same stage for the same reason. 0 repeats is the memory working.
        cur.execute(
            "SELECT count(*) FILTER (WHERE rep.n > 0), count(*) FROM ("
            " SELECT l.key, (SELECT count(*) FROM run r2 WHERE r2.repo = r.repo AND r2.started_at > l.created_at"
            "  AND r2.halt->>'stage' = r.halt->>'stage' AND left(r2.halt->>'reason', 60) = left(r.halt->>'reason', 60)) AS n"
            " FROM lesson l JOIN run r ON r.id = l.ref"
            " WHERE l.source = 'publish' AND l.retired_at IS NULL AND r.halt IS NOT NULL) rep")
        repeated, halt_lessons = (int(x) for x in cur.fetchone())
        # The rows themselves, so "what did the fleet write" is answered from the
        # field: asked on Telegram (2026-09-09 20:00Z) with only the counts in
        # front of it, the concierge invented a list with authors that do not exist.
        cur.execute("SELECT source, to_char(created_at, 'YYYY-MM-DD'), left(text, 200) FROM lesson "
                    "WHERE retired_at IS NULL AND source NOT IN ('claude','chris') "
                    "AND created_at > now() - (%s * interval '1 day') ORDER BY created_at DESC LIMIT 12", (days,))
        recent = [{"source": r[0], "at": r[1], "text": r[2]} for r in cur.fetchall()]
    return {"rows": sum(by_source.values()), "by_source": by_source, "fleet_written_recent": fleet_recent, "days": days,
            "halt_lessons": halt_lessons, "repeated_after_lesson": repeated, "recent": recent}


def rows(repo: str | None = None, limit: int = 400) -> list[dict]:
    """Active rows for a repo plus the global ones (repo NULL), newest first."""
    with ledger.connect() as c:
        cur = c.cursor()
        cur.execute("SELECT key, kind, repo, text, ref, source, weight, created_at FROM lesson "
                    "WHERE retired_at IS NULL AND (repo IS NULL OR repo = %s) ORDER BY created_at DESC LIMIT %s",
                    (repo, limit))
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def rank(items: list[dict], context: str = "", limit: int = 12, now: float | None = None) -> list[dict]:
    """Every feedback row (rules are not optional and do not count against
    the limit: eight rules once crowded a stage down to four lessons), then
    the `limit` lessons and facts that share the most words with the context,
    weighted by how often they were learned and how recent they are."""
    now = now or time.time()
    ctx = _words(context)
    feedback = [r for r in items if r["kind"] == "feedback"]
    rest = []
    for r in items:
        if r["kind"] == "feedback":
            continue
        overlap = len(ctx & _words(r["text"])) if ctx else 0
        age_days = max(0.0, (now - _ts(r.get("created_at"))) / 86400)
        score = overlap * 3 + min(int(r.get("weight") or 1), 5) + (2 if age_days < 3 else 1 if age_days < 14 else 0)
        if r.get("repo"):
            score += 1  # a repo-specific note beats a global one at equal relevance
        rest.append((score, r))
    rest.sort(key=lambda x: -x[0])
    return feedback + [r for s, r in rest[:limit]]


def _ts(v) -> float:
    if v is None:
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return v.timestamp()
    except Exception:
        return 0.0


def render(items: list[dict], title: str = "WHAT WE HAVE LEARNED (read before acting; from Chris, past runs and the mentor)") -> str:
    if not items:
        return ""
    lines = []
    for r in items:
        scope = r.get("repo") or "all repos"
        ref = f" ({r['ref']})" if r.get("ref") else ""
        lines.append(f"- [{r['kind']}, {scope}] {r['text']}{ref}")
    return title + ":\n" + "\n".join(lines)


def recall(repo: str | None, context: str = "", limit: int = 12) -> str:
    """The block a role reads before it acts. Empty string when the ledger is
    unreachable: memory never takes a run down either."""
    try:
        return render(rank(rows(repo), context, limit))
    except Exception as e:
        print(f"memory: recall unavailable ({type(e).__name__})")
        return ""


def distill_halt(stopped: dict, brief: str = "") -> str:
    """One line a future run can use, from a halt bundle: where it stopped,
    why, and what the run itself said would unblock it."""
    stage, reason = str(stopped.get("stage", "?")), str(stopped.get("reason", "?"))
    tail = " ".join(str(stopped.get("log_tail") or "").split())
    unblock = ""
    m = re.search(r"(?:what would unblock me|unblock(?:ed)? by|to unblock)[:\s]+(.{20,200})", tail, re.I)
    if m:
        unblock = " Unblock: " + m.group(1).strip()
    task = (" Task: " + " ".join(brief.split())[:120]) if brief else ""
    return f"A run halted at {stage}: {reason[:160]}.{unblock}{task}"


def lessons_in(markdown: str) -> list[str]:
    """`LESSON: ...` lines a stage wrote in its report: what it wants the next
    run to know. One line each, the model's own words."""
    out: list[str] = []
    cur: list[str] | None = None
    for line in (markdown or "").splitlines():
        m = re.match(r"\s*(?:[-*]\s*)?LESSON:\s*(.+)", line)
        if m:
            if cur: out.append(" ".join(cur))
            cur = [m.group(1).strip()]
        elif cur is not None and line.strip() and not re.match(r"\s*(?:[-*]\s|#)", line):
            cur.append(line.strip())   # a wrapped continuation of the lesson (2026-09-09: eight fragments in memory)
        else:
            if cur: out.append(" ".join(cur))
            cur = None
    if cur: out.append(" ".join(cur))
    return [l[:400] for l in out if len(l) > 12][:5]


def used_in(markdown: str) -> list[str]:
    """`USED: ...` lines a stage wrote: the lessons from WHAT WE HAVE LEARNED it
    actually applied (2026-09-10: memory efficacy measured, not assumed)."""
    return [m.group(1).strip() for m in re.finditer(r"^\s*(?:[-*]\s*)?USED:\s*(.+)$", markdown or "", re.M)]


def find(prefix: str, repo: str | None = None) -> str | None:
    """The key of the row whose text starts with these words (case-insensitive,
    first eight words), or None."""
    want = " ".join(_words_in_order(prefix)[:8])
    if not want:
        return None
    for r in rows(repo, limit=600):
        if " ".join(_words_in_order(str(r.get("text")))[:8]) == want:
            return r["key"]
    return None


def _words_in_order(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", (text or "").lower())


def touch(k: str) -> None:
    """A lesson a run applied weighs more next time."""
    with ledger.connect() as c:
        c.cursor().execute("UPDATE lesson SET weight = weight + 1, updated_at = now() WHERE key=%s", (k,))
