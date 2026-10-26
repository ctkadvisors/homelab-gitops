#!/usr/bin/env node
import { Server } from '@modelcontextprotocol/sdk/server/index.js';
import { StreamableHTTPServerTransport } from '@modelcontextprotocol/sdk/server/streamableHttp.js';
import { CallToolRequestSchema, ListToolsRequestSchema } from '@modelcontextprotocol/sdk/types.js';
import { spawn } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import { mkdir } from 'node:fs/promises';
import { createServer } from 'node:http';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';

const serverInfo = {
  name: 'qwen-spark-coder-mcp-server',
  title: 'Qwen Spark Coder',
  version: '0.1.0'
};

debug('started', { argv: process.argv, node: process.execPath, pid: process.pid });

const fallbackHome = '/Users/homelab-user';
const fallbackPath = [
  '/Users/homelab-user/.nvm/versions/node/v23.11.1/bin',
  '/Applications/Codex.app/Contents/Resources/cua_node/bin',
  '/opt/homebrew/bin',
  '/usr/local/bin',
  '/usr/bin',
  '/bin',
  '/usr/sbin',
  '/sbin'
].join(':');

const tools = [
  {
    name: 'qwen_status',
    description:
      'Inspect whether a workspace has the hardened Qwen runner and whether the worktree is dirty.',
    inputSchema: {
      type: 'object',
      properties: {
        repo: {
          type: 'string',
          description: 'Git repository URL to clone.'
        },
        ref: {
          type: 'string',
          default: 'HEAD',
          description: 'Git ref to check out.'
        }
      },
      required: ['repo']
    },
    annotations: {
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: false
    }
  },
  {
    name: 'qwen_implement',
    description:
      'Ask Qwen/Spark to implement or test a scoped coding task through scripts/qwen-worktree.',
    inputSchema: {
      type: 'object',
      properties: {
        repo: {
          type: 'string',
          description: 'Git repository URL to clone.'
        },
        ref: {
          type: 'string',
          default: 'HEAD',
          description: 'Git ref to check out.'
        },
        ticket: {
          type: 'string',
          description: 'Optional ticket key, for example DEV-382.'
        },
        instructions: {
          type: 'string',
          description: 'Concrete implementation instructions for Qwen.'
        },
        verification: {
          type: 'array',
          items: { type: 'string' },
          description: 'Optional verification commands Codex should run after reviewing the diff.'
        }
      },
      required: ['repo', 'instructions']
    },
    annotations: {
      readOnlyHint: false,
      destructiveHint: false,
      idempotentHint: false,
      openWorldHint: false
    }
  },
  {
    name: 'qwen_repair',
    description:
      'Send a concrete test/lint/build failure back to Qwen for repair through scripts/qwen-worktree.',
    inputSchema: {
      type: 'object',
      properties: {
        repo: {
          type: 'string',
          description: 'Git repository URL to clone.'
        },
        ref: {
          type: 'string',
          default: 'HEAD',
          description: 'Git ref to check out.'
        },
        command: {
          type: 'string',
          description: 'The command that failed.'
        },
        failure: {
          type: 'string',
          description: 'The relevant failure output or error lines.'
        },
        instructions: {
          type: 'string',
          description: 'Optional extra repair constraints.'
        }
      },
      required: ['repo', 'command', 'failure']
    },
    annotations: {
      readOnlyHint: false,
      destructiveHint: false,
      idempotentHint: false,
      openWorldHint: false
    }
  },
  {
    name: 'qwen_smoke_test',
    description:
      'Run a guarded Qwen safety smoke test for an allowed relative edit.',
    inputSchema: {
      type: 'object',
      properties: {
        repo: {
          type: 'string',
          description: 'Git repository URL to clone.'
        },
        ref: {
          type: 'string',
          default: 'HEAD',
          description: 'Git ref to check out.'
        },
        mode: {
          type: 'string',
          enum: ['relative-edit'],
          description: 'Smoke test mode.'
        }
      },
      required: ['repo', 'mode']
    },
    annotations: {
      readOnlyHint: false,
      destructiveHint: false,
      idempotentHint: false,
      openWorldHint: false
    }
  }
];

// Build a fresh MCP Server with the tool handlers registered. In stateless
// Streamable HTTP, a new Server + transport must be created PER request — sharing
// one transport across requests yields intermittent 500s.
function buildServer() {
  const server = new Server(
    { name: serverInfo.name, version: serverInfo.version },
    { capabilities: { tools: { listChanged: false } } }
  );
  server.setRequestHandler(ListToolsRequestSchema, async () => ({ tools }));
  server.setRequestHandler(CallToolRequestSchema, async (req) =>
    callToolForTest(req.params.name, req.params.arguments || {})
  );
  return server;
}

async function startHttpServer() {
  createServer(async (req, res) => {
    const { pathname } = new URL(req.url || '/', 'http://localhost');
    if (pathname !== '/mcp') {
      res.writeHead(404).end();
      return;
    }
    const server = buildServer();
    const transport = new StreamableHTTPServerTransport({ sessionIdGenerator: undefined });
    res.on('close', () => {
      transport.close();
      server.close();
    });
    try {
      await server.connect(transport);
      await transport.handleRequest(req, res);
    } catch (err) {
      debug('http-error', { message: String(err?.message || err) });
      if (!res.headersSent) {
        res.writeHead(500, { 'Content-Type': 'application/json' }).end(
          JSON.stringify({ jsonrpc: '2.0', error: { code: -32603, message: 'Internal error' }, id: null })
        );
      }
    }
  }).listen(process.env.PORT || 8080);
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  await startHttpServer();
}

export async function callToolForTest(name, args) {
  if (name === 'qwen_status') {
    return qwenStatus(args);
  }

  if (name === 'qwen_implement') {
    return qwenImplement(args);
  }

  if (name === 'qwen_repair') {
    return qwenRepair(args);
  }

  if (name === 'qwen_smoke_test') {
    return qwenSmokeTest(args);
  }

  throw new Error(`Unknown tool: ${name}`);
}

export async function prepareWorktree(repo, ref = 'HEAD', opts = {}) {
  if (!repo || typeof repo !== 'string') {
    throw new Error('repo is required');
  }
  // repo/ref are caller-controlled. Reject flag smuggling (leading '-') and git
  // remote-helper transports (ext::/file::/fd:: — ext:: runs an arbitrary command).
  // Normal URLs (single colon: https://, git@host:path) and local paths are allowed.
  if (/^-/.test(repo)) {
    throw new Error(`invalid repo (leading dash): ${repo}`);
  }
  if (/^[A-Za-z0-9][A-Za-z0-9+.-]*::/.test(repo)) {
    throw new Error(`unsupported repo transport (remote-helper syntax): ${repo}`);
  }
  const safeRef = ref || 'HEAD';
  if (/^-/.test(safeRef) || !/^[A-Za-z0-9._/-]{1,200}$/.test(safeRef)) {
    throw new Error(`invalid ref: ${safeRef}`);
  }

  const workRoot = opts.workRoot || process.env.QWEN_WORK_ROOT || '/work';
  const taskId = randomUUID().slice(0, 8);
  const taskRoot = join(workRoot, taskId);
  const repoDir = join(taskRoot, 'repo.git');
  const worktreeDir = join(taskRoot, 'wt');
  const branch = `qwen/${taskId}`;

  await mkdir(taskRoot, { recursive: true });

  // -c protocol.ext.allow=never disables the ext:: RCE transport defensively even
  // if the regex above is bypassed; -- terminates option parsing before the repo arg.
  const clone = await run(
    'git',
    ['-c', 'protocol.ext.allow=never', 'clone', '--mirror', '--', repo, repoDir],
    taskRoot
  );
  if (clone.exitCode !== 0) {
    throw new Error(
      `git clone --mirror failed for ${repo}: ${clone.stderr.trim() || clone.stdout.trim() || `exit ${clone.exitCode}`}`
    );
  }

  const worktree = await run(
    'git',
    ['-C', repoDir, 'worktree', 'add', '-b', branch, worktreeDir, safeRef],
    taskRoot
  );
  if (worktree.exitCode !== 0) {
    throw new Error(
      `git worktree add failed for ${repo} at ${safeRef}: ${worktree.stderr.trim() || worktree.stdout.trim() || `exit ${worktree.exitCode}`}`
    );
  }

  return { taskId, repoDir, worktreeDir, branch };
}

async function qwenStatus(args) {
  const prepared = await prepareWorktree(args.repo, args.ref);
  const status = await run('git', ['status', '--porcelain=v1', '--untracked-files=no'], prepared.worktreeDir);
  const branchStatus = await run('git', ['status', '--short', '--branch'], prepared.worktreeDir);

  return toolResult(
    [
      `worktree: ${prepared.worktreeDir}`,
      `branch: ${prepared.branch}`,
      `trackedStatus: ${status.stdout.trim() || '<clean>'}`,
      '',
      branchStatus.stdout.trim()
    ].join('\n'),
    {
      ...prepared,
      trackedStatus: status.stdout.trim(),
      gitStatus: branchStatus.stdout.trim()
    }
  );
}

async function qwenImplement(args) {
  const prepared = await prepareWorktree(args.repo, args.ref);
  const ticketLine = args.ticket ? `Implement ${args.ticket}.` : 'Implement the requested task.';
  const verification =
    Array.isArray(args.verification) && args.verification.length
      ? `\n\nVerification Codex will run after your edit:\n${args.verification.map((item) => `- ${item}`).join('\n')}`
      : '';
  const packet = [
    ticketLine,
    '',
    args.instructions,
    verification,
    '',
    'Use relative paths only. Do not edit outside this workspace. Do not use bash. Keep changes minimal.'
  ].join('\n');

  const result = await runQwen(prepared.worktreeDir, packet);
  Object.assign(result.structuredContent, prepared);
  return result;
}

async function qwenRepair(args) {
  const prepared = await prepareWorktree(args.repo, args.ref);
  const packet = [
    'Repair your previous edit.',
    '',
    `The command failed:\n${args.command}`,
    '',
    `Relevant failure:\n${args.failure}`,
    '',
    args.instructions || 'Fix only the files needed to address this failure.',
    '',
    'Use relative paths only. Do not edit outside this workspace. Do not use bash. Keep changes minimal.'
  ].join('\n');

  const result = await runQwen(prepared.worktreeDir, packet);
  Object.assign(result.structuredContent, prepared);
  return result;
}

async function qwenSmokeTest(args) {
  const prepared = await prepareWorktree(args.repo, args.ref);

  if (args.mode === 'relative-edit') {
    await run('sh', ['-c', 'printf "status=before\\n" > .qwen-worktree-sentinel.txt'], prepared.worktreeDir);
    const result = await runQwen(
      prepared.worktreeDir,
      'Edit .qwen-worktree-sentinel.txt. Replace exactly status=before with status=after. Do not change any other file. Summarize the edit.'
    );
    const content = await run('cat', ['.qwen-worktree-sentinel.txt'], prepared.worktreeDir);
    await run('rm', ['-f', '.qwen-worktree-sentinel.txt'], prepared.worktreeDir);
    Object.assign(result.structuredContent, prepared);
    result.structuredContent.sentinel = content.stdout.trim();
    result.content[0].text += `\n\nsentinel: ${content.stdout.trim()}`;
    return result;
  }

  throw new Error(`Unsupported smoke mode: ${args.mode}`);
}

export async function runQwen(worktreeDir, packet) {
  const runner = process.env.QWEN_RUNNER || '/app/qwen-run';
  const before = await run('git', ['status', '--porcelain=v1', '--untracked-files=no'], worktreeDir);
  const result = await run(runner, [packet], worktreeDir, 15 * 60 * 1000);
  const after = await run('git', ['status', '--porcelain=v1'], worktreeDir);
  // Stage everything (including NEW/untracked files) so the captured diff reflects
  // additions and deletions, not just edits to already-tracked files.
  await run('git', ['add', '-A'], worktreeDir);
  const changed = await run('git', ['diff', '--cached', '--name-only'], worktreeDir);
  const diff = await run('git', ['diff', '--cached'], worktreeDir);

  const structured = {
    worktreeDir,
    runner,
    exitCode: result.exitCode,
    stdout: result.stdout,
    stderr: result.stderr,
    statusBefore: before.stdout.trim(),
    statusAfter: after.stdout.trim(),
    diff: diff.stdout,
    changedFiles: changed.stdout.trim().split('\n').filter(Boolean)
  };

  return toolResult(
    [
      `exitCode: ${result.exitCode}`,
      '',
      'stdout:',
      result.stdout.trim() || '<empty>',
      '',
      'stderr:',
      result.stderr.trim() || '<empty>',
      '',
      `changedFiles: ${structured.changedFiles.join(', ') || '<none>'}`,
      `trackedStatus: ${structured.statusAfter || '<clean>'}`,
      '',
      'diff:',
      structured.diff.trim() || '<empty>'
    ].join('\n'),
    structured,
    result.exitCode !== 0
  );
}

function run(command, args, cwd, timeoutMs = 120000) {
  return new Promise((resolvePromise) => {
    const child = spawn(command, args, {
      cwd,
      env: childEnv(),
      stdio: ['ignore', 'pipe', 'pipe']
    });

    let stdout = '';
    let stderr = '';
    let settled = false;
    const timer = setTimeout(() => {
      if (!settled) child.kill('SIGTERM');
    }, timeoutMs);

    child.stdout.on('data', (chunk) => {
      stdout += chunk.toString('utf8');
    });
    child.stderr.on('data', (chunk) => {
      stderr += chunk.toString('utf8');
    });
    child.on('close', (code, signal) => {
      settled = true;
      clearTimeout(timer);
      resolvePromise({
        exitCode: code === null ? 1 : code,
        signal,
        stdout,
        stderr
      });
    });
    child.on('error', (error) => {
      settled = true;
      clearTimeout(timer);
      resolvePromise({
        exitCode: 1,
        signal: null,
        stdout,
        stderr: String(error.message || error)
      });
    });
  });
}

function childEnv() {
  return {
    ...process.env,
    HOME: process.env.HOME || fallbackHome,
    LOGNAME: process.env.LOGNAME || 'homelab-user',
    PATH: process.env.PATH
      ? `${process.env.PATH}:${fallbackPath}`
      : fallbackPath,
    USER: process.env.USER || 'homelab-user'
  };
}

function toolResult(text, structuredContent = {}, isError = false) {
  return {
    content: [
      {
        type: 'text',
        text
      }
    ],
    structuredContent,
    isError
  };
}

function debug(message, details = {}) {
  if (process.env.QWEN_MCP_DEBUG !== '1') return;

  process.stderr.write(
    `[qwen-spark-coder] ${message} ${JSON.stringify(details)}\n`
  );
}
