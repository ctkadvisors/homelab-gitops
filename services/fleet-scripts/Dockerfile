# fleet-scripts: the deterministic side of the agent fleet. Runs python
# jobs directly (triage, scribe, report, collect) and is copied into the
# dsh stage containers (improve-daily, missions, pr-reviewer) via an init
# container so scripts stop living inside ConfigMaps.
FROM python:3.12-alpine
RUN apk add --no-cache git openssl curl openssh-client   # openssh-client: fleet-node-runner's host actions
# kubectl for the pipeline stages, read-only through the fleet-stage
# ServiceAccount: a repair mission can look at the pod that died.
ARG KUBECTL_VERSION=v1.32.5
RUN mkdir -p /app/bin && curl -fsSL "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/amd64/kubectl" -o /app/bin/kubectl && chmod 0755 /app/bin/kubectl
# The Postgres driver travels WITH the scripts: fleet-hooks and the publish
# stage run in the agent-coder image with /app copied in, so a system-wide
# pip install here would not reach them. fleet/ledger.py adds ./vendor to sys.path.
RUN pip install --no-cache-dir --target /app/vendor pg8000==1.31.2
WORKDIR /app
COPY fleet /app/fleet
COPY scripts /app/scripts
COPY skills /app/skills
COPY plugins /app/plugins
RUN chmod +x /app/scripts/*.sh
USER 1000
CMD ["python3", "/app/scripts/triage.py"]
