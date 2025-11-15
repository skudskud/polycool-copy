# DipDup On-Chain Indexer for PolyMarket

On-chain indexer for Conditional Tokens transfers on Polygon using DipDup.

**Mission:** Track fills (BUY/SELL) and user transactions, store with optional price enrichment.

---

## 🎯 What It Does

| Event | Table | Description |
|-------|-------|-------------|
| **Transfer** (from=0x0) | `subsquid_user_transactions` | User BUY (mint) |
| **Transfer** (normal) | `subsquid_user_transactions` | User SELL (transfer) |
| **Transfer** (to=0x0) | — | IGNORED (burn) |
| **TransferBatch** | — | Tracked but not yet indexed (TODO) |
| **PayoutRedeemed** | — | Tracked but not yet indexed (TODO) |

---

## 🚀 Quick Start (Local)

### 1. Prerequisites
```bash
# Install DipDup
pip install dipdup

# Ensure database is running
echo $DATABASE_URL  # Should be set
```

### 2. Copy Environment
```bash
cp .env.example .env
# Edit .env with your Supabase credentials and RPC URL
```

### 3. Run Locally
```bash
cd apps/subsquid-silo-tests/indexer
dipdup run

# Or with custom config:
dipdup run --config dipdup.yaml --database-url $DATABASE_URL
```

### 4. Monitor Logs
```bash
# Watch for indexed events
tail -f indexer.log

# Expect messages like:
# ✅ Indexed BUY: market=248905, user=0x1234..., outcome=1, amount=1000, block=56789
# ✅ Indexed SELL: market=248905, user=0x1234..., outcome=1, amount=500, block=56790
```

---

## 📊 Verify Data

```sql
-- Check recent transactions indexed
SELECT tx_id, market_id, amount, timestamp
FROM subsquid_user_transactions
WHERE timestamp > now() - interval '1 hour'
ORDER BY timestamp DESC
LIMIT 10;

-- Count by transaction type
SELECT
  COUNT(*) as total,
  COUNT(CASE WHEN amount IS NULL THEN 1 END) as needs_price_enrichment
FROM subsquid_user_transactions
WHERE timestamp > now() - interval '24 hours';

-- Check price enrichment status
SELECT
  COUNT(*) as total,
  COUNT(CASE WHEN price IS NOT NULL THEN 1 END) as enriched,
  COUNT(CASE WHEN price IS NULL THEN 1 END) as pending
FROM subsquid_user_transactions
WHERE timestamp > now() - interval '1 hour';
```

---

## 🔧 Architecture

### Token ID Encoding
```
token_id = market_id * 2 + outcome
market_id_numeric = token_id >> 1      # Shift right = divide by 2
outcome = token_id & 0x1               # 0=NO, 1=YES
```

### Market ID Format
- **Stored as:** Numeric string (e.g., "248905")
- **NOT hex** (e.g., NOT "0x0000000...ABC")
- Matches `subsquid_markets_poll.market_id` for joins

### Price Enrichment (Option C)
```
Phase 1: DipDup indexes with price=NULL
Phase 2: Every 60s, background job runs:
  UPDATE subsquid_user_transactions
  SET price = subsquid_markets_poll.last_mid
  WHERE price IS NULL
```

**Benefits:**
- ✅ DipDup fast (no extra DB calls)
- ✅ Prices always synced with Poller (same 60s cycle)
- ✅ Fallback: if NULL after 120s, alert ops

---

## 🐳 Docker Build & Test

```bash
# Build image
docker build -f Dockerfile.indexer -t dipdup-indexer .

# Run container (with local env)
docker run \
  --env DATABASE_HOST=$DB_HOST \
  --env DATABASE_PASSWORD=$DB_PASS \
  --env POLYGON_RPC_URL=$RPC_URL \
  -it dipdup-indexer

# Check logs
docker logs -f <container_id>
```

---

## 🚂 Railway Deployment

```bash
# Link service to Railway
railway service link

# Set environment variables
railway variable set POLYGON_RPC_URL=https://polygon-mainnet.g.alchemy.com/v2/YOUR_KEY

# Deploy
railway deploy

# Monitor
railway logs
```

---

## 📋 Configuration

### `dipdup.yaml`
- **RPC:** Alchemy (better rate limits)
- **Start block:** Latest (covers recent)
- **Batch size:** 100
- **Database:** Configured via env vars

### Environment Variables
```env
DATABASE_HOST          # Supabase host
DATABASE_PASSWORD      # Supabase password
POLYGON_RPC_URL        # Alchemy RPC
EXPERIMENTAL_SUBSQUID  # Set to 'true'
```

---

## 🧪 Testing

### Unit Tests (Python)
```bash
pytest tests/  -v
```

### Integration Test (Real Events)
```bash
# Run indexer for 5 min
timeout 300 dipdup run

# Verify data in DB
SELECT COUNT(*) FROM subsquid_user_transactions WHERE timestamp > now() - interval '10 minutes';
```

### Local Mock Event Test (TODO)
```bash
# Emit mock Transfer event to test handler
python tests/mock_events.py
```

---

## 🚨 Troubleshooting

| Error | Cause | Fix |
|-------|-------|-----|
| `no such table: subsquid_user_transactions` | Migration not run | Run migrations on DB |
| `Error connecting to RPC` | Bad RPC URL | Check `POLYGON_RPC_URL` env var |
| `prices staying NULL` | Enrichment job not running | Start background job (PHASE 3) |
| `too many requests` | Rate limit from RPC | Use Alchemy key instead of free RPC |

---

## 📝 Next Steps

- [ ] PHASE 6: Run locally for 1 hour, verify data ingestion
- [ ] PHASE 6: Deploy to Railway after validation
- [ ] TODO: Implement full ABI decoding for `TransferBatch`
- [ ] TODO: Track `PayoutRedeemed` events
- [ ] FUTURE: Add metrics/monitoring dashboard

---

## 📚 References

- [DipDup Docs](https://dipdup.io/)
- [Conditional Tokens on Polygon](https://docs.conditionaltoken.com/)
- [Polymarket Technical Docs](https://docs.polymarket.com/)
- [Polygon RPC Providers](https://wiki.polygon.technology/docs/develop/ethereum-polygon/getting-started)
