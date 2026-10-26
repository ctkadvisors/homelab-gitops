# Chris Voice TTS Service

Text-to-speech service using Qwen3-TTS with Chris's cloned voice.

## Features

- FastAPI service with `/synthesize` endpoint
- Voice cloning using Qwen3-TTS 1.7B model
- Output formats: OGG Opus (WhatsApp-compatible), WAV
- Runs on Jetson Orin Nano with NVIDIA GPU acceleration

## API

### POST /synthesize

Generate speech from text.

**Request:**
```json
{
  "text": "Hello, this is a test message.",
  "format": "ogg"  // or "wav"
}
```

**Response:** Audio file (streaming)

### GET /health

Health check endpoint.

**Response:**
```json
{
  "status": "healthy",
  "model_loaded": true,
  "reference_loaded": true,
  "gpu_memory_gb": 3.92
}
```

## Deployment

### Prerequisites

1. Models downloaded to Jetson 2: `~/qwen-tts/models/1.7B-Base/`
2. Reference audio: `~/qwen-tts/chris_voice.wav`
3. Gitea registry credentials configured

### Build (on Jetson 2)

```bash
# Copy service files to Jetson
scp -r services/chris-tts chris@10.0.0.75:~/

# Build and push
ssh chris@10.0.0.75 "cd ~/chris-tts && ./build-and-push.sh"
```

### Deploy

ArgoCD auto-syncs from `k8s/apps/`. Or manually:

```bash
kubectl apply -f k8s/apps/chris-tts.yaml
```

### Access

- Internal: `http://chris-tts.ai-services.svc.cluster.local:8000`
- External: `http://10.0.0.75:31800` (NodePort)

## Usage Example (curl)

```bash
curl -X POST http://10.0.0.75:31800/synthesize \
  -H "Content-Type: application/json" \
  -d '{"text": "Hey, what's up?", "format": "ogg"}' \
  --output speech.ogg
```

## Usage from Clawdbot

The service can be called directly from Clawdbot to generate voice messages:

```bash
# Generate and send as WhatsApp voice note
curl -X POST http://10.0.0.75:31800/synthesize \
  -H "Content-Type: application/json" \
  -d '{"text": "Your message here", "format": "ogg"}' \
  -o /tmp/voice.ogg

# Then use message tool to send
```

## Architecture

```
┌─────────────────┐     ┌──────────────────────────────────────┐
│   Clawdbot      │────▶│  Jetson 2 (10.0.0.75:31800)     │
│   (Mac Mini)    │     │  ┌─────────────────────────────────┐ │
└─────────────────┘     │  │ chris-tts Pod                   │ │
                        │  │ ├── FastAPI (uvicorn)           │ │
                        │  │ ├── Qwen3-TTS 1.7B (float16)    │ │
                        │  │ └── Chris voice reference       │ │
                        │  └─────────────────────────────────┘ │
                        │  GPU: NVIDIA Orin Nano (7.4GB)       │
                        └──────────────────────────────────────┘
```
