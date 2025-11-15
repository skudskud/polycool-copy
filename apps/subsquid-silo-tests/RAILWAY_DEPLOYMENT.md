# Railway Deployment Guide

Complete guide for deploying Subsquid Silo Tests to Railway in production.

## Prerequisites

- Railway account (https://railway.app)
- Railway CLI installed: `npm i -g @railway/cli`
- Git repository connected
- Supabase project (staging database)
- Redis instance (Railway or external)

## Architecture

```
┌─────────────────────────────────────┐
│      Railway Project: subsquid      │
├─────────────────────────────────────┤
│                                     │
│  5 Separate Services                │
│  ┌────────────────────────────┐     │
│  │ poller     (512MB, 0.5 CPU)│     │
│  │ streamer   (512MB, 0.5 CPU)│     │
│  │ webhook    (256MB, 0.25CPU)│     │
│  │ bridge     (256MB, 0.25CPU)│     │
│  │ indexer    (1GB, 1 CPU)    │     │
│  └────────────────────────────┘     │
│                                     │
│  Shared Services                    │
│  ┌────────────────────────────┐     │
│  │ Supabase (Staging DB)      │     │
│  │ Redis (Staging)            │     │
│  └────────────────────────────┘     │
│                                     │
└─────────────────────────────────────┘
```

## Quick Setup

### 1. Create Railway Project

```bash
# Login
railway login

# Create project
railway new subsquid-silo

# Select Python environment
```

### 2. Link to Repository

```bash
# In project root
railway link

# Select existing project or create new
```

### 3. Add Environment Variables

```bash
# For each service, set these in Railway dashboard:

# Database (Staging)
DATABASE_URL=postgresql://user:pass@staging.supabase.co/subsquid

# Redis (Staging)
REDIS_URL=redis://staging-redis.railway.internal:6379/0

# Common
EXPERIMENTAL_SUBSQUID=true
LOG_LEVEL=INFO
```

## Deploy Each Service

### A. Deploy Poller

```bash
# Create service
railway service create poller

# Deploy
railway up --service poller

# Configure (use contents of railway-poller.json)
# Dashboard: Set environment variables
```

**Key Settings:**
- Start Command: `python -m src.polling.poller`
- Memory: 512MB
- CPU: 0.5
- Restart Policy: Max 5 retries

### B. Deploy Streamer

```bash
# Create service
railway service create streamer

# Deploy
railway up --service streamer

# Configure (use contents of railway-streamer.json)
```

**Key Settings:**
- Start Command: `python -m src.ws.streamer`
- Memory: 512MB
- CPU: 0.5
- Variables:
  - CLOB_WSS_URL: `wss://ws.clob.polymarket.com`
  - WS_HEARTBEAT_INTERVAL: `30`

### C. Deploy Webhook

```bash
# Create service
railway service create webhook

# Deploy
railway up --service webhook

# Configure (use contents of railway-webhook.json)
```

**Key Settings:**
- Start Command: `python -m src.wh.webhook_worker`
- Memory: 256MB
- CPU: 0.25
- Port: 8081
- Health Check: GET /health

### D. Deploy Bridge

```bash
# Create service
railway service create bridge

# Deploy
railway up --service bridge

# Configure (use contents of railway-bridge.json)
```

**Key Settings:**
- Start Command: `python -m src.redis.bridge`
- Memory: 256MB
- CPU: 0.25
- REDIS_BRIDGE_WEBHOOK_URL: `https://<webhook-domain>/wh/market`

### E. Deploy Indexer

```bash
# Create service
railway service create indexer

# Deploy
railway up --service indexer

# Configure (use contents of railway-indexer.json)
```

**Key Settings:**
- Start Command: `cd indexer/dipdup && python -m dipdup run`
- Memory: 1GB
- CPU: 1
- POLYGON_RPC_URL: `https://polygon-rpc.com`

## Shared Services

### Add Supabase (Staging)

```bash
# Railway → Plugins → Add Postgres

# Or link external:
railway variable DATABASE_URL postgresql://...
```

### Add Redis (Staging)

```bash
# Railway → Plugins → Add Redis

# Or link external:
railway variable REDIS_URL redis://...
```

## Post-Deployment

### Verify Services

```bash
# List all services
railway service list

# View logs
railway logs --service poller
railway logs --service webhook

# Check health
curl https://<webhook-domain>/health
```

### Connect Services

1. **Get Webhook URL from Railway Dashboard**
   - webhook service → Settings → Domain
   - Copy full URL (e.g., `https://subsquid-webhook.railway.app`)

2. **Set in Bridge service**
   - railway variable REDIS_BRIDGE_WEBHOOK_URL https://subsquid-webhook.railway.app/wh/market

3. **Restart bridge**
   - railway up --service bridge

### Database Setup

```bash
# Connect to staging Supabase
psql $DATABASE_URL

# Run migrations
\i supabase/migrations/2025-11-21_subsquid_silo.sql

# Verify tables
\dt subsquid_*
```

### Monitoring

```bash
# View all logs in real-time
railway logs --follow

# View specific service
railway logs --service poller --follow

# Export logs
railway logs --since 1h > logs.txt
```

## Environment Variables by Service

### Global (All Services)
```
EXPERIMENTAL_SUBSQUID=true
LOG_LEVEL=INFO
DATABASE_URL=postgresql://...
REDIS_URL=redis://...
```

### Poller
```
POLLER_ENABLED=true
POLL_MS=60000
GAMMA_API_URL=https://gamma-api.polymarket.com
GAMMA_API_TIMEOUT=30
```

### Streamer
```
STREAMER_ENABLED=true
CLOB_WSS_URL=wss://ws.clob.polymarket.com
WS_CONNECT_TIMEOUT=10
WS_HEARTBEAT_INTERVAL=30
WS_MAX_RECONNECT_BACKOFF=30
```

### Webhook
```
WEBHOOK_ENABLED=true
WEBHOOK_HOST=0.0.0.0
WEBHOOK_PORT=8081
WEBHOOK_TIMEOUT=10
```

### Bridge
```
REDIS_BRIDGE_ENABLED=true
REDIS_BRIDGE_WEBHOOK_URL=https://<webhook-domain>/wh/market
REDIS_BRIDGE_TIMEOUT=10
REDIS_SUBSCRIBE_PATTERNS=market.status.*,clob.trade.*,clob.orderbook.*
```

### Indexer
```
POLYGON_RPC_URL=https://polygon-rpc.com
DIPDUP_ENVIRONMENT=prod
```

## Troubleshooting

### Service won't start

```bash
# View detailed logs
railway logs --service <service> --raw

# Common issues:
# - Missing environment variables
# - Database connection timeout
# - Redis connection refused
# - Out of memory

# Solution:
railway variable <VAR_NAME> <value>
railway up --service <service>
```

### Database connection failed

```bash
# Test connection from Railway CLI
railway shell

# Inside shell:
psql $DATABASE_URL -c "SELECT 1"

# Check if tables exist
psql $DATABASE_URL -c "\dt subsquid_*"
```

### Webhook not receiving events

```bash
# Check bridge is running
railway logs --service bridge -f

# Check webhook logs
railway logs --service webhook -f

# Test webhook endpoint
curl https://<webhook-domain>/health

# Check Redis connectivity
railway shell
redis-cli -u $REDIS_URL PING
```

### Memory issues

Increase memory in railway.json:
```json
"memoryMB": 1024
```

Then redeploy:
```bash
railway up --service <service>
```

## Cost Estimation

| Service   | Memory | CPU | Est. Cost/month |
|-----------|--------|-----|-----------------|
| Poller    | 512MB  | 0.5 | $5              |
| Streamer  | 512MB  | 0.5 | $5              |
| Webhook   | 256MB  | 0.25| $2              |
| Bridge    | 256MB  | 0.25| $2              |
| Indexer   | 1GB    | 1   | $10             |
| Postgres  | 512MB  | -   | $5              |
| Redis     | 256MB  | -   | $2              |
| **Total** | -      | -   | **~$31/month**  |

## Scaling

### Horizontal Scaling (Multiple Replicas)

```bash
# Scale poller to 2 replicas
railway variable REPLICAS 2 --service poller
railway up --service poller
```

### Resource Tuning

```bash
# Increase streamer memory (WebSocket uses more)
railway variable MEMORY 1024 --service streamer

# Increase indexer CPU (on-chain processing)
railway variable CPU 2 --service indexer
```

## Migration from Staging to Production

### 1. Create Prod Database

```bash
# In Supabase:
# Create new Postgres instance for production
# OR use separate schema: subsquid_prod_*
```

### 2. Create Prod Redis

```bash
# In Railway or external provider
# Create new Redis instance for production
```

### 3. Create Prod Environment

```bash
# Create new Railway project: subsquid-prod
railway new subsquid-prod

# Deploy all services with prod URLs
```

### 4. Run Migrations

```bash
# On prod database:
psql $PROD_DATABASE_URL -f supabase/migrations/2025-11-21_subsquid_silo.sql
```

### 5. Gradual Rollover

```bash
# Keep staging running (1 week)
# Monitor prod side-by-side
# Compare freshness metrics
# Switch traffic when confident
```

## Monitoring & Alerting

### Key Metrics to Watch

```
- Poller: Updated records per minute
- Streamer: Reconnections per hour, latency p95
- Webhook: Events received per minute, errors
- Bridge: Messages bridged per minute
- Indexer: Blocks processed, events indexed
```

### Set Alerts

In Railway Dashboard:
1. Go to service
2. Monitoring → Alerts
3. Add CPU/Memory/Crash alerts

### View Metrics

```bash
# Via Railway CLI
railway insights

# Or check dashboard:
# https://railway.app → Project → Deployments
```

## Cleanup

### Stop Services

```bash
# Pause entire project
railway pause

# Or remove specific service
railway service delete poller
```

### Remove Project

```bash
railway project delete subsquid-silo
```

## Next Steps

1. **Local Testing:** Run `docker-compose.silo.yml` first
2. **Staging Deploy:** Deploy to Railway with staging credentials
3. **Monitoring:** Check logs and metrics for 24 hours
4. **Prod Deploy:** Once stable, deploy to production
5. **Gradual Rollout:** Run staging + prod in parallel

See `README.md` for full project documentation.
