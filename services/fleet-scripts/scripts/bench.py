"""The ruler (Chris, 2026-09-09: "test for success, quantifiable, incremental
improvement, with each change"). Three fixed, verifiable implement tasks run
through the real stage machinery (stage.sh implement, the real dsh patch, the
real model on the spark) inside a mission-shaped pod. Per task it records:
success (report written, commit made, the fixture's unittest passes), seconds,
prompt bytes, dsh tool-schema errors, dsh calls. Results go to stdout as JSON
and to the ledger kv `bench:<label>` so two labels can be compared.

  kubectl create job -n kagent-system --from=cronjob/fleet-bench bench-<label>
  python3 /app/scripts/bench.py --compare baseline skills     # from any pod with the ledger
  python3 /fleet/scripts/bench.py --held-out                  # the reviewer's run: HELD_OUT fixtures too
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.environ.get("BENCH_ROOT", "/workspace/bench")
FLEET = os.environ.get("FLEET_DIR", "/fleet")
TIMEOUT = int(os.environ.get("BENCH_STAGE_TIMEOUT", "900"))

TASKS = {
    # A bug behind a failing test: the smallest real implement task.
    "fix-add": {
        "files": {
            "calc.py": "def add(a, b):\n    return a - b\n",
            "test_calc.py": "import unittest\nfrom calc import add\n\nclass T(unittest.TestCase):\n    def test_add(self):\n        self.assertEqual(add(2, 3), 5)\n",
        },
        "brief": "test_calc.py fails: `python3 -m unittest -q` reports test_add FAILED. Fix the defect in calc.py so the test passes. Commit.",
    },
    # A missing function with the test already written: implement to a spec.
    "add-slugify": {
        "files": {
            "text.py": "\"\"\"text helpers\"\"\"\n",
            "test_text.py": "import unittest\nfrom text import slugify\n\nclass T(unittest.TestCase):\n    def test_slug(self):\n        self.assertEqual(slugify('Hello, World! 2026'), 'hello-world-2026')\n        self.assertEqual(slugify('  a  b  '), 'a-b')\n",
        },
        "brief": "test_text.py fails with ImportError: text.slugify does not exist. Implement slugify(s) in text.py: lower-case, drop punctuation, collapse whitespace to single hyphens, strip. Make `python3 -m unittest -q` pass. Commit.",
    },
    # A command-line behaviour that must be verified by running it.
    "cli-version": {
        "files": {
            "app/__init__.py": "VERSION = '1.0'\n",
            "app/__main__.py": "import sys\nfrom app import VERSION\n\nif __name__ == '__main__':\n    if '--verison' in sys.argv:\n        print(VERSION)\n",
            "test_cli.py": "import subprocess, sys, unittest\n\nclass T(unittest.TestCase):\n    def test_version(self):\n        out = subprocess.run([sys.executable, '-m', 'app', '--version'], capture_output=True, text=True)\n        self.assertEqual(out.stdout.strip(), '1.0')\n",
        },
        "brief": "`python3 -m app --version` prints nothing; test_cli.py fails. Find why by running it, fix app/__main__.py, and make `python3 -m unittest -q` pass. Commit.",
    },
}


# The ambiguous task: the right answer is not in the repo, only the maintainer knows.
TASKS["ask-first"] = {
    "files": {
        "calc.py": "def add(a, b):\n    return a + b\n",
        "test_calc.py": "import unittest\nimport calc\n\nclass T(unittest.TestCase):\n    def test_add(self):\n        self.assertEqual(calc.add(2, 3), 5)\n",
    },
    "brief": "The maintainer wants `add` in calc.py renamed, but has not said to what. Ask the maintainer for the new name with the ask_user_question tool before changing anything; do not guess. Then rename the function and its use in test_calc.py, make `python3 -m unittest -q` pass, and commit.",
}
ASKED: list[dict] = []
# 2026-09-10 (idea lineage, step 8): the hidden verifier. A "raise the bench"
# run targets the visible fixtures; only `--held-out` runs (the reviewer's)
# score these, and a PR is accepted only when they strictly improve.
HELD_OUT = {"ask-first"}


def fake_forum(port: int = 0) -> None:
    """A forum that answers every question with 'plus' after five seconds, so the
    ask-first task can be scored without paging a human."""
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer
    posts: list[dict] = []
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def _j(self, code, obj):
            b = json.dumps(obj).encode(); self.send_response(code); self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
        def do_GET(self): self._j(200, {"posts": list(reversed(posts))})
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"]))); body["id"] = len(posts) + 1; posts.append(body)
            if body.get("topic") == "question":
                ASKED.append(body)
                def answer(pid=body["id"]):
                    time.sleep(5); posts.append({"id": len(posts) + 1, "author": "chris", "topic": "answer", "parent_id": pid, "body": "Call it plus."})
                threading.Thread(target=answer, daemon=True).start()
            self._j(201, {"id": body["id"]})
    srv = HTTPServer(("127.0.0.1", port), H)   # port 0: whatever is free
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    os.environ["FORUM_URL"] = f"http://127.0.0.1:{srv.server_address[1]}"
    os.environ["FORUM_ASK_TIMEOUT_MS"] = "180000"
    os.environ["FORUM_ASK_POLL_MS"] = "3000"


def sh(cmd: list[str], cwd: str | None = None, timeout: int = 600) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)


def fixture(name: str) -> tuple[str, str]:
    base = os.path.join(ROOT, name)
    shutil.rmtree(base, ignore_errors=True)
    repo, p = os.path.join(base, "repo"), os.path.join(base, "p")
    os.makedirs(p)
    os.makedirs(repo)
    for rel, body in TASKS[name]["files"].items():
        path = os.path.join(repo, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, "w").write(body)
    for c in (["git", "init", "-q", "-b", "main"], ["git", "config", "user.email", "bench@fleet"], ["git", "config", "user.name", "bench"],
              ["git", "add", "-A"], ["git", "commit", "-q", "-m", "fixture"]):
        sh(c, cwd=repo)
    # stage.sh compares against origin/main: a bare origin beside the clone, so a
    # model that pushes (one did, 2026-09-09) moves origin/main there and nowhere
    # else. Success is judged by HEAD moving off the fixture commit, not by the range.
    bare = os.path.join(base, "origin.git")
    sh(["git", "clone", "-q", "--bare", repo, bare])
    sh(["git", "remote", "add", "origin", bare], cwd=repo)
    sh(["git", "fetch", "-q", "origin"], cwd=repo)
    open(os.path.join(base, "fixture.sha"), "w").write(sh(["git", "rev-parse", "HEAD"], cwd=repo).stdout.strip())
    return repo, p


def run_task(name: str) -> dict:
    repo, p = fixture(name)
    env = {**os.environ, "PIPELINE_DIR": p, "REPO_DIR": repo, "REPO": f"bench/{name}", "MISSION_BRIEF": TASKS[name]["brief"],
           "STAGE_TIMEOUT": str(TIMEOUT), "RUN_TRIGGER": "bench"}
    # The mission pipeline's brief stage (scripts/brief.py, no model) writes the
    # task into 01-findings.json / 02-verdict.json; the implement prompt reads
    # those, not MISSION_BRIEF. Until 2026-09-09 the bench skipped it, so the
    # model only ever saw a repo with failing tests, and ask-first saw nothing.
    subprocess.run([sys.executable, f"{FLEET}/scripts/brief.py"], env=env, capture_output=True, text=True, timeout=60)
    t = time.time()
    out = subprocess.run(["sh", f"{FLEET}/scripts/stage.sh", "implement"], env=env, capture_output=True, text=True, timeout=TIMEOUT + 120)
    secs = round(time.time() - t, 1)
    log = out.stdout + out.stderr
    report = os.path.exists(f"{p}/03-implementation.md")
    fixture_sha = open(os.path.join(ROOT, name, "fixture.sha")).read().strip()
    head = sh(["git", "rev-parse", "HEAD"], cwd=repo).stdout.strip()
    commit = bool(head) and head != fixture_sha and not sh(["git", "status", "--short", "--untracked-files=no"], cwd=repo).stdout.strip()
    tests = sh([sys.executable, "-m", "unittest", "-q"], cwd=repo, timeout=120)
    passed = tests.returncode == 0
    metrics = {}
    try:
        metrics = json.load(open(f"{p}/implement.metrics.json"))
    except Exception:
        pass
    stopped = None
    if os.path.exists(f"{p}/stop"):
        try:
            stopped = json.load(open(f"{p}/stop")).get("reason")
        except Exception:
            stopped = "?"
    asked_before = run_task.asked; run_task.asked = len(ASKED)
    r = {"task": name, "success": report and commit and passed, "report": report, "commit": commit, "tests_pass": passed,
         "seconds": secs, "halt": stopped, "asked": len(ASKED) - asked_before, "held_out": name in HELD_OUT, **metrics}
    if name == "ask-first":
        renamed = "def plus(" in open(os.path.join(repo, "calc.py")).read()
        r["success"] = r["success"] and r["asked"] > 0 and renamed   # asked, and used the answer
    # What the stage said (its own lines only), and on failure the tail of what dsh did.
    stage_lines = [l for l in log.splitlines() if l.startswith("stage ")]
    print(f"--- {name}: " + " | ".join(stage_lines[-6:]), flush=True)
    if not r["success"]:
        try:
            tail = open(f"{p}/implement.log", errors="replace").read().splitlines()[-25:]
            print(f"--- {name} dsh tail:\n" + "\n".join(l[:220] for l in tail), flush=True)
        except Exception:
            pass
        try:
            print(f"--- {name} git status: " + sh(["git", "status", "--short"], cwd=repo).stdout.strip().replace("\n", " ; ")[:300], flush=True)
        except Exception:
            pass
    print(json.dumps(r), flush=True)
    return r


run_task.asked = 0


def label() -> str:
    lab = os.environ.get("BENCH_LABEL") or os.environ.get("JOB_NAME", "")
    lab = re.sub(r"^bench-", "", lab) or time.strftime("%Y%m%d-%H%M")
    return lab


def record(lab: str, rows: list[dict]) -> None:
    summary = {"label": lab, "at": time.time(), "success": sum(r["success"] for r in rows), "n": len(rows),
               "seconds": round(sum(r["seconds"] for r in rows), 1), "prompt_bytes": sum(int(r.get("prompt_bytes") or 0) for r in rows),
               "schema_errors": sum(int(r.get("schema_errors") or 0) for r in rows), "dsh_calls": sum(int(r.get("dsh_calls") or 0) for r in rows),
               "rounds": sum(int(r.get("rounds") or 1) for r in rows), "wrote_verify": sum(1 for r in rows if r.get("wrote_verify")),
               "report_synthesized": sum(1 for r in rows if r.get("report_synthesized")), "asked": sum(int(r.get("asked") or 0) for r in rows),
               "rows": rows}
    print("SUMMARY " + json.dumps({k: v for k, v in summary.items() if k != "rows"}), flush=True)
    try:
        from fleet import ledger
        ledger.kv_set(f"bench:{lab}", summary)
        print(f"bench: recorded as bench:{lab}")
    except Exception as e:
        print(f"bench: ledger write skipped ({type(e).__name__}: {str(e)[:80]})")


def held_out_passes(summary: dict) -> int:
    return sum(1 for r in summary.get("rows") or [] if r.get("held_out") and r.get("success"))


def held_out_seconds(summary: dict) -> float:
    return sum(float(r.get("seconds") or 0) for r in summary.get("rows") or [] if r.get("held_out") and r.get("success"))


def verdict(before: dict, after: dict) -> str:
    """Held-out passes decide; when they tie with every held-out fixture
    passing, held-out seconds decide (10% faster = improved, 10% slower =
    regressed): with a single held-out fixture that already passes, passes
    alone could never say improved (2026-09-10, the first bench-target run).
    Any other tie is no_change: the reviewer rejects ties."""
    a, b = held_out_passes(before), held_out_passes(after)
    if b != a:
        return "improved" if b > a else "regressed"
    if a and a == len(HELD_OUT):
        sa, sb = held_out_seconds(before), held_out_seconds(after)
        if sa and sb:
            return "improved" if sb < 0.9 * sa else "regressed" if sb > 1.1 * sa else "no_change"
    return "no_change"


def compare(labels: list[str]) -> str | None:
    """Print the table; with exactly two labels also print and return the verdict."""
    from fleet import ledger
    print(f"{'label':16} {'ok':>5} {'held':>5} {'secs':>7} {'prompt_b':>9} {'schema_err':>10} {'calls':>6} {'rounds':>6} {'verify':>6} {'synth':>5} {'asked':>5}")
    got = {}
    for lab in labels:
        s = ledger.kv_get(f"bench:{lab}") or {}
        if not s:
            print(f"{lab:16} (no record)"); continue
        got[lab] = s
        print(f"{lab:16} {s['success']:>2}/{s['n']:<2} {held_out_passes(s):>5} {s['seconds']:>7} {s['prompt_bytes']:>9} {s['schema_errors']:>10} {s['dsh_calls']:>6} {s.get('rounds', '-'):>6} {s.get('wrote_verify', '-'):>6} {s.get('report_synthesized', '-'):>5} {s.get('asked', '-'):>5}")
    if len(labels) != 2 or len(got) != 2:
        return None
    a, b = got[labels[0]], got[labels[1]]
    v = verdict(a, b)
    # seconds are a tiebreaker for the reader only: a faster tie is still no_change
    print(f"verdict {labels[0]} -> {labels[1]}: {v} (held-out {held_out_passes(a)} -> {held_out_passes(b)}, {a['seconds']}s -> {b['seconds']}s)")
    return v


def main() -> int:
    if len(sys.argv) > 2 and sys.argv[1] == "--compare":
        compare(sys.argv[2:]); return 0
    visible = ",".join(n for n in TASKS if "--held-out" in sys.argv or n not in HELD_OUT)
    names = [n for n in os.environ.get("BENCH_TASKS", visible).split(",") if n in TASKS]
    lab = label()
    fake_forum()
    print(f"bench {lab}: {names} (timeout {TIMEOUT}s each)", flush=True)
    rows = [run_task(n) for n in names]
    record(lab, rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
