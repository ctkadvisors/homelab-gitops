#!/usr/bin/env node
import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { StreamableHTTPServerTransport } from '@modelcontextprotocol/sdk/server/streamableHttp.js';
import opensearch from '@opensearch-project/opensearch';
import { createServer } from 'node:http';
import { pathToFileURL } from 'node:url';
import { z } from 'zod';

import { toolError } from './src/memory.mjs';
import { createToolHandlers } from './src/tools.mjs';

const { Client } = opensearch;

const serverInfo = {
  name: 'agent-memory-mcp-server',
  title: 'Agent Memory MCP',
  version: '0.1.1'
};

const attributionInputSchema = {
  recorded_by: z.string().min(1).describe('Client or agent that recorded the memory, for example claude-code, codex, or qwen-coder.'),
  source_kind: z.string().min(1).describe('Source type, for example conversation, repo, runbook, incident, manual, smoke-test.'),
  source_ref: z.string().min(1).describe('Stable source reference such as claude-session:<id>, codex-session:<id>, file path, URL, commit, or ticket key.'),
  source_actor: z.string().min(1).describe('Original actor/source of the fact, for example user:homelab-user, agent:claude-code, system:argocd.')
};

const config = {
  port: Number.parseInt(process.env.PORT || '8080', 10),
  opensearchUrl: process.env.OPENSEARCH_URL || 'https://opensearch.search.svc.cluster.local:9200',
  opensearchUsername: process.env.OPENSEARCH_USERNAME || 'admin',
  opensearchPassword: process.env.OPENSEARCH_PASSWORD || '',
  modelId: process.env.OPENSEARCH_MODEL_ID || '',
  bearerToken: process.env.MCP_BEARER_TOKEN || '',
  rejectUnauthorized: process.env.OPENSEARCH_SSL_REJECT_UNAUTHORIZED === 'true'
};

function createOpenSearchClient() {
  const node = new URL(config.opensearchUrl);
  if (config.opensearchUsername) {
    node.username = config.opensearchUsername;
  }
  if (config.opensearchPassword) {
    node.password = config.opensearchPassword;
  }
  return new Client({
    node: node.toString(),
    ssl: {
      rejectUnauthorized: config.rejectUnauthorized
    }
  });
}

function buildServer() {
  const client = createOpenSearchClient();
  const handlers = createToolHandlers({
    client,
    modelId: config.modelId
  });

  const server = new McpServer({
    name: serverInfo.name,
    version: serverInfo.version
  });

  registerTool(server, 'agent_memory_remember', {
    title: 'Remember Agent Memory',
    description: 'Persist an attributed durable memory for an agent in OpenSearch. Use for facts, decisions, environment details, and durable handoff notes.',
    inputSchema: {
      agent_id: z.string().min(1).describe('Stable agent or client ID, for example claude-code.'),
      content: z.string().min(1).max(12000).describe('Memory text to persist.'),
      summary: z.string().max(1000).optional().describe('Optional short summary for recall display.'),
      ...attributionInputSchema,
      tags: z.array(z.string()).optional().describe('Optional tags for filtering.'),
      entities: z.array(z.object({ name: z.string(), type: z.string().optional() })).optional().describe('Optional named entities mentioned by this memory.'),
      importance: z.number().int().min(1).max(5).optional().describe('Importance from 1 low to 5 critical.'),
      trust_level: z.string().optional().describe('Review status, for example unreviewed, observed, confirmed.')
    },
    annotations: {
      readOnlyHint: false,
      destructiveHint: false,
      idempotentHint: false,
      openWorldHint: false
    }
  }, handlers.agent_memory_remember);

  registerTool(server, 'agent_memory_recall', {
    title: 'Recall Agent Memory',
    description: 'Search durable agent memory using hybrid lexical and OpenSearch neural recall, then return ranked memories.',
    inputSchema: {
      agent_id: z.string().min(1).describe('Stable agent or client ID to search within.'),
      query: z.string().min(1).max(2000).describe('Natural-language recall query.'),
      tags: z.array(z.string()).optional().describe('Optional tags that all returned memories must match.'),
      limit: z.number().int().min(1).max(50).optional().describe('Maximum ranked memories to return.'),
      model_id: z.string().optional().describe('Override OpenSearch ML model ID for neural recall.')
    },
    annotations: {
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: false
    }
  }, handlers.agent_memory_recall);

  registerTool(server, 'agent_memory_supersede', {
    title: 'Supersede Agent Memory',
    description: 'Replace an outdated memory with a new active memory and mark the old memory superseded.',
    inputSchema: {
      agent_id: z.string().min(1),
      memory_id: z.string().min(1).describe('Existing memory document ID to supersede.'),
      content: z.string().min(1).max(12000).describe('Replacement memory content.'),
      reason: z.string().optional().describe('Why the old memory is being replaced.'),
      tags: z.array(z.string()).optional(),
      ...attributionInputSchema,
      importance: z.number().int().min(1).max(5).optional()
    },
    annotations: {
      readOnlyHint: false,
      destructiveHint: true,
      idempotentHint: false,
      openWorldHint: false
    }
  }, handlers.agent_memory_supersede);

  registerTool(server, 'agent_memory_session_log', {
    title: 'Log Agent Session Message',
    description: 'Append a message/event from an agent session to the searchable session log index.',
    inputSchema: {
      agent_id: z.string().min(1),
      session_id: z.string().min(1),
      role: z.string().optional(),
      content: z.string().min(1).max(20000),
      ...attributionInputSchema,
      tags: z.array(z.string()).optional()
    },
    annotations: {
      readOnlyHint: false,
      destructiveHint: false,
      idempotentHint: false,
      openWorldHint: false
    }
  }, handlers.agent_memory_session_log);

  registerTool(server, 'agent_memory_task_upsert', {
    title: 'Upsert Agent Task',
    description: 'Create or update an agent task record for handoffs, status tracking, and follow-up retrieval.',
    inputSchema: {
      agent_id: z.string().min(1),
      task_id: z.string().min(1),
      title: z.string().optional(),
      status: z.string().optional(),
      priority: z.string().optional(),
      summary: z.string().optional(),
      ...attributionInputSchema
    },
    annotations: {
      readOnlyHint: false,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: false
    }
  }, handlers.agent_memory_task_upsert);

  registerTool(server, 'agent_memory_entity_index', {
    title: 'Index Agent Entity',
    description: 'Create or update a named entity and append an entity-history event.',
    inputSchema: {
      agent_id: z.string().min(1),
      name: z.string().min(1),
      type: z.string().optional(),
      summary: z.string().optional(),
      aliases: z.array(z.string()).optional(),
      ...attributionInputSchema,
      tags: z.array(z.string()).optional(),
      event: z.string().optional()
    },
    annotations: {
      readOnlyHint: false,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: false
    }
  }, handlers.agent_memory_entity_index);

  registerTool(server, 'agent_memory_entity_search', {
    title: 'Search Agent Entities',
    description: 'Search named entities known to an agent.',
    inputSchema: {
      agent_id: z.string().min(1),
      query: z.string().min(1),
      type: z.string().optional(),
      limit: z.number().int().min(1).max(50).optional()
    },
    annotations: {
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: false
    }
  }, handlers.agent_memory_entity_search);

  registerTool(server, 'agent_memory_health', {
    title: 'Check Agent Memory Health',
    description: 'Check whether the OpenSearch-backed memory service is reachable.',
    inputSchema: {},
    annotations: {
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: false
    }
  }, handlers.agent_memory_health);

  return server;
}

function registerTool(server, name, definition, handler) {
  server.registerTool(name, definition, async (args) => {
    try {
      return await handler(args || {});
    } catch (err) {
      return toolError(err?.message || String(err));
    }
  });
}

async function handleMcpRequest(req, res) {
  if (config.bearerToken) {
    const expected = `Bearer ${config.bearerToken}`;
    if (req.headers.authorization !== expected) {
      res.writeHead(401, { 'Content-Type': 'application/json' }).end(
        JSON.stringify({ error: 'unauthorized' })
      );
      return;
    }
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
    console.error('mcp request failed', err);
    if (!res.headersSent) {
      res.writeHead(500, { 'Content-Type': 'application/json' }).end(
        JSON.stringify({ jsonrpc: '2.0', error: { code: -32603, message: 'Internal error' }, id: null })
      );
    }
  }
}

export function startHttpServer() {
  return createServer(async (req, res) => {
    const { pathname } = new URL(req.url || '/', 'http://localhost');
    if (pathname === '/healthz') {
      res.writeHead(200, { 'Content-Type': 'application/json' }).end(
        JSON.stringify({ ok: true, service: serverInfo.name })
      );
      return;
    }
    if (pathname === '/mcp') {
      await handleMcpRequest(req, res);
      return;
    }
    res.writeHead(404).end();
  }).listen(config.port, () => {
    console.error(`${serverInfo.name} listening on :${config.port}`);
  });
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  startHttpServer();
}
