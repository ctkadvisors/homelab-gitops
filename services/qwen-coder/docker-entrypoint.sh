#!/usr/bin/env bash
set -euo pipefail

# pi reads its config from $HOME/.pi/agent; pin HOME so it finds the rendered
# models.json below (the image runs as root, where Docker may leave HOME unset,
# and server.mjs's childEnv() otherwise falls back to a stale Mac path).
export HOME=/root

: "${SPARK_BASE_URL:=http://spark-llamaswap.ai-services.svc.cluster.local:9090/v1}"
: "${SPARK_API_KEY:=dummy-key}"
# export so envsubst (a child process) sees them when rendering models.json
export SPARK_BASE_URL SPARK_API_KEY

mkdir -p /root/.pi/agent
envsubst '${SPARK_BASE_URL} ${SPARK_API_KEY}' < /app/agent/models.json > /root/.pi/agent/models.json
cp /app/agent/settings.json /root/.pi/agent/settings.json

exec node /app/server.mjs
