# Fleet memory: the mentor's foundation (2026-09-08)

Chris: "shouldn't our memory fit in here? you do ALL you can to get it to be
self reliant. act as the parent/mentor, lay the foundation for it to become a
mini-you."

## What was wrong

The fleet recorded everything (ledger, forum, brain) and learned nothing: a
halt produced a bundle, an objection a kv row, a rollback an outcome, and the
next run started as a stranger. On 2026-09-08 the implementer used yarn
`resolutions` under npm, could not install because its own prompt forbade it,
and the reviewer called a red PR correct — each a lesson nobody carried
forward.

## The shape (borrowed from Claude's own memory)

One fact per row, typed, scoped, weighted, recalled by relevance:

| kind | what | recalled |
| -- | -- | -- |
| feedback | a rule from Chris (or the mentor) about how to work | always, first |
| lesson | what a halt, an objection or a rollback taught | by word overlap with the task, weight, recency |
| fact | something true about a repo or the environment | same |

Table `lesson` in the ledger (`fleet/ledger.py`); `fleet/memory.py` is the
API: `remember(kind, text, repo, ref, source)` (same text twice = weight+1),
`recall(repo, context)` (a ranked text block), `distill_halt()`,
`lessons_in()`.

## Writers (the fleet teaches itself)

- `publish`: every real halt → one line (stage, reason, what the run said would
  unblock it); every `LESSON:` line the implementer wrote in its report.
- `review.remember_objection`: an objection becomes a lesson for the repo.
- `reconcile.observe_outcomes`: a revert on main becomes a lesson.
- The forum: anything Chris posts (`ledger.post` author `chris`) is feedback,
  scoped to the repo when the thread is about a PR or issue.
- `scripts/seed_memory.py`: the mentor's hand-down — Chris's rules and what
  this week's runs, reviews and nights of reading logs taught. Idempotent.

## Readers (nothing acts as a stranger)

- `stage.sh`: every stage prompt carries `WHAT WE HAVE LEARNED`, ranked
  against the brief, and asks for `LESSON:` lines back.
- `review.judge`: the reviewer reads the same block before judging.
- `launcher.fleet()` serves `fleet.memory`; the concierge prompt reads it
  before answering how the fleet works, and turns Chris's instructions into
  forum posts so they become memory rather than agreement.

## Rails

- Recall is a query, never a model call; it costs nothing and cannot lie.
- Memory never takes a run down: a dead ledger is a log line and an empty block.
- A row can be retired (`retire(key)`); the brain mirrors, the ledger owns.

## What comes next (not in this change)

- The concierge's instruction ledger (received → acknowledged → done) so a
  backend failure never loses Chris's words.
- Thinking control for chat agents in kagent (`enable_thinking=false`).
- A stop rule after consecutive empty improve runs; a work queue Chris feeds.
