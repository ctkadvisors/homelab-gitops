# homelab-builder Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `shell.exec` tool to kagent's tool-gateway, a new `homelab-builder` Agent that uses it (SSH to elitemini2/jetson2 as a scoped low-privilege account, git push to main), and wire it in as a child that `operator-investigator` can spawn on demand — without ever giving the casual-chat agent itself shell access.

**Architecture:** Two repos, two phases. Phase 1 (kagent repo, `/tmp/kagent-src-check`): add a new closed-enum tool kind `shell` to `@kagent/dto`, implement `SshShellRunner` in `packages/tool-gateway`, wire it into the HTTP dispatch/descriptor switches, release as a new tag so CI publishes a new `kagent-tool-gateway` image. Phase 2 (this repo, `new_localai`): manual one-time node provisioning (OS user + SSH key + cgroup cap on elitemini2/jetson2 — **not** GitOps-managed, run interactively), sealed Secrets, the new `homelab-builder` Agent CR + `builder-shell` tool profile, `operator-investigator`'s `allowedChildAgents` + prompt update, a NetworkPolicy, and bumping the parent ChannelBindings' `runConfig.timeoutSeconds` (spawned-child timeouts clamp to the parent's *remaining* budget — see Task 8 for why this matters).

**Tech Stack:** TypeScript (Node 22, pnpm workspaces, vitest), Kubernetes CRDs (kagent.example.com/v1alpha1), Kustomize, ArgoCD, SSH, systemd (cgroup v2 slices).

## Global Constraints

- kagent repo: Node `>=22.0.0 <23.0.0` required (`nvm use 22` before any pnpm command, or the pre-commit hook and `pnpm install` both fail with `ERR_PNPM_UNSUPPORTED_ENGINE`).
- Every kagent commit's pre-commit hook runs `pnpm lint-staged && pnpm -r typecheck` across all 30 workspace packages — budget for this on every commit, not just at the end.
- This repo (`new_localai`)'s GitOps rule: edit `k8s-kustomized/`, validate with `kubectl kustomize k8s-kustomized/overlays/production`, commit, push — never `kubectl apply -f`/`edit`/`patch` against the live cluster. `k8s-kustomized/overlays/production/kagent/application.yaml` must stay mirrored byte-for-byte into `k8s/argocd-apps/kagent-app.yaml` after every edit.
- kagent image tags follow `vX.Y.Z-<slug>-rc.N`; a git tag push triggers `.github/workflows/ci.yml`, which publishes `ghcr.io/ctkadvisors/kagent-<package>` images. The `channel-telegram-adapter`/`tool-gateway`/`operator`/etc. images are all re-tagged uniformly on every release tag regardless of which package's source actually changed.
- elitemini2 = `10.0.0.74`, jetson2 = `10.0.0.75` (per `config/network.yaml`) — these are the only two hosts `shell.exec` may ever target. Never elitemini (control-plane, `10.0.0.76`).
- `spawn_child_task`'s `runConfig.timeoutSeconds` is clamped to the **parent's remaining time budget** (`packages/agent-pod/src/builtin-tools-spawn.ts`) — a child cannot outlive its parent's own `ChannelBinding.spec.runConfig.timeoutSeconds`.

---

## File Structure

**kagent repo (`/tmp/kagent-src-check`):**

| File | Responsibility |
|---|---|
| `packages/dto/src/tool-session.ts` | Modify: add `'shell'` to `TOOL_KINDS`, add `SHELL_TOOL_NAMES`/`ShellToolName`/`isShellTool`, extend `ToolRuntimeToolName` union and `isToolRuntimeTool`. |
| `packages/dto/src/tool-session.test.ts` | Modify: flip the existing `isToolKind('shell')` assertion, add shell-specific assertions. |
| `packages/tool-gateway/src/shell-runner.ts` | Create: `SshShellRunner` class — host-enum validation, SSH invocation via injectable `spawn`, timeout wrapping, defense-in-depth command rejection. |
| `packages/tool-gateway/src/shell-runner.test.ts` | Create: unit tests for the above, spawn injected as a stub (no real network). |
| `packages/tool-gateway/src/http-server.ts` | Modify: new `ToolGatewayShellRunner` interface + `shellRunner` option, dispatch case, descriptor/schema/tags cases, `execShell` handler method. |
| `packages/tool-gateway/src/http-server.test.ts` | Modify: add coverage for the new dispatch case + descriptor. |
| `packages/tool-gateway/src/server.ts` | Modify: env parsing (`KAGENT_SHELL_SSH_KEY_PATH`, `KAGENT_SHELL_SSH_USER`) + `buildSshShellRunner`, wire into `buildToolGatewayHandler`. |
| `packages/tool-gateway/src/server.test.ts` | Modify: env parsing coverage for the new vars. |

**new_localai repo (this repo):**

| File | Responsibility |
|---|---|
| `docs/runbooks/kagent-builder-node-setup.md` | Create: manual, non-GitOps runbook — OS user, SSH keypair, cgroup cap on elitemini2 + jetson2. |
| `k8s-kustomized/overlays/production/kagent/homelab-builder-secrets.yaml` | Create: `kagent-builder-ssh-key` + `kagent-builder-git-token` Secrets. |
| `k8s-kustomized/overlays/production/kagent/homelab-builder-agent.yaml` | Create: the `homelab-builder` Agent CR + its NetworkPolicy. |
| `k8s-kustomized/overlays/production/kagent/operator-investigator-agent.yaml` | Modify: add `allowedChildAgents`, prompt addition. |
| `k8s-kustomized/overlays/production/kagent/channel-control.yaml` | Modify: bump both `ChannelBinding.spec.runConfig.timeoutSeconds` from 600 to 1500. |
| `k8s-kustomized/overlays/production/kagent/application.yaml` | Modify: `builder-shell` tool profile, `tool-caller-spark-qwen` reused (no new ModelEndpoint), tool-gateway image tag bump, new env vars for the shell runner. |
| `k8s-kustomized/overlays/production/kagent/kustomization.yaml` | Modify: add the two new resource files. |
| `k8s/argocd-apps/kagent-app.yaml` | Modify: mirror of `application.yaml`. |

---

### Task 1: `shell` tool kind in `@kagent/dto`

**Files:**
- Modify: `packages/dto/src/tool-session.ts`
- Modify: `packages/dto/src/tool-session.test.ts`

**Interfaces:**
- Produces: `SHELL_TOOL_NAMES: readonly ['shell.exec']`, `type ShellToolName = 'shell.exec'`, `isShellTool(value: unknown): value is ShellToolName`, `ToolRuntimeToolName` now includes `ShellToolName`, `isToolRuntimeTool` returns `true` for `'shell.exec'`, `TOOL_KINDS` now includes `'shell'`.

- [ ] **Step 1: Write the failing tests**

Add to `packages/dto/src/tool-session.test.ts` (import `isShellTool`, `SHELL_TOOL_NAMES` alongside the existing imports at the top of the file):

```ts
  it('recognizes browser, code_interpreter, and shell as tool kinds', () => {
    expect(TOOL_KINDS).toEqual(['browser', 'code_interpreter', 'shell']);
    expect(isToolKind('browser')).toBe(true);
    expect(isToolKind('code_interpreter')).toBe(true);
    expect(isToolKind('shell')).toBe(true);
    expect(isToolKind('kubectl')).toBe(false);
  });

  it('declares exactly one shell tool: shell.exec', () => {
    expect(SHELL_TOOL_NAMES).toEqual(['shell.exec']);
    expect(isShellTool('shell.exec')).toBe(true);
    expect(isShellTool('shell.ssh')).toBe(false);
    expect(isShellTool('code_interpreter.execute_command')).toBe(false);
  });

  it('treats shell.exec as a runtime tool', () => {
    expect(isToolRuntimeTool('shell.exec')).toBe(true);
  });
```

Also change the existing line:
```ts
    expect(isToolKind('shell')).toBe(false);
```
inside the `'recognizes only browser and code_interpreter as tool kinds'` test — **delete that whole `it(...)` block**, since it's superseded by the new `'recognizes browser, code_interpreter, and shell as tool kinds'` test above (same assertions, updated expectation). Add `isToolRuntimeTool` and `isShellTool` to the import list at the top of the test file.

- [ ] **Step 2: Run tests to verify they fail**

Run (from `/tmp/kagent-src-check`, Node 22 active):
```bash
source ~/.nvm/nvm.sh && nvm use 22
cd packages/dto && pnpm test -- tool-session.test.ts
```
Expected: FAIL — `isShellTool`/`SHELL_TOOL_NAMES` not exported, `TOOL_KINDS` doesn't equal the 3-element array.

- [ ] **Step 3: Implement**

In `packages/dto/src/tool-session.ts`, change:
```ts
export const TOOL_KINDS = ['browser', 'code_interpreter'] as const;
```
to:
```ts
export const TOOL_KINDS = ['browser', 'code_interpreter', 'shell'] as const;
```

After the `BROWSER_TOOL_NAMES`/`BrowserToolName` block, add:
```ts
export const SHELL_TOOL_NAMES = ['shell.exec'] as const;
export type ShellToolName = (typeof SHELL_TOOL_NAMES)[number];
```

Change:
```ts
export type ToolRuntimeToolName = CodeInterpreterToolName | BrowserToolName;
```
to:
```ts
export type ToolRuntimeToolName = CodeInterpreterToolName | BrowserToolName | ShellToolName;
```

After `isBrowserTool`, add:
```ts
export function isShellTool(value: unknown): value is ShellToolName {
  return typeof value === 'string' && (SHELL_TOOL_NAMES as readonly string[]).includes(value);
}
```

Change:
```ts
export function isToolRuntimeTool(value: unknown): value is ToolRuntimeToolName {
  return isCodeInterpreterTool(value) || isBrowserTool(value);
}
```
to:
```ts
export function isToolRuntimeTool(value: unknown): value is ToolRuntimeToolName {
  return isCodeInterpreterTool(value) || isBrowserTool(value) || isShellTool(value);
}
```

Add `SHELL_TOOL_NAMES`, `ShellToolName`, `isShellTool` to `packages/dto/src/index.ts`'s re-export list (find the existing `export { ... isToolRuntimeTool } from './tool-session.js';` block and add the three new names to it).

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd packages/dto && pnpm test -- tool-session.test.ts
```
Expected: PASS, all tests including the two new ones.

- [ ] **Step 5: Typecheck the whole workspace**

```bash
cd /tmp/kagent-src-check && pnpm -r typecheck 2>&1 | tail -60
```
Expected: every package still passes. If `packages/tool-gateway` or `packages/agent-pod` now fail because a `switch (name: ToolRuntimeToolName)` isn't exhaustive over the new `'shell.exec'` member, that's expected — Task 3 fixes those. Note which files/line numbers `tsc` reports here so Task 3 can address them precisely.

- [ ] **Step 6: Commit**

```bash
cd /tmp/kagent-src-check
git add packages/dto/src/tool-session.ts packages/dto/src/tool-session.test.ts packages/dto/src/index.ts
git commit -m "feat(dto): add shell tool kind (shell.exec)"
```

---

### Task 2: `SshShellRunner` implementation

**Files:**
- Create: `packages/tool-gateway/src/shell-runner.ts`
- Create: `packages/tool-gateway/src/shell-runner.test.ts`

**Interfaces:**
- Consumes: nothing from Task 1 directly (this is a pure runner class; the tool-name plumbing happens in Task 3).
- Produces: `SshShellRunner` class with `async exec(input: ShellExecInput): Promise<ShellExecResult>`; `ShellExecInput = { host: 'elitemini2' | 'jetson2'; command: string; timeoutSeconds?: number }`; `ShellExecResult = { stdout: string; stderr: string; exitCode: number | null; timedOut: boolean }`; constructor `new SshShellRunner({ sshKeyPath, sshUser, spawnImpl? })`. Task 3 consumes this exact shape.

- [ ] **Step 1: Write the failing tests**

Create `packages/tool-gateway/src/shell-runner.test.ts`:

```ts
/**
 * SPDX-License-Identifier: MIT
 * Copyright (c) 2026 Chris Knuteson
 */

import { EventEmitter } from 'node:events';
import type { ChildProcessWithoutNullStreams } from 'node:child_process';

import { describe, expect, it, vi } from 'vitest';

import { SshShellRunner } from './shell-runner.js';

function fakeChild(): {
  child: ChildProcessWithoutNullStreams;
  emitStdout: (s: string) => void;
  emitStderr: (s: string) => void;
  close: (code: number | null, signal: NodeJS.Signals | null) => void;
} {
  const stdout = new EventEmitter();
  const stderr = new EventEmitter();
  const child = new EventEmitter() as unknown as ChildProcessWithoutNullStreams;
  Object.assign(child, {
    stdout,
    stderr,
    kill: vi.fn(),
  });
  return {
    child,
    emitStdout: (s: string) => stdout.emit('data', Buffer.from(s)),
    emitStderr: (s: string) => stderr.emit('data', Buffer.from(s)),
    close: (code: number | null, signal: NodeJS.Signals | null) =>
      child.emit('close', code, signal),
  };
}

function makeRunner(spawnImpl: ReturnType<typeof vi.fn>): SshShellRunner {
  return new SshShellRunner({
    sshKeyPath: '/secrets/kagent-builder-ssh-key/id_ed25519',
    sshUser: 'kagent-builder',
    spawnImpl: spawnImpl as unknown as SshShellRunner extends never ? never : typeof spawnImpl,
  });
}

describe('SshShellRunner', () => {
  it('rejects a host outside the closed elitemini2/jetson2 enum before spawning anything', async () => {
    const spawnImpl = vi.fn();
    const runner = makeRunner(spawnImpl);

    await expect(
      // @ts-expect-error -- deliberately passing an invalid host to test the runtime guard
      runner.exec({ host: 'elitemini', command: 'echo hi' }),
    ).rejects.toThrow(/policy_denied.*host/i);
    expect(spawnImpl).not.toHaveBeenCalled();
  });

  it('rejects commands containing sudo before spawning anything', async () => {
    const spawnImpl = vi.fn();
    const runner = makeRunner(spawnImpl);

    await expect(runner.exec({ host: 'jetson2', command: 'sudo reboot' })).rejects.toThrow(
      /policy_denied.*sudo/i,
    );
    expect(spawnImpl).not.toHaveBeenCalled();
  });

  it('rejects commands that touch authorized_keys before spawning anything', async () => {
    const spawnImpl = vi.fn();
    const runner = makeRunner(spawnImpl);

    await expect(
      runner.exec({ host: 'jetson2', command: 'echo x >> ~/.ssh/authorized_keys' }),
    ).rejects.toThrow(/policy_denied.*authorized_keys/i);
    expect(spawnImpl).not.toHaveBeenCalled();
  });

  it('invokes ssh with the key, user, resolved host IP, and a timeout-wrapped command', async () => {
    const fake = fakeChild();
    const spawnImpl = vi.fn().mockReturnValue(fake.child);
    const runner = makeRunner(spawnImpl);

    const resultPromise = runner.exec({ host: 'elitemini2', command: 'echo hi', timeoutSeconds: 30 });
    fake.emitStdout('hi\n');
    fake.close(0, null);
    const result = await resultPromise;

    expect(result).toEqual({ stdout: 'hi\n', stderr: '', exitCode: 0, timedOut: false });
    expect(spawnImpl).toHaveBeenCalledTimes(1);
    const [command, args] = spawnImpl.mock.calls[0] as [string, string[]];
    expect(command).toBe('ssh');
    expect(args).toEqual([
      '-i',
      '/secrets/kagent-builder-ssh-key/id_ed25519',
      '-o',
      'StrictHostKeyChecking=accept-new',
      '-o',
      'BatchMode=yes',
      'kagent-builder@10.0.0.74',
      'timeout 30s echo hi',
    ]);
  });

  it('defaults to a 120s timeout and caps any requested timeout at 600s', async () => {
    const fake = fakeChild();
    const spawnImpl = vi.fn().mockReturnValue(fake.child);
    const runner = makeRunner(spawnImpl);

    const p1 = runner.exec({ host: 'jetson2', command: 'echo a' });
    fake.close(0, null);
    await p1;
    expect((spawnImpl.mock.calls[0] as [string, string[]])[1].at(-1)).toBe('timeout 120s echo a');

    const fake2 = fakeChild();
    spawnImpl.mockReturnValue(fake2.child);
    const p2 = runner.exec({ host: 'jetson2', command: 'echo b', timeoutSeconds: 99_999 });
    fake2.close(0, null);
    await p2;
    expect((spawnImpl.mock.calls[1] as [string, string[]])[1].at(-1)).toBe('timeout 600s echo b');
  });

  it('captures stderr and a non-zero exit code without throwing', async () => {
    const fake = fakeChild();
    const spawnImpl = vi.fn().mockReturnValue(fake.child);
    const runner = makeRunner(spawnImpl);

    const resultPromise = runner.exec({ host: 'jetson2', command: 'false' });
    fake.emitStderr('boom\n');
    fake.close(1, null);
    const result = await resultPromise;

    expect(result).toEqual({ stdout: '', stderr: 'boom\n', exitCode: 1, timedOut: false });
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
source ~/.nvm/nvm.sh && nvm use 22
cd /tmp/kagent-src-check/packages/tool-gateway && pnpm test -- shell-runner.test.ts
```
Expected: FAIL — `./shell-runner.js` doesn't exist yet.

- [ ] **Step 3: Implement**

Create `packages/tool-gateway/src/shell-runner.ts`:

```ts
/**
 * SPDX-License-Identifier: MIT
 * Copyright (c) 2026 Chris Knuteson
 */

import { spawn as nodeSpawn, type ChildProcessWithoutNullStreams } from 'node:child_process';

/**
 * Closed host enum, not helm/env-configurable. Adding a third host means
 * editing this file (and its tests), not a values.yaml change -- the same
 * "hardcode the allowlist in code" posture code-runner.ts uses for
 * ALLOWED_COMMANDS/DENIED_COMMANDS.
 */
const HOST_IPS: Record<ShellHost, string> = {
  elitemini2: '10.0.0.74',
  jetson2: '10.0.0.75',
};

export type ShellHost = 'elitemini2' | 'jetson2';

export interface ShellExecInput {
  readonly host: ShellHost;
  readonly command: string;
  readonly timeoutSeconds?: number;
}

export interface ShellExecResult {
  readonly stdout: string;
  readonly stderr: string;
  readonly exitCode: number | null;
  readonly timedOut: boolean;
}

export interface SshShellRunnerOptions {
  readonly sshKeyPath: string;
  readonly sshUser: string;
  /** Test-only injection point, mirrors provider-factory.ts's fetchImpl pattern. */
  readonly spawnImpl?: typeof nodeSpawn;
  readonly outputLimitBytes?: number;
}

const DEFAULT_TIMEOUT_SECONDS = 120;
const MAX_TIMEOUT_SECONDS = 600;
const DEFAULT_OUTPUT_LIMIT_BYTES = 1024 * 1024;

/**
 * Defense-in-depth command rejection. NOT a substitute for the OS-level
 * no-sudo kagent-builder account -- a cheap extra layer in case that
 * account is ever misconfigured.
 */
const FORBIDDEN_PATTERNS: readonly { readonly pattern: RegExp; readonly reason: string }[] = [
  { pattern: /\bsudo\b/, reason: 'sudo' },
  { pattern: /authorized_keys/, reason: 'authorized_keys' },
  { pattern: /rm\s+-rf\s+\/(?!\S)/, reason: 'rm -rf /' },
  { pattern: /:\(\)\s*\{\s*:\|:&\s*\}\s*;\s*:/, reason: 'fork bomb' },
];

export class SshShellRunner {
  private readonly sshKeyPath: string;
  private readonly sshUser: string;
  private readonly spawnImpl: typeof nodeSpawn;
  private readonly outputLimitBytes: number;

  constructor(options: SshShellRunnerOptions) {
    this.sshKeyPath = options.sshKeyPath;
    this.sshUser = options.sshUser;
    this.spawnImpl = options.spawnImpl ?? nodeSpawn;
    this.outputLimitBytes = options.outputLimitBytes ?? DEFAULT_OUTPUT_LIMIT_BYTES;
  }

  async exec(input: ShellExecInput): Promise<ShellExecResult> {
    const ip = this.assertHostAllowed(input.host);
    this.assertCommandAllowed(input.command);
    const timeoutSeconds = this.clampTimeout(input.timeoutSeconds);

    return this.spawnSsh(ip, input.command, timeoutSeconds);
  }

  private assertHostAllowed(host: string): string {
    const ip = (HOST_IPS as Record<string, string | undefined>)[host];
    if (ip === undefined) {
      throw new Error(
        `policy_denied: unknown shell.exec host "${host}" (allowed: ${Object.keys(HOST_IPS).join(', ')})`,
      );
    }
    return ip;
  }

  private assertCommandAllowed(command: string): void {
    for (const { pattern, reason } of FORBIDDEN_PATTERNS) {
      if (pattern.test(command)) {
        throw new Error(`policy_denied: command matches forbidden pattern "${reason}"`);
      }
    }
  }

  private clampTimeout(requested: number | undefined): number {
    if (requested === undefined) return DEFAULT_TIMEOUT_SECONDS;
    return Math.min(Math.max(1, Math.floor(requested)), MAX_TIMEOUT_SECONDS);
  }

  private spawnSsh(ip: string, command: string, timeoutSeconds: number): Promise<ShellExecResult> {
    const args = [
      '-i',
      this.sshKeyPath,
      '-o',
      'StrictHostKeyChecking=accept-new',
      '-o',
      'BatchMode=yes',
      `${this.sshUser}@${ip}`,
      `timeout ${timeoutSeconds}s ${command}`,
    ];

    const child = this.spawnImpl('ssh', args, { shell: false });

    let stdout = '';
    let stderr = '';

    return new Promise<ShellExecResult>((resolveResult, reject) => {
      child.stdout.on('data', (chunk: Buffer) => {
        stdout = this.appendBounded(stdout, chunk.toString('utf8'));
      });
      child.stderr.on('data', (chunk: Buffer) => {
        stderr = this.appendBounded(stderr, chunk.toString('utf8'));
      });
      child.on('error', reject);
      child.on('close', (exitCode) => {
        resolveResult({
          stdout,
          stderr,
          exitCode,
          // The remote `timeout` wrapper exits 124 on its own timeout;
          // ssh's local process isn't killed by us at all here (unlike
          // code-runner.ts's local spawn, this process runs over network
          // I/O and the remote timeout is the authoritative bound).
          timedOut: exitCode === 124,
        });
      });
    });
  }

  private appendBounded(current: string, next: string): string {
    const combined = current + next;
    if (Buffer.byteLength(combined, 'utf8') <= this.outputLimitBytes) return combined;
    return combined.slice(0, this.outputLimitBytes);
  }
}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /tmp/kagent-src-check/packages/tool-gateway && pnpm test -- shell-runner.test.ts
```
Expected: PASS, all 6 tests.

- [ ] **Step 5: Typecheck and lint this package**

```bash
cd /tmp/kagent-src-check/packages/tool-gateway && pnpm typecheck && pnpm lint
```
Expected: both clean. If `@ts-expect-error` in the test causes an "unused directive" lint/type error because the runtime guard makes the call fail before the type system would've complained, adjust the test to cast through `unknown` instead (`{ host: 'elitemini' as unknown as 'elitemini2', command: 'echo hi' }`) — whichever compiles cleanly, the intent (prove the *runtime* guard rejects an invalid host string) is what matters, not the exact suppression mechanism.

- [ ] **Step 6: Commit**

```bash
cd /tmp/kagent-src-check
git add packages/tool-gateway/src/shell-runner.ts packages/tool-gateway/src/shell-runner.test.ts
git commit -m "feat(tool-gateway): add SshShellRunner (elitemini2/jetson2 only)"
```

---

### Task 3: Wire `shell.exec` into the tool-gateway HTTP handler

**Files:**
- Modify: `packages/tool-gateway/src/http-server.ts`
- Modify: `packages/tool-gateway/src/http-server.test.ts`
- Modify: `packages/tool-gateway/src/server.ts`
- Modify: `packages/tool-gateway/src/server.test.ts`

**Interfaces:**
- Consumes: `SshShellRunner` from Task 2 (`exec(input): Promise<ShellExecResult>`), `isToolRuntimeTool`/`ToolRuntimeToolName` from Task 1 (now includes `'shell.exec'`).
- Produces: `ToolGatewayHttpHandlerOptions.shellRunner?: ToolGatewayShellRunner`; the gateway now advertises and executes `shell.exec` wherever it's listed in an Agent's tool profile.

- [ ] **Step 1: Write the failing test**

Add to `packages/tool-gateway/src/http-server.test.ts` (find the existing `describe('ToolGatewayHttpHandler', ...)` block and add inside it — match whatever existing test constructs a handler with `codeRunner` for its pattern):

```ts
  it('dispatches shell.exec to the injected shell runner and returns stdout as content', async () => {
    const shellRunner = {
      exec: vi.fn().mockResolvedValue({
        stdout: 'hi\n',
        stderr: '',
        exitCode: 0,
        timedOut: false,
      }),
    };
    const handler = new ToolGatewayHttpHandler({ shellRunner });

    const response = await handler.handle(
      makeInvokeRequest({
        task: sampleTask,
        call: { id: 'call-1', name: 'shell.exec', args: { host: 'jetson2', command: 'echo hi' } },
      }),
    );
    const body = (await response.json()) as { content: string; isError: boolean };

    expect(shellRunner.exec).toHaveBeenCalledWith({ host: 'jetson2', command: 'echo hi' });
    expect(body.isError).toBe(false);
    expect(body.content).toContain('hi');
  });

  it('describes shell.exec with a closed host enum in its input schema', async () => {
    const handler = new ToolGatewayHttpHandler({});
    const response = await handler.handle(
      makeDescribeRequest({ task: sampleTask, toolNames: ['shell.exec'], toolProfileRefs: [] }),
    );
    const body = (await response.json()) as { tools: { name: string; inputSchema: unknown }[] };

    expect(body.tools).toHaveLength(1);
    expect(body.tools[0]?.name).toBe('shell.exec');
    expect(JSON.stringify(body.tools[0]?.inputSchema)).toContain('elitemini2');
    expect(JSON.stringify(body.tools[0]?.inputSchema)).toContain('jetson2');
  });
```

Check the top of `http-server.test.ts` for existing helpers named `makeInvokeRequest`/`makeDescribeRequest`/`sampleTask` (or whatever the actual existing helper names are — this file already has tests for `code_interpreter.execute_command` and `browser.goto` dispatch that build requests the same way; reuse those exact helpers rather than inventing new ones). If the existing helpers have different names, use those names instead of the ones shown above, keeping the test bodies the same shape.

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /tmp/kagent-src-check/packages/tool-gateway && pnpm test -- http-server.test.ts
```
Expected: FAIL — `shellRunner` option not recognized / `shell.exec` returns `unknown runtime tool`.

- [ ] **Step 3: Implement — add the shell runner option and interface**

In `packages/tool-gateway/src/http-server.ts`, add near the top (after the `ToolGatewayCodeRunner` interface):

```ts
export interface ToolGatewayShellRunner {
  readonly exec: (input: {
    readonly host: 'elitemini2' | 'jetson2';
    readonly command: string;
    readonly timeoutSeconds?: number;
  }) => Promise<{
    readonly stdout: string;
    readonly stderr: string;
    readonly exitCode: number | null;
    readonly timedOut: boolean;
  }>;
}
```

Add `shellRunner?: ToolGatewayShellRunner;` to `ToolGatewayHttpHandlerOptions`, and a `private readonly shellRunner: ToolGatewayShellRunner | undefined;` field, set in the constructor: `this.shellRunner = options.shellRunner;`.

- [ ] **Step 4: Implement — dispatch case + handler method**

In `invokeRuntimeTool`'s switch, add a case right before `default:`:

```ts
      case 'shell.exec':
        return this.execShell(invocation.call.args);
```

Add the handler method (place it near `executeCommand`):

```ts
  private async execShell(args: unknown): Promise<ToolResult> {
    if (this.shellRunner === undefined) {
      return { content: 'shell.exec is not configured on this gateway', isError: true };
    }
    const input = parseShellExecInput(args);
    if (input === null) return invalidArgs('shell.exec');

    try {
      const result = await this.shellRunner.exec(input);
      return {
        content: result.stdout.length > 0 ? result.stdout : result.stderr,
        isError: result.exitCode !== 0,
        metadata: { stderr: result.stderr, exitCode: result.exitCode, timedOut: result.timedOut },
      };
    } catch (err) {
      return { content: err instanceof Error ? err.message : String(err), isError: true };
    }
  }
```

Add the parser near the other `parse*Input` functions (match `parseExecuteCommandInput`'s exact style/location):

```ts
function parseShellExecInput(
  args: unknown,
): { host: 'elitemini2' | 'jetson2'; command: string; timeoutSeconds?: number } | null {
  if (!isRecord(args) || typeof args.command !== 'string' || args.command.length === 0) {
    return null;
  }
  if (args.host !== 'elitemini2' && args.host !== 'jetson2') return null;
  const out: { host: 'elitemini2' | 'jetson2'; command: string; timeoutSeconds?: number } = {
    host: args.host,
    command: args.command,
  };
  if (typeof args.timeoutSeconds === 'number') out.timeoutSeconds = args.timeoutSeconds;
  return out;
}
```

- [ ] **Step 5: Fix the now-non-exhaustive descriptor switches**

```bash
cd /tmp/kagent-src-check && pnpm --filter @kagent/tool-gateway typecheck 2>&1 | head -30
```

This will report every `switch (name: ToolRuntimeToolName)` that doesn't handle `'shell.exec'` — expect `runtimeToolDescription`, `runtimeToolInputSchema`, and `runtimeToolTags` in `http-server.ts` (the same three functions this plan read in full during design). Add one case to each:

In `runtimeToolDescription`:
```ts
    case 'shell.exec':
      return 'Run a shell command over SSH on a specific homelab node (elitemini2 or jetson2 only).';
```

In `runtimeToolInputSchema`:
```ts
    case 'shell.exec':
      return objectSchema(
        {
          host: { type: 'string', enum: ['elitemini2', 'jetson2'] },
          command: { type: 'string', minLength: 1 },
          timeoutSeconds: { type: 'number', minimum: 1, maximum: 600 },
        },
        ['host', 'command'],
      );
```

In `runtimeToolTags`, check the existing function body (already read during design — it branches on `.endsWith('.terminate_session')` and a couple other suffix/prefix checks with a final fallback return). Add before the final fallback:
```ts
    if (name === 'shell.exec') return ['destructive'];
```

Re-run typecheck until clean:
```bash
pnpm --filter @kagent/tool-gateway typecheck
```

- [ ] **Step 6: Wire real SSH config in `server.ts`**

In `packages/tool-gateway/src/server.ts`, add to imports:
```ts
import { SshShellRunner } from './shell-runner.js';
```

Add two fields to `ToolGatewayServerConfig`:
```ts
  readonly shellSshKeyPath?: string;
  readonly shellSshUser?: string;
```

In `parseToolGatewayServerConfig`, add:
```ts
  const shellSshKeyPath = nonEmpty(env.KAGENT_SHELL_SSH_KEY_PATH);
  const shellSshUser = nonEmpty(env.KAGENT_SHELL_SSH_USER);
  if (shellSshKeyPath !== undefined) config.shellSshKeyPath = shellSshKeyPath;
  if (shellSshUser !== undefined) config.shellSshUser = shellSshUser;
```
(add `shellSshKeyPath`/`shellSshUser` as optional fields on the local `config` object literal's type annotation alongside the existing optional steel fields).

In `buildToolGatewayHandler`, before `const options: ToolGatewayHttpHandlerOptions = {`, add:
```ts
  let shellRunner: SshShellRunner | undefined;
  if (config.shellSshKeyPath !== undefined && config.shellSshUser !== undefined) {
    shellRunner = new SshShellRunner({
      sshKeyPath: config.shellSshKeyPath,
      sshUser: config.shellSshUser,
    });
  }
```
and add `...(shellRunner !== undefined && { shellRunner }),` to the `options` object literal.

- [ ] **Step 7: Add server-config test coverage**

Add to `packages/tool-gateway/src/server.test.ts` (find the existing `describe('parseToolGatewayServerConfig', ...)` block):

```ts
  it('parses shell SSH config from env when both vars are present', () => {
    const config = parseToolGatewayServerConfig({
      KAGENT_SHELL_SSH_KEY_PATH: '/secrets/kagent-builder-ssh-key/id_ed25519',
      KAGENT_SHELL_SSH_USER: 'kagent-builder',
    });
    expect(config.shellSshKeyPath).toBe('/secrets/kagent-builder-ssh-key/id_ed25519');
    expect(config.shellSshUser).toBe('kagent-builder');
  });

  it('leaves shell SSH config undefined when env vars are absent', () => {
    const config = parseToolGatewayServerConfig({});
    expect(config.shellSshKeyPath).toBeUndefined();
    expect(config.shellSshUser).toBeUndefined();
  });
```

- [ ] **Step 8: Run full package test + typecheck + lint**

```bash
cd /tmp/kagent-src-check/packages/tool-gateway
pnpm test && pnpm typecheck && pnpm lint
```
Expected: all clean.

- [ ] **Step 9: Commit**

```bash
cd /tmp/kagent-src-check
git add packages/tool-gateway/src/http-server.ts packages/tool-gateway/src/http-server.test.ts \
        packages/tool-gateway/src/server.ts packages/tool-gateway/src/server.test.ts
git commit -m "feat(tool-gateway): dispatch shell.exec through SshShellRunner"
```

---

### Task 3.5: Fix packages/agent-pod's own shell.exec exhaustive-switch break

**Added during execution, not in the original spec.** Task 1's enum extension
(`ToolRuntimeToolName` now includes `'shell.exec'`) breaks an exhaustive
switch in `packages/agent-pod` exactly the way it broke `packages/tool-gateway`
in Task 3 — but the original plan only scoped Task 3 to `packages/tool-gateway`.
Left unfixed, every subsequent commit needs `--no-verify` and Task 4's
release gate (which requires a clean `pnpm -r typecheck`) cannot pass. This
task closes that gap.

**Files:**
- Modify: `packages/agent-pod/src/tool-gateway-provider.ts`

**Interfaces:**
- Consumes: `SHELL_TOOL_NAMES` from `@kagent/dto` (already exported since Task 1).
- Produces: `packages/agent-pod` typechecks cleanly again.

- [ ] **Step 1: Add `SHELL_TOOL_NAMES` to the descriptor-building array**

In `packages/agent-pod/src/tool-gateway-provider.ts`, add `SHELL_TOOL_NAMES` to
the import from `@kagent/dto` (alongside the existing `BROWSER_TOOL_NAMES`,
`CODE_INTERPRETER_TOOL_NAMES` import). Change:
```ts
const RUNTIME_TOOL_DESCRIPTORS: Record<ToolRuntimeToolName, ToolDescriptor> = Object.fromEntries(
  [...BROWSER_TOOL_NAMES, ...CODE_INTERPRETER_TOOL_NAMES].map((name) => [
    name,
    descriptorForRuntimeTool(name),
  ]),
) as Record<ToolRuntimeToolName, ToolDescriptor>;
```
to:
```ts
const RUNTIME_TOOL_DESCRIPTORS: Record<ToolRuntimeToolName, ToolDescriptor> = Object.fromEntries(
  [...BROWSER_TOOL_NAMES, ...CODE_INTERPRETER_TOOL_NAMES, ...SHELL_TOOL_NAMES].map((name) => [
    name,
    descriptorForRuntimeTool(name),
  ]),
) as Record<ToolRuntimeToolName, ToolDescriptor>;
```

- [ ] **Step 2: Add a `'shell.exec'` case to `runtimeToolDescription`**

This function (the one `tsc` reports as broken, at its current line ~229) has
no `default` case — read its current content and add, following the exact
style of its existing cases:
```ts
    case 'shell.exec':
      return 'Run a shell command over SSH on a specific homelab node (elitemini2 or jetson2 only).';
```

- [ ] **Step 3: Add a `'shell.exec'` case to `runtimeToolInputSchema`**

Read this function's current content (it also switches over
`ToolRuntimeToolName` and will need a case). Add, matching the `objectSchema`
style of its sibling cases:
```ts
    case 'shell.exec':
      return objectSchema(
        {
          host: { type: 'string', enum: ['elitemini2', 'jetson2'] },
          command: { type: 'string', minLength: 1 },
          timeoutSeconds: { type: 'number', minimum: 1, maximum: 600 },
        },
        ['host', 'command'],
      );
```

- [ ] **Step 4: Add `'shell.exec'` to `runtimeToolTags`**

This function is an if-chain (not a switch) that returns `['destructive',
'idempotent']`, `['read-only']`, or `[]`. `shell.exec` is neither — it's
destructive-adjacent (runs arbitrary commands) but not idempotent and not a
terminate/stop operation. Add a branch before the final `return []`:
```ts
  if (name === 'shell.exec') return ['destructive'];
```

- [ ] **Step 5: Verify**

```bash
source ~/.nvm/nvm.sh && nvm use 22
cd /tmp/kagent-src-check
pnpm --filter @kagent/agent-pod typecheck
pnpm --filter @kagent/agent-pod test
pnpm --filter @kagent/agent-pod lint
```
Expected: all clean. Then confirm the workspace-wide picture:
```bash
pnpm -r typecheck 2>&1 | tail -20
```
Expected: no remaining failures anywhere (this was the last known gap).

- [ ] **Step 6: Commit — should NOT need `--no-verify` this time**

```bash
git add packages/agent-pod/src/tool-gateway-provider.ts
git commit -m "fix(agent-pod): handle shell.exec in exhaustive tool-descriptor switches"
```
If the pre-commit hook still fails, that means either this fix is incomplete
or a genuinely new, unrelated problem exists — do not bypass, investigate.

---

### Task 4: Full-workspace verification, tag, and release

**Files:** none (verification + release only)

- [ ] **Step 1: Full workspace test + typecheck + lint**

```bash
source ~/.nvm/nvm.sh && nvm use 22
cd /tmp/kagent-src-check
pnpm -r test 2>&1 | tail -20
pnpm -r typecheck 2>&1 | tail -40
pnpm -r lint 2>&1 | tail -40
```
Expected: all green. Pay particular attention to `packages/agent-pod` and `packages/openai-compat` — anything importing `ToolRuntimeToolName` exhaustively elsewhere would surface here.

- [ ] **Step 2: Tag and push**

```bash
git tag -a v0.2.31-shell-tool-rc.1 -m "feat(tool-gateway): shell.exec (elitemini2/jetson2 SSH)"
git push origin main
git push origin v0.2.31-shell-tool-rc.1
```

- [ ] **Step 3: Watch CI**

```bash
gh run list --limit 3
gh run watch <run-id-for-v0.2.31-shell-tool-rc.1> --interval 20 --exit-status
```
Expected: `Install + Typecheck + Lint + Test + Build + Format`, `Build + sign + SBOM (tool-gateway)` succeed. (The pre-existing unrelated `tool-gateway` job flake seen earlier this session was actually about a *different* image also named similarly in build matrix noise — if `Build + sign + SBOM (tool-gateway)` itself fails this time, that's the one that matters and must be fixed, not shrugged off; re-check the failing step's logs before assuming it's the old flake.)

- [ ] **Step 4: Verify the image published**

```bash
gh api /orgs/ctkadvisors/packages/container/kagent-tool-gateway/versions \
  --jq '.[] | select(.metadata.container.tags[]? == "v0.2.31-shell-tool-rc.1") | .metadata.container.tags'
```
Expected: an array containing `"v0.2.31-shell-tool-rc.1"`.

---

### Task 5: Manual node provisioning (elitemini2 + jetson2) — run interactively, not unattended

**Files:**
- Create: `docs/runbooks/kagent-builder-node-setup.md` (this repo)

This task touches two real, running machines outside Kubernetes entirely. It is **not** GitOps-managed and must not be scripted into an unattended agent run — run each command yourself, confirming output at each step, the same way `spark-llamaswap.yaml`'s Endpoints object is a documented manual `kubectl apply` rather than something ArgoCD reconciles.

- [ ] **Step 1: Generate the dedicated keypair (on your Mac, not on either node)**

```bash
ssh-keygen -t ed25519 -f /private/tmp/claude-501/kagent-builder-ed25519 -N "" -C "kagent-builder@homelab"
```
Expected: `/private/tmp/claude-501/kagent-builder-ed25519` (private) and `.pub` (public) created. Confirm neither is your personal key (`ls -la ~/.ssh/` should show this is a brand new file elsewhere).

- [ ] **Step 2: Create the `kagent-builder` user on elitemini2**

```bash
ssh elitemini2 "sudo useradd --create-home --shell /bin/bash --comment 'kagent homelab-builder agent' kagent-builder"
ssh elitemini2 "sudo -u kagent-builder mkdir -p /home/kagent-builder/.ssh && sudo -u kagent-builder chmod 700 /home/kagent-builder/.ssh"
cat /private/tmp/claude-501/kagent-builder-ed25519.pub | ssh elitemini2 "sudo tee -a /home/kagent-builder/.ssh/authorized_keys > /dev/null"
ssh elitemini2 "sudo chown kagent-builder:kagent-builder /home/kagent-builder/.ssh/authorized_keys && sudo chmod 600 /home/kagent-builder/.ssh/authorized_keys"
```
Expected: no errors. Verify no sudoers entry exists for this user:
```bash
ssh elitemini2 "sudo -l -U kagent-builder"
```
Expected output should indicate the user is not permitted to run any commands as root (exact wording varies by sudo version, but it must NOT list any allowed commands).

- [ ] **Step 3: Repeat step 2 on jetson2**

```bash
ssh jetson2 "sudo useradd --create-home --shell /bin/bash --comment 'kagent homelab-builder agent' kagent-builder"
ssh jetson2 "sudo -u kagent-builder mkdir -p /home/kagent-builder/.ssh && sudo -u kagent-builder chmod 700 /home/kagent-builder/.ssh"
cat /private/tmp/claude-501/kagent-builder-ed25519.pub | ssh jetson2 "sudo tee -a /home/kagent-builder/.ssh/authorized_keys > /dev/null"
ssh jetson2 "sudo chown kagent-builder:kagent-builder /home/kagent-builder/.ssh/authorized_keys && sudo chmod 600 /home/kagent-builder/.ssh/authorized_keys"
ssh jetson2 "sudo -l -U kagent-builder"
```

- [ ] **Step 4: Add a systemd cgroup resource cap on both hosts**

This is the killswitch that matters for `shell.exec` — the actual compute happens over SSH on the node, not inside a k8s pod, so pod resource limits don't cover it.

On each host (`elitemini2`, then `jetson2`):
```bash
ssh <host> "sudo mkdir -p /etc/systemd/system/user-\$(id -u kagent-builder).slice.d"
cat <<'EOF' | ssh <host> "sudo tee /etc/systemd/system/user-\$(ssh <host> id -u kagent-builder).slice.d/10-kagent-builder-cap.conf > /dev/null"
[Slice]
CPUQuota=200%
MemoryMax=4G
MemoryHigh=3G
EOF
ssh <host> "sudo systemctl daemon-reload"
```
(Run this with the literal host substituted in each `<host>` position — do not leave `<host>` as shell text; e.g. for elitemini2 every `<host>` becomes `elitemini2`.)

Verify it applies once `kagent-builder` has an active session (this can only be confirmed after Task 9's smoke test actually SSHes in): `systemctl status user-$(ssh elitemini2 id -u kagent-builder).slice` should show `CPUQuota=200%` and `MemoryMax=4G` in `systemctl show`.

- [ ] **Step 5: Write the runbook doc**

Create `docs/runbooks/kagent-builder-node-setup.md` containing exactly the commands from Steps 1–4 above (this is the durable record of what was done manually — the point of writing it down is so the next person, or you in six months, doesn't have to reconstruct it from a chat transcript).

- [ ] **Step 6: Commit the runbook (not the keys)**

```bash
git add docs/runbooks/kagent-builder-node-setup.md
git commit -m "docs(runbooks): kagent-builder node provisioning (elitemini2, jetson2)"
```

Confirm the private key file is NOT inside this repo's working tree before committing (`git status` should show nothing from `/private/tmp/claude-501/`) — it belongs only in the Secret created in Task 6.

---

### Task 6: Sealed Secrets for the SSH key and git push credential

**Files:**
- Create: `k8s-kustomized/overlays/production/kagent/homelab-builder-secrets.yaml`

**Interfaces:**
- Produces: `Secret/kagent-builder-ssh-key` (key `id_ed25519`) and `Secret/kagent-builder-git-token` (key `token`) in `kagent-system`, consumed by Task 7's Agent CR volume mounts / env.

- [ ] **Step 1: Generate a dedicated git push credential**

Not the user's personal GitHub PAT. Create a fine-grained GitHub token scoped to `ctkadvisors/new_localai` only, contents write, via `gh auth token` guidance or the GitHub UI (Settings → Developer settings → Fine-grained tokens) — this step is a manual action outside this codebase; record that it was done, don't paste the token into any file this plan writes.

- [ ] **Step 2: Write the Secret manifest**

Follow this repo's established plaintext-in-git posture for kagent Secrets in this same directory (see `channel-control.yaml`'s header comment: "plaintext-in-git is acceptable for this single-user, Tailscale-bound cluster"). Create `k8s-kustomized/overlays/production/kagent/homelab-builder-secrets.yaml`:

```yaml
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Chris Knuteson
#
# Credentials for the homelab-builder Agent's shell.exec tool (SSH to
# elitemini2/jetson2 as the kagent-builder OS user provisioned per
# docs/runbooks/kagent-builder-node-setup.md) and its git-push-to-main
# capability.
#
# Secret posture matches the existing kagent homelab Secrets in this
# directory (see channel-control.yaml): plaintext-in-git is acceptable
# for this single-user, Tailscale-bound cluster. Rotate the SSH key by
# re-running ssh-keygen, updating authorized_keys on both nodes per the
# runbook, and replacing stringData.id_ed25519 below.
---
apiVersion: v1
kind: Secret
metadata:
  name: kagent-builder-ssh-key
  namespace: kagent-system
  labels:
    app.kubernetes.io/name: kagent-homelab-builder
    app.kubernetes.io/managed-by: argocd
  annotations:
    argocd.argoproj.io/sync-wave: '5'
type: Opaque
stringData:
  id_ed25519: |
    REPLACE_WITH_CONTENTS_OF_kagent-builder-ed25519_PRIVATE_KEY
---
apiVersion: v1
kind: Secret
metadata:
  name: kagent-builder-git-token
  namespace: kagent-system
  labels:
    app.kubernetes.io/name: kagent-homelab-builder
    app.kubernetes.io/managed-by: argocd
  annotations:
    argocd.argoproj.io/sync-wave: '5'
type: Opaque
stringData:
  token: 'REPLACE_WITH_FINE_GRAINED_GITHUB_TOKEN'
```

Replace both `REPLACE_WITH_*` placeholders with the real values from Steps 1 and Task 5 Step 1 before committing — `git diff --staged` should show no literal `REPLACE_WITH_` string remaining in this file at commit time.

- [ ] **Step 2: Add to kustomization**

In `k8s-kustomized/overlays/production/kagent/kustomization.yaml`, add `- homelab-builder-secrets.yaml` to the `resources:` list (Task 7 adds the Agent CR file to the same list in one pass — do both edits together since they land in the same commit).

- [ ] **Step 3: Validate render (secrets present, no placeholder strings leaked)**

```bash
kubectl kustomize k8s-kustomized/overlays/production > /tmp/kagent-render-builder.yaml
grep -c "REPLACE_WITH_" /tmp/kagent-render-builder.yaml
```
Expected: `0`.

```bash
grep -A3 "name: kagent-builder-ssh-key" /tmp/kagent-render-builder.yaml
grep -A3 "name: kagent-builder-git-token" /tmp/kagent-render-builder.yaml
```
Expected: both Secrets present with real (non-placeholder) `stringData`.

(Commit happens together with Task 7 — one PR-sized change for "add homelab-builder", not two half-applied commits where the Secret exists without anything consuming it yet.)

---

### Task 7: `homelab-builder` Agent CR + `builder-shell` tool profile + NetworkPolicy

**Files:**
- Create: `k8s-kustomized/overlays/production/kagent/homelab-builder-agent.yaml`
- Modify: `k8s-kustomized/overlays/production/kagent/application.yaml`
- Modify: `k8s-kustomized/overlays/production/kagent/kustomization.yaml`
- Modify: `k8s/argocd-apps/kagent-app.yaml` (mirror)

**Interfaces:**
- Consumes: `Secret/kagent-builder-ssh-key`, `Secret/kagent-builder-git-token` (Task 6); `tool-caller-spark-qwen` modelClass (already exists from the earlier Telegram/Spark work this session); `ghcr.io/ctkadvisors/kagent-tool-gateway:v0.2.31-shell-tool-rc.1` (Task 4).
- Produces: `Agent/homelab-builder` for Task 8's `allowedChildAgents` to reference by name.

- [ ] **Step 1: Add the `builder-shell` tool profile + shell env vars to `application.yaml`**

In `k8s-kustomized/overlays/production/kagent/application.yaml`, find the existing `toolRuntime:` block (has `gateway.toolProfiles: [{ name: browser-code-researcher, ... }]`). Add a second profile entry to the same `toolProfiles:` list:

```yaml
              - name: builder-shell
                description: Shell/SSH + browser/code runtime profile for the homelab-builder agent.
                tools:
                  - shell.exec
                  - code_interpreter.execute_code
                  - browser.start_session
                  - browser.goto
                  - browser.extract_text
```

Bump the tool-gateway image tag. Find the existing `toolRuntime.gateway.image.tag` line (`'v0.2.16-gateway-tool-profiles-rc.1'` per this session's earlier reading) and change it:
```yaml
          gateway:
            image:
              tag: 'v0.2.31-shell-tool-rc.1'
```

Add the shell SSH env vars. Check whether the chart exposes a generic `gateway.env`/`extraEnv` values key (search the chart templates at `packages/operator/charts/kagent-operator/templates/` in `/tmp/kagent-src-check` for how `KAGENT_STEEL_BASE_URL` gets templated from `toolRuntime.browser.steel` values, and mirror that exact mechanism for `KAGENT_SHELL_SSH_KEY_PATH`/`KAGENT_SHELL_SSH_USER`/the ssh-key volume mount). If the chart has no generic passthrough, this sub-step becomes its own small chart change in the kagent repo (a `toolRuntime.gateway.shell` values block analogous to `toolRuntime.browser.steel`, templated into env vars + a volume mount for `Secret/kagent-builder-ssh-key`) — fold that into Task 3 instead if discovered before Task 4's release tag, since it needs to ship in the same image release.

- [ ] **Step 2: Write the Agent CR**

Create `k8s-kustomized/overlays/production/kagent/homelab-builder-agent.yaml`:

```yaml
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Chris Knuteson
#
# homelab-builder — spawned exclusively as a child of operator-investigator
# via spawn_child_task (see operator-investigator-agent.yaml's
# allowedChildAgents). Never bound directly to a Channel. Has shell.exec
# (SSH to elitemini2/jetson2 as the low-priv kagent-builder OS user, see
# docs/runbooks/kagent-builder-node-setup.md) plus code/browser tools, and
# can push straight to main for GitOps changes.
---
apiVersion: kagent.example.com/v1alpha1
kind: Agent
metadata:
  name: homelab-builder
  namespace: kagent-system
  annotations:
    argocd.argoproj.io/sync-wave: '8'
  labels:
    kagent.example.com/role: builder
    kagent.example.com/tenant: homelab
spec:
  agentType: homelab-builder
  toolProfileRef: builder-shell
  modelClass: tool-caller-spark-qwen
  llmParams:
    temperature: 0
    maxTokens: 1800
  maxConcurrentChildren: 0
  maxRestarts: 0
  sandboxProfile: default
  supervisionStrategy: one_for_one
  systemPrompt: |
    You are the homelab-builder agent. You were spawned by
    operator-investigator because a request needs real execution: writing
    code, running shell commands on elitemini2 or jetson2, building/pushing
    container images, or pushing GitOps changes to this cluster's config
    repo (ctkadvisors/new_localai, main branch -- push directly, no PR
    needed).

    Tools:
    - shell.exec(host, command, timeoutSeconds?) -- host must be exactly
      "elitemini2" or "jetson2". You are a low-privilege user with no
      sudo; do not attempt sudo, it will not work.
    - code_interpreter.execute_code -- JavaScript only for local scratch
      work before pushing.
    - browser.* -- for reading docs/dashboards if needed.

    Discipline:
    - State your plan in one or two sentences before executing it.
    - Prefer a small number of larger shell.exec calls over many tiny ones.
    - If a command fails, read stderr and adjust -- don't repeat the exact
      same failing command.
    - When done, report concretely what you did: commands run, exit codes,
      files changed, what was pushed and to where.
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: homelab-builder-egress
  namespace: kagent-system
  labels:
    kagent.example.com/role: builder
spec:
  podSelector:
    matchLabels:
      kagent.example.com/agent-name: homelab-builder
  policyTypes:
    - Egress
  egress:
    # DNS
    - to:
        - namespaceSelector: {}
          podSelector:
            matchLabels:
              k8s-app: kube-dns
      ports:
        - protocol: UDP
          port: 53
        - protocol: TCP
          port: 53
    # In-cluster LLM gateway (same as every other agent-pod)
    - to:
        - podSelector:
            matchLabels:
              app.kubernetes.io/name: kagent-llm-gateway
      ports:
        - protocol: TCP
          port: 4000
    # SSH to elitemini2 and jetson2 only -- not a broader CIDR, not the
    # control-plane node.
    - to:
        - ipBlock:
            cidr: 10.0.0.74/32
        - ipBlock:
            cidr: 10.0.0.75/32
      ports:
        - protocol: TCP
          port: 22
    # git push targets: GitHub (this infra repo) and the self-hosted
    # Gitea (generated-project repos).
    - to:
        - ipBlock:
            cidr: 0.0.0.0/0
      ports:
        - protocol: TCP
          port: 443
    - to:
        - ipBlock:
            cidr: 10.0.0.76/32
      ports:
        - protocol: TCP
          port: 3000
        - protocol: TCP
          port: 22
```

Note on the `podSelector` label (`kagent.example.com/agent-name: homelab-builder`): verify this is the actual label the operator stamps onto spawned agent-pod Jobs by checking `packages/operator/src/main.ts` or `packages/agent-pod/src/k8s-task-creator.ts` for the literal label key used (this plan infers the name from convention but hasn't confirmed the exact key against source — confirm before relying on it, adjust the NetworkPolicy's `matchLabels` key to whatever is actually stamped if different).

- [ ] **Step 3: Add both new files to the kustomization**

In `k8s-kustomized/overlays/production/kagent/kustomization.yaml`, add:
```yaml
  - homelab-builder-secrets.yaml
  - homelab-builder-agent.yaml
```

- [ ] **Step 4: Validate render**

```bash
kubectl kustomize k8s-kustomized/overlays/production > /tmp/kagent-render-builder2.yaml
grep -n "name: homelab-builder\|name: homelab-builder-egress\|builder-shell" /tmp/kagent-render-builder2.yaml
```
Expected: the Agent, NetworkPolicy, and tool profile all present with no YAML errors (command exits 0).

- [ ] **Step 5: Mirror to legacy copy and commit**

```bash
cp k8s-kustomized/overlays/production/kagent/application.yaml k8s/argocd-apps/kagent-app.yaml
git add k8s-kustomized/overlays/production/kagent/homelab-builder-secrets.yaml \
        k8s-kustomized/overlays/production/kagent/homelab-builder-agent.yaml \
        k8s-kustomized/overlays/production/kagent/application.yaml \
        k8s-kustomized/overlays/production/kagent/kustomization.yaml \
        k8s/argocd-apps/kagent-app.yaml
git commit -m "feat(kagent): add homelab-builder Agent (shell.exec, elitemini2+jetson2 only)"
```

Do not push yet — Task 8 and Task 9's changes land in the same push so `operator-investigator` and `homelab-builder` reconcile together (a lone `homelab-builder` with nothing able to spawn it, or a lone `allowedChildAgents` pointing at a not-yet-existent Agent, are both fine individually, but there's no reason to split the push into two ArgoCD sync cycles for one cohesive feature).

---

### Task 8: `operator-investigator` — `allowedChildAgents` + prompt update

**Files:**
- Modify: `k8s-kustomized/overlays/production/kagent/operator-investigator-agent.yaml`

**Interfaces:**
- Consumes: `Agent/homelab-builder` (Task 7) by name.

- [ ] **Step 1: Add `allowedChildAgents`**

In `operator-investigator-agent.yaml`, add to `spec:` (after `modelClass:`):
```yaml
  allowedChildAgents:
    - homelab-builder
```

- [ ] **Step 2: Extend the system prompt**

After the existing `"For investigation requests: ..."` paragraph (added earlier this session) and before the `"Useful in-cluster Workbench API endpoints:"` line, insert:

```yaml
    If the request needs real execution -- writing and deploying code,
    running shell commands on a cluster node, building/pushing a container
    image, or pushing a GitOps change -- do not attempt it yourself. Call
    spawn_child_task with agentName "homelab-builder" and a clear
    originalUserMessage describing exactly what's needed. Relay its result
    back to the user once it completes. You have no shell access yourself
    and should never claim to have run a command directly.

```

- [ ] **Step 3: Validate render**

```bash
kubectl kustomize k8s-kustomized/overlays/production > /tmp/kagent-render-builder3.yaml
grep -A2 "allowedChildAgents" /tmp/kagent-render-builder3.yaml
```
Expected: shows `- homelab-builder` under `operator-investigator`'s spec.

- [ ] **Step 4: Commit (staged, not pushed — see Task 9)**

```bash
git add k8s-kustomized/overlays/production/kagent/operator-investigator-agent.yaml
git commit -m "feat(kagent): let operator-investigator spawn homelab-builder"
```

---

### Task 9: Bump parent `ChannelBinding` timeouts (child budget clamps to parent's remaining budget)

**Files:**
- Modify: `k8s-kustomized/overlays/production/kagent/channel-control.yaml`

**Why this task exists:** `packages/agent-pod/src/builtin-tools-spawn.ts` clamps a spawned child's `runConfig.timeoutSeconds` to whatever budget remains in the *parent's* own timeout window. Both `telegram-work-operator-investigator` and `whatsapp-work-operator-investigator` `ChannelBinding`s currently set `runConfig.timeoutSeconds: 600`. If `operator-investigator` spends even a few seconds deciding to spawn, `homelab-builder` inherits whatever's left of that 600s — nowhere near enough for a real build+push+deploy cycle. Bumping the parent's budget is what actually gives the child room to work, regardless of what `homelab-builder`'s own Agent spec says.

- [ ] **Step 1: Bump both bindings**

In `channel-control.yaml`, change both occurrences of:
```yaml
    runConfig:
      maxIterations: 6
      timeoutSeconds: 600
```
(one under `telegram-work-operator-investigator`, one under `whatsapp-work-operator-investigator`) to:
```yaml
    runConfig:
      maxIterations: 6
      timeoutSeconds: 1500
```

Leave `maxIterations` at 6 — that governs `operator-investigator`'s *own* iteration count before it decides to spawn (or answers directly), which is unrelated to how long the spawned child itself can run.

- [ ] **Step 2: Add a comment explaining why**

Directly above each changed `runConfig:` block, add:
```yaml
    # timeoutSeconds bumped from 600 to 1500 (2026-07-05): a spawned
    # homelab-builder child's own timeout clamps to whatever remains of
    # this parent budget (see builtin-tools-spawn.ts), so 600s left no
    # real room for a build+push+deploy task.
```

- [ ] **Step 3: Validate render**

```bash
kubectl kustomize k8s-kustomized/overlays/production > /tmp/kagent-render-builder4.yaml
grep -B2 "timeoutSeconds: 1500" /tmp/kagent-render-builder4.yaml
```
Expected: two matches (telegram-work and whatsapp-work bindings).

- [ ] **Step 4: Commit and push everything from Tasks 7-9 together**

```bash
git add k8s-kustomized/overlays/production/kagent/channel-control.yaml
git commit -m "fix(kagent): give operator-investigator a bigger ChannelBinding budget

homelab-builder's spawned timeout clamps to the parent's remaining
budget, not its own Agent spec's timeoutSeconds. 600s left almost
nothing for a real build task; 1500s gives it room."
git push origin main
```

- [ ] **Step 5: Watch ArgoCD reconcile**

```bash
ssh elitemini "timeout 200 bash -c 'until kubectl get agent homelab-builder -n kagent-system >/dev/null 2>&1; do sleep 5; done'"
ssh elitemini "kubectl get agent homelab-builder -n kagent-system -o jsonpath='{.spec.toolProfileRef}{\"\n\"}'"
ssh elitemini "kubectl get agent operator-investigator -n kagent-system -o jsonpath='{.spec.allowedChildAgents}{\"\n\"}'"
ssh elitemini "kubectl get secret kagent-builder-ssh-key kagent-builder-git-token -n kagent-system"
```
Expected: `homelab-builder` Agent exists with `toolProfileRef: builder-shell`; `operator-investigator` shows `["homelab-builder"]`; both Secrets present.

---

### Task 10: End-to-end smoke test

**Files:** none (verification only)

- [ ] **Step 1: Low-stakes real test via Telegram**

Send @hlhermbot a message that clearly needs execution but is harmless and fast: e.g. "SSH to elitemini2 and tell me disk usage with df -h".

- [ ] **Step 2: Watch for the spawn**

```bash
ssh elitemini "kubectl get agenttask -n kagent-system --sort-by=.metadata.creationTimestamp | tail -6"
```
Expected: a new `kct-telegram-work-*` task for `operator-investigator`, followed shortly by a child task for `homelab-builder`.

- [ ] **Step 3: Confirm the shell command actually ran on elitemini2**

```bash
ssh elitemini2 "last -n 5 kagent-builder"
```
Expected: a recent login entry from the tool-gateway's pod IP, around the time of the test.

- [ ] **Step 4: Confirm the Telegram reply reflects real output**

The reply should contain actual `df -h` output (real filesystem/size numbers for elitemini2), not a generic or hallucinated answer.

- [ ] **Step 5: Confirm the cgroup cap is live**

```bash
ssh elitemini2 "systemctl show user-\$(id -u kagent-builder).slice --property=CPUQuotaPerSecUSec,MemoryMax"
```
Expected: reflects the `CPUQuota=200%`/`MemoryMax=4G` values set in Task 5.

If any of these checks fail, do not proceed to trusting `homelab-builder` with a real write/deploy task — go back and fix the specific broken link (adapter delivery, spawn wiring, SSH auth, or the cgroup slice) the same way this session's Telegram rollout debugged each failure with real evidence before declaring success.

---

## Self-Review Notes

- **Spec coverage:** shell.exec tool (Tasks 1-3), Agent CR + tool profile (Task 7), operator-investigator changes (Task 8), manual node provisioning (Task 5), NetworkPolicy (Task 7), sealed Secrets (Task 6), release conventions (Task 4) — all five components from the spec have a task. The spec's "Testing / rollout plan" section maps to Tasks 2/3's unit tests plus Task 10's end-to-end checks.
- **New finding folded in during planning, not in the original spec:** the `runConfig.timeoutSeconds` clamp-to-parent-budget behavior (Task 9) — the spec assumed `homelab-builder`'s own `timeoutSeconds: 1200` would simply apply, but `builtin-tools-spawn.ts` clamps to the parent's remaining budget instead. Without Task 9, the child would be starved regardless of its own Agent spec.
- **Open item carried from the spec, not resolved here:** per-Agent pod resource tiers (`agentPod` resources look global across all spawned Jobs in the operator chart) — still not addressed; the node-side cgroup cap (Task 5) is the resource boundary that actually matters for `shell.exec` specifically, so this doesn't block shipping, but `homelab-builder`'s own pod shares whatever ceiling `operator-investigator`'s pod has.
