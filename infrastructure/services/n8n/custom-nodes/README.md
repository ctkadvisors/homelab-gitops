# n8n MCPO Integration

This directory contains custom n8n nodes for integrating with MCPO (Model Context Protocol Operations).

## Setup

1. Custom nodes are automatically loaded from this directory when n8n starts
2. The MCPO integration allows n8n workflows to:
   - Call MCPO tools
   - Use AI models through OpenWebUI
   - Chain multiple AI operations

## Available Nodes

### MCPO Tool Node
- Execute any MCPO tool
- Pass parameters dynamically
- Handle tool responses

### Model Chat Node
- Send messages to AI models
- Support for conversation context
- Streaming responses

## Example Workflow

```json
{
  "nodes": [
    {
      "name": "Webhook",
      "type": "n8n-nodes-base.webhook",
      "position": [250, 300],
      "parameters": {
        "path": "ai-assistant",
        "responseMode": "onReceived",
        "responseData": "allEntries"
      }
    },
    {
      "name": "MCPO Tool",
      "type": "n8n-nodes-custom.mcpoTool",
      "position": [450, 300],
      "parameters": {
        "tool": "web_search",
        "query": "={{$json.query}}"
      }
    },
    {
      "name": "Model Chat",
      "type": "n8n-nodes-custom.modelChat",
      "position": [650, 300],
      "parameters": {
        "model": "mistral:7b-instruct",
        "messages": [
          {
            "role": "system",
            "content": "You are a helpful assistant."
          },
          {
            "role": "user",
            "content": "={{$json.query}}"
          }
        ]
      }
    }
  ]
}
```

## Configuration

Set these environment variables in n8n:

```bash
MCPO_API_URL=http://mcpo:8090
MODEL_ROUTER_URL=http://model-router:8000
```

## Creating Custom Tools

1. Define your tool in MCPO Control Panel
2. Use the tool name in n8n workflows
3. Pass parameters as JSON

## Troubleshooting

- Check n8n logs: `docker service logs localai_n8n`
- Verify MCPO is running: `curl http://mcpo:8090/health`
- Test model router: `curl http://model-router:8000/health`
