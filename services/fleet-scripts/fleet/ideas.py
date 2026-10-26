"""The idea archive: lineage, forks and the links that make growth possible.

Chris, 2026-09-10: "lineage and forking as core concepts for ideation. similar
to humans, the agents need to experience something before they can iterate
and grow. no connection = no growth. we need functional 'neurons' (multi node
hops)." So an idea is never a loose sentence: it is a row with a lineage, a
parent when it forks another idea, and links to the experiences it grew from
(halts, lessons, reviews, bench runs, forum questions, rules). Outcomes feed
back along those links: a shipped PR strengthens every link on the path that
led to the idea, a failed attempt weakens them, and the next ideator samples
parents by score and by how few children they have (Darwin Gödel Machine),
so every viable line stays alive.

Node ids are typed strings: idea:<id> run:<job> halt:<fp> lesson:<key>
post:<id> bench:<day> pr:<url> rule:<key>. Links are directed src -> dst
with a kind (evidence, fork, attempt, outcome, informed) and a weight.
"""
from __future__ import annotations

import json
import math
import random
import re
import time

from fleet import github, ledger

SCHEMA = """
CREATE TABLE IF NOT EXISTS idea (
  id           TEXT PRIMARY KEY,
  lineage      TEXT NOT NULL,              -- the root idea's id: variants and forks share it
  parent       TEXT,                       -- the idea this one forked from
  repo         TEXT,
  problem      TEXT NOT NULL,
  mechanism    TEXT NOT NULL,
  novelty      TEXT,
  assumptions  TEXT,
  effect       TEXT,                       -- the measurable effect, "done when"
  source       TEXT NOT NULL,              -- ideator | dream | chris | concierge
  status       TEXT NOT NULL DEFAULT 'active',  -- active historical rejected attempted shipped failed
  reason       TEXT,
  scores       JSONB NOT NULL DEFAULT '{}'::jsonb,  -- non_obviousness soundness clarity diversity (0-100)
  pr_url       TEXT,
  run_id       TEXT,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idea_status_idx ON idea(repo, status);
ALTER TABLE idea ADD COLUMN IF NOT EXISTS touches TEXT;
CREATE TABLE IF NOT EXISTS link (
  src          TEXT NOT NULL,
  dst          TEXT NOT NULL,
  kind         TEXT NOT NULL,              -- evidence fork attempt outcome informed
  weight       REAL NOT NULL DEFAULT 1,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (src, dst, kind)
);
CREATE INDEX IF NOT EXISTS link_dst_idx ON link(dst);
"""

STATUSES = ("active", "historical", "rejected", "attempted", "shipped", "failed")
QUINTET = ("problem", "mechanism", "novelty", "assumptions", "effect")
ACTIVE_CAP = 10          # IDEAgent's active archive size; the rest become historical
_ready = False


def ensure() -> None:
    """The tables, created on first use (idempotent; no migrate Job needed)."""
    global _ready
    if _ready:
        return
    with ledger.connect() as c:
        cur = c.cursor()
        for stmt in [s for s in SCHEMA.split(";") if s.strip()]:
            cur.execute(stmt)
    _ready = True


def new_id(text: str) -> str:
    return ledger.fingerprint("idea", text[:200], str(time.time()))[:12]


# A repo-relative file an idea names: at least one folder and an extension.
# Absolute paths (/workspace/p/verify.sh) are the pod's, not the repo's.
PATH_RE = re.compile(r"(?<![\w/.-])(?:[\w.-]+/)+[\w.-]+\.[A-Za-z]{1,5}\b")
_trees: dict[str, set[str]] = {}


def missing_paths(text: str, repos: list[str], tree: set[str] | None = None) -> list[str]:
    """The files an idea names that no repo it touches has, not even the folder
    they would go in. 2026-09-14: the ideator filed pipeline ideas on kagent at
    packages/agent-loop/src/stages/implement.ts; the stages are new_localai's
    services/fleet-scripts and kagent never had that folder, so two missions
    launched into it and halted asking where it was. Empty when a tree cannot
    be read: fail open, the implementer still looks."""
    named = set(PATH_RE.findall(text))
    if not named:
        return []
    tree = _paths(repos) if tree is None else tree
    return sorted(p for p in named if tree and p not in tree and p.rsplit("/", 1)[0] not in tree)


def _paths(repos: list[str]) -> set[str]:
    """Every file and folder of each repo; empty when any one cannot be read."""
    out: set[str] = set()
    for r in repos:
        if r not in _trees:
            try:
                _trees[r] = github.tree(r)
            except Exception as e:
                print(f"ideas: no tree for {r} ({type(e).__name__})")
                _trees[r] = set()
        if not _trees[r]:
            return set()
        out |= _trees[r]
    return out


def score_of(scores: dict) -> float:
    """Quality for ordering the archive and picking parents: 0.5 soundness + 0.3
    clarity + 0.2 non-obviousness (IDEAgent weights novelty 0.7; a fleet fixing
    itself weights being right, 2026-09-10), 0..100."""
    g = lambda k: float(scores.get(k) or 0)
    return 0.5 * g("soundness") + 0.3 * g("clarity") + 0.2 * g("non_obviousness")


def add(quintet: dict, repo: str | None, source: str, parent: str | None = None,
        evidence: list[str] = (), scores: dict | None = None, status: str = "active",
        touches: list[str] = ()) -> str:
    """Store an idea; a parent makes it a fork in the parent's lineage; every
    evidence node gets a link into it. `repo` is where the idea was born, not
    a fence: `touches` names every repo the change spans (Chris, 2026-09-10:
    ideas originate somewhere but can be cross-cutting). Returns the id."""
    ensure()
    q = {k: str(quintet.get(k) or "").strip() for k in QUINTET}
    if not q["problem"] or not q["mechanism"]:
        raise ValueError("an idea needs a problem and a mechanism")
    iid = new_id(q["problem"] + q["mechanism"])
    with ledger.connect() as c:
        cur = c.cursor()
        lineage = iid
        if parent:
            cur.execute("SELECT lineage FROM idea WHERE id=%s", (parent,))
            row = cur.fetchone()
            lineage = row[0] if row else iid
        spans = ",".join(sorted({t.strip() for t in touches if t and t.strip().count("/") == 1} | ({repo} if repo else set())))
        cur.execute(
            "INSERT INTO idea (id, lineage, parent, repo, problem, mechanism, novelty, assumptions, effect, source, status, scores, touches) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s)",
            (iid, lineage, parent, repo, q["problem"], q["mechanism"], q["novelty"], q["assumptions"], q["effect"],
             source[:32], status, json.dumps(scores or {}), spans or None))
        if parent:
            cur.execute("INSERT INTO link (src, dst, kind) VALUES (%s,%s,'fork') ON CONFLICT DO NOTHING", (f"idea:{parent}", f"idea:{iid}"))
        for node in evidence:
            cur.execute("INSERT INTO link (src, dst, kind) VALUES (%s,%s,'evidence') ON CONFLICT DO NOTHING", (node, f"idea:{iid}"))
    return iid


def link(src: str, dst: str, kind: str, weight: float = 1.0) -> None:
    ensure()
    with ledger.connect() as c:
        c.cursor().execute("INSERT INTO link (src, dst, kind, weight) VALUES (%s,%s,%s,%s) "
                           "ON CONFLICT (src, dst, kind) DO UPDATE SET weight = link.weight + EXCLUDED.weight", (src, dst, kind, weight))


def set_status(iid: str, status: str, reason: str | None = None, pr_url: str | None = None, run_id: str | None = None) -> None:
    if status not in STATUSES:
        raise ValueError(status)
    ensure()
    with ledger.connect() as c:
        c.cursor().execute("UPDATE idea SET status=%s, reason=COALESCE(%s, reason), pr_url=COALESCE(%s, pr_url), "
                           "run_id=COALESCE(%s, run_id), updated_at=now() WHERE id=%s", (status, reason, pr_url, run_id, iid))


def rows(repo: str | None = None, statuses: tuple[str, ...] = ("active", "historical"), limit: int = 50) -> list[dict]:
    ensure()
    with ledger.connect() as c:
        cur = c.cursor()
        # a repo sees the ideas born in it, the repo-less ones, and every idea that touches it
        cur.execute("SELECT id, lineage, parent, repo, problem, mechanism, novelty, assumptions, effect, source, status, reason, "
                    "scores, pr_url, run_id, created_at, touches, "
                    "(SELECT count(*) FROM idea k WHERE k.parent = idea.id) AS children "
                    "FROM idea WHERE (repo IS NULL OR repo = %s OR %s::text IS NULL OR ',' || COALESCE(touches, '') || ',' LIKE %s) "
                    "AND status = ANY(%s::text[]) ORDER BY created_at DESC LIMIT %s",
                    (repo, repo, f"%,{repo},%" if repo else "%", list(statuses), limit))
        cols = [d[0] for d in cur.description]
        out = []
        for r in cur.fetchall():
            d = dict(zip(cols, r))
            if isinstance(d.get("scores"), str):
                d["scores"] = json.loads(d["scores"])
            out.append(d)
        return out


def get(iid: str) -> dict | None:
    """One idea by id (any status), or None."""
    ensure()
    with ledger.connect() as c:
        cur = c.cursor()
        cur.execute("SELECT id, lineage, parent, repo, problem, mechanism, novelty, assumptions, effect, source, status, scores, touches FROM idea WHERE id=%s", (iid,))
        r = cur.fetchone()
        if not r:
            return None
        d = dict(zip(("id", "lineage", "parent", "repo", "problem", "mechanism", "novelty", "assumptions", "effect", "source", "status", "scores", "touches"), r))
        if isinstance(d.get("scores"), str):
            d["scores"] = json.loads(d["scores"])
        return d


def brief_for(idea: dict) -> str:
    """A mission brief from an archived idea, tagged so publish closes it."""
    spans = [t for t in str(idea.get("touches") or "").split(",") if t]
    return (f"[idea:{idea['id']}] {str(idea['problem']).strip()} How: {str(idea['mechanism']).strip()} "
            + (f"Assumptions: {str(idea['assumptions']).strip()} " if idea.get("assumptions") else "")
            + (f"Touches: {', '.join(spans)} (this run is in {idea.get('repo')}; say in the PR what the other repos still need). " if len(spans) > 1 else "")
            + f"Done when: {str(idea.get('effect') or '').strip()}")


def rejected_patterns(repo: str | None = None, limit: int = 12) -> list[str]:
    """What has been turned down and why, aggregated (IDEAgent keeps failure
    patterns, not the rejected texts): the next ideator reads these first."""
    ensure()
    with ledger.connect() as c:
        cur = c.cursor()
        cur.execute("SELECT reason, count(*) FROM idea WHERE status IN ('rejected','failed') AND reason IS NOT NULL "
                    "AND (repo IS NULL OR repo = %s OR %s::text IS NULL) GROUP BY reason ORDER BY count(*) DESC, max(created_at) DESC LIMIT %s",
                    (repo, repo, limit))
        return [f"{r[0]} (x{r[1]})" for r in cur.fetchall()]


def parent_weight(idea: dict) -> float:
    """Darwin Gödel Machine: roughly proportional to score, inversely to the
    number of children, never zero. Shipped lineages count double."""
    s = score_of(idea.get("scores") or {})
    base = 1.0 / (1.0 + math.exp(-(s - 50) / 10))          # sigmoid around the gate
    bonus = 2.0 if idea.get("status") == "shipped" else 1.0
    return max(0.05, base * bonus / (1.0 + int(idea.get("children") or 0)))


def sample_parent(candidates: list[dict], rng: random.Random | None = None) -> dict | None:
    """One archive idea to fork, weighted by parent_weight; None when the archive is empty."""
    if not candidates:
        return None
    rng = rng or random.Random()
    weights = [parent_weight(c) for c in candidates]
    return rng.choices(candidates, weights=weights, k=1)[0]


def demote_overflow(repo: str | None = None) -> int:
    """Keep the active archive at ACTIVE_CAP by quality; the rest become historical (kept, sampleable)."""
    active = [r for r in rows(repo, ("active",), limit=200)]
    if len(active) <= ACTIVE_CAP:
        return 0
    active.sort(key=lambda r: score_of(r.get("scores") or {}), reverse=True)
    n = 0
    for r in active[ACTIVE_CAP:]:
        set_status(r["id"], "historical")
        n += 1
    return n


def path_to(node: str, hops: int = 3) -> list[tuple[str, str, str, float]]:
    """Every link on the paths that lead INTO a node, up to `hops` back: the
    experiences an idea grew from, the idea a run attempted, and so on."""
    ensure()
    with ledger.connect() as c:
        cur = c.cursor()
        cur.execute(
            "WITH RECURSIVE up AS ("
            " SELECT src, dst, kind, weight, 1 AS depth FROM link WHERE dst = %s"
            " UNION SELECT l.src, l.dst, l.kind, l.weight, up.depth + 1 FROM link l JOIN up ON l.dst = up.src WHERE up.depth < %s)"
            " SELECT src, dst, kind, weight FROM up", (node, hops))
        return [(r[0], r[1], r[2], float(r[3])) for r in cur.fetchall()]


def reinforce(node: str, delta: float, hops: int = 3) -> int:
    """Hebbian: an outcome at `node` changes the weight of every link on the
    paths that led to it. Shipped +1, failed -0.5 (floor 0.1). Returns links touched."""
    edges = path_to(node, hops)
    if not edges:
        return 0
    with ledger.connect() as c:
        cur = c.cursor()
        for src, dst, kind, _ in edges:
            cur.execute("UPDATE link SET weight = GREATEST(0.1, weight + %s) WHERE src=%s AND dst=%s AND kind=%s", (delta, src, dst, kind))
    return len(edges)


def strongest_experiences(limit: int = 12) -> list[tuple[str, float]]:
    """Experience nodes whose outgoing links carry the most weight: the ones
    that have led somewhere before. The ideator reads these next to the unconnected ones."""
    ensure()
    with ledger.connect() as c:
        cur = c.cursor()
        cur.execute("SELECT src, sum(weight) FROM link WHERE kind='evidence' GROUP BY src ORDER BY sum(weight) DESC LIMIT %s", (limit,))
        return [(r[0], float(r[1])) for r in cur.fetchall()]


def stats(days: int = 7) -> dict:
    """By status, the day's yield (active ideas, mutually distinct by construction),
    how many ideas cite evidence, and the idea-to-shipped rate."""
    ensure()
    with ledger.connect() as c:
        cur = c.cursor()
        cur.execute("SELECT status, count(*) FROM idea GROUP BY status")
        by_status = {r[0]: int(r[1]) for r in cur.fetchall()}
        cur.execute("SELECT count(*) FROM idea WHERE created_at > now() - (%s * interval '1 day')", (days,))
        recent = int(cur.fetchone()[0])
        cur.execute("SELECT count(DISTINCT dst) FROM link WHERE kind='evidence' AND dst IN "
                    "(SELECT 'idea:' || id FROM idea WHERE created_at > now() - (%s * interval '1 day'))", (days,))
        cited = int(cur.fetchone()[0])
        cur.execute("SELECT count(*) FROM link")
        links = int(cur.fetchone()[0])
        cur.execute("SELECT count(*) FROM link WHERE kind='informed' AND created_at > now() - (%s * interval '1 day')", (days,))
        informed = int(cur.fetchone()[0])
    attempted = sum(by_status.get(s, 0) for s in ("attempted", "shipped", "failed"))
    return {"by_status": by_status, "recent": recent, "evidence_cited": cited, "days": days, "links": links,
            "shipped_rate": round(by_status.get("shipped", 0) / attempted, 2) if attempted else None,
            "lessons_applied": informed}


# --- closure (loop step 6, 2026-09-10) ------------------------------------
# The forum post carries `[idea:<id>]`; the collector, the findings and the
# brief keep the literal token; publish, reap and record_merge close the loop.
TAG = re.compile(r"\[idea:([0-9a-f]{12})\]")


def idea_in(*texts: str) -> str | None:
    """The first `[idea:<id>]` token in any of the texts, else None."""
    for t in texts:
        m = TAG.search(t or "")
        if m:
            return m.group(1)
    return None


def lookup(fp: str | None = None, pr_url: str | None = None) -> tuple[str | None, str | None]:
    """(idea id, run id) behind a PR (publish stamps pr_url/run_id on the idea when
    it ships) or behind a candidate (publish writes evidence.idea_id on the row).
    (None, None) when nothing is known."""
    ensure()
    with ledger.connect() as c:
        cur = c.cursor()
        if pr_url:
            cur.execute("SELECT id, run_id FROM idea WHERE pr_url=%s ORDER BY updated_at DESC LIMIT 1", (pr_url,))
        else:
            cur.execute("SELECT evidence->>'idea_id', NULL FROM candidate WHERE fingerprint=%s AND evidence->>'idea_id' IS NOT NULL", (fp,))
        row = cur.fetchone()
        return (row[0], row[1]) if row else (None, None)


def outcome(iid: str, run_id: str, pr_url: str | None = None, halt: dict | None = None) -> None:
    """A run's outcome reaches the idea it attempted. attempted + the idea -> run
    link first (a crash after this still leaves the attempt on record), then
    shipped (run -> pr, the path +1) or failed (the halt reason, the path -0.5;
    the reason joins rejected_patterns for the next ideator)."""
    set_status(iid, "attempted", run_id=run_id)
    link(f"idea:{iid}", f"run:{run_id}", "attempt")
    if pr_url:
        set_status(iid, "shipped", pr_url=pr_url, run_id=run_id)
        link(f"run:{run_id}", f"pr:{pr_url}", "outcome")
        reinforce(f"pr:{pr_url}", 1.0)
    else:
        h = halt or {}
        set_status(iid, "failed", reason=f"{h.get('stage', '?')}: {str(h.get('reason', ''))[:120]}", run_id=run_id)
        reinforce(f"run:{run_id}", -0.5)
