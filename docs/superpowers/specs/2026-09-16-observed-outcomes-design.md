# Observed outcomes: claims, measurement, correction

Date: 2026-09-16. Status: design approved in conversation (Chris, 2026-09-16 01:40-02:20Z), spec for review.
Supersedes the outcome rows' meaning in `2026-09-04-self-driving-fleet-design-v2.md` (recurred / rolled_back only)
and builds the `merged -> deployed -> observed` states the Codex review of 2026-09-04 prescribed and nothing implemented.

## Why

Chris, 2026-09-16: "'green' CI and self-crafted tests passing are not acceptance criteria. they're foundational blocks,
however insufficient to 'say a thing was completed and works'. it MUST be observed in action, after deployed.. and
corrected WHEN (not if) it fails/drifts." And: "if the task is 'improve agent creativity' then the measurement is how
much more creative; or 'fix zyx in the harness' then the outcome is A) dont reproduce the error we fixed AND show the
new harness works 'better'."

What exists: `reconcile.observe_outcomes` follows a merge at 24h and 7d and records two booleans, recurred (the same
candidate attempted again) and rolled_back (a human revert on main). Neither watches the change run. The bench is the one
place the fleet observes a change and reverts on regression, and it covers harness changes only. Between 2026-09-12 and
09-16 the fleet merged 5 PRs and Claude sessions merged 39 harness fixes; the Telegram adapter was dead for four days while
every tick printed the evidence. Nothing in the loop measured its own work.

## Principles

1. Done means observed. A change is accepted when its declared claim is measured true on the live system.
2. Every launch declares a claim before it starts. No claim, no launch. No claim in the PR, the reviewer objects.
3. The fleet measures; the model never grades its own claim. Baselines and after-values come from the metric catalog,
   computed from ledger, cluster and GitHub data.
4. Failure teaches. A missed claim produces the richest evidence in the system: numbers, what was tried, what it cost,
   and a fix mission. Chris is not paged for any of it.
5. Idle means working. When no user-delegated task is in flight the fleet is always on one rung of the idle ladder
   (below). Capacity gates it, never a daily count.
6. The loop watches its own inputs. A sentinel checks every prompt, brief, bridged message and tool result for size,
   duplication and nesting before a model sees it; an anomaly is adjudicated, and a real defect halts that loop until
   its fix is observed.
7. The harness is model-agnostic. Every rule here holds unchanged if a frontier model replaces ornith15 or qwen38;
   the only expected difference is the catalog reading better, faster, more reliable. No rail may depend on a model's
   capability level, and no rail exists only to compensate for a small one. The target is what a DGX Spark runs for free
   on 2026-09-15 (Chris: "our harnesses should behave the same if we swap out a frontier model... the expectation is that
   it'd be better/faster/more reliant IF we did.. but we're aiming at dgx spark capable models for 'free'").

## Domain model

Three additions to the ledger's existing candidate / run / outcome / idea tables; nothing replaced.

**Claim** (jsonb `claim` on `candidate`; mirrored on the idea row; rendered in the PR body):

```
{metric, direction: up|down, scope: {kind: fingerprint|repo|fleet|canary, id},
 baseline: {value, n, at}, samples_needed, cap_days, min_effect,
 after: {value, n, at} | null, verdict: null | improved|flat|regressed|recurred|unmeasurable, forced: bool}
```

A human brief with no named metric defaults to `recurrence` on its fingerprint plus `canary_uptime` on the repo's
canary set. Docs-only work declares `no_behavior_change` and skips measurement (verdict `kept` at deploy).

**Metric** (catalog entry in `fleet/metrics.py`): `name, kind: deterministic|judged, direction_good, samples_needed,
min_effect, measure(scope, since, until) -> (value, n)`. Judged metrics measure by running a fixed held-out prompt set
(in the repo, changed only by PR) through the subject and scoring with qwen38 at temperature 0, thinking off; value is
the mean score, n the prompt count. Results cache in kv `metric:<name>:<scope>:<day>` like the bench.

**Verdict** fills the existing `outcome` row: `metric, before_value, after_value, recurred, note` plus `obs_window` =
`claim`. `improved` when the delta in the good direction exceeds `min_effect`; `regressed` when it exceeds it the wrong
way; `flat` otherwise; `recurred` overrides at 24h or 7d; `unmeasurable` when the metric failed to compute on two
consecutive ticks (also an anomaly).

**Anomaly** (new table `anomaly`): `id, kind, where, evidence, adjudication: defect|expected|null, halted: loop kind|null,
fix_fingerprint, created_at, resolved_at`.

Candidate states, extending today's: `tested -> merged -> deployed -> observing -> kept | no_effect | missed -> fixing ->
kept | reverted`. `deployed` is set by a detector, never by the merge event. Idea lineage records the verdict with its
numbers as a node, so a fork of a missed idea starts from what was measured.

## Metric catalog, version 1

Deterministic (all computable today):

| metric | scope | measures | samples_needed | min_effect |
|---|---|---|---|---|
| recurrence | fingerprint | same candidate attempted again, or its halt reason class seen again | clock: 24h, 7d | any |
| halt_rate_by_class | fleet, repo | halted runs of a class / runs (classes: no_candidates, no_commit, degenerate, timeout, tool_error, other) | 10 runs | 5 points |
| first_pass_acceptance | repo | PRs scored at or above the merge bar on first judgment / PRs judged | 8 PRs | 5 points |
| review_rounds_to_merge | repo | rounds per merged PR, mean | 5 merges | 0.5 round |
| implement_seconds | repo | median implement stage seconds | 8 runs | 15 % |
| tokens_per_stage | stage | prompt + output tokens per stage from the dsh session (new capture in stage.sh timing.json) | 8 runs | 15 % |
| bench_pass_rate | fleet | held-out bench fixtures passed / run | 1 bench run | 1 fixture |
| canary_uptime | canary | checks passed / checks run | 24 checks | 5 points |
| concierge_answer_rate | fleet | forum questions answered by the concierge within 15 min / questions asked | 10 questions | 10 points |
| ci_green_rate | repo | homelab CI runs green on first attempt / runs | 8 runs | 10 points |

Judged, version 1 has one: `idea_novelty` (subject: ideator output against the archive; held-out set: 20 fixed evidence
bundles in `services/fleet-scripts/heldout/idea_novelty/`; score 1-10 for non-duplication and specificity; 20 samples,
min_effect 0.5). `answer_quality` and `plan_fidelity` are named for later and added when a claim needs them.

Canaries (source of `canary_uptime`, the change-agnostic floor), run every 15 minutes by `reconcile.canaries()`, results
in kv `canary:<name>` as a bounded history:

| canary | check | pass |
|---|---|---|
| telegram_roundtrip | synthetic inbound posted to the channel gateway for a dedicated canary peer | a Completed concierge task for it within 10 min |
| forum | POST a `canary` topic post, GET it back | both within 5 s |
| launcher | GET `/missions` | 200 within 5 s |
| spark_ornith15, spark_qwen38 | one-token chat completion through the llm-gateway | 200 within 60 s |
| ci_homelab | the smoke workflow on new_localai (`workflow_dispatch`, echo) | green within 10 min, checked next tick |
| tick_clean | the previous reconcile Job's log | no `Traceback`, exit 0 |

The fleet extends the catalog by PR like any code. A new metric's first claim is that it measures something: its own
`unmeasurable` rate over the first week must be zero.

## Deployed detection

Run each tick for candidates in `merged`:

- `ctkadvisors/new_localai` under `services/fleet-scripts/`: the ship run for the merge commit finished and the
  fleet-reconcile CronJob's image tag equals the tag it produced.
- `ctkadvisors/kagent`: the tag pinned in `overlays/production/kagent/application.yaml` was bumped to a tag containing
  the merge commit and every kagent Deployment is ready on it.
- Other repos: the repo's deploy workflow for the merge commit is green; immediately when the repo has none.

`deployed_at` starts the observation clock. No detection after 2 hours writes an anomaly (`deploy_stalled`) with the
evidence gathered, and the candidate stays `merged`.

## Judging

Each tick for candidates in `observing`: `after = measure(scope, deployed_at, now)`. Judge when `n >= samples_needed`
or `now - deployed_at >= cap_days` (default 7; verdict marked `forced`). Recurrence checks stay clock-based at 24h and
7d and override. Write the outcome row, set the candidate state, update the idea status with the numbers, write a memory
lesson (`source: outcome`, both successes and misses; misses carry baseline, after, n, what the implementer wrote), append
an experience node, post to the lineage's forum thread (`topic: outcome`).

## Correction

On `missed`:

1. State `fixing`. One fix mission through the launcher on the same repo: brief carries the claim, baseline, after value
   with n, the PR, the run's 03-implementation notes and the verdict thread. Its claim is the same metric with the after
   value as baseline. `requestedBy: outcome:fix`.
2. The fix ships through the normal path (review, deploy, observe). Fix verdict `improved` or `flat` sets the original
   to `kept` with both verdicts on record.
3. Fix verdict `missed` launches a revert mission (the bench's existing path); original becomes `reverted`; the lineage
   closes that branch with both measurements. A later fork starts from those numbers.
4. At most one correction in flight per candidate. No third attempt without a forked idea (new evidence).

`strongest_experiences` weights missed verdicts highest, so the ideator's next batch grows from them first.

## The sentinel

`fleet/sentinel.py check(kind, text, context) -> finding | None`, deterministic, called at four boundaries: the Telegram
adapter before `postInbound` (kagent; a port of the same rules), `stage.sh` before every dsh prompt, `ideate` and
`review` before their judge calls, the launcher when it builds a brief. Checks: bytes above 3x the rolling median for
that `kind` (kv `norm:<kind>`); a repeated block of 200+ chars; a marker (`[current message]`, `[fleet now]`, `PLAN`,
`LEARNED`, `CLAIM:`) appearing more than once; a tool result identical to the previous one in the same session.

A finding writes an anomaly row and asks the adjudicator (qwen38, evidence attached, thinking off): real defect or
expected? Defect: set kv `halt:<loop kind>` (the scheduler honors it like `pause`), file a fix mission whose claim is
`anomaly_rate` for that kind going to zero, post the thread; the loop resumes when that claim is observed. Expected: widen
the norm and record it, so the same shape does not trip twice.

## The idle ladder and scheduling

When no user-delegated task is in flight (Telegram or console-originated AgentTask running), reconcile takes the first
rung that has work, every tick:

1. correct: a candidate in `missed` with no fix in flight
2. finish: review rounds and settlements on open fleet PRs (existing `retry_reviewed`, `settle_exhausted`)
3. build: the best untried idea (existing `launch_idea`)
4. judge: claims with enough samples; canaries due
5. think: ideate when no untried idea scores above the launch floor (existing, `IDEATE_PER_DAY` removed)
6. dream: memory consolidation, bench, catalog gaps and contradictions (existing dream Job, now on the ladder)

User work preempts all rungs. Capacity gates: implement runs one at a time on ornith15 (`SPARK_BUSY_AT` stays); judge
and think use qwen38 slots and may overlap an implement. `BUDGET_PER_DAY`, `MIN_GAP_MINUTES` and `IDEATE_PER_DAY` are
removed; `IDLE_MINUTES` stays; the console pause switch stays.

## Gates that change

- `ideate.py`: the quintet shape gains `metric` and `direction`; an idea naming no catalog metric is repaired once, then
  rejected (as `missing_paths` does).
- Every launch path (idle idea, improve run, review round, launcher POST): compute the baseline from the catalog, store
  the claim on the candidate, put a `CLAIM:` line in the brief.
- `publish.py`: `### Claim` section above the pipeline evidence.
- `review.py`: a PR with no Claim section gets a deterministic objection before the judge runs; the judge prompt reads
  the claim and judges the diff against it.

## Surfacing

- Console: one Claims panel from `/api/state`: every claim with state, metric, baseline, current value, samples so far
  against needed, verdict; the catalog table (current value, 7-day trend) inside it; anomalies as rows.
- Digest (06:00): leads with claims judged in the last day with numbers, then catalog movement week over week, then
  anomalies; runs and PRs below. One line when nothing was judged.
- Forum: one post per verdict to the lineage thread, one per anomaly with the adjudication.
- The fleet's own evidence: verdicts and catalog trends are experience nodes; the think rung is seeded with the
  worst-trending catalog metric.
- Telegram: only a canary below its floor for longer than `CANARY_PAGE_MINUTES` (60), the "fleet cannot reach you" case.

## Testing

pytest as the repo does it: fake ledger, fake k8s, fake GitHub. One test per verdict path, per sentinel check, per
catalog metric on fixture data, one for the idle ladder ordering, one for deployed detection per repo kind. Judged metrics
run in tests against a three-prompt fixture set with a fake judge, so the mechanics run without the spark. The Telegram
sentinel port gets a vitest case in the adapter package.

## Rollout, four PRs, each observed before the next

1. Catalog (deterministic metrics), claims on candidates, `CLAIM:` in briefs, `### Claim` in PR bodies, reviewer gate,
   Claims panel. Claim of this PR: `first_pass_acceptance` on new_localai does not fall.
2. Deployed detection, judging, verdicts, lessons, experience nodes, digest. Claim: every candidate merged after deploy
   reaches `observing` within 2 h (`deploy_stalled` anomalies = 0).
3. Correction missions, canaries, idle ladder, budget removal. Claim: `canary_uptime` measured for all seven canaries;
   the first `missed` gets a fix mission within one tick.
4. Sentinel and adjudicator, `tokens_per_stage` capture, `idea_novelty`. Claim: `anomaly_rate` on the Telegram bridge
   and stage prompts is measured and zero.

## Designed for small local models

Chris, 2026-09-16: "mind these are not frontier models we can simply throw at a problem. this is agentic/harness
engineering of last year." The models here are ornith15 (35B-A3B, hands) and qwen38 (27B, judge), two slots each way.
So the design puts judgment in rails and asks models only for small, constrained answers:

| new model call | model | shape | size |
|---|---|---|---|
| name the idea's metric | qwen38 (ideator, existing call) | choose from the catalog list, plus a direction | +1 field in an existing JSON answer |
| adjudicate an anomaly | qwen38, thinking off | defect or expected, given the deterministic evidence | one call, < 2 KB prompt, one word + one sentence |
| score a judged metric | qwen38, temperature 0, thinking off | rubric score 1-10 on one fixed prompt | 20 calls per measurement, cached per day |
| fix mission | ornith15 (existing implement path) | one claim, one baseline, one after value, one PR | the brief stays under the current brief size; the numbers replace prose |

Everything else is arithmetic on the ledger, kubectl reads, GitHub reads and string checks. Model identity is a
config knob (`modelClass`, `JUDGE_MODEL`, the dsh patch); a swap changes numbers in the catalog and nothing in the rails,
and the catalog is how the swap is judged. The implementer's prompt
grows by one `CLAIM:` line; the reviewer's by one sentence. No stage gains a tool. Where a rule could be enforced by
code or by asking a model, this design enforces it by code (claim present, deployed detected, samples counted, verdict
computed, halt honored) and asks the model only what code cannot answer.

## Out of scope

Frontier or cloud models anywhere in the loop; a human-fed backlog as the source of work; new dashboards outside the
fleet console; changing the implementer model. Chris, 2026-09-15: the fleet is self-directed, ornith15 stays, and the
levers are focus, memory and measurement.
