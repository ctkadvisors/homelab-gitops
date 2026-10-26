#!/bin/bash
# Build and push Chris TTS service to Gitea registry
# Must be run on Jetson 2 (ARM64 with NVIDIA GPU)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REGISTRY="git.example.com"
IMAGE_NAME="homelab/chris-tts"
TAG="${1:-latest}"

echo "🔨 Building Chris TTS service..."
cd "$SCRIPT_DIR"

# Build the image
docker build -t "${REGISTRY}/${IMAGE_NAME}:${TAG}" .

echo "📤 Pushing to registry..."
# Login to Gitea registry (credentials should be in ~/.docker/config.json)
docker push "${REGISTRY}/${IMAGE_NAME}:${TAG}"

echo "✅ Done! Image: ${REGISTRY}/${IMAGE_NAME}:${TAG}"
echo ""
echo "To deploy, the ArgoCD app will auto-sync, or run:"
echo "  kubectl apply -f /path/to/k8s/apps/chris-tts.yaml"
