# AI Development Container
# Provides a complete Node.js development environment for AI to work in
FROM node:20-alpine

# Install system dependencies
RUN apk add --no-cache \
    git \
    bash \
    curl \
    openssh-client \
    python3 \
    make \
    g++ \
    && rm -rf /var/cache/apk/*

# Set up working directory
WORKDIR /workspace

# Install global npm packages that might be needed
RUN npm install -g \
    create-next-app \
    typescript \
    @types/node \
    eslint \
    prettier \
    && npm cache clean --force

# Configure git (will be overridden by runtime config)
RUN git config --global user.name "AI Developer" \
    && git config --global user.email "ai@platform.local" \
    && git config --global init.defaultBranch main

# Create directories for project work
RUN mkdir -p /workspace/project \
    && mkdir -p /workspace/temp \
    && mkdir -p /workspace/scripts

# Add helper scripts for common operations
COPY scripts/ /workspace/scripts/
RUN chmod +x /workspace/scripts/*.sh

# Set up environment
ENV NODE_ENV=development
ENV NPM_CONFIG_UPDATE_NOTIFIER=false
ENV NPM_CONFIG_FUND=false

# Expose port for development server
EXPOSE 3000

# Default command - keep container running
CMD ["tail", "-f", "/dev/null"]
