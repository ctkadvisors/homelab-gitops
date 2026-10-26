#!/bin/bash
# Start the Next.js development server

set -e

PROJECT_DIR="/workspace/project"

echo "🚀 Starting Next.js development server..."

cd "$PROJECT_DIR"

# Check if package.json exists
if [ ! -f "package.json" ]; then
    echo "❌ No package.json found. Please initialize project first."
    exit 1
fi

# Install dependencies if node_modules doesn't exist
if [ ! -d "node_modules" ]; then
    echo "📦 Installing dependencies..."
    npm install
fi

# Start development server
echo "🌐 Starting development server on port 3000..."
npm run dev
