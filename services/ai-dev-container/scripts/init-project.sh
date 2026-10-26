#!/bin/bash
# Initialize a new Next.js project from template

set -e

TEMPLATE_NAME=${1:-""}
PROJECT_NAME=${2:-"ai-project"}
PROJECT_DIR="/workspace/project"

echo "🚀 Initializing Next.js project: $PROJECT_NAME"

# Clean up any existing project
if [ -d "$PROJECT_DIR" ]; then
    echo "📁 Cleaning up existing project directory..."
    rm -rf "$PROJECT_DIR"
fi

# Create project directory
mkdir -p "$PROJECT_DIR"
cd "$PROJECT_DIR"

# Initialize git repository first
echo "📦 Initializing git repository..."
git init
git config user.name "${GIT_USER_NAME:-AI Developer}"
git config user.email "${GIT_USER_EMAIL:-ai@platform.local}"

# Create Next.js project
if [ -n "$TEMPLATE_NAME" ]; then
    echo "📋 Creating Next.js project with template: $TEMPLATE_NAME"
    npx create-next-app@latest . --example "$TEMPLATE_NAME" --typescript --tailwind --eslint --app --src-dir --import-alias "@/*" --yes
else
    echo "📋 Creating default Next.js project..."
    npx create-next-app@latest . --typescript --tailwind --eslint --app --src-dir --import-alias "@/*" --yes
fi

# Initial git commit
echo "💾 Creating initial commit..."
git add .
git commit -m "Initial commit: Next.js project with template ${TEMPLATE_NAME:-default}"

echo "✅ Project initialized successfully!"
echo "📁 Project location: $PROJECT_DIR"

# List project structure
echo "📂 Project structure:"
find . -maxdepth 2 -type f -name "*.json" -o -name "*.js" -o -name "*.ts" -o -name "*.tsx" | head -10
