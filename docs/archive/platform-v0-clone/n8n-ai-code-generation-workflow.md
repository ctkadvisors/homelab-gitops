# Enhanced AI Code Generation Workflow with Redis Queue

## Overview

This document describes the enhanced AI Code Generation workflow system that replaces the problematic webhook-based Fission functions with a robust n8n-based architecture using Redis queues and HTTP triggers.

## Architecture

```
HTTP POST Request → Job Queue → Background Processing → Progress Updates
                      ↓
                 Redis Queue → AI Generation → Repository Creation → Completion
```

### Key Improvements

1. **HTTP Triggers**: More reliable than webhooks, better error handling
2. **Redis Queue System**: Asynchronous job processing with progress tracking
3. **Immediate Response**: Returns job ID immediately for async pattern
4. **Progress Tracking**: Real-time status updates via Redis
5. **Error Handling**: Comprehensive error handling and retry logic
6. **Timeout Management**: Handles long-running AI inference gracefully

## Workflows Created

### 1. Enhanced AI Code Generation with Redis Queue (ID: 4EU6ldgHEVolM1u9)

**Main workflow for processing code generation requests.**

#### API Endpoint

- **URL**: `POST /webhook/ai-code-generate`
- **Response**: Immediate job ID (HTTP 202)
- **Processing**: Asynchronous via Redis queue

#### Request Format

```json
{
  "prompt": "Create a Python function that calculates fibonacci numbers",
  "language": "python",
  "repoName": "fibonacci-calculator",
  "description": "A simple fibonacci calculator implementation"
}
```

#### Response Format

```json
{
  "success": true,
  "jobId": "job_1721102847123_abc123def",
  "status": "queued",
  "message": "Code generation job queued successfully",
  "statusUrl": "/api/job-status/job_1721102847123_abc123def",
  "estimatedTime": "30-60 seconds"
}
```

#### Workflow Steps

1. **HTTP Code Request** - Receives POST request
2. **Generate Job ID** - Creates unique job identifier
3. **Queue Job in Redis** - Stores job data in Redis
4. **Return Job ID** - Immediate response to client
5. **Update Job Status - Processing** - Background processing begins
6. **Ollama AI Code Generation** - Calls Ollama API for code generation
7. **Process AI Response** - Extracts and processes generated code
8. **Update Job Status - Creating Repository** - Updates progress
9. **Create Gitea Repository** - Creates new Git repository
10. **Commit Generated Code** - Commits code to repository
11. **Update Job Status - Completed** - Marks job as complete

### 2. AI Code Generation Job Status API (ID: hT4qitFsrJu4vIo5)

**Status checking workflow for monitoring job progress.**

#### API Endpoint

- **URL**: `GET /webhook/job-status/{jobId}`
- **Response**: Current job status and progress

#### Response Format

```json
{
  "success": true,
  "jobId": "job_1721102847123_abc123def",
  "status": "completed",
  "progress": 100,
  "createdAt": "2025-07-16T10:30:00.000Z",
  "updatedAt": "2025-07-16T10:31:15.000Z",
  "completedAt": "2025-07-16T10:31:15.000Z",
  "repositoryUrl": "https://git.example.com/chris/fibonacci-calculator",
  "request": {
    "prompt": "Create a Python function that calculates fibonacci numbers",
    "language": "python"
  }
}
```

#### Job Status Values

- `queued` - Job received and queued for processing
- `processing` - AI code generation in progress

## CRITICAL INFRASTRUCTURE ISSUES (2025-01-20)

### ❌ WORKFLOW CURRENTLY FAILING

**Status**: BROKEN - Infrastructure dependency failure

**Root Cause**: Ollama service connectivity issues in ai-services namespace

**Error**: "The resource you are requesting could not be found" when attempting to connect to Ollama

### Infrastructure Problems Identified

1. **Multiple Ollama Deployments**:

   - `ollama` service (jetson1)
   - `ollama-n8n` service (jetson2)
   - Unclear which service should be used for n8n workflows

2. **Service Discovery Issues**:

   - Neither `ollama.ai-services.svc.cluster.local:11434` nor `ollama-n8n.ai-services.svc.cluster.local:11434` responding
   - Services may not be running or properly configured

3. **Model Availability**:
   - qwen2.5-coder:0.5b model may not be loaded/available
   - No verification of model status before workflow execution

### Lessons Learned

1. **Infrastructure First**: Always verify infrastructure dependencies before claiming workflow success
2. **End-to-End Testing**: Successful workflow configuration ≠ working system if dependencies fail
3. **Service Verification**: Must validate Ollama service accessibility from n8n pods
4. **Model Management**: Need process to ensure required models are loaded and available

### Required Fixes

1. **Diagnose Ollama Services**:

   ```bash
   kubectl get pods -n ai-services
   kubectl logs -n ai-services deployment/ollama
   kubectl logs -n ai-services deployment/ollama-n8n
   ```

2. **Verify Service Connectivity**:

   ```bash
   kubectl exec -n n8n deployment/n8n -- curl http://ollama-n8n.ai-services.svc.cluster.local:11434/api/tags
   ```

3. **Model Verification**:

   ```bash
   kubectl exec -n ai-services deployment/ollama-n8n -- ollama list
   ```

4. **Load Required Model**:
   ```bash
   kubectl exec -n ai-services deployment/ollama-n8n -- ollama pull qwen2.5-coder:0.5b
   ```

### Critical Testing Protocol

**NEVER claim a workflow is working without:**

1. ✅ End-to-end successful execution
2. ✅ All infrastructure dependencies verified
3. ✅ Fresh test execution (not relying on old successful runs)
4. ✅ Error-free response with expected data structure

- `creating_repository` - Creating Git repository
- `completed` - Job completed successfully
- `failed` - Job failed with error

## Redis Integration

### Redis Configuration

- **Host**: `redis.automation.svc.cluster.local`
- **Port**: `6379`
- **Key Pattern**: `job:{jobId}`

### Job Data Structure

```redis
HMSET job:job_1721102847123_abc123def
  status "completed"
  progress "100"
  data "{\"id\":\"job_1721102847123_abc123def\",\"request\":{...}}"
  createdAt "2025-07-16T10:30:00.000Z"
  updatedAt "2025-07-16T10:31:15.000Z"
  completedAt "2025-07-16T10:31:15.000Z"
  repositoryUrl "https://git.example.com/chris/fibonacci-calculator"
```

## Service Integration

### Ollama AI Service

- **Endpoint**: `http://10.43.5.144:11434/api/generate`
- **Model**: `gemma2:2b`
- **Timeout**: 60 seconds
- **Retry**: 2 attempts

### Gitea Git Service

- **API Base**: `https://git.example.com/api/v1`
- **Authentication**: Bearer token via `GITEA_API_TOKEN` variable
- **Operations**: Repository creation, file commits

## Error Handling

### Timeout Management

- **HTTP Request Timeout**: 60 seconds for Ollama
- **Repository Operations**: 15 seconds with 2 retries
- **Redis Operations**: 5-10 seconds

### Retry Logic

- **Ollama API**: 2 retries on failure
- **Gitea API**: 2 retries on failure
- **Redis Operations**: 3 retries on failure

### Error States

When errors occur, jobs are marked as `failed` with error details stored in Redis.

## Performance Characteristics

### Timing Estimates

- **Job Queuing**: < 1 second
- **AI Code Generation**: 24-36 seconds (Jetson Orin Nano)
- **Repository Creation**: 5-10 seconds
- **Total Processing**: 30-60 seconds

### Resource Usage

- **Memory**: Minimal (stateless processing)
- **CPU**: Managed by Ollama service on GPU nodes
- **Storage**: Redis for job tracking, Gitea for repositories

## Configuration Requirements

### n8n Variables

```bash
GITEA_API_TOKEN=your_gitea_access_token
```

### Redis Deployment

- Ensure Redis is deployed at `redis.automation.svc.cluster.local:6379`
- Configure persistence for job data retention

## Testing Strategy

### Unit Tests

1. **HTTP Trigger Test**: Verify webhook receives and processes requests
2. **Job ID Generation**: Ensure unique job IDs are created
3. **Redis Integration**: Test job storage and retrieval
4. **Ollama Integration**: Verify AI code generation
5. **Gitea Integration**: Test repository creation and commits

### Integration Tests

1. **End-to-End Flow**: Complete request → response → completion cycle
2. **Error Scenarios**: Timeout handling, API failures, network issues
3. **Concurrent Processing**: Multiple simultaneous requests
4. **Status Polling**: Job status updates and progress tracking

### Load Testing

1. **Concurrent Requests**: Test queue handling under load
2. **Redis Performance**: Verify job storage performance
3. **Timeout Behavior**: Ensure graceful handling of long operations

## Monitoring and Observability

### Key Metrics

- **Job Processing Time**: End-to-end completion time
- **Queue Depth**: Number of pending jobs
- **Success Rate**: Percentage of successful completions
- **Error Rate**: Failed job percentage by error type

### Logging

- **n8n Execution Logs**: Detailed workflow execution traces
- **Redis Logs**: Job state changes and errors
- **External API Logs**: Ollama and Gitea API interactions

## Migration from Fission

### Deprecated Components

- Fission functions (`ai-code-generator`)
- Webhook-based triggers
- Direct synchronous processing

### Migration Steps

1. Deploy Redis service
2. Create and activate n8n workflows
3. Update client applications to use new endpoints
4. Test new async workflow
5. Decommission Fission functions

## API Usage Examples

### Submit Code Generation Request

```bash
curl -X POST https://n8n.example.com/webhook/ai-code-generate \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "Create a REST API in Go for user management",
    "language": "go",
    "repoName": "user-management-api",
    "description": "REST API for managing users with CRUD operations"
  }'
```

### Check Job Status

```bash
curl -X GET https://n8n.example.com/webhook/job-status/job_1721102847123_abc123def
```

### Poll for Completion

```bash
#!/bin/bash
JOB_ID="job_1721102847123_abc123def"
while true; do
  STATUS=$(curl -s "https://n8n.example.com/webhook/job-status/$JOB_ID" | jq -r '.status')
  echo "Status: $STATUS"
  if [[ "$STATUS" == "completed" || "$STATUS" == "failed" ]]; then
    break
  fi
  sleep 5
done
```

## Security Considerations

### Authentication

- Gitea API requires valid access token
- Redis access should be restricted to automation namespace
- n8n webhooks should use authentication if exposed externally

### Data Privacy

- Generated code is stored in Git repositories
- Job data in Redis contains request details
- Consider data retention policies for Redis

### Network Security

- Internal service communication within cluster
- External Gitea API over HTTPS
- Redis should not be exposed externally

## Troubleshooting

### Common Issues

1. **Job Stuck in Processing**

   - Check Ollama service health
   - Verify GPU availability on Jetson nodes
   - Review n8n execution logs

2. **Repository Creation Fails**

   - Verify Gitea API token validity
   - Check network connectivity to git.example.com
   - Ensure repository name is unique

3. **Redis Connection Issues**
   - Verify Redis service deployment
   - Check DNS resolution for redis.automation.svc.cluster.local
   - Review Redis logs for errors

### Debugging Commands

```bash
# Check n8n workflow executions
kubectl logs -n automation deployment/n8n -f

# Check Redis connectivity
kubectl exec -n automation deployment/redis -- redis-cli ping

# Check Ollama service
kubectl logs -n ai-services deployment/ollama -f

# Test workflow endpoint
curl -v https://n8n.example.com/webhook/ai-code-generate
```

## Future Enhancements

### Planned Features

1. **Webhook Notifications**: Optional callbacks on completion
2. **Batch Processing**: Multiple code generation requests
3. **Template System**: Pre-defined code templates
4. **Quality Metrics**: Code quality scoring and validation
5. **Multi-Model Support**: Choice of different AI models

### Scalability Improvements

1. **Horizontal Scaling**: Multiple n8n instances
2. **Redis Clustering**: Distributed job storage
3. **Load Balancing**: Request distribution
4. **Caching**: Generated code caching for similar requests

---

_This documentation covers the enhanced AI Code Generation workflow system designed to replace the Fission-based architecture with a more robust, scalable, and maintainable solution._
