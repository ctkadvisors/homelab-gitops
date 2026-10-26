"""The scheduler's rails: unknown signals fail closed, the idle streak and
budget gate a launch, and the improve Job is rendered from the CronJob with
its own branch and trigger. The ledger is faked in memory."""

import json
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import reconcile  # noqa: E402
import review  # noqa: E402


class FakeLedger:
    def __init__(self):
        self.kv, self.decisions, self.runs = {}, [], []
    def kv_like(self, pat): return [(k, v) for k, v in self.kv.items() if k.startswith(pat.rstrip("%"))]
    def kv_delete(self, k): self.kv.pop(k, None)
    def kv_get(self, k): return self.kv.get(k)
    def kv_set(self, k, v): self.kv[k] = v
    def try_lease(self, holder, ttl_seconds=600): return True
    def release_lease(self, holder): pass
    def start_run(self, *a): self.runs.append(a)
    def record_decision(self, *a, **kw): self.decisions.append((a, kw)); return len(self.decisions)
    def vetoed(self, did): return self.kv.get(f"veto:{did}", False)
    halted = []
    def halted_candidates(self): return list(self.halted)
    said = []
    def say(self, *a, **kw): self.said.append((a, kw)); return len(self.said)
    def posts(self, **kw): return []
    def open_questions(self, ref): return []
    def last_run(self, fp): return None
    def unfinished_runs(self): return []
    def tested_candidates(self): return []
    def recent_runs(self, n=10): return []
    def voice(self): return "HOW WE TALK"
    def fingerprint(self, *parts): return "fp" + str(len("|".join(parts)))


def test_observe_fails_closed_on_unknown_signal():
    ok, report = reconcile.observe({"a": lambda: (True, "fine"), "b": lambda: (_ for _ in ()).throw(RuntimeError("boom"))})
    assert ok is False and report["b"]["ok"] is False and "unknown" in report["b"]["detail"]
    ok, _ = reconcile.observe({"a": lambda: (True, "fine"), "b": lambda: (True, "fine")})
    assert ok is True


def test_spark_signal_reads_gpu_util_from_llamaswap_metrics(monkeypatch):
    import io
    metrics = ('# TYPE llamaswap_gpu_util_percent gauge\n'
               'llamaswap_gpu_util_percent{id="0",name="NVIDIA GB10"} 42\n'
               'llamaswap_cpu_util_percent{core="0"} 99\n')
    monkeypatch.setattr(reconcile.urllib.request, "urlopen", lambda *a, **k: io.BytesIO(metrics.encode()))
    ok, detail = reconcile.sig_spark()
    assert ok is False and detail == "spark gpu 42% util"
    monkeypatch.setattr(reconcile.urllib.request, "urlopen", lambda *a, **k: io.BytesIO(metrics.replace(" 42", " 0").encode()))
    assert reconcile.sig_spark()[0] is True
    monkeypatch.setattr(reconcile.urllib.request, "urlopen", lambda *a, **k: io.BytesIO(b"# nothing\n"))
    assert reconcile.observe({"spark": reconcile.sig_spark})[0] is False   # no gauge -> unknown -> not eligible


def test_idle_streak_and_budget(monkeypatch):
    fake = FakeLedger(); monkeypatch.setattr(reconcile, "ledger", fake)
    now = time.time()
    assert reconcile.idle_streak(True, now) == 0.0            # streak starts
    assert reconcile.idle_streak(True, now + 600) >= 9.9      # ten minutes later
    assert reconcile.idle_streak(False, now + 700) == 0.0     # busy resets it
    assert reconcile.idle_streak(True, now + 800) == 0.0      # and it restarts from zero
    ok, why = reconcile.budget_ok(now); assert ok, why
    fake.kv[f"budget:{time.strftime('%Y-%m-%d', time.gmtime(now))}"] = {"runs": 1}
    ok, why = reconcile.budget_ok(now); assert not ok and "budget 1/1" in why
    fake.kv.clear(); fake.kv["last_run"] = {"at": now - 30 * 60}
    ok, why = reconcile.budget_ok(now); assert not ok and "min ago" in why


def test_render_improve_job_from_cronjob():
    cj = {"spec": {"jobTemplate": {"metadata": {"labels": {"x": "y"}}, "spec": {"template": {"spec": {
        "initContainers": [{"name": "collect", "env": [{"name": "BRANCH", "value": "agent/dsh-daily-x"}, {"name": "REPO", "value": "ctkadvisors/kagent"}]}],
        "containers": [{"name": "publish", "env": [{"name": "REPO", "value": "ctkadvisors/kagent"}]}]}}}}}}
    job = reconcile.render_improve_job(cj, "improve-20260904-040000")
    assert job["metadata"]["name"] == "improve-20260904-040000" and job["metadata"]["labels"]["app"] == "improve-daily"
    for c in job["spec"]["template"]["spec"]["initContainers"] + job["spec"]["template"]["spec"]["containers"]:
        env = {e["name"]: e["value"] for e in c["env"]}
        assert env["RUN_TRIGGER"] == "idle" and env["BRANCH"] == "agent/improve-20260904-040000" and env["REPO"] == "ctkadvisors/kagent"
        assert env["RUN_ID"] == "improve-20260904-040000"


def test_main_launches_only_after_idle_streak_and_budget(monkeypatch):
    fake = FakeLedger(); monkeypatch.setattr(reconcile, "ledger", fake)
    monkeypatch.setattr(reconcile, "observe", lambda signals=None: (True, {"all": {"ok": True, "detail": "x", "at": 0}}))
    launched = []
    monkeypatch.setattr(reconcile, "launch", lambda now, trigger="idle", repo=None: launched.append(repo) or "improve-test")
    monkeypatch.setattr(reconcile, "choose_repo", lambda gh=None: ("o/r", "test repo"))
    monkeypatch.setattr(reconcile, "own_failures", lambda now, pods=None: [])
    assert reconcile.main() == 0 and launched == []           # streak just started
    fake.kv["idle_since"] = {"at": time.time() - 11 * 60}
    assert reconcile.main() == 0 and launched                 # idle long enough, budget free
    assert fake.runs and fake.decisions and fake.kv["last_run"]["name"] == "improve-test"
    launched.clear(); fake.kv["idle_since"] = {"at": time.time() - 11 * 60}
    assert reconcile.main() == 0 and launched == []           # budget spent for today


def test_a_bench_target_pr_is_tier_three_until_the_held_out_run(monkeypatch):
    monkeypatch.setattr(review.ledger, "run_for_pr", lambda url: {"id": "mission-1", "trigger": "bench"} if url.endswith("/7") else None)
    assert review.effective_tier("https://github.com/o/r/pull/7", ["services/fleet-scripts/scripts/stage.sh"]) == 3
    assert review.effective_tier("https://github.com/o/r/pull/8", ["services/fleet-scripts/scripts/stage.sh"]) == 1
    monkeypatch.setattr(review.ledger, "run_for_pr", lambda url: (_ for _ in ()).throw(RuntimeError("down")))
    assert review.effective_tier("https://github.com/o/r/pull/7", ["docs/x.md"]) == 0   # a dead ledger never blocks


def test_risk_tiers_and_veto_window(monkeypatch):
    assert review.risk_tier(["docs/x.md", "tests/test_y.py"]) == 0
    assert review.risk_tier(["src/a.ts"]) == 1
    assert review.risk_tier(["src/a.ts", ".github/workflows/ci.yml"]) == 2
    assert review.risk_tier(["k8s-kustomized/base/x.yaml"]) == 2
    assert review.risk_tier(["overlays/foo-sealed.yaml"]) == 3
    assert review.risk_tier(["services/fleet-scripts/scripts/review.py"]) == 3
    fake = FakeLedger(); monkeypatch.setattr(review, "ledger", fake)
    may, why = review.merge_gate("o/r", 1, 0, "docs"); assert may and "tier 0" in why
    may, why = review.merge_gate("o/r", 2, 1, "code"); assert not may and why.startswith("announced")
    may, why = review.merge_gate("o/r", 2, 1, "code"); assert not may and "window open" in why
    fake.kv["merge:o/r#2"]["at"] -= 16 * 60
    may, why = review.merge_gate("o/r", 2, 1, "code"); assert may and "passed" in why
    fake.kv[f"veto:{fake.kv['merge:o/r#2']['decision']}"] = True   # the console vetoes THIS decision
    may, why = review.merge_gate("o/r", 2, 1, "code"); assert not may and why == "vetoed"
    # 2026-09-06: tier 3 merges too, after a long announced window (trust but verify)
    may, why = review.merge_gate("o/r", 3, 3, "rails"); assert not may and f"after {review.VETO_MINUTES[3]} min" in why
    fake.kv["merge:o/r#3"]["at"] -= (review.VETO_MINUTES[3] + 1) * 60
    may, why = review.merge_gate("o/r", 3, 3, "rails"); assert may and "passed" in why


def test_commented_pr_is_rejudged_on_a_new_head(monkeypatch):
    fake = FakeLedger(); monkeypatch.setattr(review, "ledger", fake)
    assert review.judged_sha("o/r", 5) is None            # never commented -> judge
    review.remember_judged("o/r", 5, "abc")
    assert review.judged_sha("o/r", 5) == "abc"           # same head -> skip
    class NoLedger:
        def kv_get(self, k): raise RuntimeError("down")
    monkeypatch.setattr(review, "ledger", NoLedger())
    assert review.judged_sha("o/r", 5) == "unknown"       # no ledger -> old behaviour (skip commented)


def test_merge_due_merges_only_past_window_unvetoed_green(monkeypatch):
    fake = FakeLedger(); monkeypatch.setattr(review, "ledger", fake)
    calls = []
    class GH:
        def api(self, path, data=None, method=None, **kw):
            calls.append((method or ("POST" if data is not None else "GET"), path))
            if path.endswith("/pulls/2"): return {"state": "open", "merged": False, "head": {"sha": "s2"}, "title": "t"}
            if path.endswith("/pulls/3"): return {"state": "open", "merged": False, "head": {"sha": "s3"}, "title": "t"}
            if "/check-runs" in path: return {"check_runs": [{"status": "completed", "conclusion": "success"}]}
            return {}
    monkeypatch.setattr(review, "github", GH())
    monkeypatch.setattr(review, "telegram", type("T", (), {"send": staticmethod(lambda *a, **k: None)})())
    now = time.time()
    fake.kv["merge:o/r#1"] = {"decision": 1, "at": now, "tier": 1}              # window still open
    fake.kv["merge:o/r#2"] = {"decision": 2, "at": now - 20 * 60, "tier": 1}    # due
    fake.kv["merge:o/r#3"] = {"decision": 3, "at": now - 20 * 60, "tier": 1}    # due but vetoed
    fake.kv["veto:3"] = True
    assert review.merge_due() == ["o/r#2"]
    assert ("PUT", "/repos/o/r/pulls/2/merge") in calls and not any("/pulls/3/merge" in c[1] for c in calls)
    assert "merge:o/r#2" not in fake.kv and "merge:o/r#1" in fake.kv


def test_parse_verdict_survives_junk_and_truncation():
    good = 'Sure. {"confidence": 91, "summary": "fine", "feedback": "ok"} thanks'
    assert review.parse_verdict(good)["confidence"] == 91
    nested = 'x {"a": {"b": 1}} y {"confidence": 70, "summary": "s", "feedback": "f"}'
    assert review.parse_verdict(nested)["confidence"] == 70
    truncated = '{"confidence": 88, "summary": "the diff renames a comm'
    v = review.parse_verdict(truncated)
    assert v["confidence"] == 0 and v["summary"] == "unparseable review"


def test_objection_survives_a_new_push_until_the_judge_says_addressed(monkeypatch):
    # new_localai#10: the reviewer found the wrong-table bug, a docs push earned a
    # fresh verdict with no memory of it, and the PR merged with the bug in it.
    fake = FakeLedger(); monkeypatch.setattr(review, "ledger", fake)
    prompts, calls = [], []
    class GH:
        def api(self, path, data=None, method=None, **kw):
            calls.append((method or ("POST" if data is not None else "GET"), path))
            if path.endswith("/files?per_page=100"): return [{"filename": "scripts/collect.py", "changes": 10}]
            if "/check-runs" in path: return {"check_runs": [{"status": "completed", "conclusion": "success"}]}
            if kw.get("raw"): return "diff"
            return {}
        def kid_gloves(self, repo): return False
        def push_url(self, repo): raise RuntimeError("no clone in tests")
    monkeypatch.setattr(review, "github", GH())
    monkeypatch.setattr(review, "telegram", type("T", (), {"send": staticmethod(lambda *a, **k: None)})())
    verdicts = iter([
        {"confidence": 70, "summary": "wrong table", "feedback": "kv_like reads scheduler, runs live in run"},
        {"confidence": 90, "summary": "docs look fine", "feedback": "", "prior_addressed": False},
        {"confidence": 90, "summary": "query fixed", "feedback": "", "prior_addressed": True},
    ])
    def run(cmd, **kw):
        prompts.append(cmd[-1]); return type("R", (), {"stdout": json.dumps(next(verdicts))})()
    monkeypatch.setattr(review.subprocess, "run", run)
    pr = {"number": 10, "title": "t", "body": "", "head": {"sha": "s1", "ref": "agent/x", "repo": {"full_name": "o/r"}},
          "user": {"login": "chrisknu"}, "html_url": "u"}

    review.review_pr("o/r", "/repos/o/r", pr, 10)                       # round 1: objection
    assert fake.kv["objection:o/r#10"]["feedback"].startswith("kv_like")
    assert "PRIOR OBJECTION" not in prompts[0]

    pr["head"]["sha"] = "s2"
    review.review_pr("o/r", "/repos/o/r", pr, 10)                       # round 2: docs push, judge sees the objection
    assert "PRIOR OBJECTION" in prompts[1] and "kv_like reads scheduler" in prompts[1]
    assert not any("/merge" in c[1] for c in calls), "merged over a standing objection"
    assert "objection:o/r#10" in fake.kv

    pr["head"]["sha"] = "s3"
    review.review_pr("o/r", "/repos/o/r", pr, 10)                       # round 3: fixed -> tier 1 announce, objection cleared
    assert "objection:o/r#10" not in fake.kv and "merge:o/r#10" in fake.kv


def test_observe_outcomes_records_recurrence_and_revert(monkeypatch):
    # A merge is not the end of the story: 24h and 7d later the ledger says
    # whether the same candidate came back and whether main reverted the PR.
    from datetime import datetime, timezone
    since = datetime(2026, 9, 4, 7, 40, tzinfo=timezone.utc)
    rows = {"24h": [{"fingerprint": "fpA", "run_id": "r1", "observed_at": since, "repo": "o/r", "pr_url": "https://github.com/o/r/pull/10"},
                    {"fingerprint": "fpB", "run_id": "r2", "observed_at": since, "repo": "o/r", "pr_url": "https://github.com/o/r/pull/11"}],
            "7d": []}
    out = []
    class L(FakeLedger):
        def pending_outcomes(self, window, days): return rows[window]
        def runs_since(self, fp, s): return 1 if fp == "fpA" else 0
        def record_outcome(self, fp, run_id, window, **kw): out.append((fp, window, kw["recurred"], kw["rolled_back"]))
        def set_state(self, fp, st): out.append((fp, st))
    class GH:
        def api(self, path, **kw):
            assert "since=2026-09-04T07:40:00+00:00" in path
            return [{"commit": {"message": "Revert \"fix(x)\" (#11)\n\nThis reverts #11"}}]
    monkeypatch.setattr(reconcile, "ledger", L()); monkeypatch.setattr(reconcile, "github", GH())
    assert reconcile.observe_outcomes() == ["fpA@24h", "fpB@24h"]
    assert ("fpA", "24h", True, False) in out and ("fpA", "observed") in out
    assert ("fpB", "24h", False, True) in out and ("fpB", "rolled_back") in out


def test_board_retry_comes_before_a_speculative_improve_run(monkeypatch):
    import io
    fake = FakeLedger(); monkeypatch.setattr(reconcile, "ledger", fake)
    fake.halted = [{"fingerprint": "f1", "repo": "o/r", "title": "o/r #7", "issue_url": "https://github.com/o/r/issues/7"}]
    fake.kv["idle_since"] = {"at": time.time() - 11 * 60}
    fake.kv["budget:" + time.strftime("%Y-%m-%d", time.gmtime())] = {"runs": 1}     # improve budget spent
    monkeypatch.setattr(reconcile, "observe", lambda signals=None: (True, {"all": {"ok": True, "detail": "x", "at": 0}}))
    monkeypatch.setattr(reconcile, "canary", lambda now: (True, "test"))
    launched = []; monkeypatch.setattr(reconcile, "launch", lambda now: launched.append(now) or "improve-test")
    class GH:
        def api(self, path, *a, **k):
            if path.endswith("/comments"): return [{"user": {"login": "chris"}, "body": "try the dependabot bumps first"}]
            return {"state": "open", "labels": [{"name": "mission"}], "html_url": "https://github.com/o/r/issues/7", "title": "npm audit", "body": "fix it", "number": 7}
    monkeypatch.setattr(reconcile, "github", GH())
    sent = []
    def urlopen(req, timeout=0):
        sent.append(json.loads(req.data)); return io.BytesIO(b'{"name": "mission-1"}')
    monkeypatch.setattr(reconcile.urllib.request, "urlopen", urlopen)
    assert reconcile.main() == 0 and launched == []                    # budget gone, but the board still runs
    assert sent[0]["repo"] == "o/r" and "dependabot" in sent[0]["brief"] and sent[0]["requestedBy"] == "reconcile:board"
    assert fake.kv["last_run"]["name"] == "mission-1" and fake.decisions[-1][0][0] == "launch-mission"
    fake.halted = []; fake.kv["idle_since"] = {"at": time.time() - 11 * 60}; fake.kv["last_run"] = {"at": 0}
    assert reconcile.main() == 0 and launched == []                    # empty board + spent budget = nothing


def test_reviewer_skips_vetoed_announcements_and_never_merges_without_a_ledger(monkeypatch):
    fake = FakeLedger(); monkeypatch.setattr(review, "ledger", fake)
    fake.kv["merge:o/r#18"] = {"decision": 3, "at": 0, "tier": 2}; fake.kv["veto:3"] = True
    assert review.announce_vetoed("o/r", 18) is True and review.announce_vetoed("o/r", 19) is False
    class NoLedger:
        def kv_get(self, k): raise RuntimeError("down")
    monkeypatch.setattr(review, "ledger", NoLedger())
    may, why = review.merge_gate("o/r", 1, 1, "rails")
    assert may is False and "no merge" in why


def test_review_round_reruns_a_cancelled_check_instead_of_launching(monkeypatch):
    fake = FakeLedger(); monkeypatch.setattr(reconcile, "ledger", fake)
    fake.tested_candidates = lambda: [{"fingerprint": "f2", "repo": "o/r", "pr_url": "https://github.com/o/r/pull/26",
                                       "started_at": "2026-09-07T00:00:00Z", "issue_url": None}]
    posted = []
    class GH:
        def kid_gloves(self, repo): return False
        def api(self, path, data=None, method=None, **k):
            if method == "POST": posted.append(path); return {}
            if path.endswith("/pulls/26"):
                return {"state": "open", "merged": False, "html_url": "https://github.com/o/r/pull/26", "title": "t",
                        "head": {"sha": "abcdef1234567890", "ref": "agent/x"}}
            if "/check-runs" in path:
                return {"check_runs": [{"name": "CRD drift check", "status": "completed", "conclusion": "cancelled",
                                        "details_url": "https://github.com/o/r/actions/runs/999/job/1"},
                                       {"name": "CI", "status": "completed", "conclusion": "success"}]}
            raise AssertionError(path)
    monkeypatch.setattr(reconcile, "github", GH())
    monkeypatch.setattr(reconcile.urllib.request, "urlopen", lambda req, timeout=0: (_ for _ in ()).throw(AssertionError("launched a round")))
    assert reconcile.retry_reviewed(time.time(), GH()) is None
    assert posted == ["/repos/o/r/actions/runs/999/rerun"] and fake.kv["rerun:o/r#26:abcdef123456"]["ok"]
    assert "cancelled" in fake.said[-1][0][1] and fake.said[-1][1]["mentions"] == ["reviewer"]
    assert reconcile.retry_reviewed(time.time(), GH()) is None and len(posted) == 1   # once per head


def test_commented_pr_is_rejudged_when_ci_turns_green(monkeypatch):
    fake = FakeLedger(); monkeypatch.setattr(review, "ledger", fake)
    pr = {"number": 26, "head": {"sha": "abc"}}
    green = {"v": False}
    class GH:
        def api(self, path, *a, **k):
            return {"check_runs": [{"status": "completed", "conclusion": "success" if green["v"] else "cancelled"}]}
    monkeypatch.setattr(review, "github", GH())
    review.remember_judged("o/r", 26, "abc", ci_green=False)
    assert review.already_judged("o/r", "/repos/o/r", pr)          # CI still cancelled: nothing new to say
    green["v"] = True
    assert not review.already_judged("o/r", "/repos/o/r", pr)      # CI green on the same head: judge again
    review.remember_judged("o/r", 26, "abc")                       # a verdict on green CI is final for this head
    assert review.already_judged("o/r", "/repos/o/r", pr)
    assert not review.already_judged("o/r", "/repos/o/r", {"number": 26, "head": {"sha": "def"}})  # new push


def test_canary_blocks_launches_and_pages_once_an_hour_when_the_model_is_salad(monkeypatch):
    import io
    fake = FakeLedger(); monkeypatch.setattr(reconcile, "ledger", fake)
    sent = []; monkeypatch.setattr(reconcile.telegram, "send", lambda m: sent.append(m))
    monkeypatch.setattr(reconcile.telegram, "post_link", lambda pid: f"link{pid}")
    reply = {"v": "sp sp 法律 Poly 公司"}
    monkeypatch.setattr(reconcile.urllib.request, "urlopen",
                        lambda req, timeout=0: io.BytesIO(json.dumps({"choices": [{"message": {"content": reply["v"]}}]}).encode()))
    now = time.time()
    ok, why = reconcile.canary(now)
    assert not ok and "Poly" in why and len(sent) == 1 and "gibberish" in sent[0] and fake.kv["canary"]["at"] == now
    assert not reconcile.canary(now + 60)[0] and len(sent) == 1           # once an hour, not every tick
    reply["v"] = "OK"
    assert reconcile.canary(now + 120)[0]
    monkeypatch.setattr(reconcile.urllib.request, "urlopen", lambda req, timeout=0: (_ for _ in ()).throw(OSError("down")))
    assert reconcile.canary(now)[0]                                        # unreachable is the spark signal's call, not a verdict


def test_spark_signal_prefers_ornith15s_own_queue_over_the_util_gauge(monkeypatch):
    """2026-09-06: llama-swap said 94% util for two hours while ornith15 had zero
    requests; the fleet idled on it. The model's queue is the truth."""
    import io
    util94 = 'llamaswap_gpu_util_percent{id="0",name="NVIDIA GB10"} 94\n'
    def serve(queue):
        vllm = (f'vllm:num_requests_running{{engine="0",model_name="ornith"}} {queue[0]}\n'
                f'vllm:num_requests_waiting{{engine="0",model_name="ornith"}} {queue[1]}\n')
        return lambda url, timeout=8: io.BytesIO((vllm if "/upstream/" in str(url) else util94).encode())
    monkeypatch.setattr(reconcile.urllib.request, "urlopen", serve((0.0, 0.0)))
    ok, detail = reconcile.sig_spark()
    assert ok is True and detail.startswith("ornith15 0 request(s) in flight")
    monkeypatch.setattr(reconcile.urllib.request, "urlopen", serve((1.0, 0.0)))
    assert reconcile.sig_spark()[0] is True        # one request from outside the fleet is not contention (2026-09-15)
    monkeypatch.setattr(reconcile.urllib.request, "urlopen", serve((1.0, 2.0)))
    ok, detail = reconcile.sig_spark()
    assert ok is False and "3 request(s)" in detail


def test_empty_streak_stops_speculative_runs_until_an_idea_arrives():
    """2026-09-08: the daily budget went to kagent runs that found nothing."""
    empty = {"pipeline": "improve", "repo": "o/k", "outcome": "halted", "halt": {"reason": reconcile.EMPTY_HALT}}
    runs = [dict(empty, started_at="2026-09-08 05:00"), dict(empty, started_at="2026-09-07 05:00"),
            {"pipeline": "improve", "repo": "o/k", "outcome": "shipped", "halt": None, "started_at": "2026-09-06 05:00"},
            {"pipeline": "mission", "repo": "o/k", "outcome": "halted", "halt": {"reason": reconcile.EMPTY_HALT}, "started_at": "2026-09-09 05:00"}]
    why = reconcile.empty_streak("o/k", runs=runs, ideas=[])
    assert why == "the last 2 improve runs on o/k found nothing and no idea has been posted since"
    assert reconcile.empty_streak("o/k", runs=runs, ideas=[{"created_at": "2026-09-08 09:00"}]) is None   # a new idea reopens it
    assert reconcile.empty_streak("o/other", runs=runs, ideas=[]) is None                                  # another repo is unaffected
    assert reconcile.empty_streak("o/k", runs=runs[1:], ideas=[]) is None                                  # one empty run is not a streak


def test_check_egress_flushes_the_neighbour_and_relays_the_result(monkeypatch):
    calls, fl = [], FakeLedger()
    down = {"ok": False, "result": "curl: (28) timed out"}
    answers = iter([down, down, {"ok": True, "result": "flushed"}, {"ok": True, "result": "HTTP 200 0.3s"}])
    monkeypatch.setattr(reconcile, "node_action", lambda action, args, by="reconcile": (calls.append(action), next(answers))[1])
    monkeypatch.setattr(reconcile, "ledger", fl)
    st = reconcile.check_egress(1e9, hosts=["elitemini2"])
    assert calls == ["probe-egress", "probe-egress", "neigh-flush", "probe-egress"]
    assert st["elitemini2"]["ok"] and st["elitemini2"]["healed"] and fl.kv["egress"] == st
    assert not any("elitemini2" in str(a) for a, _ in fl.said)   # 2026-09-14: a pass after the flush is not the flush's doing; nothing is posted
    # 2026-09-14: a DNS blip passes on the second probe: no flush, no post.
    calls.clear(); fl.said.clear()
    answers = iter([down, {"ok": True, "result": "HTTP 200 0.2s"}])
    st = reconcile.check_egress(1e9, hosts=["elitemini2"])
    assert calls == ["probe-egress", "probe-egress"] and st["elitemini2"]["ok"] and not st["elitemini2"]["healed"] and fl.said == []
    monkeypatch.setattr(reconcile, "node_action", lambda *a, **k: None)   # runner unreachable: unknown, no flush, no page
    st = reconcile.check_egress(1e9, hosts=["elitemini2"])
    assert st["elitemini2"] == {"ok": None, "healed": False, "at": 1e9, "detail": "node runner unreachable"}


def test_judge_asks_the_judge_model_directly_when_configured(monkeypatch):
    """2026-09-08: inside dsh's tool loop qwen38 never returned the JSON; direct, it does."""
    import io, json as _json
    from contextlib import contextmanager
    seen = {}
    @contextmanager
    def fake_open(req, timeout=0, tries=0):
        seen["body"] = _json.loads(req.data); seen["url"] = req.full_url; seen["tries"] = tries
        # streamed (2026-09-10): the reply arrives as SSE deltas and a [DONE]
        chunks = ['{"confidence": 82, ', '"summary": "s", "feedback": "f"}']
        lines = [b"data: " + _json.dumps({"choices": [{"delta": {"content": c}, "finish_reason": None}]}).encode() + b"\n\n" for c in chunks]
        lines.append(b"data: " + _json.dumps({"choices": [{"delta": {}, "finish_reason": "stop"}], "usage": {"completion_tokens": 900}}).encode() + b"\n\n")
        lines.append(b"data: [DONE]\n\n")
        yield io.BytesIO(b"".join(lines))
    monkeypatch.setattr(review, "JUDGE_URL", "http://swap:9090/v1")
    monkeypatch.setattr(review.net, "urlopen_retry", fake_open, raising=False) if hasattr(review, "net") else None
    from fleet import net
    monkeypatch.setattr(net, "urlopen_retry", fake_open)
    v = review.judge({"title": "t", "body": "b", "base": {"repo": {"full_name": "o/r"}}}, "diff --git a b")
    assert v["confidence"] == 82
    assert seen["url"] == "http://swap:9090/v1/chat/completions" and seen["body"]["model"] == "qwen38"
    assert seen["body"]["stream"] is True and seen["tries"] == 1                 # one streamed attempt, never a retry storm
    assert "judge what those prove" in seen["body"]["messages"][0]["content"]


def test_ideation_is_its_own_job_launched_once_a_day(monkeypatch):
    """2026-09-10 17:00Z: the tick (240 s deadline) was killed mid-ideation. The tick
    now launches scripts/ideate.py as a Job built from its own template, once per repo per day."""
    fl = FakeLedger()
    monkeypatch.setattr(reconcile, "ledger", fl)
    created = []
    tpl = {"spec": {"jobTemplate": {"spec": {"activeDeadlineSeconds": 240, "template": {"metadata": {"labels": {"app": "fleet-reconcile"}}, "spec": {"containers": [
        {"name": "reconcile", "image": "img", "command": ["python3", "/app/scripts/reconcile.py"], "env": [{"name": "JUDGE_URL", "value": "u"}]}]}}}}}}
    monkeypatch.setattr(reconcile, "k8s", lambda m, p, body=None: created.append((m, p, body)) or tpl)
    name = reconcile.launch_ideation("ctkadvisors/kagent", 1e9)
    assert name == "ideate-kagent-20010909"
    job = next(b for m, p, b in created if m == "POST")
    c = job["spec"]["template"]["spec"]["containers"][0]
    assert c["command"] == ["python3", "/app/scripts/ideate.py"] and {"name": "IDEATE_REPO", "value": "ctkadvisors/kagent"} in c["env"]
    assert {"name": "JUDGE_URL", "value": "u"} in c["env"] and job["spec"]["activeDeadlineSeconds"] == 3600 and job["metadata"]["labels"]["app"] == "mission"
    assert reconcile.launch_ideation("ctkadvisors/kagent", 1e9) is None      # once a day
    assert reconcile.ideate("ctkadvisors/kagent", 1e9) == 0


def test_dream_writes_the_days_lessons_into_memory_itself(monkeypatch):
    """Chris, 2026-09-09: give them the tools you want -> sleep: the fleet consolidates its own day."""
    fl = FakeLedger()
    noon = time.mktime(time.strptime("2026-09-10 12:00:00", "%Y-%m-%d %H:%M:%S")) - time.timezone
    fl.recent_runs = lambda n=10: [{"id": "improve-1", "repo": "o/r", "outcome": "shipped", "pr_url": "https://github.com/o/r/pull/9", "started_at": noon - 3600},
                                   {"id": "improve-2", "repo": "o/r", "outcome": "halted", "halt": {"reason": "implementer made no commit"}, "started_at": noon - 7200}]
    monkeypatch.setattr(reconcile, "ledger", fl)
    from fleet import memory
    written = []
    monkeypatch.setattr(memory, "remember", lambda kind, text, repo=None, ref=None, source="fleet": written.append((kind, text, source)) or "k")
    monkeypatch.setattr(memory, "recall", lambda repo, ctx, limit=12: "WHAT WE HAVE LEARNED: nothing")
    monkeypatch.setattr(reconcile.experience, "recent", lambda days=7, limit=60: [{"id": "run:improve-2", "kind": "halt", "text": "no commit", "repo": "o/r", "at": ""},
                                                                                {"id": "lesson:k1", "kind": "lesson", "text": "judge by HEAD", "repo": "o/r", "at": ""}])
    proposal = ('"proposal": {"problem": "no-commit halts recur", "mechanism": "publish checks HEAD moved", "novelty": "n", "assumptions": "a", '
                '"effect": "no halt with that reason in a week", "evidence": ["run:improve-2", "lesson:k1", "run:bogus"]}')
    asked = []
    def judge(prompt, temperature=0.2, thinking=True):
        asked.append(prompt)
        return ('{"lessons": [{"text": "A run that commits and pushes to the fixture origin looks like no commit; judge by HEAD.", "repo": "o/r"}, {"text": "short"}], '
                '"taste": [{"text": "o/r#9 changed one file and proved it with the test it named.", "repo": "o/r"}], ' + proposal + '}')
    monkeypatch.setattr(review, "ask_judge", judge)
    stored = []; monkeypatch.setattr(reconcile.ideas, "add", lambda q, repo, source, **kw: stored.append((q["problem"], repo, source, kw["evidence"])) or "id1")
    sent = []; monkeypatch.setattr(reconcile.telegram, "send", lambda m: sent.append(m))
    assert reconcile.dream(noon) == {"lessons": 1, "taste": 1, "proposed": 1}
    assert "- run:improve-2 [halt" in asked[0] and "- lesson:k1" in asked[0]              # the ids it may cite are in the prompt
    assert stored == [("no-commit halts recur", reconcile.FLEET_REPO, "dream", ["run:improve-2", "lesson:k1"])]   # bogus id dropped
    assert len(sent) == 1 and sent[0].startswith("🌙 Dreamt") and "- A run that commits" in sent[0] and "- Taste: o/r#9" in sent[0]
    assert "- proposed: no-commit halts recur" in sent[0]
    assert written == [("lesson", "A run that commits and pushes to the fixture origin looks like no commit; judge by HEAD.", "dream"),
                       ("fact", "Taste: o/r#9 changed one file and proved it with the test it named.", "dream")]
    assert "1 shipped, 1 halted" in fl.said[-1][0][1] and "wrote 1 lesson(s)" in fl.said[-1][0][1] and "proposed: no-commit halts recur" in fl.said[-1][0][1]
    assert reconcile.dream(noon) == {}                              # once a day
    early = noon - 11 * 3600                                         # 01:00Z: before DREAM_HOUR
    assert reconcile.dream(early) == {}
    # No connection, no growth: a proposal citing no real experience id is not stored.
    fl2 = FakeLedger(); monkeypatch.setattr(reconcile, "ledger", fl2)
    monkeypatch.setattr(review, "ask_judge", lambda prompt, temperature=0.2, thinking=True:
                        '{"lessons": [], "taste": [], "proposal": {"problem": "p", "mechanism": "m", "evidence": ["run:bogus"]}}')
    assert reconcile.dream(noon) == {"lessons": 0, "taste": 0, "proposed": 0} and len(stored) == 1 and len(sent) == 1


def test_weekly_bench_target_launches_once_a_week_with_the_held_out_rule(monkeypatch):
    import io
    fl = FakeLedger(); monkeypatch.setattr(reconcile, "ledger", fl)
    posted = []
    def urlopen(req, timeout=0):
        posted.append(json.loads(req.data)); return io.BytesIO(b'{"name": "mission-7"}')
    monkeypatch.setattr(reconcile.urllib.request, "urlopen", urlopen)
    noon = time.mktime(time.strptime("2026-09-10 12:00:00", "%Y-%m-%d %H:%M:%S")) - time.timezone
    assert reconcile.weekly_bench_target(noon) == "mission-7"
    assert posted[0]["repo"] == "ctkadvisors/new_localai" and posted[0]["requestedBy"] == "bench:weekly"
    brief = posted[0]["brief"]
    assert brief.startswith("Raise the bench (week 2026-W37)") and "held-out" in brief and "strictly improves" in brief
    assert "fix-add, add-slugify, cli-version" in brief and "ask-first" in brief and "stage.sh" in brief and len(brief) < 8000
    assert fl.kv["bench-target"]["week"] == "2026-W37" and "raise the bench" in fl.said[-1][0][1]
    assert reconcile.weekly_bench_target(noon + 3 * 86400) is None and len(posted) == 1     # same ISO week: nothing
    assert reconcile.weekly_bench_target(noon + 7 * 86400) == "mission-7" and len(posted) == 2   # next week: again


def test_nightly_bench_launches_once_and_the_trend_flags_a_regression(monkeypatch):
    fl = FakeLedger(); monkeypatch.setattr(reconcile, "ledger", fl)
    created = []
    monkeypatch.setattr(reconcile, "k8s", lambda m, p, body=None: created.append((m, p, body)) or {"spec": {"jobTemplate": {"metadata": {"labels": {"app": "mission"}}, "spec": {"template": {"spec": {}}}}}})
    noon = time.mktime(time.strptime("2026-09-10 12:00:00", "%Y-%m-%d %H:%M:%S")) - time.timezone
    assert reconcile.nightly_bench(noon) == "bench-20260910"
    assert created[-1][0] == "POST" and created[-1][2]["metadata"]["name"] == "bench-20260910" and created[-1][2]["metadata"]["labels"]["app"] == "mission"
    assert reconcile.nightly_bench(noon) is None                     # once a day
    fl.kv["bench:20260909"] = {"success": 4, "n": 4, "seconds": 377.0, "at": noon - 86400}
    fl.kv["bench:20260910"] = {"success": 3, "n": 4, "seconds": 400.0, "at": noon, "prompt_bytes": 24000, "rounds": 4}
    from fleet import memory
    lessons = []
    monkeypatch.setattr(memory, "remember", lambda kind, text, repo=None, ref=None, source="fleet": lessons.append((source, text)) or "k")
    line = reconcile.bench_trend(noon)
    assert line.startswith("Nightly bench 20260910: 3/4 in 400.0s") and "(last: 4/4 in 377.0s)" in line
    assert fl.said[-1][1]["topic"] == "question" and "regressed" in fl.said[-1][0][1] and lessons[0][0] == "bench"
    assert reconcile.bench_trend(noon) is None                       # reported once


def test_random_file_is_source_from_the_tree(monkeypatch):
    import base64
    class GH:
        def api(self, path, *a, **k):
            if "git/trees" in path:
                return {"tree": [{"path": "node_modules/x.js", "type": "blob", "size": 10}, {"path": "src/a.ts", "type": "blob", "size": 100},
                                 {"path": "img.png", "type": "blob", "size": 5}, {"path": "src", "type": "tree"}]}
            return {"content": base64.b64encode(b"export const a = 1;\n").decode()}
    out = reconcile.random_file("o/r", gh=GH(), pick=lambda paths: (paths == ["src/a.ts"]) and paths[0])
    assert out.startswith("RANDOM FILE src/a.ts (head):\nexport const a = 1;")


def test_a_runner_pending_over_twenty_minutes_is_deleted(monkeypatch):
    calls, said = [], []
    monkeypatch.setattr(reconcile, "k8s", lambda m, p, body=None: calls.append((m, p)) or {})
    monkeypatch.setattr(reconcile.ledger, "say", lambda *a, **k: said.append(a) or 1)
    import datetime
    now = datetime.datetime(2026, 9, 9, 20, 20, tzinfo=datetime.timezone.utc).timestamp()
    pods = [{"metadata": {"name": "old", "creationTimestamp": "2026-09-09T19:50:00Z"}, "status": {"phase": "Pending"}},
            {"metadata": {"name": "young", "creationTimestamp": "2026-09-09T20:15:00Z"}, "status": {"phase": "Pending"}},
            {"metadata": {"name": "fine", "creationTimestamp": "2026-09-09T19:00:00Z"}, "status": {"phase": "Running"}}]
    assert reconcile.clear_stuck_runners(now, pods) == ["old"]
    assert calls == [("DELETE", "/api/v1/namespaces/arc-runners/pods/old")]
    assert "Kata sandbox" in said[0][1] and "old" in said[0][1]
    assert reconcile.clear_stuck_runners(now, []) == [] and len(said) == 1


def test_reaping_a_dead_run_fails_its_idea(monkeypatch):
    fl = FakeLedger(); monkeypatch.setattr(reconcile, "ledger", fl)
    finished, states = [], []
    fl.unfinished_runs = lambda: [{"id": "mission-9", "pipeline": "mission", "repo": "o/r", "fingerprint": "fp1", "trigger": "triage", "started_at": "2026-09-10 01:00:00+00:00"}]
    fl.finish_run = lambda *a, **k: finished.append((a, k))
    fl.set_state = lambda fp, st: states.append((fp, st))
    monkeypatch.setattr(reconcile, "k8s", lambda m, p, body=None: {"status": {"failed": 1}} if "/jobs/" in p else
                        {"items": [{"status": {"containerStatuses": [{"name": "implement", "state": {"terminated": {"exitCode": 137, "reason": "OOMKilled"}}}]}}]})
    calls = []
    for name in ("set_status", "link", "reinforce"):
        monkeypatch.setattr(reconcile.ideas, name, lambda *a, _n=name, **k: calls.append((_n, a, k)))
    monkeypatch.setattr(reconcile.ideas, "lookup", lambda **k: ("0123456789ab", None) if k.get("fp") == "fp1" else (None, None))
    assert reconcile.reap_failed_runs(0, gh=type("GH", (), {"api": staticmethod(lambda *a, **k: {})})()) == ["mission-9"]
    assert states == [("fp1", "halted")] and finished[0][0][:2] == ("mission-9", "failed")
    assert ("link", ("idea:0123456789ab", "run:mission-9", "attempt"), {}) in calls
    failed = [c for c in calls if c[0] == "set_status" and c[1][1] == "failed"][0]
    assert failed[2]["run_id"] == "mission-9" and failed[2]["reason"].startswith("implement: stage container killed, exit 137 (OOMKilled")
    assert calls[-1] == ("reinforce", ("run:mission-9", -0.5), {})


def test_daily_ideation_runs_each_repo_after_the_hour(monkeypatch):
    import datetime
    calls = []
    monkeypatch.setattr(reconcile, "launch_ideation", lambda repo, now: calls.append(repo) or ("ideate-kagent" if repo.endswith("kagent") else None))
    monkeypatch.setattr(reconcile, "IDEATION_REPOS", ["o/new_localai", "o/kagent"])
    early = datetime.datetime(2026, 9, 11, 2, 0, tzinfo=datetime.timezone.utc).timestamp()
    late = datetime.datetime(2026, 9, 11, 5, 0, tzinfo=datetime.timezone.utc).timestamp()
    assert reconcile.daily_ideation(early) == [] and calls == []
    assert reconcile.daily_ideation(late) == ["o/kagent"] and calls == ["o/new_localai", "o/kagent"]   # first repo declined, second launched
    calls.clear()
    monkeypatch.setattr(reconcile, "launch_ideation", lambda repo, now: calls.append(repo) or "ideate-x")
    assert reconcile.daily_ideation(late) == ["o/new_localai"] and calls == ["o/new_localai"]          # one launch per tick


def test_one_thinker_at_a_time(monkeypatch):
    fl = FakeLedger()
    monkeypatch.setattr(reconcile, "ledger", fl)
    jobs = {"items": [{"metadata": {"name": "dream-20260910"}, "status": {"active": 1}}, {"metadata": {"name": "ideate-x-20260910"}, "status": {"succeeded": 1}}]}
    monkeypatch.setattr(reconcile, "k8s", lambda m, p, body=None: jobs)
    assert reconcile.thinker_running() == "dream-20260910"
    assert reconcile.launch_ideation("o/r", 1e9) is None and "ideate-launched:o/r" not in fl.kv   # waits, nothing recorded
    jobs["items"][0]["status"] = {"succeeded": 1}
    assert reconcile.thinker_running() is None


def test_bench_outcome_reverts_a_regression_and_reinforces_an_improvement(monkeypatch):
    kv, said, sent, posted, launched, status, reinforced, remembered = {}, [], [], [], [], [], [], []
    b = lambda d, held: {"rows": [{"held_out": True, "success": held}], "success": 3, "n": 4, "seconds": 100}
    monkeypatch.setattr(reconcile.ledger, "merged_runs", lambda trigger, limit=20: [
        {"id": "m1", "repo": "o/r", "pr_url": "https://github.com/o/r/pull/7", "merged_at": "2026-09-09 12:00:00"},
        {"id": "m2", "repo": "o/r", "pr_url": "https://github.com/o/r/pull/8", "merged_at": "2026-09-10 12:00:00"}])
    monkeypatch.setattr(reconcile.ledger, "kv_like", lambda p: [("bench:20260908", b("20260908", True)), ("bench:20260910", b("20260910", False)), ("bench:20260911", b("20260911", True)), ("bench:baseline", {"rows": []})])
    monkeypatch.setattr(reconcile.ledger, "kv_get", lambda k: kv.get(k))
    monkeypatch.setattr(reconcile.ledger, "kv_set", lambda k, v: kv.__setitem__(k, v))
    monkeypatch.setattr(reconcile.ledger, "say", lambda *a, **k: said.append(a[1]) or 1)
    monkeypatch.setattr(reconcile.telegram, "send", lambda m: sent.append(m))
    monkeypatch.setattr(reconcile.github, "api", lambda path, data=None, **k: posted.append((path, data)))
    monkeypatch.setattr(reconcile.ideas, "lookup", lambda pr_url=None, fp=None: ("idea1", "m1"))
    monkeypatch.setattr(reconcile.ideas, "set_status", lambda iid, st, **k: status.append((iid, st, k.get("reason"))))
    monkeypatch.setattr(reconcile.ideas, "reinforce", lambda node, delta, hops=3: reinforced.append((node, delta)) or 1)
    from fleet import memory
    monkeypatch.setattr(memory, "remember", lambda kind, text, **k: remembered.append(text) or "k")
    class R:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b'{"name": "mission-revert"}'
    monkeypatch.setattr(reconcile.urllib.request, "urlopen", lambda req, timeout=30: launched.append(req.data) or R())
    monkeypatch.setattr(reconcile.json, "load", lambda f: {"name": "mission-revert"})
    out = reconcile.bench_outcome(1e9)
    # PR 7 merged 09-09: before <= 09-09 is 20260908 (held 1), after 20260910 (held 0) -> regressed
    # PR 8 merged 09-10 12:00: the 03:00Z bench of 09-10 (0) is before, 20260911 (1) after -> improved
    assert out == ["https://github.com/o/r/pull/7:regressed", "https://github.com/o/r/pull/8:improved"]
    assert status == [("idea1", "failed", "bench regressed after merge (1 -> 0)")]
    assert reinforced == [("pr:https://github.com/o/r/pull/7", -1.0), ("pr:https://github.com/o/r/pull/8", 1.0)]
    assert len(launched) == 1 and b"Revert https://github.com/o/r/pull/7" in launched[0] and b"bench:revert" in launched[0]
    assert posted[0][0] == "/repos/o/r/issues/7/comments" and "regressed" in sent[0] and "reverted" in remembered[0]
    assert reconcile.bench_outcome(1e9) == []                      # once per PR


def test_the_dream_is_its_own_job_and_the_flag_forces_it(monkeypatch):
    import datetime
    fl = FakeLedger()
    monkeypatch.setattr(reconcile, "ledger", fl)
    created = []
    tpl = {"spec": {"jobTemplate": {"spec": {"activeDeadlineSeconds": 240, "template": {"metadata": {}, "spec": {"containers": [{"name": "reconcile", "command": ["python3", "/app/scripts/reconcile.py"], "env": []}]}}}}}}
    monkeypatch.setattr(reconcile, "k8s", lambda m, p, body=None: created.append((m, p, body)) or tpl)
    night = datetime.datetime(2026, 9, 11, 3, 5, tzinfo=datetime.timezone.utc).timestamp()
    assert reconcile.launch_dream(night) == "dream-20260911"
    job = next(b for m, p, b in created if m == "POST")
    assert job["spec"]["template"]["spec"]["containers"][0]["command"] == ["python3", "/app/scripts/reconcile.py", "--dream"]
    assert reconcile.launch_dream(night) is None                              # once a night
    ran = []
    monkeypatch.setattr(reconcile, "dream", lambda now, force=False: ran.append(force) or {"lessons": 0})
    monkeypatch.setattr(reconcile.sys, "argv", ["reconcile.py", "--dream"])
    assert reconcile.main() == 0 and ran == [True]


def test_a_job_that_already_exists_counts_as_launched(monkeypatch):
    import io, urllib.error
    fl = FakeLedger()
    monkeypatch.setattr(reconcile, "ledger", fl)
    tpl = {"spec": {"jobTemplate": {"spec": {"template": {"metadata": {}, "spec": {"containers": [{"name": "reconcile", "command": [], "env": []}]}}}}}}
    def k8s(m, p, body=None):
        if m == "POST":
            raise urllib.error.HTTPError(p, 409, "AlreadyExists", {}, io.BytesIO(b""))
        return tpl
    monkeypatch.setattr(reconcile, "k8s", k8s)
    assert reconcile.launch_from_template("ideate-kagent-20260910", ["python3", "x"]) == "ideate-kagent-20260910"
    def k8s_500(m, p, body=None):
        if m == "POST":
            raise urllib.error.HTTPError(p, 500, "boom", {}, io.BytesIO(b""))
        return tpl
    monkeypatch.setattr(reconcile, "k8s", k8s_500)
    assert reconcile.launch_from_template("x", ["python3", "x"]) is None


def test_launch_idea_runs_the_best_untried_archive_idea(monkeypatch):
    """An empty streak reaches into the archive before it asks anyone (2026-09-11:
    17 active ideas sat untried while the tick asked Chris to post one)."""
    import io
    from fleet import ideas
    monkeypatch.setattr(reconcile, "DRY_RUN", False)
    monkeypatch.setattr(ideas, "rows", lambda repo, statuses, limit: [
        {"id": "aaaaaaaaaaaa", "scores": {"soundness": 90, "clarity": 90, "non_obviousness": 90, "diversity": 90}, "run_id": "improve-x"},  # tried
        {"id": "bbbbbbbbbbbb", "scores": {"soundness": 60, "clarity": 60, "non_obviousness": 60, "diversity": 60}, "run_id": None},
        {"id": "cccccccccccc", "scores": {"soundness": 80, "clarity": 80, "non_obviousness": 80, "diversity": 80}, "run_id": None},
    ])
    sent = []

    class R:
        def __init__(self, req): sent.append(json.loads(req.data))
        def __enter__(self): return io.BytesIO(b'{"name": "mission-1"}')
        def __exit__(self, *a): pass
    monkeypatch.setattr(reconcile.urllib.request, "urlopen", lambda req, timeout=30: R(req))
    assert reconcile.launch_idea("o/k", 0.0) == "mission-1"
    assert sent == [{"brief": "[idea:cccccccccccc]", "repo": "o/k", "requestedBy": "reconcile:idea"}]  # best untried, not the tried best
    # 2026-09-14: an idea naming a file its repo never had is rejected, and the next one launches
    rejected = []
    monkeypatch.setattr(ideas, "rows", lambda repo, statuses, limit: [
        {"id": "dddddddddddd", "scores": {"soundness": 95, "clarity": 95, "non_obviousness": 95}, "run_id": None, "mechanism": "edit src/stages/implement.ts"},
        {"id": "cccccccccccc", "scores": {"soundness": 80, "clarity": 80, "non_obviousness": 80}, "run_id": None, "mechanism": "edit src/a.ts"}])
    monkeypatch.setattr(ideas, "_paths", lambda repos: {"src", "src/a.ts"})
    monkeypatch.setattr(ideas, "set_status", lambda iid, status, reason=None, **k: rejected.append((iid, status, reason)))
    assert reconcile.launch_idea("o/k", 0.0) == "mission-1" and sent[-1]["brief"] == "[idea:cccccccccccc]"
    assert rejected == [("dddddddddddd", "rejected", "names files not in o/k: src/stages/implement.ts")]
    monkeypatch.setattr(ideas, "rows", lambda repo, statuses, limit: [])
    assert reconcile.launch_idea("o/k", 0.0) is None


def test_two_review_rounds_close_the_pr_and_the_lineage_learns(monkeypatch):
    fl = FakeLedger(); monkeypatch.setattr(reconcile, "ledger", fl)
    from fleet import ideas, memory
    calls, lessons, status = [], [], []
    monkeypatch.setattr(memory, "remember", lambda kind, text, repo=None, ref=None, source="fleet": lessons.append((kind, text, repo)) or "k")
    monkeypatch.setattr(ideas, "lookup", lambda fp=None, pr_url=None: ("abcdefabcdef", None))
    monkeypatch.setattr(ideas, "set_status", lambda iid, st, reason=None, pr_url=None, run_id=None: status.append((iid, st)))

    class GH:
        def api(self, path, data=None, method=None): calls.append((method or "POST", path, data)); return {}
    pr = {"title": "pre-flights", "html_url": "https://github.com/o/k/pull/7"}
    reconcile.close_after_rounds("o/k", "7", pr, {"feedback": "validity checks are missing"}, GH())
    assert [(m, p) for m, p, _ in calls] == [("POST", "/repos/o/k/issues/7/comments"), ("PATCH", "/repos/o/k/pulls/7")]
    assert calls[1][2] == {"state": "closed"}
    assert lessons[0][0] == "lesson" and "validity checks are missing" in lessons[0][1] and lessons[0][2] == "o/k"
    assert status == [("abcdefabcdef", "failed")]
    assert fl.said[-1][1]["topic"] == "status"


def test_capacity_line_counts_timeouts_and_blocked_ticks(monkeypatch):
    fl = FakeLedger(); monkeypatch.setattr(reconcile, "ledger", fl)
    now = time.time()
    reconcile.bump("blocked", "spark", now); reconcile.bump("blocked", "spark", now); reconcile.bump("blocked", "thinker", now - 86400)
    evidence = "RUNS (last 24h):\n- a o/k halted dsh exceeded the 3600s stage timeout \n- b o/k halted investigator found no candidates \n- c o/k halted dsh exceeded the 1500s stage timeout "
    assert reconcile.capacity_line(now, evidence) == "2 halt(s) were stage timeouts; ticks blocked by the spark: 2, by the thinker: 1"


class RepoGh:
    def __init__(self, issues):
        self.issues = issues
    def api(self, path, *a, **k):
        lbl = path.split("label:%22")[1].split("%22")[0]
        return {"items": [{"repository_url": f"https://api.github.com/repos/{r}"} for r in self.issues.get(lbl, [])]}
    def kid_gloves(self, repo):
        return False


def test_choose_repo_ignores_the_fleets_own_halts_and_rotates(monkeypatch):
    fake = FakeLedger(); monkeypatch.setattr(reconcile, "ledger", fake)
    monkeypatch.setattr(reconcile, "IDEATION_REPOS", ["o/a", "o/b"])
    fake.recent = [{"repo": "o/a", "started_at": "2026-09-13T20:00"}, {"repo": "o/b", "started_at": "2026-09-13T10:00"}]
    monkeypatch.setattr(fake, "recent_runs", lambda limit=10: list(fake.recent), raising=False)
    # 11 open fleet:halt issues on o/a are the pipeline's own stops, not o/a's problems
    repo, why = reconcile.choose_repo(RepoGh({"fleet:halt": ["o/a"] * 11}))
    assert repo == "o/b" and "least recently" in why
    repo, why = reconcile.choose_repo(RepoGh({"fleet:repair": ["o/a"]}))
    assert repo == "o/a" and "1 open fleet problem" in why


def test_exhausted_rounds_at_high_confidence_with_green_ci_merge_under_the_window(monkeypatch):
    # kagent#48 went 80/78/58 with every check green and was closed; the third
    # verdict after two rounds should announce the merge, not object again.
    fake = FakeLedger(); monkeypatch.setattr(review, "ledger", fake)
    fake.review_rounds = lambda pr_url: 2
    prompts, calls = [], []
    class GH:
        def api(self, path, data=None, method=None, **kw):
            calls.append((method or ("POST" if data is not None else "GET"), path))
            if path.endswith("/files?per_page=100"): return [{"filename": "scripts/collect.py", "changes": 10}]
            if "/check-runs" in path: return {"check_runs": [{"name": "Lint + Test", "status": "completed", "conclusion": "success"}]}
            if kw.get("raw"): return "diff"
            return {}
        def kid_gloves(self, repo): return False
        def push_url(self, repo): raise RuntimeError("no clone in tests")
    monkeypatch.setattr(review, "github", GH())
    monkeypatch.setattr(review, "telegram", type("T", (), {"send": staticmethod(lambda *a, **k: None)})())
    verdicts = iter([{"confidence": 78, "summary": "still wants lint output", "feedback": "add lint output", "prior_addressed": False}])
    def run(cmd, **kw):
        prompts.append(cmd[-1]); return type("R", (), {"stdout": json.dumps(next(verdicts))})()
    monkeypatch.setattr(review.subprocess, "run", run)
    fake.kv["objection:o/r#11"] = {"sha": "s2", "summary": "wants lint", "feedback": "add lint output", "at": 1.0, "confidence": 78}
    pr = {"number": 11, "title": "t", "body": "", "head": {"sha": "s3", "ref": "agent/x", "repo": {"full_name": "o/r"}},
          "user": {"login": "chrisknu"}, "html_url": "u11"}
    review.review_pr("o/r", "/repos/o/r", pr, 11)
    assert "CI: Lint + Test success on this head" in prompts[0]
    assert "objection:o/r#11" not in fake.kv and "merge:o/r#11" in fake.kv
    assert not any("/merge" in c[1] for c in calls)          # announced; the window decides


def test_close_after_rounds_leaves_a_settling_pr_to_the_reviewer(monkeypatch):
    fl = FakeLedger(); monkeypatch.setattr(reconcile, "ledger", fl)
    from fleet import ideas, memory
    calls = []
    monkeypatch.setattr(memory, "remember", lambda *a, **k: "k")
    monkeypatch.setattr(ideas, "lookup", lambda fp=None, pr_url=None: (None, None))
    class GH:
        def api(self, path, data=None, method=None): calls.append((method or "POST", path)); return {}
    pr = {"title": "t", "html_url": "https://github.com/o/k/pull/8"}
    reconcile.close_after_rounds("o/k", "8", pr, {"feedback": "add lint output", "confidence": 78}, GH())
    assert calls == []                                                                   # green: the reviewer settles it
    reconcile.close_after_rounds("o/k", "8", pr, {"feedback": "add lint output", "confidence": 78}, GH(), red=["test"])
    assert ("PATCH", "/repos/o/k/pulls/8") in calls                                      # red CI: closed as before
    calls.clear()
    reconcile.close_after_rounds("o/k", "8", pr, {"feedback": "wrong", "confidence": 40}, GH())
    assert ("PATCH", "/repos/o/k/pulls/8") in calls                                      # low confidence: closed as before


def test_observe_pods_stores_new_log_trouble_as_a_fact_once_a_day(monkeypatch):
    pods = [{"metadata": {"name": "kagent-kagent-operator-channel-telegram-d47885f77-7pfm9", "labels": {}}, "spec": {"containers": [{"name": "adapter"}]}},
            {"metadata": {"name": "fleet-console-56c5d44c55-s4zqh", "labels": {}}, "spec": {"containers": [{"name": "console"}]}},
            {"metadata": {"name": "mission-20260915-1-abcde", "labels": {"job-name": "mission-20260915-1"}}, "spec": {"containers": [{"name": "stage"}]}}]
    logs = {"kagent-kagent-operator-channel-telegram-d47885f77-7pfm9": "polled\n[channel-telegram] inbound message rejected by channel gateway ChannelGatewayHttpError: channel gateway returned HTTP 400\n    message: 'request body exceeds 262144 bytes'\n",
            "fleet-console-56c5d44c55-s4zqh": "GET /health 200\nGET /api/state 200\n",
            "mission-20260915-1-abcde": "Traceback (most recent call last)\n"}
    kv, facts = {}, []
    monkeypatch.setattr(reconcile.ledger, "kv_get", lambda k: kv.get(k))
    monkeypatch.setattr(reconcile.ledger, "kv_set", lambda k, v: kv.__setitem__(k, v))
    from fleet import memory
    monkeypatch.setattr(memory, "remember", lambda kind, text, repo=None, ref=None, source="fleet": facts.append((kind, source, repo, text)) or "k")
    fetch = lambda name, c: logs.get(name, "")
    out = reconcile.observe_pods(1000.0, pods=pods, logs=fetch)
    assert len(out) == 1 and facts == [("fact", "observer", None, out[0])]            # the adapter, not the healthy console, not the stage pod
    assert out[0].startswith("kagent-kagent-operator-channel-telegram (adapter) logged 2 error line(s)") and "HTTP 400" in out[0]
    assert reconcile.observe_pods(1600.0, pods=pods, logs=fetch) == []                 # the same shape again today: said once
    assert len(reconcile.observe_pods(1000.0 + 90000, pods=pods, logs=fetch)) == 1     # a day later it is news again

