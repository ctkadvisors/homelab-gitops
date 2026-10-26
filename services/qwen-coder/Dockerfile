FROM node:24-bookworm-slim

RUN apt-get update \
  && apt-get install -y --no-install-recommends \
    git \
    bash \
    ca-certificates \
    gettext-base \
    ripgrep \
  && rm -rf /var/lib/apt/lists/*

RUN npm i -g \
  typescript \
  typescript-language-server \
  prettier \
  @earendil-works/pi-coding-agent@0.80.2 \
  @ast-grep/cli

WORKDIR /app

COPY package*.json ./

RUN npm install --omit=dev

COPY server.mjs qwen-run workspace-guard.ts docker-entrypoint.sh ./
COPY agent ./agent

RUN chmod +x qwen-run docker-entrypoint.sh

ENV HOME=/root \
  QWEN_WORK_ROOT=/work \
  QWEN_RUNNER=/app/qwen-run \
  QWEN_GUARD_EXT=/app/workspace-guard.ts \
  QWEN_TRACE_DIR=/work/traces

EXPOSE 8080

ENTRYPOINT ["/app/docker-entrypoint.sh"]
