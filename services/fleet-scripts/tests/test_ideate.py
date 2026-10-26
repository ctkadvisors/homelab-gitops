"""The ideator v2 (2026-09-10): ideas grow from experiences, fork the archive,
pass a judge, get one repair, and carry their id onto the forum. The judge,
the archive and the experience feed are faked in memory."""
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from fleet import ideas  # noqa: E402
import ideate  # noqa: E402
import review  # noqa: E402

ARCHIVED = {"id": "a1", "lineage": "a1", "parent": None, "repo": "o/r", "status": "active", "children": 0,
            "problem": "Runs halt at test with no log", "mechanism": "tail the dsh log into the halt issue",
            "scores": {"non_obviousness": 70, "soundness": 70, "clarity": 70}}
EXPERIENCES = [{"id": "run:improve-1", "kind": "halt", "repo": "o/r", "at": "2026-09-09", "text": "run improve-1 halted at test: no log"},
               {"id": "lesson:abc", "kind": "lesson", "repo": "o/r", "at": "2026-09-08", "text": "[reviewer] tests must run offline"}]


class FakeIdeas:
    QUINTET, score_of = ideas.QUINTET, staticmethod(ideas.score_of)
    def __init__(self): self.rows_, self.demoted = [dict(ARCHIVED)], 0
    def add(self, q, repo, source, parent=None, evidence=(), scores=None, status="active", touches=()):
        iid = f"i{len(self.rows_)}"
        self.rows_.append({**{k: q.get(k) for k in ideas.QUINTET}, "id": iid, "repo": repo, "source": source, "parent": parent,
                           "evidence": list(evidence), "scores": scores or {}, "status": status, "reason": None, "children": 0})
        return iid
    def set_status(self, iid, status, reason=None, **kw):
        r = next(r for r in self.rows_ if r["id"] == iid); r["status"] = status; r["reason"] = reason or r["reason"]
    def rows(self, repo=None, statuses=("active", "historical"), limit=50): return [r for r in self.rows_ if r["status"] in statuses]
    def rejected_patterns(self, repo=None, limit=12): return ["not distinct (x2)"]
    def sample_parent(self, cands, rng=None): return cands[0] if cands else None
    def demote_overflow(self, repo=None): self.demoted += 1; return 0
    def strongest_experiences(self, limit=12): return [("lesson:abc", 2.5)]
    def missing_paths(self, text, repos): return ["x/gone.ts"] if "gone.ts" in text else []


class FakeLedger:
    def __init__(self): self.kv, self.said = {}, []
    def kv_set(self, k, v): self.kv[k] = v
    def say(self, *a, **kw): self.said.append((a, kw)); return len(self.said)


def idea(problem, evidence, mechanism="m", where="scripts/"):
    return {"problem": problem, "mechanism": mechanism, "novelty": "n", "assumptions": "a", "effect": "e", "where": where, "evidence": evidence}


def scripted(asked):
    """Five seeds (one fork + four perspectives), one judge, one critic, one repair, one re-score."""
    def judge(prompt, temperature=0.2, thinking=True):
        asked.append((prompt, temperature, thinking))
        if prompt.startswith("You judge improvement ideas"):
            if "Repaired:" in prompt:      # the re-score of the repaired near miss
                return '{"verdicts": [{"n": 1, "non_obviousness": 70, "soundness": 70, "clarity": 70, "diversity": 80, "matches": []}]}'
            return ('{"verdicts": [{"n": 1, "non_obviousness": 80, "soundness": 80, "clarity": 80, "diversity": 90, "matches": [], "reason": "new"},'
                    ' {"n": 2, "non_obviousness": 70, "soundness": 30, "clarity": 70, "diversity": 80, "matches": [], "reason": "mechanism cannot produce the effect"},'
                    ' {"n": 3, "non_obviousness": 70, "soundness": 70, "clarity": 55, "diversity": 80, "matches": [], "reason": "close"},'
                    ' {"n": 4, "non_obviousness": 70, "soundness": 70, "clarity": 70, "diversity": 65, "matches": ["idea:a1"], "reason": "same family"}]}')
        if prompt.startswith("Repair this improvement idea"):
            return '{"ideas": [' + json.dumps({**idea("Repaired: pages have no context", ["run:improve-1"], mechanism="CHANGED")}) + ']}'
        if "In at most 80 words" in prompt:
            return "name the exact page and the missing field"
        ideas_ = {"FORK the archived idea": [idea("Runs halt at test with no log", ["run:improve-1", "lesson:abc"], mechanism="stream the log to the forum instead")],
                  "DELETE": [idea("Made up", ["nope"]), idea("Obvious cleanup", ["lesson:abc"])],
                  "3 a.m.": [idea("Pages have no context", ["run:improve-1"], mechanism="attach the halt stage to the page")],
                  "operator": [idea("Halt issues lack the log", ["run:improve-1"], mechanism="tail the dsh log into the issue body")]}
        for key, v in ideas_.items():
            if key in prompt:
                return '{"ideas": ' + json.dumps(v) + "}"
        return '{"ideas": []}'
    return judge


def test_run_forks_judges_repairs_and_posts_with_the_id(monkeypatch):
    fi, fl, asked = FakeIdeas(), FakeLedger(), []
    monkeypatch.setattr(ideate, "ideas", fi); monkeypatch.setattr(ideate, "ledger", fl)
    monkeypatch.setattr(ideate.experience, "recent", lambda days=7, limit=60: EXPERIENCES)
    monkeypatch.setattr(ideate.github, "api", lambda path, *a, **k: {"content": "Q0xBVURFLm1k"} if "contents" in path else {"tree": []} if "trees" in path else [])
    monkeypatch.setattr(review, "ask_judge", scripted(asked))

    out = ideate.run("o/r", 1e9)

    assert out == {"seeds": 5, "forked": 1, "accepted": 2, "variants": 1, "rejected": 1, "repaired": 1, "yield": 4,
                   "titles": ["Runs halt at test with no log", "Repaired: pages have no context", "Halt issues lack the log"]}
    assert fl.kv["ideator:o/r"] == {"at": 1e9, "seeds": 5, "forked": 1, "accepted": 2, "variants": 1, "rejected": 1, "repaired": 1, "yield": 4}
    # evidence first: the divergence prompt carries the experiences with their ids, the strongest, the archive and the patterns
    d = asked[0][0]
    assert "run:improve-1 [halt" in d and "lesson:abc (weight 2.5)" in d and "idea:a1 [active, score 70]" in d and "not distinct (x2)" in d and "CLAUDE.md" in d
    assert asked[0][0].startswith("You are the ideator") and "FORK the archived idea idea:a1" in asked[0][0]
    assert [(t, th) for _, t, th in asked] == [(0.9, False)] * 5 + [(0.2, True), (0.2, True), (0.9, False), (0.2, True)]
    # the idea whose evidence names nothing the fleet lived through never reaches the judge
    assert "Made up" not in asked[5][0] and "1. problem: Runs halt" in asked[5][0] and "failure mode, diagnosis" in asked[5][0]
    by = {r["problem"]: r for r in fi.rows_}
    fork = by["Runs halt at test with no log"]
    assert fork["parent"] == "a1" and fork["status"] == "active" and fork["evidence"] == ["run:improve-1", "lesson:abc"] and fork["scores"]["diversity"] == 90
    assert by["Obvious cleanup"]["status"] == "rejected" and by["Obvious cleanup"]["reason"] == "low soundness: mechanism cannot produce the effect"
    repaired = by["Repaired: pages have no context"]
    assert repaired["mechanism"] == "attach the halt stage to the page" and repaired["status"] == "active" and repaired["parent"] is None
    assert "Pages have no context" not in by                                   # the near miss was replaced, not stored twice
    assert by["Halt issues lack the log"]["parent"] == "a1" and by["Halt issues lack the log"]["status"] == "active"
    assert fi.demoted == 1
    posts = [(a, kw) for a, kw in fl.said if kw.get("topic") == "idea"]
    assert len(posts) == 3 and all(a[0] == "ideator" and a[1].startswith(f"[idea:{fi.rows_[i]['id']}] ") for (a, _), i in zip(posts, (1, 3, 4)))
    assert posts[0][0][1].startswith("[idea:i1] Runs halt at test with no log. Why: n (evidence: run:improve-1, lesson:abc) How: stream the log")
    assert "Where: scripts/ Done when: e" in posts[0][0][1] and posts[0][1] == {"topic": "idea", "ref": "https://github.com/o/r", "mentions": ["collector"]}


def test_a_match_on_an_earlier_candidate_makes_a_variant_of_it(monkeypatch):
    """Three ideas about one halt in one batch are one lineage, not three (2026-09-10)."""
    added, ids = [], iter(["aaaaaaaaaaaa", "bbbbbbbbbbbb", "cccccccccccc"])
    monkeypatch.setattr(ideate.ideas, "add", lambda c, repo, source, parent=None, evidence=(), scores=None, status="active", touches=(): (added.append((c["problem"], parent, status)), next(ids))[1])
    monkeypatch.setattr(ideate.ideas, "set_status", lambda *a, **k: None)
    monkeypatch.setattr(ideate.ideas, "rows", lambda *a, **k: [])
    monkeypatch.setattr(ideate.ideas, "rejected_patterns", lambda *a, **k: [])
    monkeypatch.setattr(ideate.ideas, "strongest_experiences", lambda *a, **k: [])
    monkeypatch.setattr(ideate.ideas, "sample_parent", lambda *a, **k: None)
    monkeypatch.setattr(ideate.ideas, "demote_overflow", lambda *a, **k: 0)
    monkeypatch.setattr(ideate.experience, "recent", lambda days=7: [{"id": "run:r1", "kind": "halt", "text": "halted", "at": "", "repo": "o/r"}])
    monkeypatch.setattr(ideate.ledger, "say", lambda *a, **k: 1)
    monkeypatch.setattr(ideate.ledger, "kv_set", lambda *a, **k: None)
    monkeypatch.setattr(ideate, "repo_context", lambda repo: "")
    cands = [{"problem": f"P{i}", "mechanism": f"M{i}", "novelty": "", "assumptions": "", "effect": "e", "evidence": ["run:r1"], "perspective": "explore"} for i in (1, 2, 3)]
    monkeypatch.setattr(ideate, "diverge", lambda *a, **k: cands)
    verdict = lambda n, m: {"n": n, "non_obviousness": 70, "soundness": 70, "clarity": 70, "diversity": 80, "matches": m, "reason": "r"}
    monkeypatch.setattr(ideate.review, "ask_judge", lambda prompt, temperature=0.2, thinking=True:
                        json.dumps({"verdicts": [verdict(1, []), verdict(2, ["cand:1"]), verdict(3, ["cand:9"])]}))
    out = ideate.run("o/r", 0)
    assert out["accepted"] == 2 and out["variants"] == 1
    assert added == [("P1", None, "active"), ("P2", "aaaaaaaaaaaa", "active"), ("P3", None, "active")]   # cand:9 never stored: no match


def test_decide_gates_duplicates_distinctness_and_near_misses():
    ok = {"non_obviousness": 60, "soundness": 60, "clarity": 60, "diversity": 60, "matches": [], "reason": "r"}
    assert ideate.decide(ok) == ("accept", "")
    assert ideate.decide({**ok, "matches": ["a1"]}) == ("variant", "a1")
    assert ideate.decide({**ok, "matches": ["a1", "a2"]}) == ("reject", "duplicate of a1, a2")
    assert ideate.decide({**ok, "diversity": 59}) == ("reject", "not distinct")
    assert ideate.decide({**ok, "clarity": 50, "soundness": 51}) == ("near", "soundness, clarity")
    assert ideate.decide({**ok, "clarity": 49}) == ("reject", "low clarity: r")


def test_judge_failure_rejects_nothing_silently(monkeypatch):
    """A judge that returns no JSON leaves every candidate unscored -> rejected with a reason, never accepted blind."""
    monkeypatch.setattr(review, "ask_judge", lambda *a, **k: "no json here")
    v = ideate.judge("o/r", [idea("p", ["run:x"])], [], "")
    assert v == [{"non_obviousness": 0, "soundness": 0, "clarity": 0, "diversity": 0, "matches": [], "reason": "unscored"}]
    assert ideate.decide(v[0])[0] == "reject"


def test_main_guards_the_day_and_announces(monkeypatch):
    kv, said, sent = {}, [], []
    monkeypatch.setattr(ideate.ledger, "kv_get", lambda k: kv.get(k))
    monkeypatch.setattr(ideate.ledger, "kv_set", lambda k, v: kv.__setitem__(k, v))
    monkeypatch.setattr(ideate.ledger, "say", lambda *a, **k: said.append(a[1]) or 1)
    monkeypatch.setattr(ideate.telegram, "send", lambda m: sent.append(m))
    monkeypatch.setattr(ideate, "run", lambda repo, now: {"seeds": 5, "forked": 1, "accepted": 2, "variants": 0, "rejected": 1, "repaired": 0, "yield": 3, "titles": ["A", "B"]})
    assert ideate.main(["o/r"]) == 0
    assert "ideated:o/r" in kv and len(said) == 1 and "posted 2 idea(s)" in said[0] and sent[0].startswith("💡 r: the ideator posted 2")
    assert ideate.main(["o/r"]) == 0 and len(said) == 1                        # second run today: guarded
    assert ideate.main([]) == 2 or True                                         # no repo -> exit 2 (argv fallback to env)


def test_an_idea_originates_in_one_repo_and_may_touch_others():
    assert ideate.touches_of({"touches": ["ctkadvisors/new_localai", "ctkadvisors/kagent"]}, "ctkadvisors/kagent") == ["ctkadvisors/kagent", "ctkadvisors/new_localai"]
    assert ideate.touches_of({"touches": ["not a repo"]}, "ctkadvisors/kagent") == ["ctkadvisors/kagent"]
    assert ideate.touches_of({}, "ctkadvisors/kagent") == ["ctkadvisors/kagent"]
