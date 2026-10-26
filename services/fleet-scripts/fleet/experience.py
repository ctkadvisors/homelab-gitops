"""What the fleet has lived through lately, as typed nodes an idea can link
to. Nothing new is stored: runs, memory rows, forum questions and bench
results already exist; this gives each one an id (fleet/ideas.py node ids)
and one line of text, so an ideator can cite it and a link can point at it.
"""
from __future__ import annotations

from fleet import ledger


def recent(days: int = 7, limit: int = 60) -> list[dict]:
    """[{id, kind, text, repo, at}] newest first: halts and ships, lessons the
    fleet wrote, unanswered questions and escalations, the bench trend."""
    out: list[dict] = []
    try:
        for r in ledger.recent_runs(30):
            if r.get("outcome") in ("halted", "failed"):
                h = r.get("halt") or {}
                stage, reason = (h.get("stage") if isinstance(h, dict) else None) or "?", (h.get("reason") if isinstance(h, dict) else str(h)) or ""
                out.append({"id": f"run:{r['id']}", "kind": "halt", "repo": r.get("repo"), "at": str(r.get("started_at"))[:16],
                            "text": f"run {r['id']} on {r.get('repo')} {r.get('outcome')} at {stage}: {str(reason)[:160]}"})
            elif r.get("outcome") == "shipped":
                out.append({"id": f"run:{r['id']}", "kind": "shipped", "repo": r.get("repo"), "at": str(r.get("started_at"))[:16],
                            "text": f"run {r['id']} on {r.get('repo')} shipped {r.get('pr_url') or ''} ({str(r.get('title') or '')[:100]})"})
    except Exception:
        pass
    try:
        from fleet import memory
        for m in memory.rows(limit=60):
            if m.get("source") in ("claude", "chris"):
                continue
            out.append({"id": f"lesson:{m['key']}", "kind": m.get("kind") or "lesson", "repo": m.get("repo"), "at": str(m.get("created_at"))[:16],
                        "text": f"[{m.get('source')}] {str(m.get('text'))[:200]}"})
    except Exception:
        pass
    try:
        for p in ledger.posts(limit=40, topic="question", unanswered=True):
            out.append({"id": f"post:{p['id']}", "kind": "question", "repo": None, "at": str(p.get("created_at"))[:16],
                        "text": f"open question from {p.get('author')}: {str(p.get('body'))[:200]}"})
    except Exception:
        pass
    try:
        for key, v in sorted(ledger.kv_like("bench:%"), reverse=True)[:3]:
            n = len(v.get("rows") or []); ok = sum(1 for r in (v.get("rows") or []) if r.get("success"))
            out.append({"id": key, "kind": "bench", "repo": "ctkadvisors/new_localai", "at": key.split(":", 1)[-1],
                        "text": f"bench {key.split(':', 1)[-1]}: {ok}/{n} fixtures passed"})
    except Exception:
        pass
    return out[:limit]


def render(items: list[dict]) -> str:
    return "\n".join(f"- {i['id']} [{i['kind']} {i.get('at') or ''}] {i['text']}" for i in items)
