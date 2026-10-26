"""The runnable checks: pipeline validate/brief artifacts, the GitHub App
JWT, and every script compiling. `python3 -m pytest services/fleet-scripts`."""

import base64
import json
import os
import pathlib
import py_compile
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fleet import github  # noqa: E402


def run_script(name, env, cwd=None):
    return subprocess.run([sys.executable, str(ROOT / "scripts" / name)] if name.endswith(".py")
                          else ["sh", str(ROOT / "scripts" / name)],
                          env={**os.environ, **env}, capture_output=True, text=True, cwd=cwd)


def test_every_script_compiles():
    for p in (ROOT / "scripts").glob("*.py"):
        py_compile.compile(str(p), doraise=True)
    assert subprocess.run(["sh", "-n", str(ROOT / "scripts" / "stage.sh")]).returncode == 0


def test_brief_writes_selected_candidate(tmp_path):
    p = tmp_path / "p"
    r = run_script("brief.py", {"MISSION_BRIEF": "fix the thing", "PIPELINE_DIR": str(p)})
    assert r.returncode == 0, r.stderr
    findings = json.load(open(p / "01-findings.json"))
    verdict = json.load(open(p / "02-verdict.json"))
    assert findings["candidates"][0]["claim"] == "fix the thing"
    assert verdict["selected"] == "M1"


def test_stage_halt_carries_exit_code_log_tail_and_timing(tmp_path):
    """A failing dsh must leave a legible halt: exit code, the log tail, and the stage's wall time."""
    repo = tmp_path / "repo"; (repo / ".git").mkdir(parents=True)
    cfg = tmp_path / "config"; cfg.mkdir()
    (cfg / "implement.txt").write_text("do the thing")
    fake = tmp_path / "dsh"; fake.write_text("#!/bin/sh\necho 'reading src/x.ts'\necho 'boom: model returned nothing' >&2\nexit 3\n"); fake.chmod(0o755)
    p = tmp_path / "p"
    # /config is hard-wired in stage.sh; point at our dir through a symlink-free trick: run in a shell with /config bind unavailable -> use sed copy
    script = (ROOT / "scripts" / "stage.sh").read_text().replace('"/config/$S.txt"', f'"{cfg}/$S.txt"').replace("/config/dsh-patch.yml", f"{cfg}/dsh-patch.yml")
    (tmp_path / "stage.sh").write_text(script)
    r = subprocess.run(["sh", str(tmp_path / "stage.sh"), "implement"],
                       env={**os.environ, "PIPELINE_DIR": str(p), "REPO_DIR": str(repo), "DSH": str(fake), "PATH": os.environ["PATH"]},
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    stop = json.load(open(p / "stop"))
    assert stop["stage"] == "implement" and stop["reason"] == "dsh session failed" and stop["exit_code"] == "3"
    assert "boom: model returned nothing" in stop["log_tail"] and "reading src/x.ts" in stop["log_tail"]
    assert (p / "implement.log").exists()
    timing = json.load(open(p / "timing.json"))
    assert timing["implement"]["status"] == "halted" and timing["implement"]["seconds"] >= 0


def test_clone_leaves_a_token_free_remote(tmp_path):
    repo = tmp_path / "origin"
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / "README.md").write_text("x")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init"], check=True)
    # HOME=/ is unwritable, as in the mission pod: identity must not need a global config.
    r = run_script("clone.py", {"REPO": "x/y", "REPO_DIR": str(tmp_path / "repo"), "CLONE_URL": str(repo), "HOME": "/"})
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "repo" / "README.md").exists()
    email = subprocess.run(["git", "-C", str(tmp_path / "repo"), "config", "user.email"], capture_output=True, text=True).stdout.strip()
    assert email == "builder@example.com"  # lives in the clone's .git/config, seen by every later stage
    remote = subprocess.run(["git", "-C", str(tmp_path / "repo"), "remote", "get-url", "origin"], capture_output=True, text=True).stdout.strip()
    assert remote == "https://github.com/x/y.git"  # never the token-bearing clone URL


def test_installation_repos_paginates(monkeypatch):
    pages = {1: {"total_count": 3, "repositories": [{"full_name": "o/a"}, {"full_name": "o/b"}]},
             2: {"total_count": 3, "repositories": [{"full_name": "o/c"}]}}
    monkeypatch.setattr(github, "api", lambda path, **kw: pages[int(path.rsplit("page=", 1)[1])])
    assert github.installation_repos() == ["o/a", "o/b", "o/c"]
    monkeypatch.setenv("REPOS", "x/y")
    assert github.repos_from_env() == ["x/y"]


def test_validate_stops_on_missing_or_rejected(tmp_path):
    p = tmp_path / "p"
    p.mkdir()
    env = {"PIPELINE_DIR": str(p), "REPO_DIR": str(tmp_path)}
    r = run_script("validate.py", {**env}, cwd=None) if False else None  # placeholder for clarity
    (p / "01-findings.json").write_text('{"candidates": []}')
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "validate.py"), "investigate"],
                       env={**os.environ, **env}, capture_output=True, text=True)
    assert "STOP" in r.stdout and json.load(open(p / "stop"))["stage"] == "investigate"
    (p / "stop").unlink()
    (p / "04-test-report.json").write_text('{"verdict": "REJECT", "reasoning": "nope"}')
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "validate.py"), "test"],
                       env={**os.environ, **env}, capture_output=True, text=True)
    assert json.load(open(p / "stop"))["reason"].startswith("tester rejected")


def test_app_jwt_is_rs256_signed_with_the_key(tmp_path):
    key = tmp_path / "private_key.pem"
    subprocess.run(["openssl", "genrsa", "-out", str(key), "2048"], check=True, capture_output=True)
    pub = tmp_path / "pub.pem"
    subprocess.run(["openssl", "rsa", "-in", str(key), "-pubout", "-out", str(pub)], check=True, capture_output=True)
    jwt = github.app_jwt("12345", str(key), now=1_700_000_000)
    header, payload, sig = jwt.split(".")
    pad = lambda s: s + "=" * (-len(s) % 4)
    assert json.loads(base64.urlsafe_b64decode(pad(header))) == {"alg": "RS256", "typ": "JWT"}
    claims = json.loads(base64.urlsafe_b64decode(pad(payload)))
    assert claims == {"iat": 1_700_000_000 - 60, "exp": 1_700_000_000 + 540, "iss": "12345"}
    sigfile = tmp_path / "sig"
    sigfile.write_bytes(base64.urlsafe_b64decode(pad(sig)))
    ok = subprocess.run(["openssl", "dgst", "-sha256", "-verify", str(pub), "-signature", str(sigfile)],
                        input=f"{header}.{payload}".encode(), capture_output=True)
    assert ok.returncode == 0, ok.stderr


def test_token_falls_back_to_pat_file(tmp_path, monkeypatch):
    pat = tmp_path / "token"
    pat.write_text("ghp_test\n")
    monkeypatch.setattr(github, "APP_DIR", str(tmp_path / "no-app"))
    monkeypatch.setattr(github, "PAT_FILE", str(pat))
    assert github.token() == "ghp_test"
    assert github.push_url("a/b") == "https://x-access-token:ghp_test@github.com/a/b.git"


def test_publish_candidate_identity(monkeypatch):
    # The ledger had 0 candidate rows and NULL fingerprints after the first night:
    # nothing ever named what a run was attempting. A mission is its issue, an
    # improve run is what adjudicate selected.
    sys.path.insert(0, str(ROOT / "scripts"))
    import publish
    from fleet import ledger
    monkeypatch.setattr(publish, "REPO", "o/r")
    monkeypatch.setattr(publish, "BRIEF", "GitHub issue https://github.com/o/r/issues/5 — collect evidence\n\nbody\n")
    fp, title, url = publish.candidate(None)
    assert (fp, title, url) == (ledger.fingerprint("o/r", "issue", "https://github.com/o/r/issues/5"), "collect evidence", "https://github.com/o/r/issues/5")
    monkeypatch.setattr(publish, "BRIEF", "fix the flaky test in x")
    assert publish.candidate(None)[1:] == ("fix the flaky test in x", None)
    monkeypatch.setattr(publish, "BRIEF", "")
    assert publish.candidate({"selected": "graphiti retries"}) == (ledger.fingerprint("o/r", "graphiti retries"), "graphiti retries", None)
    assert publish.candidate({}) == (None, None, None)


def test_publish_main_writes_candidate_and_run(tmp_path, monkeypatch):
    # The first edit that added candidate() never wired it into main(); the verify
    # run shipped kagent#19 with fingerprint NULL. This runs main() for real.
    sys.path.insert(0, str(ROOT / "scripts"))
    import publish
    (tmp_path / "stop").write_text(json.dumps({"stage": "implement", "reason": "dsh timeout"}))
    (tmp_path / "02-verdict.json").write_text(json.dumps({"selected": "graphiti retries", "selection_reasoning": "x"}))
    calls = []
    class L:
        @staticmethod
        def fingerprint(*parts): return "fp1"
        def __getattr__(self, name): return lambda *a, **k: calls.append((name, a, k))
    quiet = type("Q", (), {"__getattr__": lambda self, n: (lambda *a, **k: None)})()
    for attr, val in {"P": str(tmp_path), "BRIEF": "", "REPO": "o/r", "BRANCH": "agent/improve-x",
                      "ledger": L(), "brain": quiet, "telegram": quiet, "github": quiet}.items():
        monkeypatch.setattr(publish, attr, val)
    monkeypatch.setattr(publish, "file_halt_issue", lambda *a, **k: None)
    publish.main()
    by = {c[0]: c for c in calls}
    assert by["upsert_candidate"][1][:4] == ("fp1", "o/r", "graphiti retries", "improve")
    assert by["finish_run"][1][:2] == ("improve-x", "halted") and by["finish_run"][2]["fp"] == "fp1"
    assert by["set_state"][1] == ("fp1", "halted")


def test_publish_cost_and_repeat_halt_not_paged(tmp_path, monkeypatch):
    sys.path.insert(0, str(ROOT / "scripts"))
    import publish
    assert publish.cost_of({"investigate": {"seconds": 304}, "implement": {"seconds": 43}, "collect": {"seconds": 9}}) == {"model_seconds": 347, "model": "ornith15"}
    assert publish.cost_of(None) == {}
    # a repeat halt appends to its issue and does not page Telegram
    (tmp_path / "stop").write_text(json.dumps({"stage": "implement", "reason": "dsh timeout"}))
    sent = []
    quiet = type("Q", (), {"__getattr__": lambda self, n: (lambda *a, **k: None)})()
    for attr, val in {"P": str(tmp_path), "BRIEF": "", "REPO": "o/r", "BRANCH": "agent/x", "ledger": quiet, "brain": quiet, "github": quiet}.items():
        monkeypatch.setattr(publish, attr, val)
    monkeypatch.setattr(publish, "telegram", type("T", (), {"send": staticmethod(lambda m: sent.append(m))})())
    monkeypatch.setattr(publish, "file_halt_issue", lambda *a, **k: "repeat")
    publish.main()
    assert sent == []
    monkeypatch.setattr(publish, "file_halt_issue", lambda *a, **k: "new")
    publish.main()
    assert sent == []   # a new halt files its issue; nobody is paged (2026-09-13: 11 halt pages, none needed action)


def test_review_policy_says_the_fleet_merges(monkeypatch):
    sys.path.insert(0, str(ROOT / "scripts"))
    import review
    p = review.policy()
    assert p["merges_on_its_own"] is True and "chrisknu" in p["trusted_authors"]
    assert p["veto_minutes_by_tier"]["3"] == review.VETO_MINUTES[3] and "veto" in p["how"]
    written = {}
    monkeypatch.setattr(review.ledger, "kv_set", lambda k, v: written.setdefault(k, v))
    review.publish_policy()
    assert written["review_policy"]["merges_on_its_own"] is True


def test_stage_escalates_on_salad_and_on_a_second_rejection(tmp_path):
    """ornith15 first; token salad, or pre-review rejecting it twice, hands the round to the judge (escalate.py)."""
    for mode, dsh_calls in (("salad", 1), ("reject", 2)):
        d = tmp_path / mode; d.mkdir()
        repo = d / "repo"; repo.mkdir(); p = d / "p"; cfg = d / "config"; cfg.mkdir()
        g = lambda *a: subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True)
        g("init", "-q"); g("config", "user.email", "t@t"); g("config", "user.name", "t")
        (repo / "README.md").write_text("x\n"); g("add", "."); g("commit", "-qm", "init")
        (cfg / "implement.txt").write_text("do the thing")
        fake = d / "dsh"
        fake.write_text("#!/bin/sh\necho call >> \"$PIPELINE_DIR/dsh.calls\"\n"
                        + ("yes 'Ber db Ber' | head -300; exit 1\n" if mode == "salad" else
                           "cd \"$REPO_DIR\" && echo x >> work.txt && git add . && git commit -qm round && echo true > \"$PIPELINE_DIR/verify.sh\"\n"))
        fake.chmod(0o755)
        # the stage's python helpers, stubbed: no plan, precheck passes only once the judge took over
        (d / "plan.py").write_text("import sys; sys.exit(1)\n")
        (d / "validate.py").write_text("import sys; sys.exit(0)\n")
        (d / "precheck.py").write_text("import os, sys\nok = os.path.exists(os.environ['REPO_DIR'] + '/escalated')\n"
                                       "print('pre-review confidence', 90 if ok else 60); sys.exit(0 if ok else 1)\n")
        (d / "escalate.py").write_text(
            "import os, subprocess, sys\n"
            "if sys.argv[1:] == ['--degenerate']: sys.exit(0 if 'Ber db' in sys.stdin.read() else 1)\n"
            "r = os.environ['REPO_DIR']; open(r + '/escalated', 'w').write(sys.argv[1])\n"
            "open(os.environ['PIPELINE_DIR'] + '/verify.sh', 'w').write('true\\n')\n"
            "subprocess.run(['git', '-C', r, 'add', '.']); subprocess.run(['git', '-C', r, 'commit', '-qm', 'escalated'])\n"
            "print('escalate: judge edited it')\n")
        script = (ROOT / "scripts" / "stage.sh").read_text().replace('"/config/$S.txt"', f'"{cfg}/$S.txt"').replace("/config/dsh-patch.yml", f"{cfg}/dsh-patch.yml")
        (d / "stage.sh").write_text(script)
        r = subprocess.run(["sh", str(d / "stage.sh"), "implement"], capture_output=True, text=True,
                           env={**os.environ, "PIPELINE_DIR": str(p), "REPO_DIR": str(repo), "DSH": str(fake), "HOME": str(d),
                                "JUDGE_URL": "http://judge", "PATH": os.environ["PATH"]})
        assert r.returncode == 0, r.stderr
        assert not (p / "stop").exists(), (mode, r.stdout[-2000:])
        assert (repo / "escalated").read_text() == ("degenerate" if mode == "salad" else "rejected"), r.stdout[-2000:]
        assert r.stdout.count("escalating to") == 1 and "pre-review passed" in r.stdout
        assert "final verify.sh on the shipped head: rc 0" in r.stdout      # evidence is the shipped head's
        assert (p / "dsh.calls").read_text().count("call") == dsh_calls
