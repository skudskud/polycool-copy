# DipDup Indexer Dockerfile
# Handles: On-chain indexing of Conditional Tokens on Polygon
# Build context: apps/subsquid-silo-tests/indexer/

FROM python:3.10-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    curl \
    build-essential \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir dipdup

# Copy application code (all local, no ../)
COPY src ./src
COPY dipdup ./dipdup

# Copy dipdup.yaml as dipdup.yml
COPY dipdup/dipdup.yaml dipdup/dipdup.yml

# Set Python path
ENV PYTHONPATH=/app:$PYTHONPATH

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/metrics || exit 1

# Run DipDup
CMD ["sh", "-c", "cd /app/dipdup && dipdup run --config dipdup.yml 2>&1"]
