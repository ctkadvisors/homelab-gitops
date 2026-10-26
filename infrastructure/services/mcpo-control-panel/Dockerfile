# MCPO Control Panel - ARM64 Compatible Build
# Based on the official daswer123/mcpo-control-panel repository
FROM python:3.11-slim

# Install system dependencies including essential build tools and utilities
RUN apt-get update && apt-get install -y \
    curl \
    gnupg \
    git \
    build-essential \
    procps \
    && rm -rf /var/lib/apt/lists/*

# Install Node.js 22.x (required for some MCPO functionality)
RUN mkdir -p /etc/apt/keyrings && \
    curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg && \
    echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_22.x nodistro main" | tee /etc/apt/sources.list.d/nodesource.list && \
    apt-get update && apt-get install -y nodejs && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Install uv for faster Python package management
RUN pip install uv

# Create virtual environment
RUN uv venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install mcpo-control-panel using uv
RUN uv pip install mcpo-control-panel

# Set working directory
WORKDIR /app

# Expose the ports
EXPOSE 8083
EXPOSE 8000

# Set environment variables with defaults
ENV MCPO_MANAGER_HOST=0.0.0.0
ENV MCPO_MANAGER_PORT=8083
ENV MCPO_MANAGER_DATA_DIR=/data

# Create data directory
RUN mkdir -p /data

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:${MCPO_MANAGER_PORT}/ui || exit 1

# Command to run the application
CMD ["python", "-m", "mcpo_control_panel", "--host", "0.0.0.0", "--port", "8083", "--config-dir", "/data"]
