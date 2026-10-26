const DEFAULT_STATUS = 'active';
const DEFAULT_LIMIT = 10;
const MAX_LIMIT = 50;
const HALF_LIFE_DAYS = 14;

export function buildMemoryDocument(input, now = new Date()) {
  if (!input || typeof input !== 'object') {
    throw new Error('memory input is required');
  }
  const agentId = cleanString(input.agent_id);
  const content = cleanString(input.content);
  if (!agentId) {
    throw new Error('agent_id is required');
  }
  if (!content) {
    throw new Error('content is required');
  }

  const attribution = buildAttribution(input);
  const timestamp = normalizeTimestamp(input.timestamp || input.created_at || now);
  const tags = normalizeList(input.tags).map((tag) => tag.toLowerCase());
  const entities = Array.isArray(input.entities)
    ? input.entities
        .filter((entity) => entity && typeof entity === 'object')
        .map((entity) => ({
          name: cleanString(entity.name),
          type: cleanString(entity.type || 'unknown')
        }))
        .filter((entity) => entity.name)
    : [];

  return {
    agent_id: agentId,
    content,
    summary: cleanString(input.summary),
    status: cleanString(input.status) || DEFAULT_STATUS,
    ...attribution,
    trust_level: cleanString(input.trust_level || 'unreviewed'),
    importance: clampInteger(input.importance ?? 3, 1, 5),
    tags,
    entities,
    created_at: timestamp,
    updated_at: timestamp
  };
}

export function buildAttribution(input) {
  if (!input || typeof input !== 'object') {
    throw new Error('attribution input is required');
  }

  return {
    recorded_by: requiredString(input.recorded_by, 'recorded_by'),
    source_kind: requiredString(input.source_kind, 'source_kind'),
    source_ref: requiredString(input.source_ref, 'source_ref'),
    source_actor: requiredString(input.source_actor, 'source_actor')
  };
}

export function buildRecallQuery(input) {
  const queryText = cleanString(input?.query);
  const agentId = cleanString(input?.agent_id);
  if (!queryText) {
    throw new Error('query is required');
  }
  if (!agentId) {
    throw new Error('agent_id is required');
  }

  const limit = clampInteger(input.limit ?? DEFAULT_LIMIT, 1, MAX_LIMIT);
  const filter = [
    { term: { agent_id: agentId } },
    { term: { status: DEFAULT_STATUS } }
  ];
  const tags = normalizeList(input.tags).map((tag) => tag.toLowerCase());
  if (tags.length) {
    filter.push({ terms: { tags } });
  }

  const should = [
    {
      multi_match: {
        query: queryText,
        fields: ['content^4', 'summary^2', 'tags^1.5', 'entities.name^1.5', 'source_ref'],
        type: 'best_fields',
        fuzziness: 'AUTO'
      }
    }
  ];

  const modelId = cleanString(input.model_id);
  if (modelId) {
    should.push({
      neural: {
        content_embedding: {
          query_text: queryText,
          model_id: modelId,
          k: limit
        }
      }
    });
  }

  return {
    size: limit * 2,
    query: {
      bool: {
        filter,
        should,
        minimum_should_match: 1
      }
    },
    sort: [
      '_score',
      { importance: { order: 'desc' } },
      { updated_at: { order: 'desc' } }
    ]
  };
}

export function rankRecallHits(hits, opts = {}) {
  const now = opts.now instanceof Date ? opts.now : new Date();
  const limit = clampInteger(opts.limit ?? DEFAULT_LIMIT, 1, MAX_LIMIT);

  return (Array.isArray(hits) ? hits : [])
    .map((hit) => {
      const source = hit._source || {};
      const score = Number(hit._score || 0);
      const importance = clampInteger(source.importance ?? 3, 1, 5);
      const updatedAt = normalizeTimestamp(source.updated_at || source.created_at || now);
      const ageDays = Math.max(0, (now.getTime() - new Date(updatedAt).getTime()) / 86_400_000);
      const recency = Math.pow(0.5, ageDays / HALF_LIFE_DAYS);
      const finalScore = score * (0.8 + importance / 10) * (0.35 + recency);

      return {
        id: hit._id,
        opensearch_score: score,
        final_score: Number(finalScore.toFixed(4)),
        content: source.content || '',
        summary: source.summary || '',
        tags: Array.isArray(source.tags) ? source.tags : [],
        recorded_by: source.recorded_by || '',
        source_kind: source.source_kind || '',
        source_ref: source.source_ref || '',
        source_actor: source.source_actor || '',
        importance,
        trust_level: source.trust_level || 'unreviewed',
        created_at: source.created_at || '',
        updated_at: updatedAt
      };
    })
    .sort((a, b) => b.final_score - a.final_score)
    .slice(0, limit);
}

export function formatRecallResult(memories) {
  const rows = Array.isArray(memories) ? memories : [];
  if (!rows.length) {
    return {
      content: [{ type: 'text', text: 'No matching memories found.' }],
      structuredContent: { count: 0, memories: [] }
    };
  }

  const text = rows
    .map((memory, index) => {
      const tags = memory.tags?.length ? `\nTags: ${memory.tags.join(', ')}` : '';
      const attribution = [
        memory.recorded_by ? `Recorded by: ${memory.recorded_by}` : '',
        memory.source_kind || memory.source_ref ? `Source: ${[memory.source_kind, memory.source_ref].filter(Boolean).join(' ')}` : '',
        memory.source_actor ? `Source actor: ${memory.source_actor}` : ''
      ].filter(Boolean).join('\n');
      return [
        `### ${index + 1}. ${memory.id}`,
        `Score: ${memory.final_score}`,
        `Updated: ${memory.updated_at || 'unknown'}`,
        attribution,
        tags.trim(),
        '',
        memory.content
      ].filter(Boolean).join('\n');
    })
    .join('\n\n');

  return {
    content: [{ type: 'text', text }],
    structuredContent: {
      count: rows.length,
      memories: rows
    }
  };
}

export function toolResult(text, structuredContent = {}) {
  return {
    content: [{ type: 'text', text }],
    structuredContent
  };
}

export function toolError(message, details = {}) {
  return {
    isError: true,
    content: [{ type: 'text', text: `Error: ${message}` }],
    structuredContent: { error: message, ...details }
  };
}

function cleanString(value) {
  return typeof value === 'string' ? value.trim() : '';
}

function requiredString(value, name) {
  const cleaned = cleanString(value);
  if (!cleaned) {
    throw new Error(`${name} is required`);
  }
  return cleaned;
}

function normalizeList(value) {
  if (!Array.isArray(value)) {
    return [];
  }
  return [...new Set(value.map(cleanString).filter(Boolean))];
}

function clampInteger(value, min, max) {
  const parsed = Number.parseInt(value, 10);
  if (Number.isNaN(parsed)) {
    return min;
  }
  return Math.min(max, Math.max(min, parsed));
}

function normalizeTimestamp(value) {
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) {
    throw new Error(`invalid timestamp: ${value}`);
  }
  return date.toISOString();
}
