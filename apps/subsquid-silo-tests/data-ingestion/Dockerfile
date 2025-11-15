# Data Ingestion Services Dockerfile
# Handles: Poller, Webhook, Streamer, Redis Bridge
# Build context: apps/subsquid-silo-tests/data-ingestion/

FROM python:3.10-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    postgresql-client \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code (all local, no ../)
COPY src ./src
COPY tests ./tests
COPY scripts ./scripts

# Set Python path
ENV PYTHONPATH=/app:$PYTHONPATH

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD python -c "import asyncio; print('OK')" || exit 1

# Start ALL services (Poller + Streamer + Webhook) via coordinator
# Services are controlled by env vars: POLLER_ENABLED, STREAMER_ENABLED, etc.
CMD ["python", "-m", "src.main"]
