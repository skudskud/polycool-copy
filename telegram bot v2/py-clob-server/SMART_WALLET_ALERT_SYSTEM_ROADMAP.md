# Smart Wallet Alert System - Fix & Optimization Roadmap

**Date:** October 27, 2025  
**Status:** 🚨 CRITICAL - Smart Wallet Sync Blocked  
**Impact:** 25 trades stuck, 0 new alerts for 15+ minutes

---

## 📊 **Current State Analysis**

### System Health Dashboard
| Component | Status | Issue |
|-----------|--------|-------|
| **Smart Wallet Sync** | 🔴 BROKEN | NULL price blocking all inserts |
| **Alert Bot** | 🟢 HEALTHY | Working, waiting for data |
| **Twitter Bot** | 🟡 DEGRADED | Rate limit fixes deployed, monitoring |
| **Subsquid Webhook** | 🟡 DEGRADED | Sending incomplete data (NULL price) |
| **Database** | 🟢 HEALTHY | Last insert 15 min ago |

### Performance Metrics (24 Hours)
| Metric | Yesterday | Today | Change |
|--------|-----------|-------|--------|
| Telegram Alerts | 59 | 16 | **-73%** ⬇️ |
| Trades Processed | ~800 | 562 | **-30%** ⬇️ |
| Alert Rate | 1 per 24 min | 1 per 90 min | **-73%** ⬇️ |
| Twitter Success | 15 posted | 13 posted | Similar |
| Twitter Failures | ~50 failed | 91 failed | **+82%** ⬆️ |

### Root Causes Identified
1. **NULL price data** from Subsquid (technical)
2. **Low trade velocity** today (market conditions)
3. **Strict filtering** (only 2.9% of trades qualify)
4. **No error handling** for malformed data
5. **Twitter rate limits** (Free tier + burst issues)

---

## 🎯 **PHASE 0: Emergency Fixes** (Deploy ASAP - <30 minutes)

### **Fix 0.1: Smart Wallet Sync NULL Price Handling** 🚨 CRITICAL

**Problem:**
- Subsquid sending trades with `price = NULL`
- Smart wallet sync crashes on INSERT (NOT NULL constraint)
- **25 trades stuck** in retry loop right now
- **0 trades** synced in last 15 minutes

**Root Cause:**
```python
# Current behavior in smart_wallet_sync_service.py
trades = fetch_from_subsquid()  # Some have price=NULL
db.bulk_insert(trades)  # ❌ CRASHES - stops all inserts
```

**Solution: Defensive Data Validation**

**Implementation Steps:**

1. **Add NULL validation before INSERT**
   ```python
   # In smart_wallet_sync_service.py
   
   def _validate_trade_data(self, trade: Dict) -> Tuple[bool, str]:
       """Validate trade has all required fields"""
       required_fields = {
           'id': str,
           'wallet_address': str,
           'market_id': str,
           'side': str,
           'outcome': str,
           'price': (int, float, Decimal),  # NOT NULL
           'size': (int, float, Decimal),
           'value': (int, float, Decimal),
           'timestamp': datetime
       }
       
       for field, expected_type in required_fields.items():
           if field not in trade or trade[field] is None:
               return False, f"Missing or NULL: {field}"
           if not isinstance(trade[field], expected_type):
               return False, f"Invalid type for {field}"
       
       return True, "OK"
   ```

2. **Separate valid from invalid trades**
   ```python
   def _process_trades_batch(self, trades: List[Dict]):
       valid_trades = []
       invalid_trades = []
       
       for trade in trades:
           is_valid, reason = self._validate_trade_data(trade)
           if is_valid:
               valid_trades.append(trade)
           else:
               invalid_trades.append((trade, reason))
               logger.warning(f"⚠️ Invalid trade {trade.get('id', 'UNKNOWN')[:16]}: {reason}")
       
       # Insert valid trades (don't let bad data block good data)
       if valid_trades:
           success_count = self._bulk_insert(valid_trades)
           logger.info(f"✅ Synced {success_count}/{len(valid_trades)} valid trades")
       
       # Log invalid trades to separate table for investigation
       if invalid_trades:
           self._log_invalid_trades(invalid_trades)
           logger.error(f"❌ Skipped {len(invalid_trades)} invalid trades - logged for review")
   ```

3. **Create dead letter queue table** (New migration)
   ```sql
   CREATE TABLE IF NOT EXISTS smart_wallet_trades_invalid (
       id SERIAL PRIMARY KEY,
       trade_data JSONB NOT NULL,
       error_reason TEXT NOT NULL,
       received_at TIMESTAMP DEFAULT NOW(),
       reviewed BOOLEAN DEFAULT FALSE
   );
   
   CREATE INDEX idx_invalid_trades_reviewed ON smart_wallet_trades_invalid(reviewed);
   ```

4. **Add monitoring/alerting**
   ```python
   # Alert if >10% of trades are invalid
   invalid_rate = len(invalid_trades) / len(trades)
   if invalid_rate > 0.10:
       logger.critical(f"🚨 HIGH INVALID RATE: {invalid_rate:.1%} - Check Subsquid data quality!")
       # TODO: Send Telegram alert to admin
   ```

**Success Criteria:**
- ✅ Valid trades inserted (don't block on bad data)
- ✅ Invalid trades logged (for investigation)
- ✅ 0 sync crashes
- ✅ Monitoring shows <5% invalid rate normally

**Files to Modify:**
- `core/services/smart_wallet_sync_service.py`
- `supabase/migrations/2025-10-27_invalid_trades_dlt.sql` (new)

**Testing:**
1. Deploy fix
2. Wait 1 minute for next sync cycle
3. Check logs: Should see "Synced X/25 valid trades"
4. Check `smart_wallet_trades_invalid` table for bad trades
5. Verify alerts resume within 5 minutes

**Rollback Plan:**
- Previous version had no validation
- If issues, revert commit
- No data loss risk (only adding validation)

---

### **Fix 0.2: Alert Bot Service Linking** ⚠️ IMMEDIATE

**Problem:**
- Alert bot service exists in Railway but not properly linked
- Cannot get logs or monitor easily
- Service name has space: "alert bot"

**Solution:**
1. Check exact service name: `railway service list`
2. Link with proper quoting: `railway service "alert bot"`
3. Verify: `railway logs --lines 50`
4. Update documentation with correct service name

**Success Criteria:**
- ✅ Can view alert bot logs via Railway CLI
- ✅ Can monitor health without database queries

**Effort:** 5 minutes

---

## 🔧 **PHASE 1: Short-Term Improvements** (Deploy Today - <2 hours)

### **Improvement 1.1: Enhanced Error Handling & Recovery**

**Problem:**
- Single point of failure in data pipeline
- No automatic recovery from transient errors
- Limited visibility into failures

**Solution: Circuit Breaker + Retry Logic**

**Implementation:**

1. **Add retry logic with exponential backoff**
   ```python
   # In smart_wallet_sync_service.py
   
   def _bulk_insert_with_retry(self, trades: List[Dict], max_retries=3):
       for attempt in range(max_retries):
           try:
               return self.trade_repo.bulk_upsert(trades)
           except Exception as e:
               if attempt < max_retries - 1:
                   backoff = 2 ** attempt  # 1s, 2s, 4s
                   logger.warning(f"⚠️ Insert failed (attempt {attempt+1}/{max_retries}), retry in {backoff}s: {e}")
                   time.sleep(backoff)
               else:
                   logger.error(f"❌ Insert failed after {max_retries} attempts: {e}")
                   raise
   ```

2. **Implement circuit breaker for Subsquid**
   ```python
   class SubsquidCircuitBreaker:
       def __init__(self, failure_threshold=5, timeout=300):
           self.failure_count = 0
           self.failure_threshold = failure_threshold
           self.timeout = timeout  # 5 minutes
           self.last_failure_time = None
           self.state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN
       
       def call(self, func, *args, **kwargs):
           if self.state == "OPEN":
               if datetime.now() - self.last_failure_time > timedelta(seconds=self.timeout):
                   self.state = "HALF_OPEN"
                   logger.info("🔄 Circuit breaker: OPEN → HALF_OPEN (retry)")
               else:
                   raise CircuitBreakerOpen("Subsquid API unavailable")
           
           try:
               result = func(*args, **kwargs)
               if self.state == "HALF_OPEN":
                   self.reset()
               return result
           except Exception as e:
               self.record_failure()
               raise
   ```

3. **Add health checks**
   ```python
   async def health_check(self):
       """Comprehensive health check for monitoring"""
       checks = {
           "database": await self._check_database(),
           "subsquid": await self._check_subsquid(),
           "telegram_bot": await self._check_telegram_bot(),
           "twitter_bot": await self._check_twitter_bot(),
           "last_sync": await self._check_last_sync_time()
       }
       
       all_healthy = all(check["status"] == "healthy" for check in checks.values())
       
       return {
           "status": "healthy" if all_healthy else "degraded",
           "checks": checks,
           "timestamp": datetime.now(timezone.utc)
       }
   ```

**Success Criteria:**
- ✅ Automatic recovery from transient failures
- ✅ Circuit breaker prevents cascading failures
- ✅ Health endpoint for monitoring

**Files to Modify:**
- `core/services/smart_wallet_sync_service.py`
- `main.py` (add health endpoint)

**Effort:** 1 hour

---

### **Improvement 1.2: Data Quality Monitoring Dashboard**

**Problem:**
- No visibility into Subsquid data quality
- Can't tell if NULL prices are temporary or ongoing
- No historical tracking of issues

**Solution: Create monitoring view + alerts**

**Implementation:**

1. **Create data quality view**
   ```sql
   -- New migration: 2025-10-27_data_quality_monitoring.sql
   
   CREATE TABLE smart_wallet_sync_metrics (
       id SERIAL PRIMARY KEY,
       sync_timestamp TIMESTAMP NOT NULL,
       trades_received INTEGER NOT NULL,
       trades_valid INTEGER NOT NULL,
       trades_invalid INTEGER NOT NULL,
       invalid_reasons JSONB,
       sync_duration_ms INTEGER,
       error_message TEXT,
       created_at TIMESTAMP DEFAULT NOW()
   );
   
   CREATE INDEX idx_sync_metrics_timestamp ON smart_wallet_sync_metrics(sync_timestamp DESC);
   
   -- View for last 24h data quality
   CREATE OR REPLACE VIEW v_data_quality_24h AS
   SELECT 
       DATE_TRUNC('hour', sync_timestamp) as hour,
       SUM(trades_received) as total_received,
       SUM(trades_valid) as total_valid,
       SUM(trades_invalid) as total_invalid,
       ROUND(AVG(trades_invalid::DECIMAL / NULLIF(trades_received, 0) * 100), 2) as invalid_rate_pct,
       JSONB_AGG(DISTINCT invalid_reasons) as error_types
   FROM smart_wallet_sync_metrics
   WHERE sync_timestamp > NOW() - INTERVAL '24 hours'
   GROUP BY DATE_TRUNC('hour', sync_timestamp)
   ORDER BY hour DESC;
   ```

2. **Log metrics after each sync**
   ```python
   def _log_sync_metrics(self, received, valid, invalid, invalid_reasons, duration_ms, error=None):
       self.db.execute("""
           INSERT INTO smart_wallet_sync_metrics 
           (sync_timestamp, trades_received, trades_valid, trades_invalid, invalid_reasons, sync_duration_ms, error_message)
           VALUES (%s, %s, %s, %s, %s, %s, %s)
       """, (datetime.now(), received, valid, invalid, json.dumps(invalid_reasons), duration_ms, error))
   ```

3. **Add Telegram alert for admin on high error rate**
   ```python
   async def _check_and_alert_data_quality(self, invalid_rate):
       if invalid_rate > 0.20:  # >20% invalid
           await self.notification_service.send_admin_alert(
               f"🚨 DATA QUALITY ALERT\n\n"
               f"Invalid trade rate: {invalid_rate:.1%}\n"
               f"Check Subsquid API for issues!"
           )
   ```

**Success Criteria:**
- ✅ Real-time data quality metrics
- ✅ Historical tracking (identify patterns)
- ✅ Automatic alerts on degradation

**Effort:** 45 minutes

---

### **Improvement 1.3: Smart Wallet Stats Update Fix**

**Problem:**
- Smart wallet stats last updated **5 days ago** (Oct 22)
- Win rates and PnL are stale
- Affects filtering quality

**Solution: Fix wallet updater service**

**Investigation Needed:**
1. Check `smart_wallet_monitor_service.py` - is it running?
2. Check logs for wallet update errors
3. Verify Polymarket API calls working
4. Check if rate limits are blocking updates

**Implementation:**
1. Add logging to wallet update process
2. Add retry logic for failed updates
3. Consider batch updates (10 wallets at a time)
4. Add "last_updated" tracking per wallet

**Success Criteria:**
- ✅ All wallets updated daily
- ✅ No wallet older than 24 hours
- ✅ Win rates reflect recent performance

**Effort:** 1 hour (needs investigation first)

---

## 📈 **PHASE 2: Alert Optimization** (Deploy This Week - <4 hours)

### **Optimization 2.1: Adaptive Alert Criteria**

**Problem:**
- Only 2.9% of trades qualify for alerts (too strict)
- Missing 97% of trading activity
- Yesterday: 59 alerts, Today: 16 alerts (-73%)

**Current Criteria:**
```
is_first_time = TRUE
AND value >= 200
AND side = 'BUY'
AND bucket_smart = 'Very Smart'
```

**Analysis:**
- **73% drop** in alerts not sustainable
- Market may have shifted to add-on trading
- Very Smart bucket may be too restrictive

**Proposed Solution: Tiered Alert System**

**Tier 1: Premium Alerts** (Current)
- First-time positions
- $500+ value
- Very Smart bucket (>55% win rate)
- → Send to main channel

**Tier 2: Quality Alerts** (New)
- First-time OR significant add-on ($1000+)
- $200+ value
- Smart or Very Smart bucket (>50% win rate)
- → Send to main channel

**Tier 3: Activity Alerts** (Optional, future)
- Any high-value trade ($2000+)
- Any bucket
- → Send to separate "activity" channel

**Implementation:**

1. **Update alert_bot_pending_trades view**
   ```sql
   CREATE OR REPLACE VIEW alert_bot_pending_trades AS
   WITH ranked_trades AS (
       SELECT 
           swt.*,
           sw.bucket_smart,
           sw.win_rate,
           sw.smartscore,
           -- Tiered scoring
           CASE 
               -- Tier 1: Premium (score 100)
               WHEN swt.is_first_time = true 
                   AND swt.value >= 500 
                   AND sw.bucket_smart = 'Very Smart'
               THEN 100
               
               -- Tier 2: Quality (score 75)
               WHEN (swt.is_first_time = true AND swt.value >= 200)
                   OR (swt.is_first_time = false AND swt.value >= 1000)
               AND sw.bucket_smart IN ('Very Smart', 'Smart')
               THEN 75
               
               -- Tier 3: Activity (score 50)
               WHEN swt.value >= 2000
               THEN 50
               
               ELSE 0
           END as alert_priority
       FROM smart_wallet_trades swt
       INNER JOIN smart_wallets sw ON swt.wallet_address = sw.address
       WHERE swt.side = 'BUY'
           AND swt.market_question IS NOT NULL
           AND NOT EXISTS (
               SELECT 1 FROM alert_bot_sent abs 
               WHERE abs.trade_id = swt.id
           )
   )
   SELECT *
   FROM ranked_trades
   WHERE alert_priority >= 75  -- Only Tier 1 & 2 for now
   ORDER BY alert_priority DESC, value DESC;
   ```

2. **Update alert message format to show tier**
   ```python
   def format_alert(trade, tier="Premium"):
       emoji = "🔥" if tier == "Premium" else "💎"
       tag = "[PREMIUM]" if tier == "Premium" else "[QUALITY]"
       
       return f"{emoji} {tag} Smart Trade Alert\n..."
   ```

3. **A/B test for 1 week**
   - Monitor engagement metrics
   - Track user feedback
   - Adjust thresholds based on data

**Expected Impact:**
- **2-3x more alerts** (16 → 30-45 per day)
- Better coverage of trading activity
- Still maintains quality (no spam)

**Success Criteria:**
- ✅ Alert volume back to 40-60 per day
- ✅ <5% duplicate/low-quality complaints
- ✅ User engagement maintained or improved

**Effort:** 2 hours

---

### **Optimization 2.2: Add-On Trade Intelligence**

**Problem:**
- Current system ignores add-on trades (is_first_time=false)
- Missing "doubling down" signals (high conviction)
- 81% of trades are add-ons → huge missed opportunity

**Solution: "Smart Trader Doubling Down" Feature**

**Criteria for Add-On Alerts:**
```
is_first_time = FALSE
AND value >= $1,000  (significant add-on)
AND side = 'BUY'
AND bucket_smart IN ('Very Smart', 'Smart')
AND (
    -- Same market within 24h (doubling down)
    EXISTS (
        SELECT 1 FROM smart_wallet_trades prev
        WHERE prev.wallet_address = current.wallet_address
        AND prev.market_id = current.market_id
        AND prev.timestamp > current.timestamp - INTERVAL '24 hours'
        AND prev.is_first_time = true
    )
)
```

**Message Format:**
```
💪 DOUBLING DOWN

Smart trader adding $2,216 MORE to their Yes position

📊 Will the price of Ethereum be between $4,100 and $4,400?

🎯 Original position: $500 → Now: $2,716 total
⏱️ 2 hours after first entry

👤 Wallet: 57% WR | $12K PnL
🔗 [View Wallet] [Quick Copy]
```

**Expected Impact:**
- Capture high-conviction plays
- Better signal quality (trader increasing exposure)
- 10-15 additional alerts per day

**Success Criteria:**
- ✅ 10-15 add-on alerts per day
- ✅ High engagement (these are strong signals)
- ✅ No confusion with first-time trades

**Effort:** 2 hours

---

## 🏗️ **PHASE 3: Architecture Improvements** (Deploy Next Week - <8 hours)

### **Improvement 3.1: Unified Alert System**

**Problem:**
- 3 separate alert systems (Twitter, Telegram channel, User DMs)
- Different filtering logic for each
- No coordination
- Hard to maintain

**Current Architecture:**
```
smart_wallet_trades (database)
    ↓
    ├─→ Twitter Bot (separate logic)
    ├─→ Telegram Alert Bot (separate logic)
    └─→ Main Bot DMs (separate logic)
```

**Proposed Architecture:**
```
smart_wallet_trades (database)
    ↓
Central Alert Service (single source of truth)
    ├─→ evaluate_trade_for_alerts()
    ├─→ calculate_alert_priority()
    └─→ determine_channels()
         ↓
    ┌────┴────┬─────────────┐
    ↓         ↓             ↓
Twitter   Telegram      User DMs
```

**Implementation:**

1. **Create `CentralAlertService`**
   ```python
   class CentralAlertService:
       """
       Single source of truth for all alert routing
       Evaluates trades once, routes to appropriate channels
       """
       
       def evaluate_trade(self, trade) -> AlertDecision:
           """
           Evaluate a trade and decide which channels should receive it
           
           Returns AlertDecision with:
           - should_tweet: bool
           - should_channel_alert: bool
           - should_dm_users: List[user_id]
           - priority: int (0-100)
           - alert_type: str ('premium', 'quality', 'activity')
           - reasoning: str (for debugging)
           """
           pass
       
       async def dispatch_alerts(self, decision: AlertDecision, trade):
           """Send alerts to all appropriate channels"""
           tasks = []
           
           if decision.should_tweet:
               tasks.append(self.twitter_bot.tweet(trade, decision.priority))
           
           if decision.should_channel_alert:
               tasks.append(self.telegram_alert.send(trade, decision.alert_type))
           
           if decision.should_dm_users:
               for user_id in decision.should_dm_users:
                   tasks.append(self.send_user_dm(user_id, trade))
           
           results = await asyncio.gather(*tasks, return_exceptions=True)
           self._log_dispatch_results(trade, results)
   ```

2. **Unified filtering configuration**
   ```python
   # config/alert_rules.py
   
   ALERT_RULES = {
       'twitter': {
           'first_time': {'min_value': 200, 'bucket': ['Very Smart', 'Smart']},
           'add_on': {'min_value': 1000, 'bucket': ['Very Smart']}
       },
       'telegram_channel': {
           'first_time': {'min_value': 200, 'bucket': ['Very Smart']},
           'add_on': {'min_value': 1000, 'bucket': ['Very Smart'], 'requires_existing_position': True}
       },
       'user_dms': {
           'copy_trading': lambda user, trade: trade.wallet in user.followed_wallets,
           'threshold_alerts': lambda user, trade: trade.value >= user.alert_threshold
       }
   }
   ```

3. **Centralized logging & metrics**
   ```sql
   CREATE TABLE alert_dispatch_log (
       id SERIAL PRIMARY KEY,
       trade_id VARCHAR NOT NULL,
       evaluation_result JSONB NOT NULL,  -- Full decision tree
       channels_targeted TEXT[] NOT NULL,  -- ['twitter', 'telegram', 'dm:user123']
       channels_succeeded TEXT[] NOT NULL,
       channels_failed TEXT[] NOT NULL,
       processing_time_ms INTEGER,
       created_at TIMESTAMP DEFAULT NOW()
   );
   ```

**Benefits:**
- Single place to update filtering logic
- Consistent behavior across channels
- Easier testing & debugging
- Better metrics & monitoring

**Migration Strategy:**
1. Build `CentralAlertService` alongside existing systems
2. Run in parallel for 1 week (compare outputs)
3. Gradually migrate Twitter bot to use it
4. Migrate Telegram bot to use it
5. Deprecate old separate logic

**Success Criteria:**
- ✅ All alerts routed through central service
- ✅ Consistent filtering across channels
- ✅ 50% reduction in code duplication
- ✅ Improved monitoring & debugging

**Effort:** 6 hours

---

### **Improvement 3.2: Smart Batching & Rate Limit Optimization**

**Problem:**
- Twitter bot hitting rate limits (91 failures in 24h)
- Alert bot rate limit hardcoded (10/hour)
- No dynamic adjustment based on API tier

**Solution: Intelligent Rate Limiter**

**Implementation:**

1. **Token bucket algorithm**
   ```python
   class SmartRateLimiter:
       """
       Token bucket rate limiter with tier-aware limits
       Dynamically adjusts based on API responses
       """
       
       def __init__(self, tier='free'):
           self.tiers = {
               'free': {'capacity': 50, 'refill_rate': 2.08/hour},  # 50/day
               'basic': {'capacity': 500, 'refill_rate': 20.8/hour},  # 500/day
               'pro': {'capacity': 1000, 'refill_rate': 41.6/hour}  # 1000/day
           }
           
           self.tier = tier
           self.tokens = self.tiers[tier]['capacity']
           self.last_refill = time.time()
       
       def try_consume(self, tokens=1) -> bool:
           """Try to consume tokens, return success"""
           self._refill_tokens()
           
           if self.tokens >= tokens:
               self.tokens -= tokens
               return True
           return False
       
       def wait_time_for_tokens(self, tokens=1) -> float:
           """Calculate wait time in seconds for N tokens"""
           if self.tokens >= tokens:
               return 0
           
           needed = tokens - self.tokens
           refill_rate = self.tiers[self.tier]['refill_rate']
           return needed / refill_rate
   ```

2. **Adaptive batching**
   ```python
   class AdaptiveBatcher:
       """
       Batch alerts based on current rate limit availability
       Prioritizes high-value trades when limited
       """
       
       def select_batch(self, pending_trades, rate_limiter):
           """Select best batch of trades to send given current limits"""
           
           available_capacity = rate_limiter.tokens
           
           if available_capacity == 0:
               return []
           
           # Sort by priority score
           sorted_trades = sorted(pending_trades, key=lambda t: t.priority, reverse=True)
           
           # Take top N that fit capacity
           batch = sorted_trades[:int(available_capacity)]
           
           logger.info(f"📦 Batched {len(batch)}/{len(pending_trades)} trades (capacity: {available_capacity})")
           
           return batch
   ```

3. **Rate limit learning from headers**
   ```python
   def update_from_response_headers(self, response):
       """Learn actual limits from API response headers"""
       if 'x-rate-limit-remaining' in response.headers:
           self.tokens = int(response.headers['x-rate-limit-remaining'])
       
       if 'x-rate-limit-reset' in response.headers:
           reset_time = int(response.headers['x-rate-limit-reset'])
           self.next_reset = datetime.fromtimestamp(reset_time)
   ```

**Success Criteria:**
- ✅ Twitter failures drop to <5% (from 87%)
- ✅ Optimal use of API quota (no wasted capacity)
- ✅ High-priority alerts never delayed

**Effort:** 3 hours

---

## 🔬 **PHASE 4: Observability & Debugging** (Deploy Next Week - <4 hours)

### **Improvement 4.1: Real-Time Monitoring Dashboard**

**Problem:**
- Have to query database to see system health
- No real-time visibility
- Can't diagnose issues quickly

**Solution: Monitoring Endpoint + Dashboard**

**Implementation:**

1. **Add `/health` endpoint**
   ```python
   @app.get("/health")
   async def health_check():
       return {
           "status": "healthy",
           "timestamp": datetime.now(timezone.utc),
           "components": {
               "database": await check_db(),
               "subsquid": await check_subsquid(),
               "alert_bot": await check_alert_bot(),
               "twitter_bot": await check_twitter_bot()
           }
       }
   ```

2. **Add `/metrics` endpoint**
   ```python
   @app.get("/metrics")
   async def metrics():
       return {
           "smart_wallet_sync": {
               "last_sync": await get_last_sync_time(),
               "trades_synced_today": await count_trades_today(),
               "sync_errors_last_hour": await count_sync_errors(),
               "invalid_trade_rate": await get_invalid_rate()
           },
           "alerts": {
               "sent_today": await count_alerts_today(),
               "pending": await count_pending_alerts(),
               "rate_limit_remaining": await get_rate_limit_status()
           },
           "twitter": {
               "tweets_today": await count_tweets_today(),
               "success_rate": await get_tweet_success_rate(),
               "rate_limit_remaining": twitter_bot.rate_limit_remaining
           }
       }
   ```

3. **Simple HTML dashboard** (optional)
   ```html
   <!DOCTYPE html>
   <html>
   <head>
       <title>Smart Wallet Alert System</title>
       <script>
           // Auto-refresh every 10 seconds
           setInterval(() => {
               fetch('/metrics')
                   .then(r => r.json())
                   .then(data => updateDashboard(data));
           }, 10000);
       </script>
   </head>
   <body>
       <h1>🔥 Smart Wallet Alert System</h1>
       <div id="status"></div>
       <div id="metrics"></div>
   </body>
   </html>
   ```

**Success Criteria:**
- ✅ Real-time system status visible
- ✅ Can diagnose issues in <1 minute
- ✅ No need to query database manually

**Effort:** 2 hours

---

### **Improvement 4.2: Structured Logging & Traces**

**Problem:**
- Logs are text-based, hard to parse
- Can't trace a trade through the pipeline
- No correlation IDs

**Solution: Structured JSON logging + Trace IDs**

**Implementation:**

1. **Add trace IDs to every trade**
   ```python
   import uuid
   
   trade['trace_id'] = str(uuid.uuid4())
   
   logger.info("Processing trade", extra={
       "trace_id": trade['trace_id'],
       "trade_id": trade['id'],
       "value": trade['value'],
       "stage": "validation"
   })
   ```

2. **Structured logger**
   ```python
   import structlog
   
   structlog.configure(
       processors=[
           structlog.processors.TimeStamper(fmt="iso"),
           structlog.processors.StackInfoRenderer(),
           structlog.processors.format_exc_info,
           structlog.processors.JSONRenderer()
       ]
   )
   
   logger = structlog.get_logger()
   ```

3. **Pipeline tracing**
   ```python
   # Every stage logs with same trace_id
   logger.info("trade.received", trace_id=trace_id, source="subsquid")
   logger.info("trade.validated", trace_id=trace_id, valid=True)
   logger.info("trade.inserted", trace_id=trace_id, db_id=123)
   logger.info("trade.evaluated", trace_id=trace_id, should_alert=True)
   logger.info("trade.alerted", trace_id=trace_id, channels=['telegram', 'twitter'])
   ```

**Benefits:**
- Can grep logs by trace_id to see full journey
- Can aggregate/analyze logs programmatically
- Can build metrics dashboards from logs

**Success Criteria:**
- ✅ Can trace any trade end-to-end
- ✅ Logs parseable by log aggregators
- ✅ Faster debugging (5 min → 30 sec)

**Effort:** 2 hours

---

## 📊 **PHASE 5: Performance Optimization** (Deploy Later - <6 hours)

### **Optimization 5.1: Batch Processing & Parallelization**

**Problem:**
- Smart wallet sync processes trades sequentially
- Market updater blocking scheduler (15 min cycles)
- Inefficient API calls

**Solution:**
1. Batch database operations (bulk insert 100 trades at once)
2. Parallel API calls (async/await for wallet updates)
3. Move long-running jobs to background workers

**Expected Impact:**
- Sync time: 2-3 min → 30 seconds
- Market updater: 15 min → 3 min
- Better scheduler responsiveness

**Effort:** 4 hours

---

### **Optimization 5.2: Database Query Optimization**

**Problem:**
- `alert_bot_pending_trades` view can be slow
- No database indexes on key columns
- Inefficient JOIN queries

**Solution:**
1. Add indexes on frequently queried columns
2. Optimize view query (materialized view?)
3. Add query explain analysis to logs

**Expected Impact:**
- Alert bot query time: 500ms → 50ms
- Can handle 10x more trades

**Effort:** 2 hours

---

## 🧪 **PHASE 6: Testing & Validation** (Ongoing)

### **Test 6.1: Integration Test Suite**

**Coverage Needed:**
1. **NULL price handling**
   - Test: Send trade with NULL price
   - Expected: Skip, log to invalid table
   - Expected: Other trades in batch still insert

2. **Rate limit handling**
   - Test: Simulate 429 from Twitter
   - Expected: Backoff for 60 min
   - Expected: Resume after backoff

3. **Alert deduplication**
   - Test: Insert same trade twice
   - Expected: Only one alert sent

4. **Circuit breaker**
   - Test: Subsquid API down
   - Expected: Circuit opens, logs error
   - Expected: Retries after timeout

**Effort:** 3 hours

---

## 📅 **Implementation Timeline**

### **Week 1 (Oct 27 - Nov 2)**
- ✅ **Day 1 (Today):** Phase 0 - Emergency fixes (NULL handling, linking)
- ✅ **Day 1-2:** Phase 1 - Error handling, monitoring
- **Day 3-4:** Phase 2 - Alert optimization (tiered system, add-ons)
- **Day 5:** Testing & validation
- **Day 6-7:** Monitor, adjust, document

### **Week 2 (Nov 3 - Nov 9)**
- **Day 1-3:** Phase 3 - Architecture improvements (unified system)
- **Day 4-5:** Phase 4 - Observability (dashboard, logging)
- **Day 6-7:** Testing & validation

### **Week 3+ (Nov 10+)**
- **Ongoing:** Phase 5 - Performance optimization
- **Ongoing:** Phase 6 - Testing & validation
- **Ongoing:** Monitoring & iteration

---

## 🎯 **Success Metrics**

### **Immediate (Phase 0-1)**
| Metric | Current | Target | Status |
|--------|---------|--------|--------|
| Smart wallet sync errors | 100% | <1% | 🔴 |
| Trades stuck | 25 | 0 | 🔴 |
| Alert delivery time | N/A | <2 min | 🟡 |

### **Short-Term (Phase 2)**
| Metric | Current | Target | Status |
|--------|---------|--------|--------|
| Alerts per day | 16 | 40-60 | 🔴 |
| Alert quality score | N/A | >80% engagement | 🟡 |
| User complaints | 0 | <5/week | 🟢 |

### **Long-Term (Phase 3-5)**
| Metric | Current | Target | Status |
|--------|---------|--------|--------|
| System uptime | ~98% | >99.5% | 🟡 |
| Sync latency | ~2 min | <30 sec | 🟡 |
| Twitter success rate | 13% | >95% | 🔴 |

---

## 🚨 **Risk Assessment**

### **High Risk**
1. **NULL price issue persists after fix**
   - Mitigation: Thorough testing, gradual rollout
   - Rollback plan: Revert to previous version

2. **Tiered alerts reduce quality**
   - Mitigation: A/B testing, user feedback
   - Rollback plan: Revert to strict filters

### **Medium Risk**
1. **Unified alert system breaks existing workflows**
   - Mitigation: Run in parallel first, gradual migration
   - Rollback plan: Keep old systems running

2. **Rate limit changes don't work**
   - Mitigation: Conservative defaults, monitoring
   - Rollback plan: Revert to previous limits

### **Low Risk**
1. **Performance optimizations don't help**
   - Mitigation: Benchmark before/after
   - Rollback plan: Easy to revert

---

## 📝 **Next Steps**

1. **Review this roadmap** - Get feedback, adjust priorities
2. **Create branch:** `feature/smart-wallet-alert-fixes`
3. **Start with Phase 0.1** - Fix NULL price handling (CRITICAL)
4. **Deploy & monitor** - Watch for issues
5. **Iterate based on results**

---

## 📚 **References**

**Related Documents:**
- `TWITTER_RATE_LIMIT_FIX_COMPLETE.md` - Twitter bot fixes
- `polycool-alert-bot/README.md` - Alert bot documentation
- `core/services/smart_wallet_sync_service.py` - Sync service code

**Database Tables:**
- `smart_wallet_trades` - All trades
- `smart_wallets` - Wallet stats
- `alert_bot_sent` - Alert log
- `alert_bot_pending_trades` - View of qualifying trades
- `tweets_bot` - Twitter bot log

---

**Last Updated:** October 27, 2025  
**Status:** 🔴 CRITICAL - NULL price blocking 25 trades  
**Next Action:** Deploy Phase 0.1 (NULL handling fix)




