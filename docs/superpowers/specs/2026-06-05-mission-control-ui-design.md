# kagent Workbench → "Mission Control" — Enterprise UI Redesign

**Date:** 2026-06-05
**Status:** Approved (direction + scope locked via brainstorming)
**Repo:** `ctkadvisors/kagent` → `packages/workbench-ui`
**Deploys via:** kagent CI (tag `v*`) → image bump in
`new_localai/k8s-kustomized/overlays/production/kagent/workbench-application.yaml` → ArgoCD

## Problem

The workbench has six routes that already form a complete agent lifecycle but
look like three different products — and one looks like none at all:

| Route | Lifecycle role | State before |
| -- | -- | -- |
| `#/architect` | **Create** (chat-to-create) | Completely unstyled — serif browser default, raw `<textarea>`, native button. No CSS module, no `className`. |
| `#/command` | **Operate** (RTS live ops) | Polished dark game theme. The high-water mark. |
| `#/cluster` | **Observe** (nodes/pods/agents) | Clean but *light* — different universe from Command. |
| `#/gateway` | **Observe** (LLM usage) | Dense *light* data table. |
| `#/review` | **Govern** (accept/reject) | Decent but *light* and isolated. |
| `#/` Tasks | run log | Dense *light* table; the "← Back" target for all. |

**Root cause is architectural, not cosmetic:** there is no design system. No
global CSS, no design tokens (`var(--…)` appears nowhere), no shared app shell,
no font import. Every page hand-rolls a `.module.css` with hardcoded hex. That
is why the surfaces diverge and why Architect renders as raw HTML.

## Decisions (locked)

1. **Direction: "Mission Control" dark.** Standardize on the Command Center's
   existing dark palette as the house style — it is already the surface the
   owner values most, and "dark professional console" is squarely enterprise in
   2026 (Vercel / Linear / Grafana / Datadog).
2. **Command Center: light touch.** It inherits the shared tokens + typography +
   sits inside the new shell, but its isometric map, gameplay, hotkeys, and
   layout are untouched (92 KB component — minimize regression risk).
3. **Scope: everything in one pass.** Design-system foundation + all six
   surfaces re-skinned, shipped together.

## Design

### Tokens (`src/styles/tokens.css`, `:root`) — derived from Command's real palette
```
Surfaces  --bg-deep #050b18  --bg-base #0a1628  --bg-raised #14213d  --bg-panel #1f2a44
Border    --border #1f2a44   --border-strong #334155
Text      --fg #e2e8f0  --fg-dim #94a3b8  --fg-muted #64748b
Brand     --accent #fbbf24 (amber)  --accent-dim rgba(251,191,36,.15)
Semantic  --ok #34d399  --warn #fbbf24  --danger #f87171  --info #60a5fa  --live #22d3ee
Type      --font-sans "Inter", system-ui …   --font-mono ui-monospace, SFMono-Regular, Menlo
Scales    --r-1..3 (radius)  --s-1..6 (space)  --shadow-1..2
```
All page CSS consumes these; no hardcoded hex remains outside `tokens.css`.

### Typography
Self-hosted **Inter** (woff2 in `public/`, `@font-face` — no CDN, Tailscale/
offline safe) for headings + body. Keep the existing mono for IDs, metrics,
code, YAML. Imported once via `main.tsx` / global `index.css`.

### App shell (`src/AppShell.tsx`) — the navigational spine
Persistent **left rail** grouped by lifecycle, replacing scattered "← Back"
buttons:
```
CREATE  → Architect
OPERATE → Command Center · Tasks
OBSERVE → Cluster · Gateway
GOVERN  → Review  [live count badge]
```
Thin **top bar** carrying the global KPIs currently trapped inside Command
(In-flight · Completed 1h · Failed 1h · Models · Cost/hr) so they show on every
page. Active route highlighted amber. `App.tsx` wraps every route in the shell;
detail routes (`#/tasks/:ns/:name`) keep a contextual back affordance.

### Per-surface work
- **Architect** — full rebuild into a real chat surface: message stream, sticky
  composer, generated AgentTemplate in a syntax-highlighted card with
  **Try it live** / **Copy YAML**, draft-namespace badge, repair/loading states.
- **Cluster / Gateway / Tasks / Review** — re-skin light→dark on tokens: stat/
  node cards, dense tables with row hover + zebra + sticky headers, status pills
  via semantic tokens. Same logic/components, new skin.
- **Command Center** — replace local color literals with shared tokens, adopt
  Inter for chrome text, render inside the shell. No behavioral change.

### Shared primitives (`src/ui/`) — prevents future drift
Extract `Button`, `StatusPill`, `StatCard`, `DataTable`, `PageHeader`
(~5 small components) consumed by all re-skinned pages.

## Testing
- `pnpm -C packages/workbench-ui test` (Vitest) stays green — existing
  `api.test.ts` / `ReviewPage.test.tsx` unaffected by skin changes.
- `pnpm -C packages/workbench-ui build` (tsc + vite) clean.
- Repo lint/prettier clean (CI `verify` job gates the image build).
- Visual verification via Playwright against the deployed image on all six
  routes after ArgoCD sync.

## Out of scope
- No Command Center gameplay/layout changes.
- No backend/API changes (architect endpoints already shipped in Phase 1).
- No new routes; lifecycle grouping is presentational only.

## Rollout
1. Implement in `ctkadvisors/kagent` clone (Node 22, `engine-strict`).
2. Green local: tests + build + lint.
3. Tag `v0.2.1-mission-control-rc.1` → CI builds + signs
   `kagent-workbench-{api,ui}` images.
4. Bump UI image tag in `workbench-application.yaml`, push `new_localai` main →
   ArgoCD syncs.
5. Playwright-verify all six routes live at `kagent.example.com`.
