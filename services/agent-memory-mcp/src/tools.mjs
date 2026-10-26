import {
  buildAttribution,
  buildMemoryDocument,
  buildRecallQuery,
  formatRecallResult,
  rankRecallHits,
  toolResult
} from './memory.mjs';

export const INDICES = {
  memory: 'agent-memory',
  messages: 'agent-messages',
  tasks: 'agent-tasks',
  sessions: 'agent-sessions',
  status: 'agent-status',
  entities: 'agent-entities',
  entityHistory: 'agent-entity-history'
};

export function createToolHandlers({ client, modelId = '', now = () => new Date() }) {
  if (!client) {
    throw new Error('OpenSearch client is required');
  }
  let cachedModelId = modelId;

  return {
    agent_memory_remember: async (args) => {
      const body = buildMemoryDocument(args, now());
      const response = await client.index({
        index: INDICES.memory,
        id: args.id,
        body,
        refresh: true
      });
      const id = response?.body?._id || args.id;
      return toolResult(`Stored memory ${id}.`, { id, result: response?.body?.result, memory: body });
    },

    agent_memory_recall: async (args) => {
      const limit = args.limit ?? 10;
      const body = buildRecallQuery({ ...args, model_id: args.model_id || await resolveModelId() });
      const response = await client.search({
        index: INDICES.memory,
        body
      });
      const hits = response?.body?.hits?.hits || [];
      const ranked = rankRecallHits(hits, { now: now(), limit });
      return formatRecallResult(ranked);
    },

    agent_memory_supersede: async (args) => {
      if (!args.memory_id) {
        throw new Error('memory_id is required');
      }
      const replacement = buildMemoryDocument(
        {
          ...args,
          source_kind: args.source_kind || 'supersession',
          tags: args.tags || [],
          timestamp: now()
        },
        now()
      );
      replacement.supersedes = args.memory_id;
      replacement.supersession_reason = args.reason || '';

      const created = await client.index({
        index: INDICES.memory,
        id: args.replacement_id,
        body: replacement,
        refresh: true
      });
      const replacementId = created?.body?._id || args.replacement_id;

      await client.update({
        index: INDICES.memory,
        id: args.memory_id,
        refresh: true,
        body: {
          doc: {
            status: 'superseded',
            superseded_by: replacementId,
            superseded_at: now().toISOString(),
            supersession_reason: args.reason || ''
          }
        }
      });

      return toolResult(`Superseded ${args.memory_id} with ${replacementId}.`, {
        memory_id: args.memory_id,
        replacement_id: replacementId
      });
    },

    agent_memory_session_log: async (args) => {
      const timestamp = now().toISOString();
      const body = {
        agent_id: requiredString(args.agent_id, 'agent_id'),
        session_id: requiredString(args.session_id, 'session_id'),
        role: args.role || 'assistant',
        content: requiredString(args.content, 'content'),
        ...buildAttribution(args),
        tags: Array.isArray(args.tags) ? args.tags : [],
        created_at: args.timestamp || timestamp
      };
      const response = await client.index({
        index: INDICES.messages,
        id: args.id,
        body,
        refresh: args.refresh ?? false
      });
      return toolResult(`Logged session message ${response?.body?._id || args.id || ''}.`, {
        id: response?.body?._id || args.id,
        message: body
      });
    },

    agent_memory_task_upsert: async (args) => {
      const taskId = requiredString(args.task_id, 'task_id');
      const timestamp = now().toISOString();
      const body = {
        agent_id: requiredString(args.agent_id, 'agent_id'),
        task_id: taskId,
        title: args.title || taskId,
        status: args.status || 'open',
        priority: args.priority || 'normal',
        summary: args.summary || '',
        ...buildAttribution(args),
        updated_at: timestamp,
        created_at: args.created_at || timestamp
      };
      const response = await client.index({
        index: INDICES.tasks,
        id: taskId,
        body,
        refresh: true
      });
      return toolResult(`Upserted task ${taskId}.`, { id: response?.body?._id || taskId, task: body });
    },

    agent_memory_entity_index: async (args) => {
      const name = requiredString(args.name, 'name');
      const type = args.type || 'unknown';
      const agentId = requiredString(args.agent_id, 'agent_id');
      const id = args.id || `${agentId}:${type}:${slug(name)}`;
      const timestamp = now().toISOString();
      const body = {
        agent_id: agentId,
        name,
        type,
        summary: args.summary || '',
        aliases: Array.isArray(args.aliases) ? args.aliases : [],
        ...buildAttribution(args),
        tags: Array.isArray(args.tags) ? args.tags : [],
        updated_at: timestamp,
        created_at: args.created_at || timestamp
      };
      await client.index({ index: INDICES.entities, id, body, refresh: true });
      await client.index({
        index: INDICES.entityHistory,
        body: { ...body, entity_id: id, event: args.event || 'indexed', created_at: timestamp },
        refresh: false
      });
      return toolResult(`Indexed entity ${id}.`, { id, entity: body });
    },

    agent_memory_entity_search: async (args) => {
      const query = requiredString(args.query, 'query');
      const limit = Math.min(Math.max(Number.parseInt(args.limit ?? 10, 10), 1), 50);
      const filter = [{ term: { agent_id: requiredString(args.agent_id, 'agent_id') } }];
      if (args.type) {
        filter.push({ term: { type: args.type } });
      }
      const response = await client.search({
        index: INDICES.entities,
        body: {
          size: limit,
          query: {
            bool: {
              filter,
              should: [
                {
                  multi_match: {
                    query,
                    fields: ['name^4', 'aliases^3', 'summary^2', 'tags'],
                    fuzziness: 'AUTO'
                  }
                }
              ],
              minimum_should_match: 1
            }
          }
        }
      });
      const entities = (response?.body?.hits?.hits || []).map((hit) => ({
        id: hit._id,
        score: hit._score,
        ...hit._source
      }));
      return toolResult(JSON.stringify({ count: entities.length, entities }, null, 2), {
        count: entities.length,
        entities
      });
    },

    agent_memory_health: async () => {
      const [info, health] = await Promise.all([
        client.info ? client.info() : Promise.resolve({ body: {} }),
        client.cluster?.health ? client.cluster.health() : Promise.resolve({ body: {} })
      ]);
      return toolResult('OpenSearch memory backend is reachable.', {
        opensearch: info.body,
        health: health.body,
        model_id: modelId
      });
    }
  };

  async function resolveModelId() {
    if (cachedModelId) {
      return cachedModelId;
    }
    if (!client.get) {
      return '';
    }
    try {
      const response = await client.get({
        index: INDICES.status,
        id: 'embedding-model'
      });
      cachedModelId = response?.body?._source?.source_ref || '';
      return cachedModelId;
    } catch {
      return '';
    }
  }
}

function requiredString(value, name) {
  if (typeof value !== 'string' || !value.trim()) {
    throw new Error(`${name} is required`);
  }
  return value.trim();
}

function slug(value) {
  return String(value)
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-|-$/g, '')
    .slice(0, 120);
}
