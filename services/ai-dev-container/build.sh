#!/bin/bash
# Build the AI development container

set -e

IMAGE_NAME="git.example.com/homelab/ai-dev-container"
TAG=${1:-"latest"}

echo "🐳 Building AI development container..."
echo "📦 Image: $IMAGE_NAME:$TAG"

# Build the Docker image
docker buildx build --platform linux/amd64 --load -t "$IMAGE_NAME:$TAG" .

echo "✅ Build complete!"
echo "🚀 To push: docker push $IMAGE_NAME:$TAG"
echo "🏃 To run: docker run -it --rm $IMAGE_NAME:$TAG /bin/bash"
