# 🚀 PRODUCTION DEPLOYMENT GUIDE - Polycool on Railway

**Status:** ✅ IN PROGRESS - Nov 9, 2025

---

## 📊 CURRENT DEPLOYMENT STATUS

| Service | Status | Endpoint | Notes |
|---------|--------|----------|-------|
| **polycool-api** | ✅ **RUNNING** | https://polycool-api-production.up.railway.app | FastAPI, Supabase connected |
| **polycool-bot** | ✅ **RUNNING** | Telegram polling | Bot ready, SKIP_DB=true |
| **polycool-workers** | ✅ **RUNNING** | Background tasks | Streamer + TP/SL + Copy-trading listener |
| **polycool-indexer** | 🔄 **BUILDING** | Subsquid TypeScript | EVM indexer for on-chain fills |
| **Redis-suej** | ✅ **RUNNING** | redis-suej.railway.internal:6379 | Single shared cache instance |
| **Supabase (xxzdlbwfyetaxcmodiec)** | ✅ **RUNNING** | Pooler: aws-1-eu-north-1 | PostgreSQL via connection pooler |

---

## 🎯 ARCHITECTURE DECISION

### Why Multi-Service? (Not Monolithic)

**Problem with 1 service:**
- All background tasks in FastAPI lifespan
- Database fail → entire app crashes
- WebSocket hang → everything zombie
- Startup > 60s → Railway kills process

**Solution: 4 specialized services**
```
┌─────────────────────────────────────────────────┐
│           Railway Services Architecture        │
├─────────────────────────────────────────────────┤
│                                                  │
│ polycool-api      → FastAPI (2-3s startup)     │
│ polycool-bot      → Telegram (3-5s startup)    │
│ polycool-workers  → Background (5-10s startup) │
│ polycool-indexer  → Subsquid (10-15s startup)  │
│                                                  │
│ Redis-suej        → Shared cache               │
│ Supabase Pooler   → Database                   │
└─────────────────────────────────────────────────┘
```

**Benefit:** Each service can fail independently, restart quickly, scale separately

---

## 🔧 CONFIGURATION APPLIED

### 1️⃣ Database: Supabase Pooler (Not Direct Connection)

**Why Pooler?**
- Direct: `db.xxzdlbwfyetaxcmodiec.supabase.co` → Railway can't reach (network isolation)
- Pooler: `aws-1-eu-north-1.pooler.supabase.com` → Optimized for Railway/Vercel

**Current Config (All Services):**
```bash
DATABASE_URL=postgresql://postgres.xxzdlbwfyetaxcmodiec:ClDSK0N5IedorZes@aws-1-eu-north-1.pooler.supabase.com:5432/postgres
```

**Changed from:** `db.xxzdlbwfyetaxcmodiec.supabase.co` (direct, unreachable)

---

### 2️⃣ Redis: Single Instance Sufficient

**Why NOT multiple instances?**
- ❌ Cache incoherence (stale data)
- ❌ Pub/Sub broken (messages lost between instances)
- ❌ Expensive + complex

**Current Config (All Services):**
```bash
REDIS_URL=redis://redis-suej.railway.internal:6379
```

**Serves:**
- Price cache (TTL 20s)
- Position cache (TTL 3min)
- Redis Pub/Sub (copy-trading listener)
- Session storage

---

### 3️⃣ Service-Specific Configuration

#### **polycool-api**
```bash
DATABASE_URL=postgresql://postgres.xxzdlbwfyetaxcmodiec:...@aws-1-eu-north-1.pooler...
REDIS_URL=redis://redis-suej.railway.internal:6379
SKIP_DB=false              # Init database on startup
STREAMER_ENABLED=false     # No background workers
TPSL_MONITORING_ENABLED=false
```
- Entry: `api_only.py`
- Startup: 2-3s
- Role: HTTP API server
- Health: `GET /health/live`, `GET /health/ready`

#### **polycool-bot**
```bash
DATABASE_URL=postgresql://postgres.xxzdlbwfyetaxcmodiec:...@aws-1-eu-north-1.pooler...
REDIS_URL=redis://redis-suej.railway.internal:6379
SKIP_DB=true               # Don't try to init DB
STREAMER_ENABLED=false     # No background workers
TPSL_MONITORING_ENABLED=false
```
- Entry: `bot_only.py`
- Startup: 3-5s
- Role: Telegram polling bot
- Behavior: Listens to `/start`, `/wallet`, `/markets`, etc.

#### **polycool-workers**
```bash
DATABASE_URL=postgresql://postgres.xxzdlbwfyetaxcmodiec:...@aws-1-eu-north-1.pooler...
REDIS_URL=redis://redis-suej.railway.internal:6379
SKIP_DB=false              # Init database on startup
STREAMER_ENABLED=true      # WebSocket streamer
TPSL_MONITORING_ENABLED=true  # TP/SL monitor
```
- Entry: `workers.py`
- Startup: 5-10s
- Role: Background tasks
  - WebSocket streamer (market prices)
  - TP/SL monitor (order trigger check)
  - Copy-trading listener (Redis Pub/Sub)
  - Watched addresses sync (every 5 min)

#### **polycool-indexer**
```bash
DATABASE_URL=postgresql://postgres.xxzdlbwfyetaxcmodiec:...@aws-1-eu-north-1.pooler...
REDIS_URL=redis://redis-suej.railway.internal:6379
POLYGON_RPC_URL=https://polygon-rpc.com
```
- Entry: `npm start` (Subsquid)
- Startup: 10-15s
- Role: EVM indexer
  - Tracks trades on Polygon
  - Publishes to Redis `copy_trade:*`
  - Updates watched addresses

---

## 📋 DEPLOYMENT CHECKLIST

### ✅ Pre-Deployment
- [x] Supabase project created (`xxzdlbwfyetaxcmodiec`)
- [x] Railway project linked (`cheerful-fulfillment`)
- [x] All services created on Railway
- [x] Redis instance provisioned

### ✅ Configuration
- [x] DATABASE_URL → Pooler (all services)
- [x] REDIS_URL → redis-suej (all services)
- [x] SKIP_DB → proper values per service
- [x] STREAMER/TPSL flags → correct overrides

### ✅ Deployments
- [x] polycool-api → Running ✅
- [x] polycool-bot → Running ✅
- [x] polycool-workers → Running ✅
- [ ] polycool-indexer → Building 🔄

### 📋 Post-Deployment Validation

Once all services are running, execute this checklist:

```bash
# 1. API Health Check
curl https://polycool-api-production.up.railway.app/health/live
# Expected: {"status": "up"}

curl https://polycool-api-production.up.railway.app/health/ready
# Expected: {"status": "ready", "components": {...}}

# 2. Check Logs
railway logs --service polycool-api --lines 20
railway logs --service polycool-bot --lines 20
railway logs --service polycool-workers --lines 20
railway logs --service polycool-indexer --lines 20

# 3. Verify Database Connection
railway variables --service polycool-api | grep DATABASE_URL

# 4. Test Telegram Bot
# Send /start to bot → should respond

# 5. Check Redis Connectivity
# polycool-workers logs should show "✅ Redis PubSub connected"
```

---

## 🔧 TROUBLESHOOTING

### Issue: `OSError [Errno 101] Network is unreachable`

**Cause:** Using direct Supabase URL instead of Pooler

**Solution:**
```bash
# ❌ Wrong:
DATABASE_URL=postgresql://postgres:pwd@db.xxzdlbwfyetaxcmodiec.supabase.co:5432/postgres

# ✅ Correct:
DATABASE_URL=postgresql://postgres.xxzdlbwfyetaxcmodiec:pwd@aws-1-eu-north-1.pooler.supabase.com:5432/postgres
```

### Issue: `Database not initialized` in workers

**Cause:** Worker startup race condition or DB not yet accessible

**Solution:**
- Workers retry automatically
- Check Supabase is healthy: `mcp_supabase_list_tables(...)`
- Workers will connect once DB is reachable

### Issue: Redis connection failed

**Cause:** REDIS_URL is empty or incorrect

**Solution:**
```bash
railway variables --service polycool-workers --set "REDIS_URL=redis://redis-suej.railway.internal:6379"
```

---

## 🚀 DEPLOYMENT SCRIPTS

### Deploy Single Service
```bash
cd /Users/ulyssepiediscalzi/Documents/polynuclear/polycool/polycool-rebuild
./scripts/deployment/push_service.sh api
./scripts/deployment/push_service.sh bot
./scripts/deployment/push_service.sh workers

# For indexer (different directory)
cd /Users/ulyssepiediscalzi/Documents/polynuclear/polycool/apps/subsquid-silo-tests/indexer-ts
railway up --service polycool-indexer
```

### Redeploy All (Fresh Build)
```bash
cd /Users/ulyssepiediscalzi/Documents/polynuclear/polycool/polycool-rebuild

# Rebuild all Python services
railway up --service polycool-api
./scripts/deployment/push_service.sh bot
./scripts/deployment/push_service.sh workers

# Rebuild indexer
cd /Users/ulyssepiediscalzi/Documents/polynuclear/polycool/apps/subsquid-silo-tests/indexer-ts
railway up --service polycool-indexer
```

---

## 📊 MONITORING

### Real-time Logs
```bash
# Stream logs (new only)
railway logs --service polycool-api --follow
railway logs --service polycool-bot --follow
railway logs --service polycool-workers --follow
railway logs --service polycool-indexer --follow
```

### Health Endpoints
```bash
# API liveness (is it running?)
curl https://polycool-api-production.up.railway.app/health/live

# API readiness (is it ready to serve?)
curl https://polycool-api-production.up.railway.app/health/ready

# Expected response:
# {"status": "ready", "timestamp": 1..., "components": {"database": {...}, "redis": {...}}}
```

### Database Status
```bash
# List tables
mcp_supabase_list_tables(project_id="xxzdlbwfyetaxcmodiec")

# Check logs for errors
mcp_supabase_get_logs(project_id="xxzdlbwfyetaxcmodiec", service="postgres")
```

---

## 🎯 WHAT'S NEXT

### Immediate (This Session)
1. ✅ Supabase Pooler configured → All services connected
2. ✅ Redis unified → All caching working
3. ✅ API + Bot + Workers → Running
4. 🔄 Indexer → Finishing build

### Short Term (Next Session)
1. Validate all services health checks
2. Test Telegram bot with `/start`
3. Monitor workers for DB init stability
4. Set up Railway alerts/monitoring

### Future
1. Scale services as needed
2. Add branch deployments for staging
3. Implement CI/CD pipeline
4. Performance optimization

---

## 📚 REFERENCE

### Key Files
- **API Entry:** `api_only.py`
- **Bot Entry:** `bot_only.py`
- **Workers Entry:** `workers.py`
- **Indexer Entry:** `apps/subsquid-silo-tests/indexer-ts/src/main.ts`
- **Deploy Script:** `scripts/deployment/push_service.sh`

### Railway Project
- **Project:** cheerful-fulfillment
- **Environment:** production
- **Region:** eu-north-1 (Supabase), eu-west-4 (Railroad services)

### Supabase
- **Project:** xxzdlbwfyetaxcmodiec
- **Database:** PostgreSQL 17.6
- **Pooler:** aws-1-eu-north-1.pooler.supabase.com

### Redis
- **Service:** Redis-suej
- **Domain:** redis-suej.railway.internal
- **Port:** 6379

---

**Created:** Nov 9, 2025
**Status:** In Progress (Indexer deploying)
**Next:** Validate all services health
