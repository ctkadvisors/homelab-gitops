# Paperclip AI Agent Postmortem (2026-03-09)

## What Is Paperclip

Paperclip is an AI agent orchestration platform deployed in the cluster as `paperclip` in `ai-services` namespace. It runs autonomous AI agents on a heartbeat timer that wake up, check for tasks, execute code, and go back to sleep.

- **Image**: `git.example.com/homelab/paperclip:latest`
- **Port**: 3100 (ClusterIP + NodePort 31300)
- **Data**: Persistent volumes at `/app/data` and `/app/.paperclip`
- **Domain**: `paperclip.example.com`
- **Adapter**: `codex_local` (OpenAI Codex running locally)
- **Model**: `gpt-5.3-codex` (via OpenAI API key)
- **Sandbox**: `dangerouslyBypassApprovalsAndSandbox: true` — unrestricted shell access

## What Went Wrong

The CEO agent ran 13 times in 2.5 hours doing "planning" work — reading codebases, writing design docs, creating issues, updating memory files. Each run accumulated massive context (~5.5M input tokens for the biggest single run). The founding engineer agent completed 2 real tasks (SEE-4, SEE-5) but the CEO agent consumed 85% of all tokens (22M out of 26M total) on management overhead.

Total token consumption: **26.1M tokens** in ~3 hours. Burned through $5 OpenAI credits. After quota exhaustion, both agents continued attempting hourly heartbeats for 17+ hours, all failing immediately with "Quota exceeded."

Gemini API key was configured in secrets but the adapter was `codex_local` (OpenAI only). Without Gemini support in Paperclip's codex adapter, there's no free-tier fallback.

## Resolution

Scaled deployment to 0: `kubectl scale deployment paperclip -n ai-services --replicas=0`

## How to Investigate Paperclip Issues

### Key Paths Inside the Pod

```
/app/data/run-logs/{companyId}/{agentId}/{runId}.ndjson   # Per-run NDJSON logs
/app/data/ai-interviewer/                                  # Working directory (SeekArc product)
/app/data/instances/                                       # Instance configs
/app/.paperclip/logs/                                      # App-level logs
```

### Company & Agent IDs

| Entity | ID |
|--------|----|
| Company (SEE) | `3452387a-ea87-4ded-bcc7-2378e799080b` |
| CEO agent | `aae891ce-0fb1-42d4-a637-f995a1dbaba4` |
| Founding Engineer agent | `f760e021-d35a-4f69-b81b-baf8b8569df0` |

### Reading Run Logs

Run logs are NDJSON. Each line: `{"ts": "...", "stream": "stdout|stderr", "chunk": "{...}\n"}`. The `chunk` field contains newline-delimited JSON events:

- `thread.started` — new conversation thread
- `turn.started` / `turn.completed` — API call lifecycle; `turn.completed` has `usage` with token counts
- `turn.failed` / `error` — failures (e.g., quota exceeded)
- `item.started` / `item.completed` — individual actions (shell commands, file changes, agent messages)

```bash
# List all runs for an agent, sorted by size
kubectl exec -n ai-services <pod> -- sh -c 'for f in /app/data/run-logs/<companyId>/<agentId>/*.ndjson; do echo "$(wc -c < $f) $(basename $f)"; done' | sort -rn

# Read a specific run
kubectl exec -n ai-services <pod> -- cat /app/data/run-logs/<companyId>/<agentId>/<runId>.ndjson

# Extract token usage from all runs
kubectl exec -n ai-services <pod> -- sh -c 'for f in /app/data/run-logs/<companyId>/<agentId>/*.ndjson; do bytes=$(wc -c < $f); if [ $bytes -gt 5000 ]; then echo "=== $(basename $f) ${bytes}B ==="; grep -o "turn.completed.*" $f | head -3; fi; done'
```

### API Endpoints (require auth session cookie)

The SPA frontend calls these backend routes:
- `GET /heartbeat-runs/{runId}/events?afterSeq=0&limit=200`
- `GET /agents/{agentSlug}?companyId={companyId}`
- `GET /companies/{companyId}/heartbeat-runs?agentId={agentId}`
- `GET /agents/{agentId}/runtime-state?companyId={companyId}`
- `GET /companies/{companyId}/live-runs`

These return 304 (cached) or JSON. Direct `wget` from inside the pod without cookies returns empty responses — must go through the NDJSON log files instead.

### Secrets

Stored in `paperclip-secrets` secret in `ai-services` namespace:
- `better-auth-secret`
- `gemini-api-key`
- `openai-api-key`

## Lessons Learned

1. **CEO/manager agents are token sinks.** The "CEO" agent consumed 5x more tokens than the engineer doing actual work. Planning/management agents on short heartbeat intervals will burn through credits fast.
2. **Heartbeat timers don't stop on quota exhaustion.** The agents kept trying every hour for 17+ hours after credits ran out. Need budget limits or auto-pause on repeated failures.
3. **WebFetch won't work on Paperclip's SPA.** The run detail page (`/SEE/agents/.../runs/...`) is a client-rendered React app. WebFetch only gets the theme initialization script. Go straight to the NDJSON files in the pod.
4. **The pod's `wget` requires auth cookies.** Don't waste time trying to hit the API from inside the pod — read the flat files directly.
5. **Thread history accumulates per-run.** Each heartbeat loads the full thread history, which is why later runs had 5M+ input tokens. Long-running thread IDs are expensive.
