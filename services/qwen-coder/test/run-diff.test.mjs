import assert from 'node:assert/strict';
import { execFile } from 'node:child_process';
import { mkdtemp, mkdir, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { promisify } from 'node:util';
import test, { after } from 'node:test';

import { callToolForTest, prepareWorktree, runQwen } from '../server.mjs';

const execFileAsync = promisify(execFile);

after(() => {
  process.stdin.removeAllListeners('data');
  process.stdin.removeAllListeners('end');
  process.stdin.pause();
});

async function git(cwd, args) {
  return execFileAsync('git', args, { cwd });
}

async function makeRepo() {
  const dir = await mkdtemp(join(tmpdir(), 'qwen-coder-repo-'));
  await git(dir, ['init']);
  await git(dir, ['config', 'user.email', 'test@example.com']);
  await git(dir, ['config', 'user.name', 'Test User']);
  await writeFile(join(dir, 'sample.txt'), 'before\n');
  await git(dir, ['add', 'sample.txt']);
  await git(dir, ['commit', '-m', 'initial']);
  return dir;
}

async function makeRunner(line = 'after') {
  const dir = await mkdtemp(join(tmpdir(), 'qwen-coder-runner-'));
  const runner = join(dir, 'fake-qwen-run');
  await writeFile(
    runner,
    `#!/usr/bin/env bash\nset -euo pipefail\nprintf '${line}\\n' >> sample.txt\n`
  );
  await execFileAsync('chmod', ['+x', runner]);
  return runner;
}

test('runQwen returns the full diff and changed files', async () => {
  const repo = await makeRepo();
  const runner = await makeRunner('after');
  process.env.QWEN_RUNNER = runner;

  const result = await runQwen(repo, 'append a line');

  assert.equal(result.isError, false);
  assert.match(result.structuredContent.diff, /^\+after$/m);
  assert.deepEqual(result.structuredContent.changedFiles, ['sample.txt']);
});

test('callToolForTest prepares a worktree and returns a diff', async () => {
  const origin = await makeRepo();
  const runner = await makeRunner('tool-after');
  const workRoot = await mkdtemp(join(tmpdir(), 'qwen-coder-work-'));
  process.env.QWEN_RUNNER = runner;
  process.env.QWEN_WORK_ROOT = workRoot;

  const result = await callToolForTest('qwen_implement', {
    repo: origin,
    instructions: 'x'
  });

  assert.equal(result.isError, false);
  assert.match(result.structuredContent.diff, /^\+tool-after$/m);
  assert.deepEqual(result.structuredContent.changedFiles, ['sample.txt']);
  assert.match(result.structuredContent.branch, /^qwen\/[a-f0-9]{8}$/);
});

test('runQwen captures NEW (untracked) files in the diff', async () => {
  const repo = await makeRepo();
  // runner creates a brand-new file rather than editing a tracked one
  const dir = await mkdtemp(join(tmpdir(), 'qwen-coder-runner-'));
  const runner = join(dir, 'fake-qwen-run');
  await writeFile(runner, "#!/usr/bin/env bash\nset -euo pipefail\nprintf 'hello new file\\n' > created.txt\n");
  await execFileAsync('chmod', ['+x', runner]);
  process.env.QWEN_RUNNER = runner;

  const result = await runQwen(repo, 'create a file');

  assert.equal(result.isError, false);
  assert.deepEqual(result.structuredContent.changedFiles, ['created.txt']);
  assert.match(result.structuredContent.diff, /^\+hello new file$/m);
  assert.match(result.structuredContent.diff, /new file mode/);
});

test('prepareWorktree rejects dangerous repo/ref inputs', async () => {
  const workRoot = await mkdtemp(join(tmpdir(), 'qwen-coder-sec-'));
  await assert.rejects(
    prepareWorktree('ext::sh -c id', 'HEAD', { workRoot }),
    /unsupported repo transport/
  );
  await assert.rejects(
    prepareWorktree('--upload-pack=evil', 'HEAD', { workRoot }),
    /invalid repo \(leading dash\)/
  );
  await assert.rejects(
    prepareWorktree('/tmp/whatever', '--upload-pack=evil', { workRoot }),
    /invalid ref/
  );
});
