import assert from 'node:assert/strict';
import test from 'node:test';

import {
  buildMemoryDocument,
  buildRecallQuery,
  formatRecallResult,
  rankRecallHits
} from '../src/memory.mjs';

test('buildMemoryDocument normalizes required metadata for durable memories', () => {
  const doc = buildMemoryDocument({
    agent_id: 'claude-code',
    content: 'OpenSearch memory lives on elitemini2.',
    recorded_by: 'claude-code',
    source_kind: 'conversation',
    source_ref: 'claude-session:test',
    source_actor: 'user:homelab-user',
    tags: ['opensearch', 'homelab'],
    importance: 4,
    timestamp: '2026-07-09T12:00:00.000Z'
  });

  assert.equal(doc.agent_id, 'claude-code');
  assert.equal(doc.status, 'active');
  assert.equal(doc.content, 'OpenSearch memory lives on elitemini2.');
  assert.deepEqual(doc.tags, ['opensearch', 'homelab']);
  assert.equal(doc.importance, 4);
  assert.equal(doc.recorded_by, 'claude-code');
  assert.equal(doc.source_kind, 'conversation');
  assert.equal(doc.source_ref, 'claude-session:test');
  assert.equal(doc.source_actor, 'user:homelab-user');
  assert.equal(doc.created_at, '2026-07-09T12:00:00.000Z');
  assert.equal(doc.updated_at, '2026-07-09T12:00:00.000Z');
});

test('buildMemoryDocument requires explicit memory attribution', () => {
  assert.throws(
    () => buildMemoryDocument({
      agent_id: 'claude-code',
      content: 'Missing attribution should not be stored.'
    }),
    /recorded_by is required/
  );

  assert.throws(
    () => buildMemoryDocument({
      agent_id: 'claude-code',
      content: 'Missing source actor should not be stored.',
      recorded_by: 'claude-code',
      source_kind: 'conversation',
      source_ref: 'claude-session:test'
    }),
    /source_actor is required/
  );
});

test('buildRecallQuery combines filters with lexical and neural recall clauses', () => {
  const query = buildRecallQuery({
    query: 'where should OpenSearch run?',
    agent_id: 'claude-code',
    model_id: 'model-123',
    limit: 7,
    tags: ['homelab']
  });

  assert.equal(query.size, 14);
  assert.deepEqual(query.query.bool.filter, [
    { term: { agent_id: 'claude-code' } },
    { term: { status: 'active' } },
    { terms: { tags: ['homelab'] } }
  ]);
  assert.deepEqual(query.query.bool.should[0].multi_match.fields, [
    'content^4',
    'summary^2',
    'tags^1.5',
    'entities.name^1.5',
    'source_ref'
  ]);
  assert.equal(query.query.bool.should[1].neural.content_embedding.query_text, 'where should OpenSearch run?');
  assert.equal(query.query.bool.should[1].neural.content_embedding.model_id, 'model-123');
  assert.equal(query.query.bool.should[1].neural.content_embedding.k, 7);
});

test('rankRecallHits applies importance and recency decay without losing OpenSearch score', () => {
  const now = new Date('2026-07-09T12:00:00.000Z');
  const ranked = rankRecallHits(
    [
      {
        _id: 'old-critical',
        _score: 8,
        _source: {
          content: 'older but important',
          importance: 5,
          updated_at: '2026-06-01T12:00:00.000Z'
        }
      },
      {
        _id: 'fresh-normal',
        _score: 7,
        _source: {
          content: 'fresh normal',
          importance: 1,
          recorded_by: 'codex',
          source_kind: 'smoke-test',
          source_ref: 'codex-session:test',
          source_actor: 'agent:codex',
          updated_at: '2026-07-09T11:00:00.000Z'
        }
      }
    ],
    { now, limit: 2 }
  );

  assert.equal(ranked[0].id, 'fresh-normal');
  assert.equal(ranked[0].opensearch_score, 7);
  assert.equal(ranked[0].content, 'fresh normal');
  assert.equal(ranked[0].recorded_by, 'codex');
  assert.equal(ranked[0].source_kind, 'smoke-test');
  assert.equal(ranked[0].source_ref, 'codex-session:test');
  assert.equal(ranked[0].source_actor, 'agent:codex');
  assert.equal(ranked[1].id, 'old-critical');
});

test('formatRecallResult returns markdown and structured content', () => {
  const result = formatRecallResult([
    {
      id: 'm1',
      content: 'OpenSearch runs on elitemini2.',
      tags: ['opensearch'],
      recorded_by: 'claude-code',
      source_kind: 'conversation',
      source_ref: 'claude-session:test',
      source_actor: 'user:homelab-user',
      final_score: 9.25,
      updated_at: '2026-07-09T12:00:00.000Z'
    }
  ]);

  assert.match(result.content[0].text, /OpenSearch runs on elitemini2/);
  assert.match(result.content[0].text, /Recorded by: claude-code/);
  assert.match(result.content[0].text, /Source: conversation claude-session:test/);
  assert.match(result.content[0].text, /Source actor: user:homelab-user/);
  assert.deepEqual(result.structuredContent.memories[0].tags, ['opensearch']);
  assert.equal(result.structuredContent.memories[0].source_actor, 'user:homelab-user');
});
