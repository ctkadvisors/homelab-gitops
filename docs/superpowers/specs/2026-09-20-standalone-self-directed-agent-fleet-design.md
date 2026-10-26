# Standalone Self-Directed Agent Fleet

**Status:** Revised design; runtime implementation and acceptance remain unproven.
**Date:** 2026-09-20
**Execution:** [Implementation plan](../plans/2026-09-20-standalone-self-directed-agent-fleet.md)

## Purpose, autonomy, and limits

Build a fleet that independently discovers problems, experiments, changes permitted
code, measures outcomes, and retains predictive evidence. Normal selection, rejection,
retry, parking, publication, promotion, and restoration require no human approval.
Activity, merge counts, model confidence, and reviewer votes are not growth.

The cognitive design asks: **if it had its own unbounded sandbox, what would it do?**
It should inspect its environment, form hypotheses, simulate, fork competing approaches,
build temporary tools, attack its own assumptions, preserve discoveries, abandon dead
ends, and improve its methods. Give it a generous disposable private laboratory, not
a human-maintained backlog. Freedom inside the laboratory grants no external authority.

One GPU serves local models of roughly year-old capability. Finite time, compute, and
storage still apply: broad experimentation is allowed inside a supervisor-issued
resource envelope. No cloud inference, transcript ingestion, or product-repository
access is permitted. Weak planning, malformed output, and correlated mistakes are normal.

Humans establish or explicitly alter the constitution and may emergency-stop the
system. Bootstrap includes trustworthy contracts, permissions, recovery targets, and
acceptance criteria. The fleet cannot change these. Missing authority parks a proposal;
it does not create a routine approval queue. An emergency stop revokes execution and
deployment capabilities; resumption is an explicit constitutional operation.

Discovery is open-ended within protected measurement contracts. Arbitrary new semantic
correctness standards cannot become authoritative merely because the fleet wrote and
calibrated an evaluator. Such proposals remain advisory until a constitutional extension
establishes an independent oracle. Absolute detection of every secret in arbitrary text
is impossible; exclude those channels and bootstrap-review the permitted input boundary.

## Three boundaries

| Boundary | Responsibility | Authority limit |
|---|---|---|
| Immutable deterministic authority | Admission, identities, budgets, ledger, sandbox creation, publication, deployment, recovery | No model judgment grants permission |
| One untrusted cognitive worker | Private experiments, tools, hypotheses, patches, counterexamples, predictions | No credentials, merging, deployment, or policy changes |
| Protected external oracles | Independent expected outcomes, measurements, challenge generation, health probes | Candidate claims/tests cannot authorize promotion |

Use one authority service, PostgreSQL, one generic worker, and one local inference
broker. Run the outbox reconciler within the authority service. Oracle adapters and
the independent acceptance harness are protected programs, not reasoning agents.
Reuse artifact storage and local inference only after verifying their isolation.

The protected repository is `ctkadvisors/fleet-constitution`. Its code, configuration,
build/release pipeline, GitOps source, admission policy, fixtures, and recovery bundles
are outside fleet read/write authority. The runtime identity cannot alter its own
deployment or constitution. Bootstrap deployer credentials are unavailable at runtime.

## Enforced permissions and input boundary

- Only `ctkadvisors/new_localai` and `ctkadvisors/kagent` are potentially writable.
  A protected manifest enumerates exact writable file paths; everything else is denied.
  Bootstrap discovery determines the manifest, not worker requests or inferred intent.
- Move credential wiring, security/RBAC/network policy, CI/release authority, GitOps
  configuration, and sandbox/deployment templates outside writable paths. Source code
  cannot change the mechanism that grants its own permissions.
- Check the actual Git tree at publication and deployment. Reject traversal, symlinks,
  submodules, unexpected renames, and path/type changes outside the approved contract.
  Build untrusted code without secrets/network using pinned approved dependencies.
  Candidate-controlled build hooks cannot run in a credential-owning process.
- A trusted publisher accepts patch artifacts. Separate protected identities publish
  branches and update protected production branches. Workers receive no App keys or
  GitHub tokens. Branch rules deny old fleet identities direct push/merge authority.
  Product repositories are excluded from installations, broker APIs, mounts, and caches,
  including historical copies. Required metadata uses narrow protected adapters.
- Only the authority creates fixed-template sandboxes. Admission policy enforces image
  digest, service account, limits, restricted pod security, mounts, and egress. Deny
  host access, privilege, account substitution, Kubernetes access, and secret mounts.
  Namespace RBAC alone is insufficient.
- Every fleet-modifiable application, including canary and promoted processes, remains
  inside an enforced runtime capability envelope excluding product repositories, secrets,
  chat/transcript bodies, cloud inference, and authority modification. Deny application
  path admission when its deployed process cannot meet this envelope; independently
  verify effective permissions after each activation.
- Workers reach only scoped authority endpoints and the local inference broker.
  The broker admits one GPU request at a time, pins installed local model digests,
  and bounds context, output, wall-time, queue depth, and attempt expenditure.
  Cancellation releases capacity; no cloud fallback exists.
- Observations use protected source-specific schemas and enumerated error classes.
  Exclude chat/transcript bodies, arbitrary logs, exception text, and arbitrary URLs/files.
  Bootstrap-reviewed code snapshots are separate permitted inputs; exclude secret-bearing
  paths/history. Scanner findings quarantine input; scanner silence does not establish
  that arbitrary text is safe.
- Evaluators retain expected answers/fixtures in a separate protected process. Candidate
  sandboxes receive controlled task inputs only, never fixture stores, evaluator tokens,
  acceptance seeds, or unrestricted outputs. Release bounded result schemas; protect raw
  evidence. Treat candidate-generated output as untrusted data, never executable control.

## Private laboratory

An admitted laboratory session receives sanitized code/evidence snapshots, a scratch
filesystem, approved tool/runtime images, and finite CPU/storage/GPU/time quotas. It may
fork local approaches, write temporary programs/tests, simulate failures, and discard
work without requesting promotion. It has no route to live repositories, production
services, secrets, cloud models, or deployment authority. Network-isolated scratch
experiments need not satisfy a production oracle merely to run.

One worker can switch bounded invocation modes and run many local experiments; no
agent society or multi-agent voting system is required. Its scratch tools and methods
may evolve freely within the sandbox. Changes to the deployed worker still require
the same protected evaluation and promotion as other real-world changes.

The authority accounts for resources and session lifecycle, not every private thought.
Persist content-addressed experimental artifacts and typed summaries within a storage
quota. Mark them untrusted and non-authoritative. Garbage-collect disposable state under
a fixed retention policy; durable validated knowledge is a separate evidence-derived view.
The model can choose what to investigate; it cannot expand quotas by recursively creating
sessions, renaming fingerprints, or asserting urgency.

Exporting a proposed code change, authoritative knowledge claim, or new challenge case
crosses the boundary: require a registered contract, bounded scope, prediction, and
independent evaluation. Interesting experiments without such a contract remain advisory.

## Canonical state and external effects

Version all event schemas. Authenticate the actor and attempt scope, lock the aggregate,
check expected version/transition, then append an event and update derived state in one
transaction. Allocate commit order with a transactional counter; database sequences are
not gapless commit ordering. Repeated command IDs return the original result only if
actor, operation, and payload match. Reject invalid events before commit.

Use a non-login migration owner and a restricted runtime database role. No runtime
update/delete/truncate of history is permitted. Back up ledger/artifacts and verify
restoration/replay equivalence. Reports name a committed cutoff and source watermarks;
unavailable sources mean incomplete, never an empty healthy state.

External operations use a transactional outbox, deterministic operation IDs, and
reconciliation against Kubernetes/GitHub/deployment state. Crashes after an external
effect but before acknowledgement recover the result without duplication. Observations
use source revision identities, durable cursors, pagination, and unavailable intervals.
Each deployment scope has a monotonic generation enforced at the mutation boundary,
including delayed effect completion. Restoration/quarantine advances it and invalidates
older pending operations; stale generations cannot reactivate a rejected candidate.

### Work and attempts

Work: `proposed -> admitted -> active -> resolved`, with `proposed -> refused` and
`active -> parked -> active`. Resolution requires the registered terminal predicate.
Exhausting attempts never resolves a defect. Parked defects retain evidence, blocking
scope, and a deterministic retest trigger; unrelated safe work can continue.

An admitted implementation item pins repository, exact paths, evidence, oracle version,
metric direction/scale, baseline/target, sample rule, stopping rule, and total budget.
References must resolve in the protected registry. A laboratory item instead references
the protected sandbox/resource contract; that contract grants no export/promotion rights.

Attempt: `leased -> executing -> submitted -> completed`; any nonterminal attempt can
become `failed`, `expired`, or `cancelled`. An attempt has an ID, fencing generation,
expiry, base SHA when applicable, budget reservation, and verified initial checkpoint.
Only its current generation may checkpoint/finish. Expiry revokes execution; a replacement
attempt resumes the same item. Checkpoints are immutable, verified before acknowledgement,
and unpacked only in sandboxes.

Timeouts identify their layer; unknown layers never increase budgets. Allow three
attempts per work item per retest cycle. Retries record a bounded method change or
transient-fault recovery; exhaustion parks the item until new evidence or its retest
condition. Duplicate speculative items cannot reset this budget.

Priority: invariant/restoration, regression, unfinished retryable work, recurring failure,
measured capability gap, then laboratory exploration. Safety recovery preempts retries.
Initially permit one active attempt, one pending promotion, and one GPU request.
Exploration uses at most ten percent of registered daily inference budget without
banking unused quota; cognitive freedom within that allocation is intentionally broad.

### Evaluation and promotion

Promotion: `submitted -> evaluated -> canary_running -> canary_passed -> promoted`.
Evaluation failure is `rejected`; canary/post-promotion regression enters
`restoring -> restored | quarantined`.

Evidence pins base SHA, resulting tree, image digest, dependencies, configuration,
oracle versions, raw result digests, sample rule, and preregistered prediction. Changed
base/artifacts invalidate eligibility. Candidate code never runs with release credentials.
Require complete invariants, held-out non-regression, declared meaningful improvement
(or explicitly registered non-regression objective), valid cost bounds, no blocking
defect/conflict, and a tested restoration bundle. Missing values, NaN, unregistered
objectives, zero coverage, and insufficient samples fail closed.

Deploy isolated canary artifacts before production branch update and broad activation.
Observe independent probes for the registered window. On failure, restore the last
known-good deployed bundle immediately, then reconcile Git; record both convergences.
A missed restoration deadline quarantines the scope, revokes execution, and stops its
promotions. Bounded backoff must not become an infinite rollback loop. Irreversible
migrations are outside initial authority.

## Self-direction, knowledge, and oracle growth

Typed failures, regressions, challenge results, and protected capability gaps generate
deduplicated work. Targets and normalized gaps use registered contracts. Issues and
worker proposals are signals only; they cannot choose priority, authority, or thresholds.
When higher-priority work is absent, the worker chooses laboratory experiments from
permitted code and evidence. No human backlog or obligation to stay busy is required.

Each model call reconstructs bounded context from canonical records or its explicitly
untrusted scratch artifacts and emits a validated artifact. Malformed output is failure
or abstention. Confidence, role separation, lineage, votes, and self-written tests never
establish independence or permission.

The protected oracle registry defines expected-output methods, allowed generators and
transformations, scoring, thresholds, limits, and scope. Generated cases gain authority
only when an existing protected oracle independently derives their expected results.
Generated workloads may exercise existing measurement adapters, never redefine them.
Arbitrary fleet-authored evaluator executables cannot gain authority through calibration,
delayed use, or lineage exclusion.

For example, approved generators can create fresh interruption schedules for a protected
resumability contract that independently measures equivalence/recovery. The fleet cannot
write a usefulness scorer and use its own score as permission. New semantic standards
remain advisory or require explicit constitutional extension.

Knowledge is a typed predicate with scope, prediction, evidence, sample counts, and
expiry. One protected evaluation establishes it; a later fresh evaluation confirms its
preregistered prediction. Contradictions contest it; expiry schedules retest. Free-form
summaries and private discoveries remain explanatory, never authoritative.

## Migration and deletion

Freeze all mutation entry points/credentials first: schedules, webhooks, launchers,
console routes, tools, CI/GitOps, node access, and active attempts. Stop/drain active
jobs and prove stale workers cannot act. Snapshot unresolved work and recovery state.
Install isolation, transaction/recovery core, complete source adapters, one worker,
and protected oracles in order. Reconcile history before execution; enable constrained
repair only after isolation/restoration tests pass.

Delete idle/ideation/dream loops, reinforcement memory, model merge gates, veto timers,
direct launch/retry paths, duplicate evaluators, and obsolete identities. Retain needed
collectors only after replacing bounded scans with cursors. Preserve raw historical
evidence read-only. Reporting is canonical/read-only. Build neither an arbitrary
evaluator-admission subsystem nor a society of separately deployed reasoning agents.

## Falsifiable unattended acceptance

Prerequisites: boundary attacks/restoration drills pass; imports reconcile; sources are
complete; protected baselines/thresholds are recorded; actual older models fit the
one-GPU envelope. Freeze task families, hidden seeds, sample sizes, improvement rules,
daily compute budget, freshness limits, canary windows, and recovery deadlines before
the week. Bootstrap measurements determine values; missing values prevent the run.

A protected harness independently delivers challenges/faults, queries source/GitHub/
deployment state, and records evidence separately from the authority ledger. It uses
the available hardware budget. Require seven consecutive days without a human hint,
patch, merge, evaluator change, or operational decision, and all of these conditions:

- At least 20 completed scored trials across three protected families, including an
  unseen repair family beyond seeded resumability/ledger maintenance exercises.
- An autonomous improvement promotion on fresh held-out trials, independently reproduced
  after promotion, and rejection of a plausible incorrect challenger.
- A worker-generated new challenge family or measurement case admitted under an existing
  contract, producing actionable work and measured results. Private exploration must
  demonstrate competing approaches and abandonment of a failed approach without hints.
- A canary regression restored within its deadline; an exhausted item remaining unresolved
  while unrelated safe work continues.
- Recovery from authority restart, database interruption, GPU outage, duplicate delivery,
  stale completion, evaluator crash, and interrupted publication/deployment.
- A delayed original deployment completing after restoration cannot change the restored
  state; canary and promoted processes retain the runtime capability envelope.
- Refusal of product/protected-path writes, credential mounting, cloud inference,
  fixture exfiltration, transcript ingestion, and colluding evaluator proposals.

Expected attack refusals do not reset the window. Successful forbidden access, secret/
fixture exposure, unauthorized mutation, ledger corruption, or a missed restoration
deadline immediately FAILS and kills affected execution: revoke capabilities, restore
if possible, quarantine, preserve evidence. Stop the whole fleet if containment is
unproven. Human intervention invalidates the run. Incomplete sources, missed workload/
quality thresholds, or unreconciled effects fail too. Idle/disconnected fleets cannot pass.

PASS requires independent evidence for every predicate and exact reconciliation at a
committed cutoff with complete watermarks. It automatically enables the broader already
authorized catalog, never expands the constitution. Failed runs remain constrained until
recorded failures are resolved. A fresh window cannot erase history or implicitly restore
emergency-revoked authority.
