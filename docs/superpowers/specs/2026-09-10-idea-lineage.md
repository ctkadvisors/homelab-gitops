# Idea lineage: experience, forks and neurons

Chris, 2026-09-10: "lineage and forking as core concepts for ideation. similar
to humans, the agents need to experience something before they can iterate
and grow. no connection = no growth. we need functional 'neurons' (multi node
hops) that act similarly."

Research behind it (2026-09-10 survey): IDEAgent (quality-diversity search
with active/historical/rejected archives, a diversity judge, a repair pass
and a yield metric; 3.9x more usable distinct ideas), the Darwin Gödel
Machine (an archive of every viable line, parents sampled by score and by
few children, proposals from evaluation logs), Hermes dreaming (a scored
promotion gate and a REM phase that proposes structural change), and the
self-evolving-harness survey (the selection gate decides reliability:
non-regression, held-out split, hidden verifier).

## The model

- An **experience** is anything the fleet lived through: a halt or a ship
  (`run:<job>`), a lesson it wrote (`lesson:<key>`), an open question or an
  escalation (`post:<id>`), a bench result (`bench:<day>`), a rule from Chris
  (`rule:<key>`). `fleet/experience.py` enumerates them; nothing new is stored.
- An **idea** is a row (`fleet/ideas.py`, table `idea`): a quintet (problem,
  mechanism, novelty, assumptions, measurable effect), a source, scores
  (non-obviousness, soundness, clarity, diversity; 0-100), a status
  (active, historical, rejected, attempted, shipped, failed) with a reason,
  a **lineage** (the root idea's id) and a **parent** when it forks another.
- A **link** (table `link`) is a directed, weighted edge `src -> dst` of kind
  evidence (experience -> idea), fork (idea -> idea), attempt (idea -> run),
  outcome (run -> pr), informed (lesson/rule -> idea). Links are the neurons:
  `ideas.path_to(node, hops)` walks back up to 3 hops; `ideas.reinforce(node,
  delta)` changes every link on the paths into an outcome node (+1 shipped,
  -0.5 failed, floor 0.1). `ideas.strongest_experiences()` are the ones that
  have led somewhere before.
- **Selection**: `ideas.sample_parent()` picks an archive idea to fork with
  weight sigmoid(score) x (2 if shipped) / (1 + children), never zero. The
  active archive is capped at 10 by quality (`demote_overflow`); the rest is
  historical and still sampleable. Rejected ideas keep only their reason
  (`rejected_patterns`), which the next ideator reads first.

## The loop (one day)

1. **Evidence first.** The ideator (`scripts/ideate.py`) reads the last 7
   days of experiences, the strongest experiences, the active and historical
   archives, and the rejected patterns.
2. **Parents and seeds.** One parent sampled from the archive to fork, plus
   blank-page seeds from the evidence (four perspectives as today). Every
   idea must name the experience ids it addresses.
3. **Diverge, then judge.** qwen38 without thinking at 0.9 diverges; the
   judge with thinking scores the quintet on non-obviousness, soundness,
   clarity and, against the archives, diversity on eight axes (failure mode,
   diagnosis, intervention, signal source, locus, objective, evaluation,
   assumptions). A close match to one archived idea is a variant in that
   lineage; several matches reject it; diversity < 60 rejects it.
4. **Gate and repair.** non-obviousness >= 60 and soundness >= 60 and
   clarity >= 60. A near miss gets one critic pass and one repair that must
   keep the mechanism.
5. **Archive and post.** Accepted ideas become rows with links; the forum
   post (topic idea) carries `[idea:<id>]` so the collector and the run carry
   the id through candidate -> run -> PR.
6. **Closure.** When a run attempts an idea its status is attempted and a
   link idea -> run is made; shipped sets shipped, links run -> pr and
   reinforces the path +1; a halt sets failed with the halt reason and
   reinforces -0.5. The reason joins the rejected patterns.
7. **REM.** The nightly dream adds one structural proposal as an idea with
   source dream, linked to the lessons and halts it derives from ("a rule
   learned three times wants to become a check").
8. **Bench as target.** One improve run a week has the brief "raise the
   bench": fixtures split into visible and held-out, the reviewer's verdict
   on that PR requires a held-out score strictly above the current one (ties
   rejected).

## Measures (in `ideas.stats()`, the health summary and the nightly Telegram line)

- yield: active ideas above the gate, mutually distinct by construction
- evidence_cited: ideas of the week that link to at least one experience
- shipped_rate: shipped / (attempted + shipped + failed)
- links: total, and the strongest experiences
- bench trend (already)

Where they surface (E, 2026-09-10): `launcher.health()["ideas"]` is
`ideas.stats()` verbatim (`{"note": "unavailable (...)"}` when the ledger is
down, like memory), and the computed summary sentence the concierge says first
ends with ` Ideas: N active, R new in D days, M shipped of K attempted; L links.`
(by_status counts are the whole archive's; only `recent` is windowed, so the
sentence says so rather than calling all of it "this week"). `/missions`
carries `ideas.active` (id, lineage, parent, problem, effect, status, source,
scores; up to 10) for the concierge's [fleet now] block. The console serves
`GET /api/ideas?status=&limit=` and `GET /api/ideas/<id>/path` and renders an
Ideas section: the active archive with a "grew from" line of evidence node ids,
deep-linkable as `#idea-<id>`. The nightly Telegram line is still to carry
yield and shipped_rate (it lives in `reconcile.py`, off E's paths).

## Ownership for the fan-out

- Foundation (this spec, `fleet/ideas.py`, `fleet/experience.py`, tests): done.
- B `scripts/ideate.py` + the call in `reconcile.py` replacing `ideate()`.
- C closure: `scripts/collect.py`, `scripts/publish.py`, `scripts/reconcile.py`
  (reap and retry paths) carry `[idea:<id>]` and call `ideas.set_status` /
  `ideas.reinforce`.
- D `reconcile.dream` REM proposal; `scripts/bench.py` held-out split and
  non-regression compare; the weekly "raise the bench" brief in reconcile.
- E `scripts/console.py` `/api/ideas` and a lineage section on the page;
  `scripts/launcher.py` health carries `ideas.stats()`; the summary line
  carries yield and shipped counts: done (branch `agent/idea-E-console`).
  The nightly Telegram line still needs them (reconcile.py, with C/D).
