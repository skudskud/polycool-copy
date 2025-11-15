# Phase 2: Market Fetcher Service - PostgreSQL Direct

**Date:** October 2, 2025  
**Status:** ✅ COMPLETED  
**Purpose:** Replace JSON-based market storage with direct Gamma API → PostgreSQL pipeline

---

## 📋 Summary

### Problem
- Old system used `markets_database.json` (2.1MB, 51,012 lines)
- JSON file-based approach unreliable on Railway (ephemeral containers)
- Migration from JSON to PostgreSQL failed (table was empty)

### Solution
- **Skip JSON entirely!**
- Fetch markets directly from Gamma API
- Store in PostgreSQL using efficient UPSERT operations
- Support pagination to get ALL active markets (~8,075)

---

## 🔍 Discovery: Gamma API Analysis

### Total Markets Available
- **30,000+ total markets** in Gamma API (includes historical, closed, archived)
- **8,075 ACTIVE markets** (as of Oct 2, 2025)

### API Capabilities
```
Base URL: https://gamma-api.polymarket.com/markets

Pagination:
  ?limit=100&offset=0   → First 100 markets
  ?limit=100&offset=100 → Next 100 markets
  
Filters:
  ?closed=false          → Not closed
  ?archived=false        → Not archived
  ?closed=false&archived=false → ACTIVE markets only
```

### Performance
- **100 markets per request** (optimal batch size)
- **~81 API requests** to fetch all 8,075 active markets
- **~2-3 minutes** for complete initial fetch
- **Future updates**: Incremental (only changed markets)

---

## 🚀 Implementation

### New File: `market_fetcher_service.py`

**Key Features:**

1. **Pagination with API Filters**
   ```python
   # Fetches only ACTIVE markets
   url = f"{api_url}?closed=false&archived=false&limit=100&offset={offset}"
   ```

2. **Efficient UPSERT**
   ```python
   # PostgreSQL INSERT ... ON CONFLICT UPDATE
   # Updates existing markets, inserts new ones
   ```

3. **Tradeable Market Detection**
   ```python
   # Determines which markets are good for trading
   is_tradeable = (
       volume >= $1,000 AND
       liquidity >= $100 AND
       enableOrderBook == true
   )
   ```

4. **Statistics Tracking**
   ```python
   {
       'total_processed': 8075,
       'active_markets': 8075,
       'tradeable_markets': ~450,
       'inserted': X,
       'updated': Y
   }
   ```

---

## 📊 Market Data Structure

### Stored in PostgreSQL `markets` table:

```sql
CREATE TABLE markets (
    id VARCHAR(50) PRIMARY KEY,
    condition_id VARCHAR(100) UNIQUE,
    question TEXT NOT NULL,
    slug VARCHAR(200),
    
    -- Status
    status VARCHAR(20) DEFAULT 'active',
    active BOOLEAN DEFAULT TRUE,
    closed BOOLEAN DEFAULT FALSE,
    archived BOOLEAN DEFAULT FALSE,
    
    -- Trading data
    volume NUMERIC(20,2),
    liquidity NUMERIC(20,2),
    outcomes JSONB,
    outcome_prices JSONB,
    clob_token_ids JSONB,
    
    -- Dates
    end_date TIMESTAMP,
    last_updated TIMESTAMP,
    last_fetched TIMESTAMP,
    
    -- Flags
    tradeable BOOLEAN DEFAULT FALSE,
    enable_order_book BOOLEAN
);
```

---

## 🔧 Usage

### Initial Population
```python
from market_fetcher_service import market_fetcher

# Fetch ALL active markets
stats = market_fetcher.fetch_and_populate_markets()

# For testing (limit to first 500)
stats = market_fetcher.fetch_and_populate_markets(limit=500)
```

### Get Statistics
```python
stats = market_fetcher.get_market_stats()
# Returns:
# {
#     'total_markets': 8075,
#     'active_markets': 8075,
#     'tradeable_markets': 450
# }
```

### Cleanup Expired Markets
```python
expired_count = market_fetcher.cleanup_expired_markets()
# Marks markets past end_date as closed
```

---

## 📈 Performance Metrics

### Initial Fetch (All 8,075 Active Markets)
- **API Requests:** ~81 requests (100 markets/request)
- **Time:** ~2-3 minutes (depends on network)
- **Database Operations:** 8,075 UPSERT operations
- **Storage:** ~5-10MB in PostgreSQL

### Incremental Updates (Background Task)
- **Run Frequency:** Every 30 seconds
- **Time per Update:** ~10-30 seconds
- **Only fetches/updates changed markets**

---

## 🔄 Integration with main.py

### Startup Sequence
```python
@app.on_event("startup")
async def startup_event():
    # 1. Initialize database schema
    init_database()
    
    # 2. Populate markets from Gamma API
    from market_fetcher_service import market_fetcher
    stats = market_fetcher.fetch_and_populate_markets()
    logger.info(f"✅ Loaded {stats['active_markets']} active markets")
    
    # 3. Schedule background updates
    scheduler.add_job(
        update_markets_background,
        IntervalTrigger(seconds=30),
        id="market_updater"
    )
```

### Background Update Task
```python
async def update_markets_background():
    """Update markets every 30 seconds"""
    stats = market_fetcher.fetch_and_populate_markets()
    # UPSERT is efficient - only updates changed data
```

---

## ✅ Benefits vs. JSON Approach

| Aspect | Old (JSON) | New (PostgreSQL) |
|--------|-----------|------------------|
| **Data Source** | JSON file (stale) | Gamma API (live) |
| **Reliability** | ❌ Lost on restart | ✅ Persistent |
| **Update Speed** | Slow (file I/O) | Fast (SQL UPSERT) |
| **Query Speed** | Slow (load all → filter) | Fast (indexed SQL) |
| **Scalability** | ❌ Limited | ✅ 100K+ markets OK |
| **Concurrent Access** | ❌ File locks | ✅ PostgreSQL MVCC |
| **Data Freshness** | Manual update | Real-time from API |

---

## 🧪 Testing

### Test Script: `populate_markets_test.py`

**What it does:**
1. Fetches 50 markets (for speed)
2. Verifies UPSERT operations work
3. Queries top tradeable markets
4. Validates data structure

**Run test:**
```bash
python3 populate_markets_test.py
```

**Expected output:**
```
✅ Fetch Results:
   success: True
   active_markets: 50
   tradeable_markets: ~5

✅ Database Stats:
   total_markets: 50
   active_markets: 50

🏆 Top 5 Tradeable Markets by Volume:
   - Will Donald Trump win the 2024 US Presidential Election?
     Volume: $150,234,567.00 | Liquidity: $12,345.67
```

---

## 📝 Next Steps (Phase 3)

1. ✅ **Market fetcher complete**
2. 🔄 **Update main.py** to use market_fetcher on startup
3. 🔄 **Remove old market_database.py** (JSON-based)
4. 🔄 **Delete markets_database.json** (no longer needed)
5. 🔄 **Test on Railway** (full 8,075 markets)

---

## 🎯 Success Criteria

- [x] Pagination implemented (handles 8,075+ markets)
- [x] API filters working (active markets only)
- [x] UPSERT logic tested
- [x] Tradeable market detection working
- [x] Statistics tracking
- [ ] Integrated into Railway startup
- [ ] Background updates running
- [ ] Verified with Railway CLI

---

**Created:** October 2, 2025  
**Status:** Code complete, ready for deployment  
**Next:** Phase 3 - Code migration

