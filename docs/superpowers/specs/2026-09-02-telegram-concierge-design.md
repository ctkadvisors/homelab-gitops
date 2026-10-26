# Telegram concierge: the brain is the memory

Chris, 2026-09-02: "i should be able to ask it to do anything, and it'll find a
way to execute (spin up subagents, create new agents, use tools, create tools)."
And: "you have memory. graphiti." Dealer's choice on authority: PRs for code,
direct-with-confirm for agents and tools, autonomy for anything read-only.

## Why every Telegram turn was a fresh task

The channel path mints one AgentTask per inbound message. A ChannelSession
groups them under a session key and records `lastTaskRef`, but nothing loaded
prior turns into the next task. The door had no memory.

## Design

**Memory = graphiti, both directions.** No second store.

1. *Write side, in the telegram adapter (kagent PR #9).* At delivery the adapter
   has both halves of the exchange. It writes one episode: `Chris (telegram):
   <message>` / `<agent> replied: <reply>` (or the failure), source `message`,
   group `main`, `reference_time` = when the message arrived. Failures log and
   never block delivery. Off unless the brain values are set.
2. *Read side, in the concierge prompt.* Search facts and recent episodes before
   answering anything about Chris, the homelab, or past work.
3. *The bridge.* graphiti ingestion runs through ornith15 and takes minutes, so
   the previous turn is not in the graph when the next arrives. The adapter's
   inbound path prepends the peer's last exchange (session `lastTaskRef` ->
   task annotation + result) under `[previous turn]` / `[current message]`
   markers. The writer strips the markers so episodes carry only what was
   typed. It is a bridge over lag, not a second memory.

**The concierge Agent** (`overlays/production/kagent/concierge-agent.yaml`):
ornith15 via `reasoner-default`, `browser-code-researcher` profile (brain
read/write, Steel browser, code interpreter), children `operator-investigator`
and `homelab-builder`. Telegram's ChannelBinding now targets it
(`telegram-work-concierge`, 8 iterations / 1500 s). WhatsApp unchanged.

**Not in this slice: the mission hand-off.** "Fix Z and open a PR" needs the dsh
staged pipeline (improve-daily's stages) launched with the message as the brief,
results back through Telegram and the brain. Nothing conversational can reach
a Job today; that is the next piece. Until then, code-shaped requests go to
homelab-builder (bare agent-loop with shell.exec), which is the weaker path.

## Non-goals

- n8n. The flow is fixed; the workflows live outside git; the node reported
  success on failed tasks.
- Hardcoded agent lists in the concierge: the children are declared on the
  Agent CR (`allowedChildAgents`), the fleet is discoverable via
  `/api/agents`, and new specialists become children by editing that list.
