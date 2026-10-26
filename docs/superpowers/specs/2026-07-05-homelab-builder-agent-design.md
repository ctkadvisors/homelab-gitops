# homelab-builder agent — design

Date: 2026-07-05
Status: approved (informal, "yolo" — see conversation this doc originated from)

## Context

The homelab previously had "Clawdbot" (later rebranded OpenClaw, https://openclaw.ai/)
running on a Mac mini with full shell + SSH access using the user's own keys, bridged
to WhatsApp. It built and deployed `services/chris-tts/` end to end: wrote a FastAPI
wrapper around Qwen3-TTS voice-clone inference, `scp`/SSH'd to jetson2, built + pushed
the Docker image, `kubectl apply`'d the Deployment, then called the running service to
generate WhatsApp voice notes. Note: this was **zero-shot reference-audio inference**
(`model.generate_voice_clone(ref_audio=...)` in `chris-tts/main.py`), not a training/
fine-tuning loop — there is no multi-hour training job in the precedent workflow.

Clawdbot is gone. The user wants a comparable "actually does things" capability back,
but explicitly does not want Opus/any cloud LLM (accepts the capability tradeoff of
staying local-only on Spark's Qwen3-Coder-Next), and does not want to blindly recreate
Clawdbot's blast radius (full shell with personal SSH keys, unrestricted).

This builds on the Telegram channel work landed earlier the same day: `telegram-work`
Channel/ChannelBinding → `operator-investigator` Agent, backed by
`qwen-coder-spark` ModelEndpoint (Spark DGX, `coder` model via llama-swap,
`backendKind: localai`), `modelClass: tool-caller-spark-qwen`.

## Goal

A general-purpose "builder" capability, reachable from the same Telegram bot
(@hlhermbot) already wired up, that can write code, execute real shell commands on
specific homelab nodes, build/push container images, and push GitOps changes straight
to `main` — without turning every casual chat message into a shell-capable request.

## Decisions from brainstorming

- **Scope**: general-purpose builder, not narrowly chris-tts-specific.
- **Execution tier**: real, arbitrary-command shell access (not a fixed script menu,
  not a command-pattern allowlist) — but via a dedicated low-privilege OS account with
  no sudo, not the user's personal SSH key.
- **Node scope**: `elitemini2` (compute-worker) + `jetson2` (GPU worker). Explicitly
  **not** `elitemini` (control-plane) — no direct kubectl/cluster-control-plane access
  via this path.
- **Deploy authority**: full autonomy. The builder agent commits and pushes straight to
  `main`; ArgoCD reconciles as usual. No human merge checkpoint.
- **Trigger surface**: same bot/channel as `operator-investigator` (@hlhermbot). One
  agent decides whether a message is casual chat or a build request.
- **Privilege-split pattern**: dispatcher + child agent, using kagent's existing
  `spawn_child_task` / `Agent.spec.allowedChildAgents` mechanism (already implemented,
  fail-closed by default — verified in `packages/agent-pod/src/builtin-tools-spawn.ts`).
  `operator-investigator` is unchanged and never gets a shell tool; it only gains
  `allowedChildAgents: [homelab-builder]` and a prompt update telling it when to
  delegate. The shell/SSH tool exists exclusively in the new `homelab-builder` Agent's
  pod.
- **Runtime model**: a new kagent `Agent` CR, not a separate always-on process. Reuses
  Channel/AgentTask/Job/capability-JWT/Langfuse-tracing machinery already built. Gets a
  larger iteration/timeout budget than `operator-investigator` since build+push+deploy
  takes longer than casual chat, but is still bounded per-task (minutes, not hours) —
  consistent with the chris-tts precedent having no real training loop.

## Architecture

```
Telegram (@hlhermbot) ──DM──▶ telegram-work Channel ──▶ operator-investigator
                                                              │
                                            casual chat ──────┤── investigation
                                            (reply directly)  │   (existing tools,
                                                               │    unchanged)
                                                               │
                                                   needs real execution?
                                                               │
                                                   spawn_child_task
                                                               ▼
                                                      homelab-builder Agent
                                                      (new, separate AgentTask/Job)
                                                               │
                                                   shell.exec tool (new, tool-gateway)
                                                               │
                                                   SSH as kagent-builder@{elitemini2,jetson2}
                                                   (dedicated key, no sudo, cgroup-capped)
                                                               │
                                                   git commit + push → main
                                                   (ArgoCD reconciles as usual)
                                                               │
                                                   result bubbles back up through
                                                   the parent AgentTask → Telegram reply
```

## Components

### 1. `shell.exec` tool (new, `packages/tool-gateway`)

- Input: `{ host: 'elitemini2' | 'jetson2', command: string, timeoutSeconds?: number }`.
  `host` is a closed enum — the tool rejects anything else at the schema level, not
  just by convention.
- Execution: SSH as the `kagent-builder` OS user, using a dedicated key (never the
  user's personal key). Every invocation wraps the remote command in `timeout
  ${min(timeoutSeconds ?? 120, 600)}s` so a hung command can't block the tool forever
  even before the node-side cgroup cap kicks in.
- Defense-in-depth command rejection (belt-and-suspenders on top of the no-sudo OS
  account): reject command strings containing `sudo`, edits to
  `~/.ssh/authorized_keys`, and a short list of obviously destructive patterns
  (`rm -rf /`, fork bombs). This is not a substitute for the OS-level restriction, just
  a cheap extra layer.
- Returns `{ stdout, stderr, exitCode }` (truncated for storage like other tool
  outputs in this codebase) so the agent can see failures and retry/adjust.

### 2. `homelab-builder` Agent CR (new)

- `modelClass: tool-caller-spark-qwen` — same Spark-backed Qwen3-Coder-Next endpoint
  already wired for `operator-investigator`. No new ModelEndpoint needed.
- New tool profile (e.g. `builder-shell`): `shell.exec` + the existing
  `code_interpreter.execute_code` (JS) and `browser.*` tools, so it can draft files
  locally before pushing, in addition to running remote commands.
- Larger budget than `operator-investigator`: proposed `maxIterations: 15`,
  `timeoutSeconds: 1200` (20 min) — enough for a chris-tts-style build+push+deploy
  cycle, still bounded.
- Git identity: a dedicated bot credential (Gitea/GitHub token, scoped to this repo if
  the host supports fine-grained tokens — not the user's personal token), sealed as a
  Secret, mounted only into this Agent's pod.

### 3. `operator-investigator` changes (existing Agent, minimal diff)

- Add `spec.allowedChildAgents: [homelab-builder]`.
- System prompt addition: when a request clearly needs real execution (building,
  deploying, running commands on cluster nodes — as opposed to investigating existing
  state, which it already does itself), call `spawn_child_task` targeting
  `homelab-builder` with a clear task description, then relay the child's result back
  to the user.
- No changes to its own tool profile — it never gains a shell tool.

### 4. SSH credential + node-side account provisioning (manual, one-time, outside GitOps)

This touches real machines directly and is **not** something ArgoCD can reconcile —
call this out explicitly as a manual step, same posture as the existing
`spark-llamaswap` Endpoints object:

- Generate a fresh ed25519 keypair dedicated to this agent (`kagent-builder`) — never
  reuse the user's personal key.
- On `elitemini2` and `jetson2`: create a `kagent-builder` user, no sudoers entry,
  standard login shell. Install the public key in that user's
  `~/.ssh/authorized_keys`.
- Node-side resource cap (the killswitch that matters here, since the actual compute
  happens over SSH on the node, not inside a k8s pod — pod resource limits don't cover
  this): a systemd user slice / cgroup for `kagent-builder` with CPU and memory
  ceilings, analogous in spirit to the pod-level killswitch the Hermes convention
  requires for in-cluster agents.
- Private key sealed as a k8s Secret (`kagent-builder-ssh-key`), mounted only into
  `homelab-builder`'s agent-pod.

### 5. NetworkPolicy / egress

`homelab-builder`'s pod egress allowlist: DNS, the in-cluster `kagent-llm-gateway`
(same as every other agent-pod — it does not need direct Spark egress, LLM calls
already route through the gateway), SSH (port 22) to `elitemini2` and `jetson2`
specifically (not a broader CIDR), and git push targets. "General-purpose" means this
could be either host this homelab actually uses for git: GitHub (`github.com`, this
infra repo, `ctkadvisors/new_localai`) or the self-hosted Gitea at
`git.example.com:10.0.0.76` (used for generated-project repos under the
`ai-generated` org). Allowlist both explicitly rather than a broad `0.0.0.0/0:443`
egress rule — mirrors the pattern `qwen-coder.yaml`'s NetworkPolicy already uses for
its own Gitea + public-HTTPS egress. No control-plane node in the allowlist.

## Error handling

- `spawn_child_task` fails closed if `allowedChildAgents` is misconfigured — this is
  existing, already-implemented behavior, not new code.
- `shell.exec` rejects any `host` outside the closed enum, wraps every command in a
  timeout, and returns structured stdout/stderr/exitCode rather than throwing, so the
  agent can see and react to a failed command instead of the task just dying.
- Node-side cgroup/systemd caps bound worst-case resource consumption from a runaway
  or malicious command, independent of anything the agent-pod itself does.
- `homelab-builder`'s `maxIterations`/`timeoutSeconds` bound worst-case task runtime.
- Git push failures (auth, conflicts) surface as a normal tool error back to the
  agent — not silently swallowed — so it can report the failure back to the user
  instead of claiming false success.

## Testing / rollout plan

1. Unit tests for `shell.exec`'s host-enum rejection, timeout wrapping, and
   defense-in-depth pattern rejection (mirroring the tool-mapper test conventions
   already in this codebase).
2. Before trusting it with anything real: a harmless dry run — ask it (or invoke
   directly) to SSH to `elitemini2` and run `whoami`/`echo test`, confirm the
   `kagent-builder` account and key work, and confirm a request targeting a host
   outside the enum is rejected.
3. Confirm the node-side resource cap actually bites — deliberately run a CPU-bound
   loop under `kagent-builder` and confirm it gets throttled/killed rather than
   contending unbounded with production workloads (LocalAI on jetson2 in particular).
4. Confirm `operator-investigator` correctly distinguishes "investigate" from "build"
   requests without spawning the child on casual chat (same category of prompt-tuning
   already done for the Telegram rollout) and without false negatives on real build
   requests.
5. End-to-end on a small, low-stakes real task first (e.g., "SSH to elitemini2 and
   report disk usage") before handing it something with real write/deploy
   consequences.

## Explicit non-goals / open follow-ups

- No long-running/background task orchestration is being built — if a future task
  genuinely needs multi-hour execution (a real training loop, unlike the chris-tts
  precedent), that's a separate design.
- Per-Agent pod resource tiers: `agentPod` resource limits in the operator Helm values
  currently look global across all spawned agent-pods rather than configurable per
  Agent. Not blocking this design (the node-side SSH cgroup cap is the resource
  boundary that actually matters for shell.exec), but worth revisiting if
  `homelab-builder`'s own pod needs a different ceiling than `operator-investigator`'s.
- No separate "builder" bot/channel — accepted risk per user's explicit choice is that
  a dispatch/classification mistake in `operator-investigator` could, in principle,
  spawn `homelab-builder` for a message that didn't warrant it. Mitigated by
  `allowedChildAgents` being the only escalation path (fail-closed) and by
  `homelab-builder` itself still being bounded (no sudo, two-node scope, timeouts).
