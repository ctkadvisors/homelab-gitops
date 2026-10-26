"""Plan for the implement stage (2026-09-15): the judge (qwen38, called direct)
turns the task into a numbered checklist, and the implementer (ornith15 in dsh)
works through it. Chris: "qwen38 as the planner, delegate to ornith ... qwen38
as reviewer". ornith15 did 3.5 of 5 review points on kagent#60's round and no
fleet PR in 27 reached the reviewer's 85; a small fast model carries out an
explicit list better than an open brief. qwen38 stays out of dsh itself: inside
the tool loop it wandered and never answered (review.py, 2026-09-08).

Writes $P/plan.md and prints its path. Fails open: no judge, no plan, no change.
"""

from __future__ import annotations

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.dirname(HERE), HERE]
import review  # noqa: E402

P = os.environ.get("PIPELINE_DIR", "/workspace/p")
REPO_DIR = os.environ.get("REPO_DIR", "/workspace/repo")


def task_text() -> str:
    """The mission brief (a review round carries the reviewer's points in it), or
    the improve run's adjudicated candidate."""
    brief = os.environ.get("MISSION_BRIEF", "")
    try:
        verdict = open(f"{P}/02-verdict.json").read()[:6000]
    except OSError:
        verdict = ""
    return (brief + ("\n\nADJUDICATED CANDIDATE:\n" + verdict if verdict else "")).strip()


def prompt_for(task: str, files: list[str]) -> str:
    return ("You plan a code change that a smaller, fast model will carry out step by step. It follows explicit "
            "steps well and open briefs badly: it does most of a list and quietly skips the rest, so leave nothing to "
            "its judgement.\n\nTASK:\n" + task[:8000]
            + "\n\nFILES IN THE REPOSITORY (first 400):\n" + "\n".join(files[:400])
            + "\n\nReply with STRICT JSON, nothing else: {\"steps\": [{\"file\": \"<a path above, or a new test file>\", "
            "\"change\": \"<exactly what to change>\", \"proof\": \"<the command or test that shows it is done>\"}]}. "
            "3 to 8 steps. Every point of any REVIEW FEEDBACK in the task is its own step. The last step writes "
            "/workspace/p/verify.sh, which runs every proof and prints its output.")


def render(steps: list[dict]) -> str:
    return "".join(f"{i}. {s.get('file', '')}: {s.get('change', '')}\n   proof: {s.get('proof', '')}\n"
                   for i, s in enumerate(steps, 1) if isinstance(s, dict))


def main() -> int:
    task = task_text()
    if not review.JUDGE_URL or not task:
        return 0
    files = subprocess.run(["git", "-C", REPO_DIR, "ls-files"], capture_output=True, text=True).stdout.splitlines()
    try:
        # Thinking off: a checklist from a brief is extraction, not deliberation, and with
        # thinking on the first mission's plan sat in qwen38's two slots behind reviewer
        # verdicts for 10+ min of its 90 (2026-09-15). precheck keeps thinking: it is the bar.
        steps = review.parse_json(review.ask_judge(prompt_for(task, files), thinking=False)).get("steps") or []
    except Exception as e:  # the judge being down must not stop the implementer
        print(f"plan: judge unavailable ({type(e).__name__}: {str(e)[:80]})", file=sys.stderr)
        return 0
    text = render(steps)
    if text:
        with open(f"{P}/plan.md", "w") as f:
            f.write(text)
        print(f"{P}/plan.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
