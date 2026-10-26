# CodeGen Service

AI-powered code generation service using OpenRouter for fast, reliable Next.js project generation.

## Overview

The CodeGen Service replaces the slow Jetson Ollama setup with a fast, cloud-based AI inference solution using OpenRouter's free and paid models. This service generates complete Next.js projects based on natural language descriptions.

## Features

- **Fast AI Generation**: Uses OpenRouter's optimized models for sub-30-second response times
- **Free Tier Support**: Supports free models like Moonshot Kimi K2, Llama 3.2 3B, and Phi-3 Mini
- **Paid Model Options**: Can upgrade to Claude 3.5 Sonnet, GPT-4o Mini, and other premium models
- **Production Ready**: Includes proper error handling, logging, and monitoring
- **Kubernetes Native**: Designed for deployment in your GitOps workflow

## API Endpoints

### `POST /generate`
Generate a new Next.js project.

**Request:**
```json
{
  "projectName": "my-awesome-app",
  "description": "A todo app with user authentication",
  "framework": "nextjs",
  "features": ["typescript", "tailwind"],
  "styling": "tailwind",
  "database": "supabase",
  "userId": "user123"
}
```

**Response:**
```json
{
  "success": true,
  "data": {
    "files": [
      {
        "path": "package.json",
        "content": "..."
      },
      {
        "path": "src/app/page.tsx",
        "content": "..."
      }
    ],
    "instructions": "Run: npm install && npm run dev",
    "buildCommand": "npm run build",
    "startCommand": "npm run dev"
  },
  "requestId": "uuid-here",
  "timestamp": "2025-01-07T...",
  "model": "openrouter"
}
```

### `POST /generate/:model`
Generate with a specific model (e.g., `/generate/claude-3.5-sonnet`).

### `GET /models`
List available models and their capabilities.

### `GET /health`
Health check endpoint.

## Available Models

### Free Models
- **kimi-k2**: Moonshot Kimi K2 - Good for code generation
- **llama-3.2-3b**: Meta Llama 3.2 3B - Fast and capable
- **phi-3-mini**: Microsoft Phi-3 Mini - Optimized for coding

### Paid Models
- **claude-3.5-sonnet**: Anthropic Claude 3.5 Sonnet - Premium quality
- **gpt-4o-mini**: OpenAI GPT-4o Mini - Balanced performance
- **llama-3.1-70b**: Meta Llama 3.1 70B - Large context window

## Environment Variables

- `OPENROUTER_API_KEY`: Required. Your OpenRouter API key
- `PORT`: Optional. Server port (default: 3000)
- `NODE_ENV`: Optional. Environment (default: production)

## Development

```bash
# Install dependencies
npm install

# Start development server
npm run dev

# Build for production
npm run build

# Start production server
npm start
```

## Docker Build

```bash
# Build image
docker build -t codegen-service .

# Run container
docker run -p 3000:3000 -e OPENROUTER_API_KEY=your-key codegen-service
```

## Deployment

The service is deployed via GitOps using ArgoCD:

1. **Build and Push**: Use `scripts/build-codegen-service.sh`
2. **Commit Changes**: Git commit the Kubernetes manifests
3. **ArgoCD Sync**: ArgoCD automatically deploys the changes

### Kubernetes Resources

- **Deployment**: `codegen-service` in `ai-services` namespace
- **Service**: ClusterIP service for internal access
- **Secret**: OpenRouter API key storage
- **NetworkPolicy**: Restricts traffic to platform namespace

### Resource Requirements

- **Requests**: 256Mi memory, 250m CPU
- **Limits**: 512Mi memory, 500m CPU
- **Node Selector**: Runs on EliteMini x86_64 nodes

## Integration

The service integrates with the Platform API's `aiWorkflowService.ts`:

```typescript
// Platform API calls CodeGen service
const response = await fetch('http://codegen-service.ai-services.svc.cluster.local:3000/generate', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(request)
});
```

## Performance

- **Response Time**: ~10-30 seconds (vs 10+ minutes with Jetson Ollama)
- **Throughput**: Handles concurrent requests efficiently
- **Reliability**: Professional API service with 99.9% uptime
- **Cost**: Free tier available, paid models cost-effective

## Monitoring

- **Health Checks**: Kubernetes liveness and readiness probes
- **Logging**: Structured JSON logs with request IDs
- **Metrics**: Request duration, success rates, model usage
- **Alerts**: Failed requests, high latency, service unavailability

## Security

- **API Key**: Stored as Kubernetes Secret
- **Network Policy**: Restricts ingress/egress traffic
- **Non-root User**: Container runs as non-privileged user
- **Read-only Filesystem**: Security hardening enabled

## Troubleshooting

### Common Issues

1. **API Key Invalid**: Check OpenRouter API key in secret
2. **Model Not Found**: Verify model name in request
3. **Timeout**: Increase request timeout for complex projects
4. **Rate Limits**: Monitor OpenRouter usage limits

### Logs

```bash
# Check service logs
kubectl logs -n ai-services deployment/codegen-service -f

# Check specific pod
kubectl logs -n ai-services pod/codegen-service-xxx -f
```

### Debug Mode

Set `NODE_ENV=development` for verbose logging.

## Migration from Ollama

This service replaces the slow Jetson Ollama setup:

- **Before**: 10+ minutes per request, 1 token/second
- **After**: 10-30 seconds per request, professional API
- **Benefits**: 20x faster, more reliable, better quality output
- **Cost**: Free tier available, paid models very affordable

The Platform API automatically falls back to OpenAI if this service fails, ensuring high availability.
