import assert from 'node:assert/strict';
import test from 'node:test';

import { createToolHandlers } from '../src/tools.mjs';

test('agent_memory_remember indexes a normalized memory document', async () => {
  const calls = [];
  const handlers = createToolHandlers({
    client: {
      index: async (request) => {
        calls.push(request);
        return { body: { _id: request.id || 'generated-id', result: 'created' } };
      }
    },
    modelId: 'model-123',
    now: () => new Date('2026-07-09T12:00:00.000Z')
  });

  const result = await handlers.agent_memory_remember({
    agent_id: 'claude-code',
    content: 'Use OpenSearch for durable agent memory.',
    recorded_by: 'claude-code',
    source_kind: 'conversation',
    source_ref: 'claude-session:test',
    source_actor: 'user:homelab-user',
    tags: ['Memory']
  });

  assert.equal(calls[0].index, 'agent-memory');
  assert.equal(calls[0].refresh, true);
  assert.equal(calls[0].body.agent_id, 'claude-code');
  assert.equal(calls[0].body.recorded_by, 'claude-code');
  assert.equal(calls[0].body.source_kind, 'conversation');
  assert.equal(calls[0].body.source_ref, 'claude-session:test');
  assert.equal(calls[0].body.source_actor, 'user:homelab-user');
  assert.deepEqual(calls[0].body.tags, ['memory']);
  assert.equal(result.structuredContent.id, 'generated-id');
});

test('agent_memory_remember rejects writes without attribution', async () => {
  const handlers = createToolHandlers({
    client: {
      index: async () => {
        throw new Error('index should not be called');
      }
    },
    now: () => new Date('2026-07-09T12:00:00.000Z')
  });

  await assert.rejects(
    () => handlers.agent_memory_remember({
      agent_id: 'claude-code',
      content: 'This write is missing attribution.'
    }),
    /recorded_by is required/
  );
});

test('agent_memory_recall searches and ranks hits', async () => {
  const searches = [];
  const handlers = createToolHandlers({
    client: {
      search: async (request) => {
        searches.push(request);
        return {
          body: {
            hits: {
              hits: [
                {
                  _id: 'm1',
                  _score: 5,
                  _source: {
                  content: 'OpenSearch memory is on elitemini2.',
                  tags: ['opensearch'],
                  recorded_by: 'claude-code',
                  source_kind: 'conversation',
                  source_ref: 'claude-session:test',
                  source_actor: 'user:homelab-user',
                  importance: 3,
                  updated_at: '2026-07-09T11:00:00.000Z'
                }
                }
              ]
            }
          }
        };
      }
    },
    modelId: 'model-123',
    now: () => new Date('2026-07-09T12:00:00.000Z')
  });

  const result = await handlers.agent_memory_recall({
    agent_id: 'claude-code',
    query: 'where is memory stored?',
    limit: 5
  });

  assert.equal(searches[0].index, 'agent-memory');
  assert.equal(searches[0].body.query.bool.should[1].neural.content_embedding.model_id, 'model-123');
  assert.equal(result.structuredContent.memories[0].id, 'm1');
  assert.equal(result.structuredContent.memories[0].recorded_by, 'claude-code');
  assert.equal(result.structuredContent.memories[0].source_actor, 'user:homelab-user');
  assert.match(result.content[0].text, /OpenSearch memory is on elitemini2/);
  assert.match(result.content[0].text, /Recorded by: claude-code/);
});

test('agent_memory_recall loads the model id from agent-status when env is empty', async () => {
  const searches = [];
  const handlers = createToolHandlers({
    client: {
      get: async (request) => {
        assert.equal(request.index, 'agent-status');
        assert.equal(request.id, 'embedding-model');
        return { body: { _source: { source_ref: 'status-model-id' } } };
      },
      search: async (request) => {
        searches.push(request);
        return { body: { hits: { hits: [] } } };
      }
    },
    now: () => new Date('2026-07-09T12:00:00.000Z')
  });

  await handlers.agent_memory_recall({
    agent_id: 'claude-code',
    query: 'what model is deployed?'
  });

  assert.equal(searches[0].body.query.bool.should[1].neural.content_embedding.model_id, 'status-model-id');
});

test('agent_memory_supersede marks the old memory and writes the replacement', async () => {
  const updates = [];
  const indexes = [];
  const handlers = createToolHandlers({
    client: {
      update: async (request) => {
        updates.push(request);
        return { body: { result: 'updated' } };
      },
      index: async (request) => {
        indexes.push(request);
        return { body: { _id: 'replacement-id', result: 'created' } };
      }
    },
    now: () => new Date('2026-07-09T12:00:00.000Z')
  });

  const result = await handlers.agent_memory_supersede({
    agent_id: 'claude-code',
    memory_id: 'old-id',
    content: 'Replacement memory.',
    reason: 'new facts',
    recorded_by: 'claude-code',
    source_kind: 'conversation',
    source_ref: 'claude-session:test',
    source_actor: 'user:homelab-user'
  });

  assert.equal(updates[0].index, 'agent-memory');
  assert.equal(updates[0].id, 'old-id');
  assert.equal(updates[0].body.doc.status, 'superseded');
  assert.equal(updates[0].body.doc.superseded_by, 'replacement-id');
  assert.equal(indexes[0].body.supersedes, 'old-id');
  assert.equal(indexes[0].body.recorded_by, 'claude-code');
  assert.equal(indexes[0].body.source_actor, 'user:homelab-user');
  assert.equal(result.structuredContent.replacement_id, 'replacement-id');
});

test('write helpers persist attribution fields', async () => {
  const indexes = [];
  const handlers = createToolHandlers({
    client: {
      index: async (request) => {
        indexes.push(request);
        return { body: { _id: request.id || 'generated-id', result: 'created' } };
      }
    },
    now: () => new Date('2026-07-09T12:00:00.000Z')
  });

  await handlers.agent_memory_session_log({
    agent_id: 'claude-code',
    session_id: 'session-1',
    role: 'assistant',
    content: 'Session event',
    recorded_by: 'claude-code',
    source_kind: 'conversation',
    source_ref: 'claude-session:session-1',
    source_actor: 'assistant:claude-code'
  });

  await handlers.agent_memory_task_upsert({
    agent_id: 'claude-code',
    task_id: 'task-1',
    title: 'Task',
    recorded_by: 'claude-code',
    source_kind: 'repo',
    source_ref: 'new_localai#task-1',
    source_actor: 'agent:claude-code'
  });

  await handlers.agent_memory_entity_index({
    agent_id: 'claude-code',
    name: 'OpenSearch',
    type: 'service',
    recorded_by: 'claude-code',
    source_kind: 'conversation',
    source_ref: 'claude-session:session-1',
    source_actor: 'user:homelab-user'
  });

  assert.equal(indexes[0].body.recorded_by, 'claude-code');
  assert.equal(indexes[0].body.source_ref, 'claude-session:session-1');
  assert.equal(indexes[1].body.source_kind, 'repo');
  assert.equal(indexes[1].body.source_actor, 'agent:claude-code');
  assert.equal(indexes[2].body.recorded_by, 'claude-code');
  assert.equal(indexes[3].body.source_actor, 'user:homelab-user');
});
