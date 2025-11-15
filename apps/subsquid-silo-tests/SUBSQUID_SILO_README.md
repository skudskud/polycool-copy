# Subsquid Silo Tests - Quick Reference Guide

Fast reference for common tasks and workflows.

## Start Here

### First Time Setup

```bash
# 1. Navigate to project
cd apps/subsquid-silo-tests

# 2. Copy environment template
cp .env.example .env

# 3. Edit .env with your Supabase staging credentials
# DATABASE_URL=postgresql://...
# REDIS_URL=redis://...

# 4. Start services
docker-compose -f docker-compose.silo.yml up -d

# 5. Run database migrations
docker-compose exec postgres psql -U subsquid -d subsquid < supabase/migrations/2025-11-21_subsquid_silo.sql

# 6. Verify everything is running
docker-compose -f docker-compose.silo.yml ps
```

## View Data

### See What's Being Collected

```bash
# Polling data (Gamma API)
python scripts/read_poll.py

# WebSocket data (CLOB real-time)
python scripts/read_ws.py

# Webhook events (Redis bridge)
python scripts/read_wh.py

# Side-by-side comparison
python scripts/compare_freshness.py
```

## Test Everything

```bash
# All tests
pytest tests/ -v

# Specific test
pytest tests/test_isolation.py -v

# With coverage
pytest --cov=src --cov-report=html tests/

# In Docker
docker-compose exec orchestrator pytest tests/ -v
```

## Common Tasks

### Generate Test Data

```bash
# Seed Redis with 100 test events
python scripts/seed_redis.py --count 100

# Check webhook received them
python scripts/read_wh.py
```

### Check Service Status

```bash
# All services
docker-compose -f docker-compose.silo.yml ps

# Specific service logs
docker-compose -f docker-compose.silo.yml logs -f poller
docker-compose -f docker-compose.silo.yml logs -f webhook

# Last 50 lines
docker-compose -f docker-compose.silo.yml logs --tail=50 webhook
```

### Query Database Directly

```bash
# Connect to PostgreSQL
docker-compose exec postgres psql -U subsquid -d subsquid

# Inside psql:
# \dt subsquid_*              -- List tables
# SELECT COUNT(*) FROM subsquid_markets_poll;
# SELECT * FROM subsquid_markets_ws LIMIT 5;
# \q                          -- Exit
```

### Test Webhook Endpoint

```bash
# Health check
curl http://localhost:8081/health

# Send test event
curl -X POST http://localhost:8081/wh/market \
  -H "Content-Type: application/json" \
  -d '{"market_id": "0xtest", "event": "test", "payload": {}}'

# View metrics
curl http://localhost:8081/metrics
```

## Deploy to Railway

```bash
# Quick setup (see RAILWAY_DEPLOYMENT.md for full guide)

railway login
railway new subsquid-silo

# Deploy each service
railway up --service poller
railway up --service streamer
railway up --service webhook
railway up --service bridge
railway up --service indexer

# View logs
railway logs --service poller -f
```

## Monitor Metrics

### Freshness

```bash
# Polling freshness (should be ~60ms)
python scripts/read_poll.py | grep freshness

# WebSocket freshness (should be ~50ms)
python scripts/read_ws.py | grep latency

# Compare all
python scripts/compare_freshness.py
```

## Troubleshooting

### Services Won't Start

```bash
# Check memory/CPU
docker stats

# Check logs for errors
docker-compose -f docker-compose.silo.yml logs

# Restart everything
docker-compose -f docker-compose.silo.yml restart
```

### No Data in Tables

```bash
# Check if services are running
docker-compose -f docker-compose.silo.yml ps

# View service logs
docker-compose logs poller -f

# Manually seed data
python scripts/seed_redis.py --count 10
python scripts/read_wh.py
```

### Database Connection Failed

```bash
# Test connection
docker-compose exec orchestrator psql $DATABASE_URL -c "SELECT 1"

# Check environment variables
docker-compose exec orchestrator env | grep DATABASE_URL
```

## File Locations

| File | Purpose |
|------|---------|
| `.env.example` | Environment variables template |
| `supabase/migrations/2025-11-21_subsquid_silo.sql` | Database schema |
| `src/main.py` | Orchestrator entry point |
| `src/polling/poller.py` | Gamma API polling |
| `src/ws/streamer.py` | CLOB WebSocket |
| `docker-compose.silo.yml` | Local orchestration |

## Typical Workflow

### Development Iteration

```bash
# Start fresh
docker-compose down -v
docker-compose up -d

# Wait for services
sleep 10

# View freshness
python scripts/compare_freshness.py

# Make code changes and test
pytest tests/ -v

# Rebuild and verify
docker-compose build
docker-compose restart poller
```

### Deploy to Staging

```bash
# Commit changes
git add -A
git commit -m "feat: improve polling"

# Deploy to Railway
railway up --service poller

# Monitor
railway logs -f
```

## Quick Help

| Question | Command |
|----------|---------|
| Services running? | `docker-compose ps` |
| Why is it failing? | `docker-compose logs <service>` |
| How fresh is data? | `python scripts/compare_freshness.py` |
| Run tests? | `pytest tests/ -v` |
| Deploy? | `railway up --service <name>` |

---

For more details, see README.md, DOCKER_README.md, or RAILWAY_DEPLOYMENT.md
