"""Clone the target repo for a pipeline run. Deterministic, holds the
GitHub credential only for the clone, and leaves a token-free remote so
the model stages that follow never see it (publish re-adds it for push)."""

import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fleet import github  # noqa: E402

REPO = os.environ.get("REPO", "ctkadvisors/kagent")
REPO_DIR = os.environ.get("REPO_DIR", "/workspace/repo")
url = os.environ.get("CLONE_URL") or github.push_url(REPO)

subprocess.run(["git", "clone", "--depth", "50", url, REPO_DIR], check=True)
# A review round continues the PR's own branch (reconcile.retry_reviewed sets
# BRANCH to the open PR's head): fetch it and work from there, so the push
# updates that PR instead of opening a second one.
BRANCH = os.environ.get("BRANCH", "")
if BRANCH and subprocess.run(["git", "-C", REPO_DIR, "ls-remote", "--exit-code", "--heads", url, BRANCH],
                             capture_output=True).returncode == 0:
    subprocess.run(["git", "-C", REPO_DIR, "fetch", "--depth", "50", url, BRANCH], check=True)
    subprocess.run(["git", "-C", REPO_DIR, "checkout", "-B", BRANCH, "FETCH_HEAD"], check=True)
    print(f"clone: continuing existing branch {BRANCH}")
subprocess.run(["git", "-C", REPO_DIR, "remote", "set-url", "origin", f"https://github.com/{REPO}.git"], check=True)
# Identity goes in the clone's own .git/config on the shared /workspace:
# every later stage is a different container with a different HOME, and
# this container's HOME is unwritable (missions died on //.gitconfig).
subprocess.run(["git", "-C", REPO_DIR, "config", "user.email", "builder@example.com"], check=True)
subprocess.run(["git", "-C", REPO_DIR, "config", "user.name", "kagent homelab-builder"], check=True)
print(f"clone: {REPO} -> {REPO_DIR} (remote left token-free)")
