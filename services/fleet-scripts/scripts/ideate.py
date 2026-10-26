"""ideate: the ideator, v2 (2026-09-10, docs/superpowers/specs/2026-09-10-idea-lineage.md).

Chris, 2026-09-09: "No new ideas? that sounds like an opportunity for an idea."
Chris, 2026-09-10: "the agents need to experience something before they can
iterate and grow. no connection = no growth." So every idea here starts from
evidence the fleet lived through (fleet/experience.py) and must cite it, one
seed forks an archived idea (keep the problem, change the mechanism or the
locus), the judge scores the quintet and its distance from the archive on
eight axes, a near miss gets one repair, and what is accepted becomes a row
with links (fleet/ideas.py) and a forum post carrying [idea:<id>] so the
collector, the run and the PR carry the id through.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fleet import experience, github, ideas, ledger, telegram  # noqa: E402
import review  # noqa: E402

GATE = 60           # soundness, clarity and diversity >= 60; non-obviousness ranks, it does not gate
# The first live run (2026-09-10 16:19Z): 12 grounded candidates, 12 rejected, 11 of them for
# "low non_obviousness". IDEAgent gates on it because a research idea must surprise; a fleet
# fixing its own halts wants the obvious right fix shipped, and novelty only relative to what
# is already in the archive (that is the diversity axis). So non-obviousness stays a score
# that orders the archive and picks parents, and the gate is soundness, clarity, diversity.
NEAR = 10           # within NEAR below the gate = one repair pass
SCORED = ("non_obviousness", "soundness", "clarity", "diversity")
AXES = "failure mode, diagnosis, intervention, signal source, locus, objective, evaluation, assumptions"

# Harness change 4 (2026-09-09): divergence and convergence are two different
# jobs. Forced perspectives at a high temperature produce the candidates; the
# judge at a low temperature scores them. A single call at 0.2 regresses to the
# most probable idea.
PERSPECTIVES = {
    "explore": "You just read one source file you had never seen before (RANDOM FILE, below). What does it reveal that the rest of the evidence does not: a smell, a missing test, a shortcut, a thing nobody would notice from the outside?",
    "delete": "You hate machinery. What would you DELETE, simplify or stop doing in this repository, and what breaks nothing when gone?",
    "3am": "You get paged at 3 a.m. for this system. What breaks, what is invisible when it breaks, and what one change makes the next page unnecessary?",
    "operator": "You are the operator who reads the forum and the runs every morning. What keeps costing time, what does he keep asking for, and what is the smallest change that gives it back?",
}
QUINTET_SHAPE = ("Reply with STRICT JSON only: {\"ideas\": [{\"problem\": \"<what is wrong, one sentence>\", \"mechanism\": \"<how the change works>\", "
                 "\"novelty\": \"<what makes it unlike the archive>\", \"assumptions\": \"<what must be true for it to work>\", "
                 "\"effect\": \"<the measurable effect, the check that proves it>\", \"where\": \"<files or area>\", "
                 "\"touches\": [\"<owner/name of every repo the change spans, this one first; an idea may be cross-cutting>\"], \"evidence\": [\"<experience id>\"]}]}")
SOURCE_EXT = (".py", ".ts", ".tsx", ".js", ".go", ".sh", ".yaml", ".yml", ".md")


def random_file(repo: str, gh=None, pick=None) -> str:
    """The head of one source file chosen at random from the repo tree, as
    evidence the ideator did not ask for. Exposure is most of creativity."""
    import base64
    import random
    gh = gh or github
    tree = gh.api(f"/repos/{repo}/git/trees/HEAD?recursive=1").get("tree", [])
    paths = [t["path"] for t in tree if t.get("type") == "blob" and t["path"].endswith(SOURCE_EXT)
             and "node_modules" not in t["path"] and "/dist/" not in t["path"] and int(t.get("size") or 0) < 60000]
    if not paths:
        return ""
    path = (pick or random.choice)(paths)
    body = base64.b64decode(gh.api(f"/repos/{repo}/contents/{path}").get("content", "")).decode(errors="replace")
    return f"RANDOM FILE {path} (head):\n" + body[:3000]


def repo_context(repo: str) -> str:
    ctx = []
    try:
        import base64
        c = github.api(f"/repos/{repo}/contents/CLAUDE.md")
        ctx.append("CLAUDE.md (head):\n" + base64.b64decode(c.get("content", "")).decode(errors="replace")[:6000])
    except Exception as e:
        ctx.append(f"(no CLAUDE.md: {type(e).__name__})")
    try:
        issues = github.api(f"/repos/{repo}/issues?state=open&per_page=20")
        ctx.append("Open issues (never propose what one already covers):\n" + "\n".join(f"- #{i['number']} {i['title']}" for i in issues if "pull_request" not in i)[:2000])
    except Exception:
        pass
    try:
        ctx.append(random_file(repo))   # curiosity: one file it has never read
    except Exception as e:
        print(f"ideate: no random file ({type(e).__name__})")
    return "\n\n".join(ctx)


def archive_lines(archive: list[dict]) -> str:
    return "\n".join(f"- idea:{r['id']} [{r.get('status')}, score {ideas.score_of(r.get('scores') or {}):.0f}] {str(r.get('problem'))[:160]} | mechanism: {str(r.get('mechanism'))[:160]}"
                     for r in archive) or "- (empty)"


def evidence_text(exp: list[dict], strong: list, archive: list[dict], patterns: list[str]) -> str:
    return ("EXPERIENCES (last 7 days, newest first; every idea cites these ids):\n" + (experience.render(exp) or "- (none)")
            + "\n\nSTRONGEST EXPERIENCES (the ones that led to ideas before):\n" + ("\n".join(f"- {n} (weight {w:.1f})" for n, w in strong) or "- (none)")
            + "\n\nARCHIVE (ideas already held; do not repeat them, fork them):\n" + archive_lines(archive)
            + "\n\nREJECTED PATTERNS (why ideas were turned down before; do not repeat them):\n" + ("\n".join(f"- {p}" for p in patterns) or "- (none)"))


def fork_angle(parent: dict) -> str:
    return (f"FORK the archived idea idea:{parent['id']}: problem \"{str(parent.get('problem'))[:200]}\", mechanism \"{str(parent.get('mechanism'))[:200]}\". "
            "Keep the problem, change the mechanism or the locus (attack the same problem from a different place in the system).")


def diverge(repo: str, seeds: dict, evidence: str, known: set[str]) -> list[dict]:
    """Candidates from every seed at 0.9 without thinking; an idea that cites no
    experience the fleet actually had is dropped (no connection, no growth)."""
    out: list[dict] = []
    for name, angle in seeds.items():
        prompt = (f"You are the ideator for the repository {repo}, one of a fleet of local agents that ship small pull requests. {angle} "
                  "Propose up to 3 ideas a single agent could ship in one pull request of under 300 changed lines, each verifiable by a "
                  "test or a command; no rewrites, no new services. The fleet's own pipeline (the stages, stage.sh, validate.py, verify.sh, "
                  "halts and artifacts like 01-findings.json, reconcile, the forum, the reviewer, this ideator) is ctkadvisors/new_localai "
                  "services/fleet-scripts whatever repository you ideate for: an idea about it touches that repo and names files that exist there. "
                  "Every idea must grow from the EXPERIENCES below and list the ids it "
                  "addresses in \"evidence\"; an idea that cites none is discarded. " + QUINTET_SHAPE + "\n\nEVIDENCE:\n" + evidence)
        try:
            for it in (review.parse_json(review.ask_judge(prompt, temperature=0.9, thinking=False)).get("ideas") or [])[:3]:
                if with_evidence(it, known):
                    out.append({**it, "perspective": name})
                else:
                    print(f"ideate: dropped an idea from {name} with no valid evidence id")
        except Exception as e:
            print(f"ideate: perspective {name} failed ({type(e).__name__}: {str(e)[:80]})")
    return out


def touches_of(c: dict, repo: str) -> list[str]:
    """Every repo the change spans, the origin first."""
    named = [str(t).strip() for t in (c.get("touches") or []) if str(t).strip().count("/") == 1]
    return [repo] + [t for t in named if t != repo]


def with_evidence(it: dict, known: set[str]) -> bool:
    it["evidence"] = [str(e) for e in (it.get("evidence") or []) if str(e) in known]
    return bool(it["evidence"]) and bool(str(it.get("problem", "")).strip()) and bool(str(it.get("mechanism", "")).strip())


def candidate_line(i: int, c: dict) -> str:
    return (f"{i}. " + " | ".join(f"{k}: {str(c.get(k, ''))[:240]}" for k in ideas.QUINTET) + " | evidence: " + ", ".join(c.get("evidence") or []))


def judge(repo: str, cands: list[dict], archive: list[dict], evidence: str) -> list[dict]:
    """One judge pass with thinking at 0.2: four scores 0-100 per candidate and
    the archived ideas it is a variant of. A candidate the judge did not score is treated as unscored (rejected)."""
    if not cands:
        return []
    listing = "\n".join(candidate_line(i, c) for i, c in enumerate(cands, 1))
    prompt = (f"You judge improvement ideas for the repository {repo} against its archive. Score every candidate 0-100 on:\n"
              "- non_obviousness: would a competent engineer reading the evidence propose it at once? (100 = nobody would)\n"
              "- soundness: does the mechanism plausibly produce the effect, given the assumptions and the evidence it cites?\n"
              "- clarity: are the problem, the mechanism and the done-when check unambiguous enough to implement and verify?\n"
              f"- diversity: how far it is from EVERY archived idea on eight axes: {AXES} (100 = differs on all axes from all of them)\n"
              "\"matches\": the ids of archived ideas the candidate is a variant of (same problem and mechanism family, differing on "
              "at most two axes), and cand:<n> for an EARLIER candidate in this list it is a variant of (the first live run "
              "accepted three ideas about the same halt as three lineages, 2026-09-10); empty when it is new. "
              "Reply with STRICT JSON only: {\"verdicts\": [{\"n\": <1-based index>, "
              "\"non_obviousness\": <0-100>, \"soundness\": <0-100>, \"clarity\": <0-100>, \"diversity\": <0-100>, "
              "\"matches\": [\"<idea id>\"], \"reason\": \"<=25 words\"}]}"
              "\n\nCANDIDATES:\n" + listing + "\n\nARCHIVE:\n" + archive_lines(archive) + "\n\nEVIDENCE:\n" + evidence[:6000])
    by_n: dict[int, dict] = {}
    try:
        for v in review.parse_json(review.ask_judge(prompt, temperature=0.2, thinking=True)).get("verdicts") or []:
            by_n[int(v.get("n", 0))] = v
    except Exception as e:
        print(f"ideate: judge failed ({type(e).__name__}: {str(e)[:80]})")
    out = []
    for i in range(1, len(cands) + 1):
        v = by_n.get(i) or {}
        out.append({**{k: int(v.get(k) or 0) for k in SCORED},
                    "matches": [str(m).removeprefix("idea:") for m in (v.get("matches") or [])], "reason": str(v.get("reason") or "unscored")[:120]})
    return out


def decide(v: dict) -> tuple[str, str]:
    """(accept | variant | near | reject, reason-or-parent)."""
    if len(v["matches"]) > 1:
        return "reject", "duplicate of " + ", ".join(v["matches"])
    if v["diversity"] < GATE:
        return "reject", "not distinct"
    low = [k for k in ("soundness", "clarity") if v[k] < GATE]
    if not low:
        return ("variant", v["matches"][0]) if v["matches"] else ("accept", "")
    if all(v[k] >= GATE - NEAR for k in low):
        return "near", ", ".join(low)
    return "reject", f"low {', '.join(low)}: {v['reason']}"


def repair(repo: str, cand: dict, v: dict, low: str, known: set[str]) -> dict | None:
    """One critic pass (judge, thinking) then one repair (diverger) that must keep the mechanism."""
    line = candidate_line(1, cand)
    try:
        feedback = review.ask_judge(f"This improvement idea for {repo} scored just under the gate on {low} (scores: "
                                    + ", ".join(f"{k} {v[k]}" for k in SCORED) + f"; reason: {v['reason']}).\n{line}\n"
                                    "In at most 80 words, say precisely what would raise those scores WITHOUT changing the mechanism.",
                                    temperature=0.2, thinking=True)[:800]
        prompt = (f"Repair this improvement idea for {repo}. Keep the mechanism exactly; sharpen the rest to the feedback. "
                  + QUINTET_SHAPE + f"\n\nIDEA:\n{line}\n\nFEEDBACK:\n{feedback}")
        it = (review.parse_json(review.ask_judge(prompt, temperature=0.9, thinking=False)).get("ideas") or [None])[0]
    except Exception as e:
        print(f"ideate: repair failed ({type(e).__name__}: {str(e)[:80]})"); return None
    if not isinstance(it, dict):
        return None
    it["mechanism"] = cand["mechanism"]                       # the repair sharpens, it does not swap the idea
    it.setdefault("evidence", cand["evidence"]); it.setdefault("where", cand.get("where"))
    return {**it, "perspective": cand["perspective"]} if with_evidence(it, known) else None


def post(repo: str, iid: str, c: dict) -> bool:
    body = (f"[idea:{iid}] {str(c.get('problem')).strip().rstrip('.')}. Why: {str(c.get('novelty') or c.get('mechanism')).strip()} "
            f"(evidence: {', '.join(c.get('evidence') or [])}) How: {str(c.get('mechanism')).strip()} "
            f"Where: {str(c.get('where') or '').strip()} "
            + (f"Touches: {', '.join(touches_of(c, repo))} " if len(touches_of(c, repo)) > 1 else "")
            + f"Done when: {str(c.get('effect') or '').strip()}")
    return bool(ledger.say("ideator", body, topic="idea", ref=f"https://github.com/{repo}", mentions=["collector"]))


def run(repo: str, now: float) -> dict:
    """The loop's steps 1-5 for one repo. Returns the counts (also in kv ideator:<repo>) plus the posted titles."""
    # Experience is the fleet's one memory, never scoped to a repo, and an idea
    # is not fenced by one either (Chris, 2026-09-10): it originates in the
    # repo the ideator ran for and may touch others (`touches`).
    exp = experience.recent(7)
    strong = ideas.strongest_experiences()
    archive = ideas.rows(repo, ("active", "historical"))
    patterns = ideas.rejected_patterns(None)        # every repo: a misread halt is misread everywhere
    known = {e["id"] for e in exp} | {n for n, _ in strong}
    evidence = evidence_text(exp, strong, archive, patterns)
    parent = ideas.sample_parent(archive)
    seeds = ({"fork": fork_angle(parent)} if parent else {}) | PERSPECTIVES
    cands = diverge(repo, seeds, evidence + "\n\n" + repo_context(repo), known)
    counts = {"seeds": len(seeds), "forked": 0, "accepted": 0, "variants": 0, "rejected": 0, "repaired": 0}
    grounded = []
    for c in cands:                                  # a file no touched repo has never reaches the judge (ideas.missing_paths)
        gone = ideas.missing_paths(f"{c.get('where') or ''} {c['mechanism']}", touches_of(c, repo))
        if not gone:
            grounded.append(c)
            continue
        iid = ideas.add(c, repo, "ideator", None, c["evidence"], {}, status="rejected", touches=touches_of(c, repo))
        ideas.set_status(iid, "rejected", reason=f"names files not in {', '.join(touches_of(c, repo))}: {', '.join(gone[:3])}")
        counts["rejected"] += 1
    cands = grounded
    titles = []
    stored: dict[int, str] = {}                      # candidate index -> stored id, for cand:<n> matches
    for n, (c, v) in enumerate(zip(cands, judge(repo, cands, archive, evidence)), 1):
        # A match on an earlier candidate of this batch is a variant of it when
        # that one was stored; a match on a rejected one is no match.
        v["matches"] = [stored[int(m[5:])] if m.startswith("cand:") and m[5:].isdigit() and int(m[5:]) in stored else m
                        for m in v["matches"] if not (m.startswith("cand:") and (not m[5:].isdigit() or int(m[5:]) not in stored))]
        what, detail = decide(v)
        if what == "near":
            fixed = repair(repo, c, v, detail, known)
            counts["repaired"] += 1
            if fixed:
                c, v = fixed, judge(repo, [fixed], archive, evidence)[0]
                what, detail = decide(v)
            if what == "near":
                what, detail = "reject", f"low {detail} after repair: {v['reason']}"
        scores = {k: v[k] for k in SCORED}
        fork_parent = parent["id"] if parent and c["perspective"] == "fork" else None
        if what == "reject":
            iid = ideas.add(c, repo, "ideator", fork_parent, c["evidence"], scores, status="rejected", touches=touches_of(c, repo))
            ideas.set_status(iid, "rejected", reason=detail)
            counts["rejected"] += 1
            continue
        iid = ideas.add(c, repo, "ideator", detail if what == "variant" else fork_parent, c["evidence"], scores, touches=touches_of(c, repo))
        stored[n] = iid
        counts["variants" if what == "variant" else "accepted"] += 1
        if what == "accept" and fork_parent:
            counts["forked"] += 1
        if post(repo, iid, c):
            titles.append(str(c["problem"])[:160])
    ideas.demote_overflow(repo)
    counts["yield"] = len(ideas.rows(repo, ("active",), limit=200))
    try:
        ledger.kv_set(f"ideator:{repo}", {"at": now, **counts})
    except Exception:
        pass
    print(f"ideate: {len(seeds)} seeds -> {len(cands)} candidates -> " + ", ".join(f"{k} {n}" for k, n in counts.items()))
    return {**counts, "titles": titles}


def main(argv: list[str] | None = None) -> int:
    """The ideation Job (reconcile.launch_ideation): one repo, once a day. The
    reconcile tick has a 240 s deadline and an ideation takes ten minutes of
    qwen38 (2026-09-10 17:00Z: the tick was killed mid-run), so it is its own
    Job with its own guard, and the tick only launches it."""
    import time
    repo = (argv or sys.argv[1:] or [os.environ.get("IDEATE_REPO", "")])[0]
    if not repo:
        print("ideate: no repo (IDEATE_REPO or argv)"); return 2
    now = time.time()
    day = time.strftime("%Y-%m-%d", time.gmtime(now))
    # IDEATE_FORCE: reconcile's repeat launch when the archive is spent (launch_ideation, IDEATE_PER_DAY)
    if (ledger.kv_get(f"ideated:{repo}") or {}).get("day") == day and "--force" not in (argv or sys.argv) and not os.environ.get("IDEATE_FORCE"):
        print(f"ideate: {repo} already ideated today"); return 0
    ledger.kv_set(f"ideated:{repo}", {"day": day, "at": now})
    out = run(repo, now)
    n, titles = out["accepted"] + out["variants"], out["titles"]
    if n:
        ledger.say("reconcile", f"The ideator (qwen38) posted {n} idea(s) for {repo} from the fleet's experiences, the archive and the repo "
                   f"({out['rejected']} rejected, {out['repaired']} repaired, yield {out['yield']}). "
                   "The next improve run collects them; reply on one to steer it, or say it is wrong.", topic="status", ref=f"https://github.com/{repo}")
        try:
            telegram.send(f"💡 {repo.split('/')[-1]}: the ideator posted {n} idea(s); the next improve run collects them.\n"
                          + "\n".join(f"- {t[:160]}" for t in titles[:3]) + f"\n{telegram.CONSOLE_URL}")
        except Exception as e:
            print(f"ideate: telegram failed ({type(e).__name__})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
