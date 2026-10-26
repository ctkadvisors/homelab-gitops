"""triage: GitHub issues labeled `mission` become missions.

Deterministic intake for the night shift. Each picked issue gets a comment
naming the Job so it is never picked twice.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fleet import github  # noqa: E402

LAUNCHER = os.environ.get("LAUNCHER", "http://mission-launcher.kagent-system.svc.cluster.local:8080")
LABEL = os.environ.get("LABEL", "mission")
MARK = "mission started:"


def brief_for(issue: dict, comments: list[dict] | None = None) -> str:
    """The issue as the mission brief. Human comments ride along (the console's
    feedback lands there), fleet chatter does not."""
    notes = [c for c in (comments or []) if MARK not in (c.get("body") or "") and not (c.get("user") or {}).get("login", "").endswith("[bot]")]
    talk = "".join(f"\n\n> {(c.get('user') or {}).get('login', '?')}: {(c.get('body') or '').strip()[:1500]}" for c in notes[-5:])
    return (f"GitHub issue {issue['html_url']} — {issue['title']}\n\n{(issue.get('body') or '').strip()}"
            + (f"\n\nFeedback on the issue, newest last:{talk}" if talk else "") +
            f"\n\nImplement what the issue asks, nothing more. Reference the issue number in the commit message "
            f"(#{issue['number']}).")[:8000]


def launch(brief: str, repo: str, requested_by: str) -> dict:
    req = urllib.request.Request(LAUNCHER + "/missions",
                                 data=json.dumps({"brief": brief, "repo": repo, "requestedBy": requested_by}).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    return json.load(urllib.request.urlopen(req, timeout=30))


def triage_repo(repo: str) -> int:
    """Start a mission for every unclaimed `mission` issue in one repo. Returns the count."""
    started = 0
    try:
        issues = github.api(f"/repos/{repo}/issues?state=open&labels={LABEL}&per_page=30")
    except urllib.error.HTTPError as e:
        print(f"triage: {repo}: cannot list issues: HTTP {e.code} (check the token's Issues permission)")
        return 0
    for issue in issues:
        if "pull_request" in issue:
            continue
        comments = github.api(issue["comments_url"] + "?per_page=100")
        if any(MARK in (c.get("body") or "") for c in comments):
            continue
        try:
            res = launch(brief_for(issue, comments), repo, f"triage:{issue['html_url']}")
        except urllib.error.HTTPError as e:
            why = e.read()[:200].decode(errors="replace")
            print(f"triage: {repo}#{issue['number']}: {'refused' if e.code == 409 else 'launch failed'}: HTTP {e.code} {why}")
            continue
        except Exception as e:
            print(f"triage: {repo}#{issue['number']}: launch failed: {e}")
            continue
        github.api(issue["comments_url"], {"body": f"{MARK} `{res['name']}` on branch `{res['branch']}` "
                   "(dsh staged pipeline, all-local). The PR or halt reason lands here and on Telegram when it finishes."})
        print(f"triage: {repo}#{issue['number']} -> {res['name']}")
        started += 1
    return started


def main() -> None:
    started = sum(triage_repo(repo) for repo in github.repos_from_env())  # every repo the App is installed on
    print(f"triage: {started} mission(s) started")


if __name__ == "__main__":
    main()
