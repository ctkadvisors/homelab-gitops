# Agent Memory MCP

Streamable HTTP MCP server backed by OpenSearch. It gives local coding agents a durable memory store with lexical plus neural recall, session logs, tasks, and entity tracking.

## Tools

- `agent_memory_remember`
- `agent_memory_recall`
- `agent_memory_supersede`
- `agent_memory_session_log`
- `agent_memory_task_upsert`
- `agent_memory_entity_index`
- `agent_memory_entity_search`
- `agent_memory_health`

## Local Run

```bash
npm install
OPENSEARCH_URL=https://localhost:9200 \
OPENSEARCH_USERNAME=admin \
OPENSEARCH_PASSWORD=... \
OPENSEARCH_SSL_REJECT_UNAUTHORIZED=false \
npm start
```

MCP endpoint: `http://localhost:8080/mcp`.

## Image

```bash
docker build --platform linux/amd64 --provenance=false --sbom=false \
  -t git.example.com/homelab/agent-memory-mcp:0.1.1 .
```
