# n8n Workflows for RAG Pipeline

This directory contains n8n workflows that integrate with the RAG pipeline infrastructure.

## Available Workflows

### 1. Document Ingestion to Qdrant (`document-ingestion.json`)

**Purpose**: Processes documents and stores them as embeddings in Qdrant for RAG functionality.

**Workflow Steps**:
1. **Document Webhook** - Receives document content via HTTP POST
2. **Split Document** - Chunks document into 1000-character segments with 200-character overlap
3. **Generate Embeddings** - Creates embeddings using `nomic-embed-text:latest` model via Ollama
4. **Store in Qdrant** - Saves embeddings and metadata to Qdrant vector database
5. **Success/Error Response** - Returns appropriate HTTP response

**Webhook Endpoint**: `https://n8n.homelab/webhook/ingest-document`

**Request Format**:
```json
{
  "text": "Your document content here...",
  "source": "document.txt",
  "id": "optional-document-id"
}
```

**Response Format**:
```json
{
  "status": "success",
  "message": "Document ingested successfully",
  "chunks_processed": 5,
  "collection": "openwebui_docs"
}
```

## Deployment

### Via GitOps (Recommended)
```bash
# Deploy workflows via the deployment script
./scripts/deploy-n8n-workflows.sh
```

### Manual Import
1. Access n8n UI at https://n8n.homelab
2. Go to Workflows → Import from File
3. Select the workflow JSON file
4. Activate the workflow

## Configuration

### Service Endpoints
- **Ollama**: `http://ollama.ai-services.svc.cluster.local:11434`
- **Qdrant**: `http://qdrant.vector-db.svc.cluster.local:6333`
- **n8n**: `https://n8n.homelab`

### Environment Variables
The workflows use cluster-internal service DNS names for communication between services.

## Integration with RAG Pipeline

### OpenWebUI Integration
Documents processed through this workflow are automatically available in OpenWebUI's RAG functionality:

1. Upload documents via the n8n webhook
2. Documents are chunked and embedded
3. Embeddings stored in Qdrant collection `openwebui_docs`
4. OpenWebUI can now search and retrieve relevant document chunks

### Usage Example
```bash
# Ingest a document
curl -X POST https://n8n.homelab/webhook/ingest-document \
  -H 'Content-Type: application/json' \
  -d '{
    "text": "This is a sample document about artificial intelligence...",
    "source": "ai-guide.txt"
  }'

# Document is now available for RAG queries in OpenWebUI
```

## Monitoring

### Workflow Execution
- Monitor workflow executions in n8n UI
- Check logs for embedding generation and Qdrant storage
- Verify document chunks in Qdrant dashboard

### Troubleshooting
1. **Webhook not responding**: Check n8n deployment status
2. **Embedding generation fails**: Verify Ollama service and model availability
3. **Qdrant storage fails**: Check Qdrant service connectivity and collection existence

## Development

### Adding New Workflows
1. Create new JSON workflow file in this directory
2. Follow naming convention: `workflow-name.json`
3. Include appropriate tags and metadata
4. Test workflow before committing
5. Update this README with workflow documentation

### Workflow Standards
- Use cluster-internal service DNS names
- Include error handling nodes
- Add appropriate tags for organization
- Document webhook endpoints and data formats
- Follow consistent naming conventions

## Security

### API Access
- Workflows use internal cluster networking
- No external API keys required for basic functionality
- Webhook endpoints are publicly accessible (consider authentication if needed)

### Data Privacy
- Document content is processed and stored in Qdrant
- Embeddings are generated locally via Ollama
- No external AI services used

## Next Steps

1. **Enhanced Document Processing**: Add support for file uploads, PDF parsing, etc.
2. **Batch Processing**: Create workflows for bulk document ingestion
3. **Document Management**: Add workflows for updating/deleting documents
4. **Analytics**: Create workflows for RAG usage analytics and monitoring
