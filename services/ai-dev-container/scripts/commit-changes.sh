#!/bin/bash
# Commit changes to git with AI-generated message

set -e

PROJECT_DIR="/workspace/project"
COMMIT_MESSAGE=${1:-"AI: Update project files"}

echo "💾 Committing changes to git..."

cd "$PROJECT_DIR"

# Check if there are any changes
if git diff --quiet && git diff --cached --quiet; then
    echo "ℹ️  No changes to commit"
    exit 0
fi

# Add all changes
echo "📁 Adding changes..."
git add .

# Show what's being committed
echo "📋 Changes to be committed:"
git diff --cached --name-status

# Commit with message
echo "💾 Committing with message: $COMMIT_MESSAGE"
git commit -m "$COMMIT_MESSAGE"

# Show commit info
echo "✅ Commit successful!"
git log --oneline -1

echo "📊 Repository status:"
git status --short
