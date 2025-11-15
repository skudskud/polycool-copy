# CLI Scripts for Subsquid Silo Tests

Collection of Python scripts for reading, validating, and testing the subsquid_* data tables.

## Usage

All scripts require `EXPERIMENTAL_SUBSQUID=true` feature flag.

### 1. `read_poll.py` - Read Polling Data

Displays markets from Gamma API polling, freshness metrics, and recent updates.

```bash
python scripts/read_poll.py
```

**Output:**
- Total records in `subsquid_markets_poll`
- Freshness metrics (overall + p95 percentile)
- Recent 5 markets with metadata

**Expected Freshness:**
- p95: ~60-90 seconds (polling every 60s)

---

### 2. `read_ws.py` - Read WebSocket Data

Displays markets from CLOB WebSocket streaming with real-time pricing.

```bash
python scripts/read_ws.py
```

**Output:**
- Total records in `subsquid_markets_ws`
- Freshness metrics (overall + p95 percentile)
- Last 10 markets with bid/ask/mid/trade prices
- Spread analysis (in basis points)

**Expected Freshness:**
- p95: <1-5 seconds (real-time streaming)

---

### 3. `read_wh.py` - Read Webhook Events

Displays webhook events from Redis bridge ingestion.

```bash
python scripts/read_wh.py
```

**Output:**
- Last 20 webhook events from `subsquid_markets_wh`
- Event types (market.status.update, clob.trade.executed, etc.)
- Event payload details (JSON pretty-printed)
- Event type summary (counts)

---

### 4. `seed_redis.py` - Seed Test Data

Populates Redis Pub/Sub channels with mock data for local testing.

```bash
python scripts/seed_redis.py
```

**Actions:**
- Publishes 3 test markets to `market.status.*` channels
- Publishes trades to `clob.trade.*` channels
- Publishes orderbooks to `clob.orderbook.*` channels
- Displays Redis info (keys, memory, clients)

**Next Steps (after running):**
```bash
# Terminal 1
python -m src.wh.webhook_worker

# Terminal 2
python -m src.redis.bridge

# Terminal 3
python scripts/read_wh.py
```

---

### 5. `compare_freshness.py` - Compare Polling vs Streaming

Compares freshness metrics between polling (Gamma API) and streaming (CLOB WS).

```bash
python scripts/compare_freshness.py
```

**Output:**
- Comparison table (Polling vs Streaming)
- Performance analysis with recommendations
- Health status for each source
- Freshness delta calculation

**Example Output:**
```
Metric                         Polling (Gamma)        Streaming (WS)
Total Records                  847                    1,234
Freshness (s)                  45.23                  2.15
Freshness p95 (s)              67.89                  3.45

Fresher Source:                Streaming (WS)
Freshness Delta (p95):         64.44s

📈 Polling (Gamma API):
  • Records:       847
  • Freshness p95: 67.89s
  • Expected:      60-90s
  ✅ Polling: Healthy

🌊 Streaming (CLOB WS):
  • Records:       1,234
  • Freshness p95: 3.45s
  • Expected:      <5s
  ✅ Streaming: Healthy
```

---

## Testing Workflow

### 1. Start all services
```bash
# Terminal 1
python -m src.polling.poller

# Terminal 2
python -m src.ws.streamer

# Terminal 3
python -m src.wh.webhook_worker

# Terminal 4
python -m src.redis.bridge

# Terminal 5
python -m src.main
```

### 2. Check data (in another terminal)
```bash
# Poll data
python scripts/read_poll.py

# WebSocket data
python scripts/read_ws.py

# Webhook events
python scripts/read_wh.py

# Freshness comparison
python scripts/compare_freshness.py
```

### 3. Seed test data
```bash
python scripts/seed_redis.py
```

---

## Development

### Adding New Scripts

1. Create `scripts/my_script.py`
2. Import and use `get_db_client()`:
   ```python
   from src.db.client import get_db_client, close_db_client
   db = await get_db_client()
   ```
3. Always validate feature flag:
   ```python
   from src.config import validate_experimental_subsquid
   validate_experimental_subsquid()
   ```
4. Add to this README

---

## Troubleshooting

### Script fails: "EXPERIMENTAL_SUBSQUID not enabled"
**Solution:** Set `EXPERIMENTAL_SUBSQUID=true` in `.env`

### Script fails: "No database available"
**Solution:** Check `DATABASE_URL` in `.env` and ensure PostgreSQL is running

### Script fails: "No Redis connection"
**Solution:** Check `REDIS_URL` in `.env` and ensure Redis is running

### `read_poll.py` shows "⚠️ No data"
**Solution:** Start the poller: `python -m src.polling.poller`

### `read_ws.py` shows "⚠️ No data"
**Solution:** Start the streamer: `python -m src.ws.streamer`

### `read_wh.py` shows "⚠️ No webhook events"
**Solution:** 
1. Start webhook worker: `python -m src.wh.webhook_worker`
2. Start Redis bridge: `python -m src.redis.bridge`
3. Seed test data: `python scripts/seed_redis.py`

---

## Performance Targets

| Source | Metric | Target | Status |
|--------|--------|--------|--------|
| Polling | p95 Freshness | <90s | ✅ |
| Streaming | p95 Freshness | <5s | ✅ |
| Webhook | p95 Latency | <100ms | ✅ |
| Overall | End-to-end | <2s | ✅ |

---

## References

- `src/db/client.py` - Database client methods
- `src/config.py` - Configuration and feature flags
- `README.md` - Main project documentation
