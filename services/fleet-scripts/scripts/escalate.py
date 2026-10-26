"""Escalation for the implement stage (2026-09-15, Chris: "Escalate to qwen38").
ornith15 implements first; when pre-review rejects it twice, or its session
collapses into token salad (mission-20260915-180448-3ca8: "Ber db Ber ..." to the
token ceiling, halted after 1506 s), the judge model takes over the open points.
qwen38 cannot drive dsh's tool loop (review.py, 2026-09-08), so this is patch
mode: one direct call with the plan, the open points and the current contents of
every file involved. It answers with SEARCH/REPLACE edits that this script
applies and commits; stage.sh then runs verify.sh and pre-review on the result.

escalate.py <why>        exit 0: a commit was made. exit 1: nothing applied.
escalate.py --degenerate exit 0 when stdin (a log tail) is token salad.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.dirname(HERE), HERE]
import plan  # noqa: E402
import precheck  # noqa: E402
import review  # noqa: E402

P = os.environ.get("PIPELINE_DIR", "/workspace/p")
REPO_DIR = os.environ.get("REPO_DIR", "/workspace/repo")
MAX_FILE, MAX_TOTAL = 24000, 90000   # one qwen38 slot is 131072 tokens; this leaves room to think and answer
BLOCK = re.compile(r"^FILE: *(\S+)\n<<<<<<< SEARCH\n(.*?)^=======\n(.*?)^>>>>>>> REPLACE$", re.M | re.S)


def slurp(path: str, limit: int) -> str:
    try:
        return open(path, errors="replace").read()[:limit]
    except OSError:
        return ""


def git(*a: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", REPO_DIR, *a], capture_output=True, text=True)


def files_involved(start: str, plan_md: str) -> list[str]:
    changed = git("diff", "--name-only", f"{start}..HEAD").stdout.splitlines() if start else []
    planned = re.findall(r"^\d+\. ([^\s:]+):", plan_md, re.M)
    out: list[str] = []
    for f in changed + planned:
        if f not in out and not f.startswith("/") and f != "verify.sh":
            out.append(f)
    return out[:15]


def target(path: str) -> str | None:
    """Where an edit may land: inside the repo (not .git), or the pipeline's verify.sh."""
    if path == f"{P}/verify.sh":
        return path
    full = os.path.realpath(os.path.join(REPO_DIR, path))
    root = os.path.realpath(REPO_DIR)
    if not full.startswith(root + os.sep) or ".git" in os.path.relpath(full, root).split(os.sep):
        return None
    return full


def apply(reply: str) -> list[str]:
    done = []
    for path, search, replace in BLOCK.findall(reply):
        full = target(path)
        old = slurp(full, 10**8) if full and os.path.exists(full) else None
        if not full:
            new = None
        elif not search.strip():
            new = replace if not (old or "").strip() else None   # an empty SEARCH only creates
        else:
            new = old.replace(search, replace) if old is not None and old.count(search) == 1 else None
        if new is None:
            print(f"escalate: skipped an edit to {path} (outside the repo, or its SEARCH text is not in the file exactly once)")
            continue
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w") as f:
            f.write(new)
        done.append(path)
    return done


def prompt_for(why: str, task: str, plan_md: str, points: str, diff: str, files: dict[str, str | None]) -> str:
    shown, total = [], 0
    for path, text in files.items():
        body = "(does not exist yet)" if text is None else text[:MAX_FILE]
        if total + len(body) > MAX_TOTAL:
            break
        total += len(body)
        shown.append(f"=== {path} ===\n{body}")
    lead = ("The implementer (a smaller model) had two tries and the reviewer rejected both. You take over: "
            "address every open point below yourself." if why == "rejected" else
            "The implementer (a smaller model) collapsed into gibberish; nothing it wrote this round can be trusted. "
            "You take over: carry out the plan yourself.")
    return (lead + "\n\nTASK:\n" + task[:6000] + "\n\nPLAN:\n" + (plan_md or "(none)")[:3000]
            + "\n\nOPEN POINTS:\n" + (points or "(none: do the plan)")[:4000]
            + "\n\nTHE CHANGE SO FAR (git diff against the base):\n" + (diff or "(nothing committed)")[:20000]
            + "\n\nCURRENT FILE CONTENTS:\n" + "\n\n".join(shown)
            + "\n\nAnswer ONLY with edit blocks, as many as needed, each exactly:\n"
            "FILE: <repo-relative path>\n<<<<<<< SEARCH\n<lines copied exactly from the file above>\n=======\n"
            "<the replacement lines>\n>>>>>>> REPLACE\n"
            "The SEARCH text must appear exactly once in that file; keep it short but unique. An empty SEARCH "
            f"creates a new file. If {P}/verify.sh does not exist, add a block for FILE: {P}/verify.sh with an empty "
            "SEARCH: a POSIX sh script, run from the repo root, that runs the tests proving the change and exits "
            "non-zero when they fail. Every open point is addressed by at least one block.")


def main(argv: list[str]) -> int:
    if argv[:1] == ["--degenerate"]:
        import publish   # its token-salad test, the one that keeps salad out of Telegram
        return 0 if publish.degenerate(sys.stdin.read()) else 1
    why = argv[0] if argv else "rejected"
    if not review.JUDGE_URL:
        return 1
    start = precheck.pr_base()   # the PR's whole change, as the reviewer sees it
    plan_md = slurp(f"{P}/plan.md", 3000)
    points = slurp(f"{P}/precheck.out", 4000) if why == "rejected" else ""
    if slurp(f"{P}/verify.rc", 10).strip() == "1":
        points += "\n\nverify.sh failed:\n" + slurp(f"{P}/verify.out", 10**6)[-2000:]
    files = {f: (slurp(os.path.join(REPO_DIR, f), MAX_FILE) if os.path.exists(os.path.join(REPO_DIR, f)) else None)
             for f in files_involved(start, plan_md)}
    files[f"{P}/verify.sh"] = slurp(f"{P}/verify.sh", 4000) if os.path.exists(f"{P}/verify.sh") else None
    diff = git("diff", f"{start}..HEAD").stdout if start else ""
    # Thinking off (2026-09-15): the first live escalation (mission 3e9c) thought for 20 min at
    # ~8-10 tok/s and was killed by the cap with nothing applied. The answer is edit blocks,
    # a few thousand tokens; pre-review keeps thinking on and judges the result.
    review.JUDGE_MAX_TOKENS = int(os.environ.get("ESCALATE_MAX_TOKENS", "12000"))
    try:
        reply = review.ask_judge(prompt_for(why, plan.task_text(), plan_md, points, diff, files), thinking=False)
    except Exception as e:  # the judge being down leaves the implementer's work as it was
        print(f"escalate: judge unavailable ({type(e).__name__}: {str(e)[:80]})")
        return 1
    done = apply(reply)
    repo = [os.path.relpath(target(d), os.path.realpath(REPO_DIR)) for d in done if d != f"{P}/verify.sh"]
    if not repo or git("add", "--", *repo).returncode or git("commit", "-qm", f"fix: {review.JUDGE_MODEL} takes over the open points").returncode:
        print(f"escalate: nothing committed ({len(BLOCK.findall(reply))} edit block(s) in the reply, {len(done)} applied)")
        return 1
    with open(f"{P}/03-implementation.md", "a") as f:
        f.write(f"\n\n## Escalation ({review.JUDGE_MODEL} took over: {why})\n" + "".join(f"- {d}\n" for d in done))
    print(f"escalate: {review.JUDGE_MODEL} edited {', '.join(done)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
