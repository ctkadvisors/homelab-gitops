"""Publish stage of the staged pipeline (improve-daily and missions).

Reads the stage artifacts from /workspace/p, pushes the branch and opens
the PR when nothing halted upstream, then reports to the brain and to
Telegram either way. The only stage that holds credentials.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fleet import brain, github, ideas, ledger, telegram  # noqa: E402

P = os.environ.get("PIPELINE_DIR", "/workspace/p")
REPO_DIR = os.environ.get("REPO_DIR", "/workspace/repo")
REPO = os.environ.get("REPO", "ctkadvisors/kagent")
PIPELINE = os.environ.get("PIPELINE", "Daily self-improvement")
BRANCH = os.environ.get("BRANCH") or ("agent/dsh-daily-" + date.today().strftime("%Y%m%d"))
BRIEF = os.environ.get("MISSION_BRIEF", "")
# The ledger row is the Job name. It used to be derived from BRANCH, which is
# wrong for a review round (2026-09-06 21:00: mission-20260906-210005 worked on
# agent/mission-20260906-073003 and finished the other run's row, leaving its
# own open and counted as running for three hours).
def run_id() -> str:
    return os.environ.get("RUN_ID") or BRANCH.split("/", 1)[-1]


def slurp(name: str, limit: int = 6000) -> str:
    try:
        return open(f"{P}/{name}").read()[:limit]
    except Exception:
        return "(missing)"


def pipeline_evidence() -> str:
    """What the pipeline itself ran, not what the model says it ran: verify.sh and
    its output. The reviewer reads the first 2000 chars of the body and closed
    rounds for "no recorded test output" while the run sat in the pod log (2026-09-13)."""
    if not os.path.exists(f"{P}/verify.sh"):
        return ""
    out = ANSI.sub("", slurp("verify.out", 200000))[-800:]
    rc = slurp("verify.rc", 10).strip()
    return ("### Pipeline-run evidence (stage.sh executed this; the model did not write the output)\n"
            f"exit {rc or '?'}\n```sh\n" + slurp("verify.sh", 600) + "\n```\noutput (tail):\n```\n" + out + "\n```")


def build_trace(stopped: dict | None) -> str:
    return "\n\n".join(s for s in [
        "## Pipeline trace (investigate -> adjudicate -> implement -> test)",
        ("### Mission brief\n" + BRIEF) if BRIEF else "",
        "### Halted: " + json.dumps(stopped) if stopped else "### Result: SHIP",
        pipeline_evidence(),
        "### 01 findings\n```json\n" + slurp("01-findings.json") + "\n```",
        "### 02 adjudication\n```json\n" + slurp("02-verdict.json") + "\n```",
        "### 03 implementation\n" + slurp("03-implementation.md"),
        "### 04 test report\n```json\n" + slurp("04-test-report.json") + "\n```",
    ] if s)


ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def pr_body() -> str:
    """The PR is for a reader: the pipeline's own test run first (the reviewer reads
    the first 2000 chars), then what the implementer says it did. The whole trace
    (brief, findings and verdict JSON, ANSI test output) made bodies 10-19 KB and
    every review round re-posted it (2026-09-15); the trace goes to the brain."""
    return "\n\n".join(s for s in [
        pipeline_evidence(),
        "### What changed\n" + slurp("03-implementation.md", 3000),
        f"{PIPELINE} run `{run_id()}` (staged pipeline, all-local).",
    ] if s)


def open_pr(body: str, gh=None) -> str | None:
    """Push the branch and open its PR; when the PR already exists (a review
    round on the same branch, clone.py checked it out) the push updated it, so
    comment the new body there instead of opening a second one."""
    gh = gh or github
    run = lambda *a: subprocess.run(a, cwd=REPO_DIR, check=True, capture_output=True, text=True)
    run("git", "checkout", "-B", BRANCH)
    run("git", "push", gh.push_url(REPO), BRANCH)
    # the oldest commit is the change; the newest can be stage.sh's "style: prettier" commit (kagent#60's title was)
    title = run("git", "log", "--reverse", "origin/main..HEAD", "--format=%s").stdout.splitlines()[0]
    owner = REPO.split("/")[0]
    existing = gh.api(f"/repos/{REPO}/pulls?state=open&head={owner}:{BRANCH}")
    if existing:
        pr = existing[0]
        # The reviewer judges the PR body: a round replaces it, or the evidence stays the first
        # round's (kagent#62, 2026-09-15: one round's verify.sh beside an older round's output).
        gh.api(f"/repos/{REPO}/pulls/{pr['number']}", {"body": body}, method="PATCH")
        gh.api(f"/repos/{REPO}/issues/{pr['number']}/comments", {"body": "**Review round**: the branch was updated; the description now carries this round's evidence."})
        return pr.get("html_url")
    pr = gh.api(f"/repos/{REPO}/pulls", {"title": title, "head": BRANCH, "base": "main", "body": body})
    return pr.get("html_url")


def candidate(verdict: dict | None) -> tuple[str | None, str | None, str | None]:
    """(fingerprint, title, issue_url) of what this run attempted: a mission's issue
    (triage briefs open with 'GitHub issue <url> — <title>'), a concierge brief by
    its text, or the improve run's selected candidate. Same work -> same fingerprint,
    so the ledger can see a repeat."""
    if BRIEF:
        return ledger.mission_candidate(REPO, BRIEF)
    sel = (verdict or {}).get("selected")
    if not sel:
        return (None, None, None)
    # The finding, not its slot: every investigator names its first candidate "C1",
    # so keying on the id gave every improve run on a repo one fingerprint
    # (a58e70973bf0 reached 11 attempts and orphaned PR 173, 2026-09-13).
    try:
        found = next(c for c in json.load(open(f"{P}/01-findings.json")).get("candidates") or [] if c.get("id") == sel)
        what = f"{found.get('file') or ''}: {found.get('claim') or ''}".strip(": ")
    except Exception:
        what = ""
    what = what or str(sel)
    return (ledger.fingerprint(REPO, what), what[:300], None)


def idea_of(verdict: dict | None) -> str | None:
    """The `[idea:<id>]` this run worked on: in the brief (a mission on an idea) or
    in the finding the adjudicator selected (the investigator copies the token
    from the forum evidence into its finding). None when the run had no idea."""
    sel = (verdict or {}).get("selected")
    try:
        found = [c for c in json.load(open(f"{P}/01-findings.json")).get("candidates") or [] if c.get("id") == sel]
    except Exception:
        found = []
    return ideas.idea_in(BRIEF, json.dumps(found), str(sel or ""), str((verdict or {}).get("selection_reasoning") or ""))


MODEL_STAGES = ("investigate", "adjudicate", "implement", "test")


def cost_of(timing: dict | None) -> dict:
    """What the run spent: seconds of ornith15 on the spark, the one resource the
    fleet pays with. Tokens are not counted; dsh does not report them."""
    secs = sum(int((timing or {}).get(s, {}).get("seconds") or 0) for s in MODEL_STAGES)
    return {"model_seconds": secs, "model": "ornith15"} if secs else {}


# Halts that are outcomes, not faults: no GitHub issue (they lured the improve
# budget back to kagent all day on 09-07 as "open fleet problems") and no page.
QUIET_HALTS = ("investigator found no candidates", "review round pushed no new commit")


def degenerate(text: str) -> bool:
    """True when a model's tail is token salad. improve-20260908-000000's
    implementer emitted 'sp sp 法律 Poly 公司 ...' for its whole budget and
    publish pasted it into Chris's Telegram as the halt. A tail whose
    characters are mostly outside ASCII letters/digits/punctuation, or
    whose words are mostly a handful of repeats, is not something to page."""
    t = (text or "").strip()
    if len(t) < 80:
        return False
    odd = sum(1 for ch in t if ord(ch) > 0x2FF) / len(t)
    words = t.split()
    top = max((words.count(w) for w in set(words)), default=0) / max(len(words), 1)
    return odd > 0.15 or top > 0.3


def clean_tail(text: str) -> str:
    return "(model output degenerate: token salad, not shown; the run's implement log has it)" if degenerate(text) else text


def review_round_unchanged() -> bool:
    """A review round works on the PR's branch (clone.py continued it). When it
    pushed no new commit there is nothing for the reviewer to re-judge, and
    calling that "shipped" is what let the concierge tell Chris that kagent#26
    had shipped three times on 2026-09-07."""
    out = subprocess.run(["git", "rev-list", "--count", f"origin/{BRANCH}..HEAD"], cwd=REPO_DIR, capture_output=True, text=True)
    return out.returncode == 0 and out.stdout.strip() == "0"


def main() -> None:
    if os.path.exists(f"{P}/quiet"):
        print("publish: quiet skip (guard)")
        return
    stopped = json.load(open(f"{P}/stop")) if os.path.exists(f"{P}/stop") else None
    unchanged = not stopped and review_round_unchanged()
    if unchanged:
        stopped = {"stage": "implement", "reason": QUIET_HALTS[1], "exit_code": 0}
    trace = build_trace(stopped)
    pr_url = None if stopped else open_pr(pr_body())
    if pr_url:
        print("PR_URL:", pr_url)
        stale = close_stale_halts(pr_url, run_started_at(json.load(open(f"{P}/timing.json")) if os.path.exists(f"{P}/timing.json") else None))
        if stale:
            print("ledger: closed stale halt issue(s):", stale)

    outcome = f"halted at {stopped['stage']}: {stopped['reason']}" if stopped else f"shipped PR {pr_url}"
    # What this run teaches the next one (fleet/memory.py): a halt's reason and
    # what would unblock it; the LESSON: lines the implementer wrote for its
    # successors. Quiet halts (no candidates, unchanged round) teach nothing.
    lessons: list[str] = []
    try:
        from fleet import memory
        if stopped and stopped.get("reason") not in QUIET_HALTS:
            memory.remember("lesson", memory.distill_halt(stopped, BRIEF), repo=REPO, ref=run_id(), source="publish")
        report = slurp("03-implementation.md", 20000)
        lessons = memory.lessons_in(report)
        # USED: lines are the lessons the implementer says it applied: a link
        # lesson -> run (kind informed) and a heavier row. This is the number
        # behind "did memory change a run" (2026-09-10).
        for used in memory.used_in(report)[:8]:
            k = memory.find(used, REPO)
            if k:
                memory.touch(k)
                ideas.link(f"lesson:{k}", f"run:{run_id()}", "informed")
        for line in lessons:
            memory.remember("lesson", line, repo=REPO, ref=pr_url or run_id(), source="implementer")
    except Exception as e:
        print("memory write failed (non-fatal):", e)
    # On the thread, so a repeat is visible next to the lesson that should have prevented it (new_localai#67).
    learned = (" Lessons recorded: " + " | ".join(l[:200] for l in lessons[:5])) if lessons else ""
    try:
        v = json.load(open(f"{P}/02-verdict.json"))
    except Exception:
        v = {}
    sel = f" Selected candidate: {v.get('selected')} — {str(v.get('selection_reasoning', ''))[:300]}." if v.get("selected") else ""
    # The ledger rows for this run (fleet/ledger.py): the candidate it attempted and
    # the run itself. The Job name is the run id; BRANCH is agent/<job name> for
    # missions and agent/dsh-daily-<date> for the daily.
    iid = idea_of(v)
    try:
        fp, title, issue_url = candidate(v)
        if fp:
            ledger.upsert_candidate(fp, REPO, title, "human" if BRIEF else "improve", issue_url=issue_url,
                                    evidence={"idea_id": iid} if iid else None)
        timing = json.load(open(f"{P}/timing.json")) if os.path.exists(f"{P}/timing.json") else None
        ledger.finish_run(run_id(), "halted" if stopped else "shipped", halt=stopped, timing=timing,
                          pr_url=pr_url, pipeline="mission" if BRIEF else "improve", repo=REPO,
                          trigger=os.environ.get("RUN_TRIGGER", "unknown"), fp=fp, cost=cost_of(timing))
        if fp:
            # tested = PR open, the reviewer's turn; an unchanged review round leaves it there
            ledger.set_state(fp, "halted" if stopped and not unchanged else "tested")
        print(f"ledger: run recorded (candidate {fp})")
    except Exception as e:
        print("ledger write failed (non-fatal):", e)
    # Closure (lineage spec step 6, 2026-09-10): the idea this run attempted hears
    # how it went. A review round iterates on a PR the idea already shipped, and a
    # quiet halt attempted nothing, so neither touches the idea.
    if iid and os.environ.get("RUN_TRIGGER") != "review" and not (stopped and stopped.get("reason") in QUIET_HALTS):
        try:
            ideas.outcome(iid, run_id(), pr_url=pr_url, halt=stopped)
            print(f"ideas: {iid} {'shipped' if pr_url else 'failed'}")
        except Exception as e:
            print("ideas write failed (non-fatal):", e)
    what = f"Mission on {REPO} ({BRIEF[:200]})" if BRIEF else f"The daily self-improvement pipeline on the {REPO} repo"
    try:
        brain.add_episode(
            f"{PIPELINE.lower()} pipeline ({date.today()})",
            f"{what} {outcome}.{sel} Stages ran brief-or-investigate/adjudicate/implement/test with "
            f"per-stage artifacts in the run's pod logs and (when shipped) the PR body.",
            f"{PIPELINE.lower()} pipeline trace", client="fleet-publish")
        print("brain: episode queued")
    except Exception as e:
        print("brain write failed (non-fatal):", e)

    label = PIPELINE + ((": " + BRIEF[:120]) if BRIEF else "")
    # The forum: what was done and what was not, in the implementer's own words,
    # addressed to the reviewer (a PR) or to reconcile and Chris (a halt).
    if stopped and degenerate(stopped.get("log_tail") or ""):
        stopped["reason"] = "model output degenerate (token salad): " + str(stopped.get("reason", ""))[:120]
    tail0 = clean_tail((stopped.get("log_tail") or "").strip()[-600:]) if stopped else ""
    if pr_url:
        ledger.say("implementer", f"Opened {pr_url} for {what[:160]}.{sel} The PR body carries the pipeline's own test run; "
                   "the adversarial test stage said SHIP. Not done: anything outside the selected candidate's scope." + learned,
                   topic="status", ref=pr_url, mentions=["reviewer"])
    else:
        # A halt is status, not a question: a real question is what the implementer
        # posts itself mid-run (topic question, mentions chris), and that one makes
        # reconcile wait for the answer instead of relaunching.
        ledger.say("implementer", f"I stopped: {what[:160]} halted at {stopped['stage']}: {stopped['reason'][:200]}. "
                   + (f"Last output: {tail0}" if tail0 else "No output captured.") + " What would unblock me: a brief that addresses this reason, or a human saying the task is wrong." + learned,
                   topic="status", ref=candidate(v)[2], mentions=["reconcile"])
    if pr_url:
        telegram.send(f"\U0001F528 {label}: PR opened {pr_url}\nThe reviewer scores it within 15 min.")
    else:
        # The halt bundle (stage.sh): exit code + the last lines of dsh's own output.
        tail = clean_tail((stopped.get("log_tail") or "").strip())
        code = stopped.get("exit_code") or "?"
        if stopped["reason"] in QUIET_HALTS:
            print(f"publish: quiet halt ({stopped['reason']}): ledger + forum only, no issue, no page")
            return
        # A halt is the fleet's to retry (its issue, the forum, the night line);
        # 11 halt pages in one day needed no action from Chris (2026-09-13).
        print(f"publish: halt {file_halt_issue(stopped, tail, code)}: issue + forum, not paged")
        return
    print("telegram: notified")


def run_started_at(timing: dict | None) -> str:
    """When this run's first stage began (ISO, UTC), from timing.json: each
    stage records when it ended and how long it took. "" when unknown, and
    then close_stale_halts closes nothing."""
    from datetime import datetime, timedelta, timezone
    starts = []
    for t in (timing or {}).values():
        try:
            starts.append(datetime.strptime(t["at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc) - timedelta(seconds=int(t.get("seconds") or 0)))
        except Exception:
            pass
    return min(starts).strftime("%Y-%m-%dT%H:%M:%SZ") if starts else ""


def close_stale_halts(pr_url: str, started_at: str) -> list[int]:
    """A ship on this repo closes the open fleet:halt issues filed before this
    run started: the pipeline got past the stage they name, so the halt did
    not recur (new_localai#75 and kagent#29 sat open for a day after the fix
    shipped, kept the repo at the top of choose_repo and the console red).
    A repeat files a new issue by fingerprint. Returns the numbers closed."""
    closed: list[int] = []
    if not started_at:
        return closed
    try:
        for iss in github.api(f"/repos/{REPO}/issues?state=open&labels=fleet:halt&per_page=50"):
            if iss.get("pull_request") or (iss.get("created_at") or "") >= started_at:
                continue
            github.api(iss["comments_url"], {"body": f"Run `{run_id()}` shipped {pr_url} on this repo after this halt was filed, "
                                              "so the halt did not recur. Closed by publish; a repeat files a new issue."})
            github.api(f"/repos/{REPO}/issues/{iss['number']}", {"state": "closed", "state_reason": "completed"}, method="PATCH")
            closed.append(iss["number"])
    except Exception as e:
        print(f"ledger: could not close stale halts (non-fatal): {e}")
    return closed


def file_halt_issue(stopped: dict, tail: str, code) -> str | None:
    """The ledger entry for a halt: a GitHub issue on the repo the run touched,
    fingerprinted so the same halt does not pile up. fleet:halt is the label
    the reconciler and the console read; nobody has to notice a Telegram line.
    Returns "new", "repeat" (appended to the existing issue) or None (could not file)."""
    import hashlib
    fp = hashlib.sha1(f"{REPO}|{stopped['stage']}|{stopped['reason']}|{BRIEF[:200]}".encode()).hexdigest()[:12]
    title = f"fleet halt: {PIPELINE.lower()} stopped at {stopped['stage']} ({stopped['reason'][:60]})"
    timing = slurp("timing.json", 2000)
    st = (stopped.get("session_tail") or "")[-5000:]
    session = f"\n<details><summary>dsh session transcript (tail)</summary>\n\n```\n{st}\n```\n</details>\n" if st else ""
    body = (f"<!-- fleet-fingerprint:{fp} -->\n"
            f"**Pipeline:** {PIPELINE}\n**Stage:** {stopped['stage']}\n**Reason:** {stopped['reason']}\n**Exit code:** {code}\n"
            f"**When:** {stopped.get('at', '')}\n" + (f"**Brief:** {BRIEF[:500]}\n" if BRIEF else "") +
            f"\n<details><summary>last dsh output</summary>\n\n```\n{tail[-3500:]}\n```\n</details>\n"
            f"{session}"
            f"\n<details><summary>stage timing</summary>\n\n```json\n{timing}\n```\n</details>\n"
            "\nLabel `mission` to have the fleet retry with this halt as context; `fleet:declined` to drop it.")
    try:
        open_issues = github.api(f"/repos/{REPO}/issues?state=open&labels=fleet:halt&per_page=50")
        for iss in open_issues:
            if fp in (iss.get("body") or ""):
                github.api(iss["comments_url"], {"body": f"Halted again at {stopped['stage']} ({stopped.get('at', '')}), exit {code}.\n\n```\n{tail[-1500:]}\n```"})
                print(f"ledger: appended to issue #{iss['number']}")
                return "repeat"
        for lbl in ("fleet:halt",):
            try:
                github.api(f"/repos/{REPO}/labels", {"name": lbl, "color": "b60205", "description": "a fleet pipeline run halted; body carries the diagnostic bundle"})
            except Exception:
                pass  # exists
        iss = github.api(f"/repos/{REPO}/issues", {"title": title, "body": body, "labels": ["fleet:halt"]})
        print(f"ledger: filed issue #{iss.get('number')} {iss.get('html_url')}")
        return "new"
    except Exception as e:
        print(f"ledger: could not file the halt issue (non-fatal): {e}")


if __name__ == "__main__":
    main()
