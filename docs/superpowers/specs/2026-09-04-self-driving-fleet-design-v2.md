# Self-driving fleet with steering — design v2 (as built, 2026-09-04)

v1 (`2026-09-04-idle-improvement-design-v1.md`) was reviewed adversarially by
Codex gpt-5.6-sol (`2026-09-04-idle-improvement-codex-review.md`): "do not build
v1 as written". Chris then set the default: "it should not be human dependent.
it SHOULD be self driving, but with [the console] for steering", and the goal:
"build it; test steering; prove it works and adds value (no use in burning
tokens/power overnight if its not useful)". This is what got built.

## Principle

The fleet decides and acts; a human steers. Approval is replaced by a veto
window scaled to risk. Every decision is recorded with its evidence. Rails
(budgets, tiers, windows) live in git and change only through a reviewed PR.

## Pieces

| Piece | Where | What |
| -- | -- | -- |
| Legible halts | `services/fleet-scripts/scripts/stage.sh`, `publish.py` | every stage keeps dsh's full output, exit code, log tail and wall time; a stage timeout; halts file a `fleet:halt` issue (fingerprinted; repeats append) and a ledger run row |
| Ledger | `fleet/ledger.py`, `overlays/production/kagent/fleet-ledger.yaml` | Postgres db `fleet`: candidate (fingerprint, tier, evidence, state), run (stages, halt, timing, PR), decision (action, tier, veto window, veto), outcome (metric before/after, recurrence, rollback), scheduler (lease, budget, idle streak). Sealed credentials. GitHub issues are the human-visible queue; the brain mirrors; neither owns |
| Scheduler | `scripts/reconcile.py`, `fleet-reconcile.yaml` | CronJob every 5 min. Signals: spark GPU util (llama-swap `/metrics`), fleet Jobs, AgentTasks, arc-runners pods, workbench sessions `lastActivityAt`, webhook activity (stamped by fleet-hooks). Unknown or stale = busy. Idle streak persisted; launch when idle ≥ IDLE_MINUTES within BUDGET_PER_DAY and MIN_GAP_MINUTES, under one lease. Launch = Job from the improve-daily CronJob template with `RUN_TRIGGER=idle` and its own branch |
| Veto gate | `scripts/review.py` | risk tier from touched paths: 0 docs/tests, 1 code, 2 workflows/manifests/lockfiles/Dockerfiles, 3 secrets/rails/policy. A merge is announced (`fleet:announced`, Telegram, console) and happens after 0 / 15 / 120 minutes unless vetoed; tier 3 never merges on its own |
| Console | `scripts/console.py`, `fleet-console.yaml` | fleet.example.com (LAN, Traefik basic-auth): scheduler state and signals, announced merges with **veto**, the board (`fleet:*` and `mission` issues across every installed repo) with **run** / **decline** / **ask**, runs with stage timings and halt reasons, knobs with a link to the file they live in |

## What was deliberately not built (Codex's list, kept)

No sampler thread in fleet-hooks; no second scheduler; no four runs a day; no
graph-authored scheduler state; no automated graph invalidation or entity
merging; no auto-merge of tier 2+ without a window; no self-registering tools;
no self-modification of rails. Dreaming jobs and the tool RFC lifecycle are
Phase 2 and 3 and start only after the loop below has a record.

## The steering test

1. Two tier-1 PRs on kagent (`agent/steer-veto`, `agent/steer-pass`), one
   comment line each, CI on the homelab runner.
2. The reviewer scores them, announces both (label + Telegram + console card
   with a countdown).
3. Veto one from the console. Expected: next review round says `vetoed`, the PR
   stays open, the decision row carries `vetoed_by`.
4. Leave the other. Expected: after 15 minutes the reviewer merges it, labels
   `fleet:merged`, the ledger shows the decision unvetoed.
5. The scheduler: with everything quiet for 10 minutes, one improve run starts
   with `RUN_TRIGGER=idle`; its run row, timing and outcome appear in the
   console; a halt shows its bundle and files an issue.

## What "adds value" means, measured

The loop is worth keeping if, over its first week:

- runs end legibly: 100% of runs have an explicit outcome and, when halted, a
  log tail (before today: 0 of 2 missions did);
- the scheduler never launches into contention: zero runs while a mission,
  a CI job or a chat was active;
- proposals are real: at least one idle-triggered PR passes the reviewer and
  survives its window, or the halts it files name a root cause that gets fixed;
- steering costs seconds, not attention: vetoes and labels from the console
  take effect within one review round (≤ 5 min via webhook, ≤ 60 via cron);
- cost stays inside the budget: one run a day, on the spark, admitted only when its GPU is idle.

If a week of runs produces only halts with the same root cause, or PRs the
reviewer rejects, the honest call is to lower BUDGET_PER_DAY to 0 and fix the
pipeline, not to keep the lights on.

## Open items

- Postgres credentials for the llm-gateway, OpenWebUI and pgAdmin are plaintext
  in git; the ledger's are sealed. Seal the rest.
- The console reads knobs from its own env; it should read the reconciler's
  CronJob so the two cannot drift.
- Dreaming (Phase 2): outcome linker, failure clustering, contradiction
  candidates, tool-gap mining, retrieval evaluation — narrow, replayable,
  append-only.
- Tool RFCs (Phase 3): tiers, shadow mode, approval bound to an artifact digest.

## Results, night of 2026-09-04 (first run of the loop)

| Claim | Evidence |
| -- | -- |
| Runs end legibly | daily run `dsh-daily-20260904` and idle run `improve-20260904-055500` both halted at investigate with a reason, timing and a `fleet:halt` issue (kagent#17, second run appended by fingerprint); ledger rows for both |
| Scheduler never launches into contention | 30+ ticks refused while CI runners, the daily run or webhook activity were live, each with the reason named; launched once, at 05:55Z, after 15 quiet minutes (decision 2) |
| Self-driving merge | kagent#16 (tier 2, conf 92) announced 05:18Z, merged by the scheduler at 07:20:03Z, 69 s after its window closed, as `app/example-fleet`, Telegram notified |
| Steering works | kagent#18 (tier 2, conf 88) announced, vetoed from the console (`decision 3 vetoed_by human:chris`), still open past its window |
| Cost inside budget | one idle run (5 min of investigate on ornith15), budget 1/1 for the day; nothing ran on the spark for the loop beyond that |

| Steering held at window close | #18's 120-minute window closed at 08:23:23Z with the PR still open; the ledger's decision 3 carries `vetoed_by human:chris`; no reconcile tick merged it |

## Codex's review of night one, and what it changed (2026-09-04)

Codex read the ledger, the Jobs and PR #10 after the first night and called it
"working autonomous execution with useful diagnostics, but unreliable review,
incomplete memory, and no measured learning yet." Verified against the repo and
the live db; all of it held. Fixed the same morning:

| Finding | Fix |
| -- | -- |
| `collect_ledger_runs` read the scheduler kv, not the run table; the collector's memory was always empty and its except never fired | `ledger.recent_runs`: run joined to candidate, one row per candidate, halt reason not log |
| The reviewer found that bug at 06:41, a docs push at 07:19 got a fresh verdict (88) with no memory of it, and it merged | objections persist in the ledger (`objection:<repo>#<n>`) and are fed to every later verdict; merge needs `prior_addressed` |
| 0 candidate rows, fingerprint NULL on all 9 runs, trigger "unknown" on the 7 missions | publish names the candidate (a mission = its issue, an improve run = what adjudicate selected), the launcher sets RUN_TRIGGER, the reviewer marks the candidate merged |
| reconcile admitted on the minis' `/slots` while ornith15 ran on the spark | the signal is the spark's GPU util from llama-swap `/metrics` (`SPARK_BUSY_UTIL`, default 10%) |

Same afternoon: the merge rebuilds the image. `fleet-scripts.yml` ship job joins the
tailnet as an ephemeral tag:ci node, pushes `fleet-scripts:<date>-<sha>` and bumps the
nine overlay manifests; first proof `20260904-ecb36f8` landed on the cluster with no
hand on it. Evening: the learning half. `mark_pr('merged')` opens an outcome row and reconcile
follows up at 24h and 7d (recurred = attempted again, rolled_back = a revert on main);
every run records `cost.model_seconds` of ornith15; the launcher admits through the
ledger (one candidate, `MAX_ATTEMPTS` 3, refused while one runs, parked with
`fleet:declined` after - #5 launched seven times because the dedupe was a comment that
failed six times); a repeat halt appends to its issue and does not page. Live check:
the launcher answered `409 parked after 7 attempts` for #5. Still by design: halted
Jobs show Complete in Kubernetes (stage.sh exits 0 so publish can report).

## Why no run had ever shipped code, found by running it

Four causes, each invisible until the one before it was fixed. All found from
the halt bundles, which is what the bundles are for.

| # | Cause | Seen as | Fix |
| -- | -- | -- | -- |
| 1 | dsh `maxTokens: 4096` consumed entirely by ornith15's hidden reasoning | step returns empty content, finish `max-tokens`, dsh exits 1 without a word | `maxTokens: 16384` (7416896) - necessary, not sufficient |
| 2 | clone runs as uid 1000 (fleet-scripts), implement as uid 1001 (agent-coder), no pod securityContext | `index.lock: Permission denied`; mission-080839 wrote its whole diff into the report instead of committing | pod `runAsUser/fsGroup 1001` (390a40d) |
| 3 | 1500 s stage timeout, and a prompt that asked the model to retype the full diff into the report | mission-083236 committed, then timed out mid-report | implement gets 3600 s; report asks for `git diff --stat` (7cbc5c1) |
| 4 | dsh's deepseek provider sends `thinking:{type:disabled}`; vLLM ignores it for a Qwen-style template | mission-090553 step 9: 16384 output tokens in 228 s, empty | pi-ai provider, `thinkingFormat: qwen-chat-template` -> `chat_template_kwargs.enable_thinking=false` (91b9912). Verified on the spark: reasoning null, 4 tokens for "17*23" |

Cause 2 through 4 were only readable because the halt bundle now carries the
dsh transcript tail (decoded per zstd frame with Node, 96bd97a and 1caf39a;
agent-coder has no zstd binary and Node's decoder stops after the first frame).

Local implement run under all four fixes: 119 steps, largest step 3674 output
tokens, commit `d38c3a4` plus the report in 29 minutes. Before: every run, empty.

First shipped run, in the cluster: `mission-20260904-095932` on new_localai#5 opened
[PR #10](https://github.com/ctkadvisors/new_localai/pull/10) at 10:19Z (implement 1012 s,
test 178 s, +372/-23 in `collect.py` and a new `tests/test_collect.py`), authored by
`app/example-fleet`, and the reviewer picked it up from the webhook. The whole chain -
label `mission` from the console, triage, mission Job, PR, review - ran without a hand on it.

Then the rest of the loop, on that PR:

| Step | When (UTC) | What |
| -- | -- | -- |
| Reviewer, first pass | 10:20 | "unparseable review", escalated. A reviewer defect (the same prompt parsed at 90 a minute later); fixed so it retries once and skips the round (`415ef21`) |
| CI | 10:33 | new `fleet-scripts` workflow on the homelab runner **failed**: collect.py ran `os.makedirs('/workspace/p')` at import. The in-pod test stage never saw it because the pod has one. Fixed on the branch (`bf2a1d0`) |
| Reviewer, second pass | 11:08 | confidence 80, comment: the docstring claimed a `mission` filter the code never had. Fixed on the branch (`aff53e0`) |
| Reviewer, third pass | 11:20 | confidence 88, tier 1, announced, 15-minute window (decision 5) |
| Merge | 11:40:03 | merged by `app/example-fleet`, no veto |

Two human touches on the branch, both fixes the loop itself surfaced. The merge
does not rebuild the fleet-scripts image; 20260904t was tagged by hand. That is
the next gap: an image build on merge, so a merged fleet PR is live without a
person. Reviewer verdicts are not repeatable (new_localai#6). Both were found by running the loop, which is the point of the ledger.
