# Adversarial review of the idle-improvement design v1

Reviewer: OpenAI Codex, model gpt-5.6-sol, run 2026-09-04 by Chris's request ("use codex 5.6-sol to adversarially review it"). Verbatim output; the design it reviewed is 2026-09-04-idle-improvement-design-v1.md.

---

# Adversarial review: idle-triggered self-improvement v1

## Overall verdict

Do not build v1 as written.

The design automates a pipeline that is already failing opaquely, gives it an unreliable definition of idleness, makes its work non-preemptible, and allows the same model family to propose, implement, test, and indirectly approve changes. That is not yet a learning system. It is a failure-amplification system with a prose ledger.

The first useful version should be a durable, singleton eligibility controller that runs the existing pipeline in **proposal-only mode**, with strict deadlines and observable outcomes. Dreaming and self-generated tooling should remain quarantined proposal generators until the basic loop has demonstrated that it can finish runs, avoid duplication, and correlate changes with actual improvements.

## 1. Failure modes

Scores use likelihood and severity from 1–5. Severity 5 means plausible repository, cluster, security, or control-plane damage.

| Rank | Failure mode | Likelihood | Severity | Score | Concrete consequence |
|---:|---|---:|---:|---:|---|
| 1 | Automating a pipeline already known to fail silently | 5 | 4 | 20 | Idle periods generate repeated seven-minute `dsh session failed` runs with no diagnostic artifact. Because no PR is opened, the open-PR guard does not suppress retries. |
| 2 | Duplicate launches from an in-process sampler | 4 | 5 | 20 | Multiple `fleet-hooks` replicas, a rollout, or a restart can each observe idle and launch a run. The design has no durable lease, compare-and-create operation, or idempotency key. |
| 3 | Telemetry failure is mistaken for idleness | 4 | 5 | 20 | A timeout, missing metric, partial K8s list, brain lag, or API error becomes zero work unless every unknown explicitly fails closed. The system starts background work precisely when its view of the fleet is degraded. |
| 4 | Prompt injection through operational evidence | 4 | 5 | 20 | GitHub issues, PR comments, logs, alerts, and brain episodes are untrusted input. An error message can instruct the investigator or implementer to alter files, leak context, weaken tests, or create a malicious tool. |
| 5 | Non-preemptible work interferes with recovery | 4 | 4 | 16 | A hung or long generation keeps consuming minis, storage, network, Kata capacity, or API concurrency after user work arrives. “It does not use the Spark” is not equivalent to “it cannot harm foreground work.” |
| 6 | Correlated self-approval | 3 | 5 | 15 | One local model family interprets evidence, selects a fix, writes it, and tests it. A second prompt is not an independent reviewer. Shared misconceptions can pass every stage and reach auto-merge. |
| 7 | A small PR causes a large operational blast radius | 3 | 5 | 15 | The `<400 lines` and path denylist are weak proxies. A one-line image tag, workflow reference, admission rule, dependency range, shell command, or deployment value can compromise or disable the cluster. |
| 8 | Memory poisoning compounds across runs | 3 | 5 | 15 | Incorrect conclusions become graph facts, are retrieved by later runs, and are then cited as evidence for more changes. The known 20% invalidation noise makes deletion of correct context especially likely. |
| 9 | The daily cron and idle trigger race | 3 | 4 | 12 | The 05:15 job and idle watcher use separate triggering paths. Without one shared atomic lease, both can pass their preflight checks and launch. |
| 10 | A stale guard permanently wedges the system | 4 | 3 | 12 | An abandoned `agent/dsh-daily-*` PR blocks all future work. Conversely, a run using another branch prefix bypasses the guard. Branch naming is not scheduler state. |
| 11 | Sequential brain ingestion makes activity signals stale | 4 | 3 | 12 | With roughly two minutes per episode and possible backlog, “last Telegram episode” is not the last Telegram interaction. Both false-idle and never-idle states are possible. |
| 12 | “Merged” is counted as success | 4 | 3 | 12 | The loop optimizes for passing review rather than reducing failures. Harm may appear only after deployment, the next workload, or a later rollback. |
| 13 | Candidate repetition is only cosmetically suppressed | 4 | 3 | 12 | Reading ten prose episodes does not reliably identify semantically identical fixes, renamed symptoms, reverted changes, or failures older than ten runs. |
| 14 | Warm or stuck infrastructure prevents work forever | 4 | 2 | 8 | A warm ARC pod, stale AgentTask status, leaked Job, noisy GPU metric, or frequent harmless push continually resets the ten-minute counter. |
| 15 | The watcher degrades the webhook service | 2 | 4 | 8 | K8s enumeration, metrics calls, and brain queries inside `fleet-hooks` increase latency and failure coupling for the externally exposed webhook path. |

Additional ways this damages the environment:

- A generated change can pass unit tests but trigger a GitOps rollout that fails only on the live cluster.
- Investigation can overload Neo4j or the sequential ingestion queue even when inference capacity is idle.
- Repeated Kata jobs and image pulls can exhaust disk, inode, CNI, registry, or pod-start capacity without high GPU utilization.
- Failed runs can accumulate branches, Jobs, pods, logs, graph episodes, and review notifications.
- Publish-only credentials do not make earlier stages safe. Earlier stages can prepare malicious artifacts or instructions that the privileged publish stage executes.
- A compromised or merely confused tool generator can create an MCP provider that expands future authority far beyond the original change.

Required control fixes:

1. Put scheduling state in a durable store.
2. Acquire a cluster-wide lease atomically before launching.
3. Give every intent a stable run ID and idempotency key.
4. Treat missing or stale telemetry as **not eligible**.
5. Revalidate eligibility before every expensive or mutating stage.
6. Give every run and stage a deadline, cancellation path, and complete diagnostic bundle.
7. Keep scheduler and policy enforcement outside repositories the agent can modify.
8. Never use model confidence, line count, or prompt diversity as a substitute for an independent trust boundary.

## 2. Idle definition

The current definition confuses four different things:

- absence of observed work;
- availability of the intended resource;
- permission to start speculative work;
- safety to continue once foreground work returns.

“Idle” should not be a single fleet-wide boolean. It should be **admission eligibility for one specific workload**.

### Important false positives

- `requests_running == 0` ignores queued requests, requests between samples, model loading, and work about to be admitted.
- A dropped GitHub webhook looks exactly like no GitHub activity.
- Brain timestamps lag actual Telegram activity.
- K8s list permissions may omit another namespace.
- A CI run can be queued before a runner pod exists.
- GPU utilization can be low while memory pressure, model loading, storage, or network capacity is constrained.
- Restarting `fleet-hooks` can erase the ten-minute observation history and cooldown.
- The system may be operationally unsafe for changes even though compute is idle—for example, during an outage or immediately after a deployment.

### Important false negatives

- A warm but inactive ARC runner blocks forever.
- A completed AgentTask with stale status appears in flight.
- Background embedding or health-check activity keeps GPU utilization above 10%.
- Frequent unrelated pushes reset the timer.
- The Spark’s state blocks a job that uses only the minis.
- A stuck open PR suppresses unrelated candidates indefinitely.

### Better definition

Define:

> A background run is eligible when its required capacity is healthy and reserved, no higher-priority work is queued or running, all required observations are fresh, safety and resource budgets permit it, and the scheduler atomically owns the singleton lease.

Concretely:

- Observe the **minis’** queue depth, active generation count, memory headroom, and health—not the Spark’s GPU utilization.
- Check foreground queues, not only running requests.
- Require timestamps and freshness limits for every input. Unknown or stale means ineligible.
- Use a Kubernetes `Lease` or an equivalent atomic database record shared by idle and scheduled runs.
- Enforce daily compute, token, wall-clock, disk, and attempted-change budgets.
- Add a quiet period after deployments, alerts, failed CI, and cluster degradation.
- Recheck before `investigate`, `implement`, `test`, and `publish`.
- On foreground demand, stop at the next stage boundary. Hard-cancel before mutation if necessary.
- Expire leases and mark abandoned runs explicitly; never infer state from branch names.
- Replace “never pre-empted” with “checkpointable and deadline-bound.”

A five-minute reconciler is sufficient. It does not need to be a permanently running sampler, and it definitely should not live inside `fleet-hooks`.

## 3. Learning loop

This is currently a ledger somebody hopes the model will read. It is not meaningful learning.

The last ten prose episodes provide short-term reminder context. They do not provide stable identity, causal attribution, policy improvement, calibrated selection, or evidence that an action helped.

### What makes it compound

Use a structured candidate and outcome record outside the graph:

- Stable candidate fingerprint.
- Evidence and source event IDs.
- Affected component and failure signature.
- Proposed measurable outcome.
- Risk class and expected blast radius.
- State: `proposed → selected → attempted → tested → reviewed → merged → deployed → observed`.
- Terminal states including `rejected`, `duplicate`, `halted`, `rolled_back`, and `no_effect`.
- Links to runs, commits, tests, deployments, alerts, reviewer feedback, and later recurrences.
- Observation windows such as 24 hours and seven days.

The graph may index and retrieve these records, but it should not be the authoritative workflow database.

Compounding should occur through:

- Turning every escaped defect into a regression test.
- Mapping recurring failure signatures to verified diagnostic playbooks.
- Suppressing candidates by fingerprint and reason, with explicit expiry conditions.
- Promoting successful investigation strategies only after repeated, measured success.
- Demoting strategies correlated with rejections, rollbacks, or inconclusive work.
- Replaying historical incidents to evaluate whether the current selector and memories would have produced better decisions.
- Reviewing outcomes after deployment, rather than ending the loop at merge.

### What to measure

Do not optimize PR count, tokens generated, ledger size, or adjudication score.

Measure:

- Run start and stage-completion rates.
- Percentage of halts with actionable diagnostics.
- Duplicate-candidate rate.
- Proposal acceptance rate and human review minutes.
- Merge-to-deploy success rate.
- Rollbacks, incidents, and escaped regressions caused by autonomous changes.
- Recurrence rate of targeted failure signatures.
- Time to detect, diagnose, and repair operational failures.
- Difference in the candidate’s declared target metric before and after deployment.
- GPU-minutes, tokens, pod-minutes, storage, and network consumed per accepted improvement.
- Foreground request delay attributable to background work.
- Memory retrieval precision on a labeled incident set.
- False invalidation and false entity-merge rates.

A merged change with no measurable effect is not a success. It is an expensive unknown.

## 4. Dreaming

Dreaming belongs in a separate, non-authoritative analysis plane. It should produce hypotheses and derived memories, not rewrite truth or launch changes.

### Memory architecture

Use three layers:

1. **Immutable evidence:** raw session events, tool results, commits, test results, deployments, reviews, alerts, and human corrections.
2. **Structured operational records:** candidates, runs, outcomes, incidents, and tool proposals.
3. **Derived memory:** summaries, clusters, inferred strategies, contradiction candidates, and retrieval indexes.

Every graph fact should retain:

- source event IDs;
- observed time;
- claimed valid-from and valid-to times;
- transaction-from and transaction-to times;
- extraction version;
- confidence;
- whether it is observed, inferred, summarized, or human-confirmed.

Do not overwrite a disputed fact. Append a `PROPOSED_INVALIDATION`, `CONTRADICTS`, or `SUPERSEDES` assertion. Preserve both the original claim and the later correction.

### Idle consolidation jobs

Run narrow, replayable jobs rather than one “dream about everything” prompt:

1. **Outcome linker:** deterministically connect tasks, commits, PRs, deploys, alerts, rollbacks, and human feedback.
2. **Exact deduplication:** hash and collapse duplicate events without semantic judgment.
3. **Failure clustering:** group recurring signatures and produce candidate clusters with cited examples.
4. **Strategy extraction:** propose short playbooks from multiple successful cases, including preconditions and counterexamples.
5. **Contradiction detection:** emit contradiction candidates with evidence from both sides.
6. **Entity-resolution review:** propose possible duplicate entities; do not merge them.
7. **Staleness review:** identify facts whose validity should be checked.
8. **Retrieval evaluation:** replay labeled historical questions and score whether retrieved memories were relevant and correct.
9. **Tool-gap mining:** identify repeated manual sequences or failures caused by missing capabilities.
10. **Summary regeneration:** rebuild disposable summaries from immutable evidence when extraction logic changes.

For a 35B-A3B local model:

- Give it small, typed tasks with strict JSON schemas.
- Require source IDs and short evidence spans for every assertion.
- Use deterministic preprocessing before model inference.
- Keep extraction, contradiction detection, and adjudication as separate passes.
- Treat two passes by the same model as correlated evidence, not independent votes.
- Never recursively summarize prior summaries without returning to source events.
- Version prompts and derived artifacts so consolidation can be replayed.
- Quarantine low-confidence outputs and expire them if unconfirmed.

Given the measured 20% invalidation noise, semantic invalidation should default to human review. Even a 5% false-deletion rate would be dangerous in a memory system that drives autonomous action.

### What must never be auto-applied

- Deleting immutable session or operational evidence.
- Invalidating human-confirmed or authorization-relevant facts.
- Merging entities that represent people, repositories, clusters, credentials, or environments.
- Changing guardrails, adjudication weights, approval thresholds, or sensitive-path policy.
- Granting permissions, registering credentials, or widening network access.
- Treating generated summaries as authorization.
- Converting a dream-derived hypothesis directly into a repository change.
- Feeding graph conclusions back as unquestioned facts.
- Rewriting the agent’s own evaluation criteria based on its self-reported success.

Safe automatic outputs are limited to append-only candidate assertions, exact deduplication, disposable indexes, provisional summaries, and reproducible reports.

## 5. Tooling that “just happens”

The acceptable version is:

> Tool proposals, implementations, and evidence appear automatically. Authority does not.

### Proposed lifecycle

1. Detect a repeated tool gap—preferably the same missing capability across at least three independent tasks.
2. Create a structured tool RFC containing use cases, non-goals, data flows, permissions, failure behavior, abuse cases, and alternatives.
3. Assign a risk tier from the required capabilities, not from code size.
4. Generate the implementation in a sandbox branch.
5. Test it against mocks or recorded fixtures.
6. Produce:
   - a typed capability manifest;
   - exact filesystem paths, network destinations, and API scopes;
   - contract and negative tests;
   - sample invocation traces;
   - rate and resource limits;
   - secret-scan and dependency results;
   - rollback procedure;
   - expiry or review date.
7. Run it first in shadow or read-only mode.
8. Require approval to activate the capability.
9. Bind approval to an immutable artifact digest and manifest version.
10. Canary it with audit logging, quotas, a kill switch, and automatic disablement on policy violation.

### Risk tiers

- **Tier 0:** Deterministic, repository-local, read-only code with no network, secrets, subprocesses, or automatic invocation. Code may be auto-generated and possibly auto-merged after strong tests, but activation should still be explicit.
- **Tier 1:** Read-only MCP or network access. Human approves destinations, schemas, rate limits, and registration.
- **Tier 2:** Write APIs, GitHub mutation, Kubernetes access, shell execution, or secret use. Human approves every initial grant and any scope expansion.
- **Tier 3:** RBAC, credential creation, deployment control, merge authority, policy changes, or arbitrary code execution. Proposal-only; no autonomous activation.

The capability broker must be outside the repositories the fleet can edit. An agent must not be able to change its tool manifest, merge the change, and thereby grant itself the tool.

### Making the human gate cheap

Present one compact approval packet:

- What recurring problem this solves.
- One representative trace.
- Exact permission diff.
- Data leaving the machine, if any.
- Test and canary results.
- Maximum cost and call rate.
- Failure containment and rollback.
- Artifact digest and expiration date.

Approval should be one action, but it should approve a specific version and permission set. Any code, destination, credential, or scope change invalidates the approval.

The current PR reviewer is not an adequate tool-security gate. Model confidence and `<400 lines` say almost nothing about capability risk.

## 6. Smallest version worth building first

### Build this

First, fix the known `dsh` failure path:

- Capture exit code, stderr, last tool call, stage timing, pod status, resource usage, and relevant events.
- Persist the diagnostic bundle even if publish never runs.
- Add stage and whole-run deadlines.
- Verify that twenty consecutive representative runs terminate with an explicit outcome.

Then build one small eligibility reconciler:

- Run every five minutes as a Kubernetes CronJob or minimal controller.
- Do not place it in `fleet-hooks`.
- Share one durable atomic lease with the 05:15 path—or delete the separate 05:15 trigger and express it as a force-eligibility policy in the same scheduler.
- Treat stale or missing observations as ineligible.
- Use stable run and candidate IDs.
- Start at **one run per day**, not four.
- Use minis-specific capacity signals and a hard resource budget.
- Recheck foreground demand at every stage boundary.
- Permit cancellation.
- Run only `collect → investigate → adjudicate`.
- Produce a structured proposal with evidence; do not implement, push, merge, or deploy.
- Persist outcomes in an authoritative structured store, then mirror them into graphiti.

After a useful sample—at least twenty clean runs and several human-accepted proposals—allow implementation only for a narrow allowlist such as tests, diagnostics, or documentation. Keep merge human-gated until post-deployment outcomes demonstrate low rollback and recurrence rates.

### Explicitly do not build yet

- No sampler thread in `fleet-hooks`.
- No two independent schedulers.
- No four-runs-per-day quota.
- No non-preemptible background jobs.
- No automated graph invalidation.
- No autonomous entity merging.
- No broad “summarize the whole brain” dream.
- No recursive summaries treated as evidence.
- No auto-merge for operational changes.
- No self-registering MCP providers.
- No autonomous permission or secret grants.
- No tool factory before the base pipeline is reliable.
- No reinforcement-learning or bandit language around ten prose episodes.
- No graph-based scheduler state.
- No self-modification of rails, prompts, weights, or reviewer policy.
- No claim of success at PR merge time.

The smallest worthwhile system is not an autonomous self-improver. It is a reliable, interruptible proposal generator with durable state and measurable outcomes. Once that works, dreaming can improve retrieval and candidate quality. Self-tooling comes last, because it expands authority—and authority is the part of this system that should compound most slowly.
