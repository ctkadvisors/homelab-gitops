# Standalone Self-Directed Agent Fleet Implementation Plan

**Goal:** Deterministic authority, one untrusted local cognitive worker, and protected
external oracles; normal work requires no human approval or maintained backlog.
**Architecture:** Freeze mutation first. Install isolation/recovery, import evidence,
connect a generous private laboratory, then prove unattended growth before expansion.
**Stack:** Reuse verified Python/PostgreSQL, Kubernetes, GitHub, artifact storage, and
local inference components; pin dependencies/images during bootstrap.
**Design:** [Standalone fleet specification](../specs/2026-09-20-standalone-self-directed-agent-fleet-design.md)

## Execution contract and repository map

Executing this plan changes runtime infrastructure; this document establishes no claim
that deployment is complete. Execute tasks in order and retain machine-readable gate
evidence. Failed gates block dependent work, not read-only diagnosis. Humans install or
alter the constitution and emergency-stop only; routine selection, rejection, retry,
parking, publication, promotion, and restoration are autonomous.

The root checkout can lag production. The implementation inspected for this revision
was `new_localai/.claude/worktrees/github-tools` at `aeaff611`; do not deploy from or
overwrite that worktree's user edits. Discover current production SHAs and prepare an
isolated checkout at those SHAs. Read applicable instructions; verify paths below there.

Existing `new_localai` areas to inspect:

- `services/fleet-scripts/scripts/`: `reconcile.py`, `launcher.py`, `hooks.py`,
  `console.py`, `collect.py`, `stage.sh`, `publish.py`, `review.py`, `clone.py`,
  `plan.py`, `triage.py`, `bench.py`, `noderun.py`, `ideate.py`, `scribe.py`,
  `seed_memory.py`, and their actual imports/callers.
- `services/fleet-scripts/fleet/` and `services/fleet-scripts/tests/`.
- `k8s-kustomized/overlays/production/kagent/`: `kustomization.yaml`,
  `fleet-reconcile.yaml`, `fleet-hooks.yaml`, `fleet-console.yaml`, `fleet-stage.yaml`,
  `fleet-node-runner.yaml`, `fleet-ledger.yaml`, `fleet-bench.yaml`, `fleet-auditor.yaml`,
  `fleet-brainstormer.yaml`, `mission.yaml`, and `improve-daily.yaml`.
- `.github/workflows/fleet-scripts.yml`, other workflow callers, and actual GitOps
  application/project sources discovered by tracing production ownership.

Discover the `ctkadvisors/kagent` checkout, deployment entry points, tools, routing,
and tests before changing it; no unverified filenames are prescribed. Task 2 creates
or inspects private `ctkadvisors/fleet-constitution` and records a concrete file map
for policy, service, schema/migrations, sandbox, build, oracles, deployment, harness,
and tests before implementation. Task 5 chooses worker/client filenames only after
inspecting existing package conventions. Discovery is a required deliverable, not
permission to implement against guessed paths.

Initial limits: one active attempt, one pending promotion, one local GPU request,
three attempts per work item per retest cycle, ten percent maximum daily inference
budget for exploration. Product repos, chat/transcript bodies, cloud inference,
arbitrary executable evaluator admission, and irreversible migrations are excluded.

## Task 1 — Inventory and completely freeze mutation

**Outcome:** No legacy route or stale worker can launch mutating work, push, merge,
or deploy; historical/in-flight state and independent recovery are preserved.
**Areas:** Existing areas above; discovered live Jobs/CronJobs, service routes, agent
tools, GitHub installations/tokens/rules, CI/GitOps, node-runner access, and workspaces.

- [ ] Discover production owners/SHAs, launch/merge/deploy callers, mounted credentials,
  active Jobs, persistent workspaces, and credential scopes. Map every capability to
  an enforcing control and verification probe in a retained freeze inventory.
- [ ] Capture recovery targets, then suspend schedules and deny mutating webhook,
  launcher, console retry, and tool routes. Revoke/downscope old credentials and enforce
  branch restrictions. Prevent stale workers acting; stop/drain active mutating Jobs.
- [ ] Snapshot unresolved halts/anomalies/claims/PRs, source positions, deployed
  artifacts, and recovery state. Preserve raw history read-only without body ingestion.
- [ ] Apply the freeze independently and verify live state. Removing a manifest or
  changing `reconcile.main()` does not prove callers, running Jobs, or keys are disabled.

**Acceptance:** Probe every inventoried route using benign inputs and actual old
identities; assert no Job creation, repository update, merge, or deployment. Exercise
direct `reconcile.launch` callers and a stale running worker. Account for every active
operation as stopped, drained, or quarantined. Reports contain no credential values.
**Stop:** Unaccounted mutation capability/live operations block new infrastructure
activation. Do not remove the sole recovery path before capturing an independent one.

## Task 2 — Bootstrap protected authority and isolation

**Outcome:** Structural isolation exists before any new candidate executes.
**Areas:** Protected repository/file map and discovered bootstrap/GitOps/CI owners;
existing workflows, sandbox/RBAC/network/node access, GitHub settings; discovered
`kagent` routing and the actual local inference deployment.

- [ ] Record protected file layout and bootstrap identities. Verify actual fleet App
  installation lists and access, including a positive allowed-repository control;
  an unauthenticated 404 does not prove exclusion.
- [ ] Build the exact writable-file manifest for application code in the two repos.
  Move authority-bearing CI/release/GitOps/security, credentials, sandbox templates,
  and dependency policy outside it. Audit indirect build execution and historical
  product-repository copies as well as current paths.
- [ ] Provision separate publisher, production updater, runtime, evaluator, and bootstrap
  identities. Workers get no GitHub/Kubernetes credentials. Restrict installations,
  protected branches, bypasses, and old keys; bootstrap credentials are absent at runtime.
- [ ] Install fixed-template restricted sandboxes with enforced admission, pinned
  images/dependencies, no host/secret/API access, and scoped egress. Check actual
  changed trees, including path/type changes, against the protected manifest.
- [ ] Enforce a runtime capability envelope for every fleet-modifiable application's
  canary and promoted processes: no product repositories, secrets, chat/transcript
  bodies, cloud inference, or authority modification. Deny application path admission
  when its deployed process cannot meet this envelope.
- [ ] Install the local broker with model-digest allowlist, one request at a time,
  cancellation, bounded queue/context/output/time, and attempt accounting. Benchmark
  intended older models and register a feasible daily CPU/storage/GPU envelope.

**Acceptance:** Live negative tests reject account substitution, secret mounts,
privilege/host access, network escape, cloud endpoints, dependency fetching, product
reads/writes, protected changes, symlink/submodule/traversal tricks, direct pushes,
and worker/legacy merges. Positive controls publish an allowed scratch branch through
the publisher and perform one bounded local request. Verify resource cancellation.
**Stop:** Any escape blocks candidate execution. If older models cannot meet the
protocol, adjust bounded work/prompting; do not substitute cloud inference or hardware.

## Task 3 — Implement transaction, attempt, and effect recovery

**Outcome:** State/effects recover deterministically without model inference.
**Areas:** Protected service, schema/migrations, policy, integration tests from Task 2's
file map; artifact storage discovered through existing stage and Job mounts.

- [ ] Define all versioned event schemas/transitions before API routes. Work:
  proposed/admitted/active/resolved, refused, parked. Attempt:
  leased/executing/submitted/completed or failed/expired/cancelled. Promotion:
  submitted/evaluated/canary_running/canary_passed/promoted, rejected, restoring,
  restored/quarantined. Laboratory items use the sandbox contract, never export rights.
- [ ] Atomically authenticate scope, lock/check aggregate version, validate transition,
  update projection, and append in transactional commit order. Bind idempotency to
  actor/operation/payload; reject ID reuse and unknown schemas before commit.
- [ ] Use non-login migration ownership and restricted runtime append/read permissions.
  Exclude reset tools from the deployed package. Verify database/artifact backup recovery.
- [ ] Implement leases/fencing, verified initial/checkpoint artifacts, revocation on
  expiry, bounded retries, method/transient-fault evidence, parking/retest conditions,
  and blocking scopes. Invariant/restoration recovery outranks retries.
- [ ] Add transactional outbox operation IDs and external reconciliation with bounded
  retry. Rebuild identical projections from committed events after a crash.

**Acceptance:** Real disposable PostgreSQL tests cover duplicate-then-new append,
rolled-back sequence allocation, reversed concurrent commits, payload conflict,
concurrent claims, stale results, invalid events, expiry, missing first-stage output,
exhaustion visibility, and replay equality. Inject crashes before/after every external
effect and acknowledgement; restore backup and reconcile without duplicate mutations.
**Stop:** Divergence, duplicate effects, unfenced results, or writable history block
workers. Database tests must run, never silently skip because a DSN was not supplied.

## Task 4 — Import complete observations and autonomous selection

**Outcome:** Complete evidence drives work without a human backlog.
**Areas:** `scripts/collect.py`, source clients in `fleet/`, tests, protected ingestion/
selection policy, Task 1 inventory, and `scripts/console.py` reporting routes.

- [ ] Discover source pagination/revision semantics. Replace recent-item caps with
  durable cursors, revision-aware IDs, full pagination, unavailable intervals, and
  watermarks. Enforce source-specific protected schemas and enumerated error classes.
- [ ] Reject chat/transcript bodies, arbitrary logs/URLs/files, extra fields, and unsafe
  source paths at the authority API; source credentials cannot read excluded channels.
- [ ] Import unresolved history with exact imported/duplicate/rejected-with-reason
  accounting. Preserve uncertainty; exhausted attempts do not close defects.
- [ ] Implement deduplication, deterministic priority/gap normalization, scope/budget
  checks, and retest triggers. Implementation admission requires registry-backed oracle,
  direction/scale, target, samples, and terminal predicate. Idle capacity may admit a
  bounded laboratory session under its protected resource contract.
- [ ] Serve canonical read-only reports with cutoff and source completeness. Unavailable
  sources must not report zero problems or authorize dependent promotion.

**Acceptance:** More items than old limits, changed revisions, delayed events, duplicate
pages, restarts, and unavailable sources reconcile exactly. Every imported row has one
disposition. A 24-hour shadow interval matches independent watermarks/counts at a fixed
cutoff and selects the same action after restart; shadow selection issues no leases.
**Stop:** Lost records, accepted secret-bearing payloads, or incomplete cutoff evidence
block execution. Repair and restart shadow accounting before connecting the worker.

## Task 5 — Connect one cognitive worker, laboratory, and protected oracles

**Outcome:** Generous private experimentation produces bounded proposals, never authority.
**Areas:** `scripts/stage.sh`, `plan.py`, `triage.py`, `publish.py`, `clone.py`, imports/
tests; discovered `kagent` tool/model adapters; protected API, oracle registry, artifact
storage, publisher, resource policy, and fixed sandbox templates.

- [ ] Choose concrete client/worker/test files after caller discovery. Reuse safe stage
  handling, replacing conversational repair and launch logic with one generic worker
  using bounded invocation modes and strict typed artifacts.
- [ ] Issue an authority-created laboratory sandbox with sanitized snapshots, scratch
  storage, approved tools, and accounted quotas. Allow local forks, temporary tools,
  simulations, adversarial tests, preserved discoveries, and abandoned approaches
  without a production oracle. Deny all external effects and recursive quota expansion.
- [ ] Retain untrusted private artifacts by digest within a storage/retention quota;
  distinguish them from validated knowledge. Reconstruct bounded call context from
  canonical state plus explicitly untrusted artifacts. Invalid output fails/abstains.
- [ ] Export patches only through the trusted publisher after contract/scope admission;
  remove direct PR credentials. Verify checkpoint upload before acknowledgement. A
  proposed deployed-worker improvement passes the same gates as any other change.
- [ ] Install protected contracts with independent expected-output methods, thresholds,
  scoring/sample rules, limits, and allowed generators. Candidate execution is separate
  from the fixture/credential-owning evaluator process.
- [ ] Admit generated cases only when an existing oracle independently derives expected
  results. Novel semantic evaluator programs remain advisory. Build no executable-test
  admission subsystem or lineage-based authority. Confirm typed knowledge only through
  later fresh protected evaluation; contradiction contests, expiry triggers retest.

**Acceptance:** Actual older local models complete bounded protocol trials. Malformed
output, timeout, duplicate completion, bogus oracle IDs, prose claims, and quota exhaustion
fail deterministically. A worker explores competing approaches, discards a dead end,
and proposes a fresh generated case without hints. Its expected outcome is independently
derived and creates actionable work. A colluding test/change pair cannot gain authority;
candidate code cannot see protected fixtures, forge scores, or escape via scratch tools.
**Stop:** Any candidate-controlled authority or fixture exposure blocks evaluation.
Inability to discover admissible work is a measured capability limit, not justification
to weaken admission or secretly add human tasks.

## Task 6 — Bind evaluation, canary, publication, and restoration

**Outcome:** Valid changes promote and regressions restore without approval.
**Areas:** Protected builder/publisher/oracle/deployment/outbox modules and tests;
`scripts/publish.py`/`review.py` callers and discovered GitOps ownership.

- [ ] Bind results to base/tree/image/dependency/configuration digests, oracle versions,
  raw evidence, and preregistered sampling/metric rules. Changed base/artifacts invalidate
  evidence. Reject missing, NaN, zero-coverage, or candidate-forged results.
- [ ] Test a known-good immutable restoration bundle, then deploy isolated canary
  artifacts without advancing the production branch. Candidate build has no credentials.
- [ ] Observe independent probes for the contract window; promote only after all gates
  pass. Serialize production changes and reconcile partial effects. Restore deployed
  artifacts first on regression, then reconcile Git; record both convergence states.
- [ ] Enforce a monotonic generation per deployment scope at the mutation boundary,
  including delayed effect completion. Restoration/quarantine advances the generation
  and invalidates older pending operations; reject stale generations.
- [ ] Independently verify effective runtime permissions against the capability envelope
  after every canary/production activation; violations trigger restoration/quarantine.
- [ ] Enforce restoration deadlines/bounded retries; quarantine and revoke failed scopes.
  Do not keep exploring against a broken deployment or admit irreversible migrations.

**Acceptance:** A valid challenger promotes; a plausible incorrect challenger fails.
Changed bases cannot reuse evidence. Inject canary regression, failed Git update, and
crashes at deployment boundaries; prove restoration deadline, external reconciliation,
and persistent quarantine on unavailable restoration. Test post-promotion regression.
Delay an original deployment until after restoration and prove it cannot change restored
state. Probe forbidden access from activated canary and promoted application processes.
**Stop:** Missing restoration, scope leakage, or irreversible effects block production
promotion. Keep execution constrained to already proved contracts.

## Task 7 — Delete obsolete machinery and prove the sole execution path

**Outcome:** Only the protected authority can cause production mutation.
**Areas:** Listed scripts/manifests; `fleet/ideas.py`, `fleet/memory.py`, and
`fleet/experience.py` if present; discovered imports/tools/schedules/keys/RBAC/CI/tests.

- [ ] Delete idle/ideation/dream/brainstorm schedules, reinforcement memory, old bench/
  merge gates, veto timers, direct retry/launch paths, and unused stage agents. Delete
  old hooks or keep only schema-bound observation adapters.
- [ ] Remove obsolete identities, secrets, node access, Jobs, ConfigMaps, and policies
  after identifying replacement/read-only archival roles. No compatibility wrapper may
  retain mutation authority. Preserve necessary raw historical evidence read-only.
- [ ] Remove callers/tests; make console canonical/read-only. Confirm live pruning,
  image/workflow updates, and credential revocation, not just deleted source files.

**Acceptance:** Repository search/rendered manifests expose no executable retired path.
All Task 1 negative probes still fail. Run the full fleet suite, shell syntax checks,
manifest rendering, and server-side validation through the discovered toolchain.
**Stop:** Any surviving bypass blocks the acceptance week. Do not delete evidence or
the independent restoration bundle to make checks pass.

## Task 8 — Prove one unattended week and enable the permitted catalog

**Outcome:** An independently observed mechanical verdict establishes autonomous growth.
**Areas:** Protected harness, frozen acceptance configuration, challenge generators,
reporting, and bootstrap deployment policy.

- [ ] Freeze measured baselines, three families, hidden seeds, sample counts, meaningful
  improvement/non-regression thresholds, daily GPU budget, freshness limits, canary
  windows, restoration deadlines, and attack/fault schedule. Missing numeric limits
  or an infeasible one-GPU workload prevent starting the run.
- [ ] Give the harness independent source/GitHub/deployment reads and a separate protected
  evidence record. It supplies challenges/faults and checks effects; worker claims and
  internally consistent event counts alone cannot establish success.
- [ ] Run seven consecutive days on intended local models without a human hint, patch,
  merge, evaluator change, or operational decision. Require at least 20 completed scored
  trials across three families, including an unseen repair family beyond seeded ledger/
  resumability tasks. Require an autonomous improvement promotion reproduced on fresh
  trials and rejection of a plausible incorrect challenger.
- [ ] Require a worker-generated new challenge family or measurement case under an
  existing contract, actionable measured work from it, private competing approaches
  and abandonment of a failed approach, automatic canary restoration, and an exhausted
  unresolved item alongside continued unrelated safe work.
- [ ] Inject authority restart, database interruption, GPU outage, duplicate delivery,
  stale completion, evaluator crash, and interrupted publication/deployment. Attempt
  product/protected-path writes, credential mounts, cloud inference, fixture exfiltration,
  transcript ingestion, and colluding evaluator authorization. Expected refusals pass.
- [ ] Reconcile independent evidence and ledger at one committed cutoff with complete
  watermarks. PASS requires every workload/quality/recovery/authority predicate and
  automatically enables the broader already-authorized catalog, never new permissions.

**Acceptance:** Report PASS/FAIL with evidence IDs and exact predicates; identical
evidence produces the same verdict. Demonstrate that idle, disconnected, stale-source,
and self-reported-success runs fail. Every minimum-work and fault/attack condition is
mandatory. Thresholds cannot change during the window.
**Stop/kill:** Successful forbidden access, secret/fixture exposure, unauthorized mutation,
ledger corruption, or missed restoration deadline immediately FAILS, revokes affected
capabilities, restores if possible, and quarantines. Stop globally if containment is
unproven. Human intervention invalidates the window. Other quality/completeness failures
leave the fleet constrained. Resolve failures before a fresh window; do not reset history
or implicitly restore emergency-revoked authority.

## Completion and maintenance boundary

Completion requires all eight gates, a live sole-authority check, and independently
observed PASS. Normal operation stays autonomous within installed contracts. Explicit
constitutional maintenance is never a generated approval flow. If a desired capability
cannot be independently measured by an existing contract, preserve the proposal as
advisory. Do not recreate a human backlog or let a fleet-written evaluator define the
permission it needs. Private experimentation may continue within its resource envelope.
