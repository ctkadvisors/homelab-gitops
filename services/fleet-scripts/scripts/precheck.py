"""Pre-review for the implement stage (2026-09-15): the PR reviewer's own judge
(review.judge: same prompt, same model, same bar) scores this run's diff before
it becomes a PR. Below PRECHECK_MIN the open points go back to the implementer
inside the same stage, minutes later, instead of a review round hours later. No
fleet PR in 27 reached 85, and review rounds drifted down (80 -> 78 -> 58): the
implementer never saw the bar until it had already shipped.

Exit 0: good enough, or no judge, or an error (fail open). Exit 1: the verdict
and its open points are on stdout. The verdict is kept in $P/precheck.json.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.dirname(HERE), HERE]
import review  # noqa: E402

P = os.environ.get("PIPELINE_DIR", "/workspace/p")
REPO_DIR = os.environ.get("REPO_DIR", "/workspace/repo")
PRECHECK_MIN = int(os.environ.get("PRECHECK_MIN", str(review.MERGE_MIN)))
ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def slurp(name: str, limit: int) -> str:
    try:
        return open(f"{P}/{name}", errors="replace").read()[-limit:]
    except OSError:
        return ""


def pr_base() -> str:
    """What the PR reviewer diffs from: the merge-base with the default branch. On a review
    round STAGE_START_SHA is the PR's head, so this round's diff alone showed kagent#62's round
    deleting main.test.ts - a file the PR itself had added - and pre-review scored the removal
    the reviewer asked for 45 (2026-09-15). A fresh mission branches from main: same base."""
    mb = subprocess.run(["git", "-C", REPO_DIR, "merge-base", "HEAD", "origin/HEAD"], capture_output=True, text=True).stdout.strip()
    return mb or os.environ.get("STAGE_START_SHA", "")


def main() -> int:
    start = os.environ.get("STAGE_START_SHA", "")
    if not review.JUDGE_URL or not start:
        return 0
    diff = subprocess.run(["git", "-C", REPO_DIR, "diff", f"{pr_base()}..HEAD"], capture_output=True, text=True).stdout
    if not diff.strip():
        return 0
    brief = os.environ.get("MISSION_BRIEF", "") or slurp("02-verdict.json", 3000)
    pr = {"title": (brief.splitlines() or ["implement"])[0][:200],
          "body": ("### Pipeline-run evidence (stage.sh executed this; the model did not write the output)\n"
                   + ANSI.sub("", slurp("verify.out", 1500))
                   + "\n\n### Plan\n" + slurp("plan.md", 3000) + "\n\n### Task\n" + brief[:3000])}
    try:
        v = review.judge(pr, diff[:review.JUDGE_DIFF_CHARS], cwd=REPO_DIR)
    except Exception as e:  # the judge being down must not block the run: the PR reviewer still judges it
        print(f"precheck: judge unavailable ({type(e).__name__}: {str(e)[:80]})")
        return 0
    conf = int(v.get("confidence") or 0)
    with open(f"{P}/precheck.json", "w") as f:
        json.dump({"confidence": conf, "summary": v.get("summary", ""), "feedback": v.get("feedback", "")}, f)
    print(f"pre-review confidence {conf} (bar {PRECHECK_MIN}): {v.get('summary', '')}\n{v.get('feedback', '')}")
    return 0 if conf >= PRECHECK_MIN or v.get("summary") == "unparseable review" else 1


if __name__ == "__main__":
    sys.exit(main())
