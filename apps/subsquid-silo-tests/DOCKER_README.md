# Docker Setup for Subsquid Silo Tests

Complete Docker Compose setup for local development and testing of all 7 services.

## Quick Start

### Prerequisites
- Docker & Docker Compose (v2.0+)
- 4GB+ RAM available
- Ports 5432, 6379, 8081 available

### Run Everything
```bash
cd apps/subsquid-silo-tests

# Start all services
docker-compose -f docker-compose.silo.yml up -d

# View logs
docker-compose -f docker-compose.silo.yml logs -f

# Stop all services
docker-compose -f docker-compose.silo.yml down
```

## Architecture

```
┌─────────────────────────────────────────────────┐
│         Docker Network (subsquid-network)       │
├─────────────────────────────────────────────────┤
│                                                 │
│  ┌──────────────┐         ┌──────────────┐     │
│  │   Redis      │         │  PostgreSQL  │     │
│  │   Port 6379  │         │  Port 5432   │     │
│  └──────┬───────┘         └──────┬───────┘     │
│         │                        │              │
│  ┌──────┴────────────────────────┴───────┐     │
│  │     5 Services (Off-Chain)            │     │
│  ├───────────────────────────────────────┤     │
│  │ • Poller (Gamma API polling)         │     │
│  │ • Streamer (CLOB WebSocket)          │     │
│  │ • Webhook (FastAPI, port 8081)       │     │
│  │ • Bridge (Redis Pub/Sub)             │     │
│  │ • Orchestrator (All services)        │     │
│  └───────────────────────────────────────┘     │
│                                                 │
│  ┌──────────────────────────────────────┐     │
│  │  Indexer (On-Chain via DipDup)       │     │
│  └──────────────────────────────────────┘     │
│                                                 │
└─────────────────────────────────────────────────┘
```

## Services

### 1. Redis
- **Image:** `redis:7-alpine`
- **Port:** `6379`
- **Volume:** `redis_data`
- **Purpose:** Pub/Sub, caching

### 2. PostgreSQL
- **Image:** `postgres:15-alpine`
- **Port:** `5432`
- **Volume:** `postgres_data`
- **Database:** `subsquid`
- **Credentials:** `subsquid:subsquid_dev_password`

### 3. Poller
- **Polls:** Gamma API every 60s
- **Updates:** `subsquid_markets_poll`
- **Logs:** `docker-compose logs poller -f`

### 4. Streamer
- **Connects:** CLOB WebSocket
- **Updates:** `subsquid_markets_ws`
- **Auto-reconnect:** Enabled
- **Logs:** `docker-compose logs streamer -f`

### 5. Webhook
- **Endpoint:** `http://localhost:8081/wh/market`
- **Health:** `http://localhost:8081/health`
- **Metrics:** `http://localhost:8081/metrics`
- **Logs:** `docker-compose logs webhook -f`

### 6. Bridge
- **Subscribes:** Redis Pub/Sub channels
- **Posts:** To webhook worker
- **Channels:** `market.status.*`, `clob.trade.*`, `clob.orderbook.*`
- **Logs:** `docker-compose logs bridge -f`

### 7. Indexer (DipDup)
- **Indexes:** Polygon (Conditional Tokens)
- **Updates:** `subsquid_fills_onchain`, `subsquid_user_transactions`
- **RPC:** `https://polygon-rpc.com`
- **Logs:** `docker-compose logs indexer -f`

### 8. Orchestrator
- **Runs:** All 5 off-chain services simultaneously
- **Replaces:** Individual service containers
- **Logs:** `docker-compose logs orchestrator -f`

## Usage

### View Logs
```bash
# All services
docker-compose -f docker-compose.silo.yml logs -f

# Specific service
docker-compose -f docker-compose.silo.yml logs -f poller
docker-compose -f docker-compose.silo.yml logs -f webhook

# Last 100 lines
docker-compose -f docker-compose.silo.yml logs --tail=100
```

### Access Database
```bash
# Connect via psql
docker-compose -f docker-compose.silo.yml exec postgres \
  psql -U subsquid -d subsquid

# Query example:
# SELECT * FROM subsquid_markets_poll LIMIT 5;
```

### Access Redis
```bash
# Connect via redis-cli
docker-compose -f docker-compose.silo.yml exec redis redis-cli

# Commands:
# KEYS subsquid_*
# DBSIZE
# MONITOR
```

### Test Webhook Locally
```bash
# Health check
curl http://localhost:8081/health

# Send test event
curl -X POST http://localhost:8081/wh/market \
  -H "Content-Type: application/json" \
  -d '{
    "market_id": "0x123",
    "event": "test.event",
    "payload": {"test": "data"}
  }'

# View metrics
curl http://localhost:8081/metrics
```

### Run CLI Scripts
```bash
# From container
docker-compose -f docker-compose.silo.yml exec orchestrator \
  python scripts/read_poll.py

docker-compose -f docker-compose.silo.yml exec orchestrator \
  python scripts/compare_freshness.py

# Or from host (if environment set)
python scripts/read_poll.py
```

## Environment Variables

Override in `docker-compose.silo.yml` or `.env`:

```bash
DATABASE_URL=postgresql://subsquid:subsquid_dev_password@postgres:5432/subsquid
REDIS_URL=redis://redis:6379/0
EXPERIMENTAL_SUBSQUID=true
POLL_MS=60000
LOG_LEVEL=INFO
```

## Troubleshooting

### Service won't start
```bash
# Check logs
docker-compose -f docker-compose.silo.yml logs webhook

# Common issues:
# - Port already in use: kill other processes on 5432, 6379, 8081
# - Out of memory: increase Docker memory limit
# - Network issues: restart Docker daemon
```

### Database connection failed
```bash
# Restart postgres
docker-compose -f docker-compose.silo.yml restart postgres

# Check health
docker-compose -f docker-compose.silo.yml ps
```

### Redis connection failed
```bash
# Restart redis
docker-compose -f docker-compose.silo.yml restart redis

# Check connection
docker-compose -f docker-compose.silo.yml exec redis redis-cli ping
```

### Webhook not receiving events
```bash
# Check bridge is running
docker-compose -f docker-compose.silo.yml ps

# Check bridge logs
docker-compose -f docker-compose.silo.yml logs bridge -f

# Seed test data
docker-compose -f docker-compose.silo.yml exec orchestrator \
  python scripts/seed_redis.py
```

## Development Workflow

### 1. Start services
```bash
docker-compose -f docker-compose.silo.yml up -d
```

### 2. Verify health
```bash
# Check all services are running
docker-compose -f docker-compose.silo.yml ps

# Test endpoints
curl http://localhost:8081/health
docker-compose exec postgres psql -U subsquid -d subsquid -c "SELECT 1"
docker-compose exec redis redis-cli ping
```

### 3. Monitor logs
```bash
docker-compose -f docker-compose.silo.yml logs -f
```

### 4. Run tests
```bash
docker-compose -f docker-compose.silo.yml exec orchestrator \
  pytest tests/ -v
```

### 5. Clean up
```bash
# Stop services
docker-compose -f docker-compose.silo.yml down

# Remove volumes (careful!)
docker-compose -f docker-compose.silo.yml down -v
```

## Performance Tuning

### For slower machines
```yaml
# In docker-compose.silo.yml
services:
  poller:
    environment:
      POLL_MS: "120000"  # Increase to 2 minutes
```

### For faster local testing
```yaml
services:
  poller:
    environment:
      POLL_MS: "30000"  # Decrease to 30 seconds
```

### Resource Limits
```yaml
# Add to services
resources:
  limits:
    cpus: '0.5'
    memory: 512M
  reservations:
    cpus: '0.25'
    memory: 256M
```

## Production Notes

- `docker-compose.silo.yml` is for **local development only**
- For production on Railway, use individual services with `railway.json`
- Never commit `.env` file with secrets
- Use strong passwords for PostgreSQL
- Enable SSL for PostgreSQL connections
- Use managed Redis (e.g., Railway Redis) in production

## Useful Commands

```bash
# View all services
docker-compose -f docker-compose.silo.yml ps

# Restart all
docker-compose -f docker-compose.silo.yml restart

# Restart specific service
docker-compose -f docker-compose.silo.yml restart webhook

# Execute command in container
docker-compose -f docker-compose.silo.yml exec poller python -c "print('test')"

# View image sizes
docker images | grep subsquid

# Clean up unused images/volumes
docker image prune
docker volume prune

# Full cleanup (careful!)
docker-compose -f docker-compose.silo.yml down -v
docker system prune -a
```

## Next Steps

After local testing with Docker:
1. Deploy to Railway (Phase 12)
2. Configure production environment variables
3. Set up monitoring and alerting
4. Enable SSL/TLS

See `README.md` for more information.
