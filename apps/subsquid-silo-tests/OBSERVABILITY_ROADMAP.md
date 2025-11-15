# 🚀 Subsquid Services - Observability & Reliability Improvements

**Branch:** `feature/subsquid-observability-improvements`  
**Created:** October 23, 2025  
**Status:** 📋 PLANNING PHASE  
**Estimated Time:** 4-6 hours implementation + 2 hours testing

---

## 📊 Executive Summary

Following the technical audit of poller and streamer services, this roadmap outlines **6 critical improvements** to elevate the services from "good" (90-95%) to "excellent" (98%+) production readiness.

**Key Objectives:**
- ✅ Add health check endpoints for external monitoring
- ✅ Add database retry logic for transient failures
- ✅ Add deduplication to prevent duplicate processing
- ✅ Add timestamp validation to skip stale data
- ✅ Add Prometheus metrics for observability
- ✅ Maintain 100% async compatibility

**Impact:**
- **Reliability:** 3x improvement in DB failure recovery
- **Observability:** Real-time service health visibility
- **Efficiency:** 15-20% reduction in duplicate processing
- **Monitoring:** Grafana/Railway dashboards enabled

---

## 🎯 Implementation Phases

### **Phase 1: Foundation** (Priority: CRITICAL)
**Estimated Time:** 2-3 hours

#### 1.1 Health Check Infrastructure
- Create `src/utils/health_server.py` - Reusable FastAPI health server
- Add health endpoints to poller and streamer
- Implement graceful shutdown hooks

#### 1.2 Database Retry Logic
- Add `tenacity` dependency
- Wrap all DB upsert methods with retry decorator
- Add retry attempt logging

**Deliverables:**
- ✅ `/health` endpoint on both services
- ✅ Automatic 3x retry for DB failures
- ✅ Graceful service shutdown

---

### **Phase 2: Resilience** (Priority: HIGH)
**Estimated Time:** 1.5-2 hours

#### 2.1 Message Deduplication (Streamer)
- Add `deque` for recent message fingerprints
- Implement fingerprint generation (market_id + timestamp + price)
- Add duplicate detection logic

#### 2.2 Timestamp Validation (Streamer)
- Add staleness check (60s threshold)
- Skip processing of old messages
- Log stale message metrics

**Deliverables:**
- ✅ Zero duplicate message processing
- ✅ No stale data in database
- ✅ Memory-efficient deduplication (1000 messages)

---

### **Phase 3: Observability** (Priority: MEDIUM)
**Estimated Time:** 1.5-2 hours

#### 3.1 Prometheus Metrics
- Add `prometheus_client` dependency
- Create metrics collectors (Counters, Gauges, Histograms)
- Expose `/metrics` endpoint

#### 3.2 Structured Logging Enhancement
- Add retry attempt logs
- Add deduplication logs
- Add metrics summary logs

**Deliverables:**
- ✅ Prometheus metrics at `/metrics`
- ✅ Grafana-compatible dashboards
- ✅ Railway monitoring integration

---

## 📂 File Structure Changes

```
apps/subsquid-silo-tests/
│
├── src/
│   ├── polling/
│   │   └── poller.py                    [MODIFIED] Add health server integration
│   │
│   ├── ws/
│   │   └── streamer.py                  [MODIFIED] Add health + dedup + validation
│   │
│   ├── db/
│   │   └── client.py                    [MODIFIED] Add retry decorators
│   │
│   ├── utils/
│   │   ├── __init__.py                  [NEW]
│   │   ├── health_server.py             [NEW] Reusable health endpoint
│   │   └── metrics.py                   [MODIFIED] Add Prometheus metrics
│   │
│   └── config.py                        [MODIFIED] Add new config vars
│
├── requirements.txt                     [MODIFIED] Add tenacity, prometheus-client
├── OBSERVABILITY_ROADMAP.md             [NEW] This file
└── OBSERVABILITY_TESTING.md             [NEW] Testing guide (to be created)
```

---

## 🔧 Detailed Implementation Plan

### **Task 1: Health Check Endpoints**

#### **File:** `src/utils/health_server.py` [NEW]
```python
# Lightweight FastAPI server for health + metrics
# Runs in background asyncio task (non-blocking)
# Reusable across poller and streamer
```

**Features:**
- `/health` endpoint with JSON response
- `/metrics` endpoint for Prometheus
- Service status detection (healthy/degraded/error)
- Uptime tracking
- Last update timestamp
- Error count monitoring

**Status Logic:**
```python
if consecutive_errors > 3:
    status = "error"
elif last_update_age > 90 seconds:
    status = "degraded"
else:
    status = "healthy"
```

#### **Integration Points:**
- `poller.py` - Lines ~50-60 (after start())
- `streamer.py` - Lines ~50-60 (after start())

**Configuration:**
```python
# config.py additions
HEALTH_SERVER_ENABLED: bool = True
HEALTH_SERVER_PORT_POLLER: int = 8080
HEALTH_SERVER_PORT_STREAMER: int = 8081
HEALTH_CHECK_DEGRADED_THRESHOLD_SECONDS: int = 90
HEALTH_CHECK_ERROR_THRESHOLD: int = 3
```

---

### **Task 2: Database Retry Logic**

#### **File:** `src/db/client.py` [MODIFIED]
```python
# Add retry decorator to all upsert methods
# Methods to wrap:
# - upsert_markets_poll()
# - upsert_market_ws()
# - upsert_market_ws_trade()
# - insert_webhook_event()
```

**Retry Configuration:**
- **Attempts:** 3
- **Wait Strategy:** Exponential backoff (1s → 2s → 4s → 10s max)
- **Reraise:** True (propagate error after exhaustion)
- **Logging:** Warning level on each retry

**Example:**
```python
from tenacity import retry, stop_after_attempt, wait_exponential, before_sleep_log

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True
)
async def upsert_markets_poll(self, markets: List[Dict]) -> int:
    # Existing implementation
    pass
```

**Error Scenarios Covered:**
- Network timeouts
- Connection pool exhaustion
- Transient database locks
- Temporary database unavailability

---

### **Task 3: Message Deduplication (Streamer)**

#### **File:** `src/ws/streamer.py` [MODIFIED]
```python
# Add to StreamerService.__init__()
from collections import deque

self.recent_messages = deque(maxlen=1000)  # Last 1000 fingerprints
self.duplicate_count = 0
```

**Fingerprint Generation:**
```python
def _generate_fingerprint(self, data: Dict[str, Any]) -> str:
    """Generate unique message fingerprint for deduplication"""
    import hashlib
    
    market_id = data.get("market", "")
    timestamp = data.get("timestamp", "")
    price = data.get("price", 0)
    
    fingerprint_str = f"{market_id}_{timestamp}_{price}"
    return hashlib.md5(fingerprint_str.encode()).hexdigest()[:12]
```

**Integration Points:**
- `_handle_trade()` - Line ~200
- `_handle_orderbook()` - Line ~218
- `_handle_snapshot()` - Line ~249
- `_handle_delta()` - Line ~282

**Performance:**
- Memory: ~50KB for 1000 fingerprints
- Lookup: O(n) worst case, O(1) average with hash
- Auto-eviction: Oldest messages naturally drop off

---

### **Task 4: Timestamp Validation (Streamer)**

#### **File:** `src/ws/streamer.py` [MODIFIED]
```python
# Add validation helper
def _is_message_stale(self, data: Dict[str, Any]) -> bool:
    """Check if message timestamp is too old"""
    try:
        msg_timestamp = datetime.fromisoformat(data.get("timestamp"))
        now = datetime.now(timezone.utc)
        age_seconds = (now - msg_timestamp).total_seconds()
        
        if age_seconds > settings.WS_MESSAGE_MAX_AGE_SECONDS:
            logger.warning(
                f"⚠️ Stale message: age={age_seconds:.0f}s, "
                f"market={data.get('market')}"
            )
            self.stale_message_count += 1
            return True
        return False
    except:
        return False  # Process if timestamp invalid
```

**Configuration:**
```python
# config.py
WS_MESSAGE_MAX_AGE_SECONDS: int = 60  # Configurable staleness threshold
```

**Integration:**
- Call at start of each handler
- Skip processing if stale
- Track stale message count for metrics

---

### **Task 5: Prometheus Metrics**

#### **File:** `src/utils/metrics.py` [MODIFIED/ENHANCED]

**Metric Types:**

**Counters** (monotonically increasing):
```python
from prometheus_client import Counter

# Poller metrics
poll_cycles_total = Counter(
    'subsquid_poller_cycles_total',
    'Total number of polling cycles'
)

poll_markets_fetched_total = Counter(
    'subsquid_poller_markets_fetched_total',
    'Total markets fetched from Gamma API'
)

poll_errors_total = Counter(
    'subsquid_poller_errors_total',
    'Total polling errors',
    ['error_type']  # Label: connection, parse, db
)

# Streamer metrics
stream_messages_total = Counter(
    'subsquid_streamer_messages_total',
    'Total WebSocket messages received',
    ['message_type']  # Label: trade, orderbook, snapshot, delta
)

stream_duplicates_total = Counter(
    'subsquid_streamer_duplicates_total',
    'Total duplicate messages detected'
)

stream_stale_messages_total = Counter(
    'subsquid_streamer_stale_messages_total',
    'Total stale messages skipped'
)

stream_reconnections_total = Counter(
    'subsquid_streamer_reconnections_total',
    'Total WebSocket reconnections'
)

# Database metrics
db_upserts_total = Counter(
    'subsquid_db_upserts_total',
    'Total database upserts',
    ['table']  # Label: markets_poll, markets_ws, markets_wh
)

db_retries_total = Counter(
    'subsquid_db_retries_total',
    'Total database retry attempts',
    ['table']
)

db_errors_total = Counter(
    'subsquid_db_errors_total',
    'Total database errors (after retries)',
    ['table']
)
```

**Gauges** (current state):
```python
from prometheus_client import Gauge

# Poller gauges
poll_last_cycle_duration_seconds = Gauge(
    'subsquid_poller_last_cycle_duration_seconds',
    'Duration of last polling cycle'
)

poll_markets_count = Gauge(
    'subsquid_poller_markets_count',
    'Number of markets in last cycle'
)

poll_consecutive_errors = Gauge(
    'subsquid_poller_consecutive_errors',
    'Number of consecutive errors'
)

# Streamer gauges
stream_active_subscriptions = Gauge(
    'subsquid_streamer_active_subscriptions',
    'Number of active market subscriptions'
)

stream_last_message_age_seconds = Gauge(
    'subsquid_streamer_last_message_age_seconds',
    'Seconds since last message received'
)

stream_consecutive_errors = Gauge(
    'subsquid_streamer_consecutive_errors',
    'Number of consecutive errors'
)
```

**Histograms** (distribution tracking):
```python
from prometheus_client import Histogram

# Latency tracking
poll_cycle_duration_seconds = Histogram(
    'subsquid_poller_cycle_duration_seconds',
    'Polling cycle duration distribution',
    buckets=[1, 5, 10, 30, 60, 120, 300]  # 1s to 5min
)

stream_message_processing_seconds = Histogram(
    'subsquid_streamer_message_processing_seconds',
    'Message processing duration distribution',
    buckets=[0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0]  # 1ms to 1s
)

db_upsert_duration_seconds = Histogram(
    'subsquid_db_upsert_duration_seconds',
    'Database upsert duration distribution',
    buckets=[0.01, 0.05, 0.1, 0.5, 1.0, 5.0, 10.0]  # 10ms to 10s
)
```

**Metrics Endpoint:**
```python
# In health_server.py
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

@app.get("/metrics")
def metrics():
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST
    )
```

---

### **Task 6: Configuration Updates**

#### **File:** `src/config.py` [MODIFIED]

**New Configuration Variables:**
```python
class Settings(BaseSettings):
    # ... existing config ...
    
    # ========================================
    # Health Check Configuration
    # ========================================
    HEALTH_SERVER_ENABLED: bool = True
    HEALTH_SERVER_PORT_POLLER: int = 8080
    HEALTH_SERVER_PORT_STREAMER: int = 8081
    HEALTH_CHECK_DEGRADED_THRESHOLD_SECONDS: int = 90
    HEALTH_CHECK_ERROR_THRESHOLD: int = 3
    
    # ========================================
    # Database Retry Configuration
    # ========================================
    DB_RETRY_ATTEMPTS: int = 3
    DB_RETRY_MIN_WAIT_SECONDS: int = 1
    DB_RETRY_MAX_WAIT_SECONDS: int = 10
    DB_RETRY_MULTIPLIER: float = 1.0
    
    # ========================================
    # Streamer Deduplication Configuration
    # ========================================
    STREAMER_DEDUP_CACHE_SIZE: int = 1000
    STREAMER_DEDUP_ENABLED: bool = True
    
    # ========================================
    # Streamer Timestamp Validation
    # ========================================
    WS_MESSAGE_MAX_AGE_SECONDS: int = 60
    WS_TIMESTAMP_VALIDATION_ENABLED: bool = True
    
    # ========================================
    # Metrics Configuration
    # ========================================
    METRICS_ENABLED: bool = True
    METRICS_PORT: Optional[int] = None  # Uses health server port if None
```

---

## 📦 Dependency Updates

#### **File:** `requirements.txt` [MODIFIED]

**Add:**
```txt
# Retry logic
tenacity>=8.2.0

# Metrics and monitoring
prometheus-client>=0.19.0
```

**Full Context:**
```txt
# Existing dependencies
asyncio>=3.4.3
asyncpg>=0.29.0
httpx>=0.25.0
websockets>=12.0
fastapi>=0.104.0
uvicorn[standard]>=0.24.0
pydantic>=2.5.0
pydantic-settings>=2.1.0
python-dateutil>=2.8.2

# NEW: Retry logic
tenacity>=8.2.0

# NEW: Metrics and monitoring
prometheus-client>=0.19.0

# Existing dev dependencies
pytest>=7.4.0
pytest-asyncio>=0.21.0
pytest-cov>=4.1.0
```

---

## 🧪 Testing Strategy

### **Unit Tests**

#### **Test File:** `tests/test_health_server.py` [NEW]
```python
# Test health endpoint responses
# Test status transitions (healthy → degraded → error)
# Test uptime calculation
# Test concurrent access
```

#### **Test File:** `tests/test_db_retries.py` [NEW]
```python
# Test successful retry after 1 failure
# Test successful retry after 2 failures
# Test failure after 3 attempts
# Test exponential backoff timing
```

#### **Test File:** `tests/test_deduplication.py` [NEW]
```python
# Test duplicate detection
# Test cache eviction (after 1000 messages)
# Test fingerprint generation
# Test edge cases (missing fields)
```

#### **Test File:** `tests/test_timestamp_validation.py` [NEW]
```python
# Test stale message detection
# Test fresh message processing
# Test missing timestamp handling
# Test invalid timestamp format
```

#### **Test File:** `tests/test_metrics.py` [NEW]
```python
# Test metric increments
# Test gauge updates
# Test histogram recording
# Test /metrics endpoint format
```

---

### **Integration Tests**

#### **Test File:** `tests/integration/test_poller_health.py` [NEW]
```bash
# Start poller service
# Wait 120 seconds (2 polling cycles)
# Check /health endpoint
# Verify status = "healthy"
# Verify last_update < 90 seconds
# Stop service
```

#### **Test File:** `tests/integration/test_streamer_health.py` [NEW]
```bash
# Start streamer service
# Wait for WebSocket connection
# Check /health endpoint
# Verify status = "healthy"
# Verify message_count > 0
# Stop service
```

#### **Test File:** `tests/integration/test_db_retry_recovery.py` [NEW]
```bash
# Start service with mocked DB (fail twice, succeed third)
# Verify data written to DB
# Verify retry logs present
# Verify retry metrics incremented
```

---

### **Load Tests**

#### **Test File:** `tests/load/test_dedup_performance.py` [NEW]
```python
# Send 10,000 messages with 20% duplicates
# Verify memory usage < 100MB
# Verify deduplication accuracy = 100%
# Verify processing time < 5 seconds
```

#### **Test File:** `tests/load/test_metrics_overhead.py` [NEW]
```python
# Run service with metrics enabled vs disabled
# Compare CPU usage (should be < 2% difference)
# Compare memory usage (should be < 10MB difference)
# Compare latency (should be < 5ms difference)
```

---

## 📊 Success Criteria

### **Phase 1: Foundation**
- ✅ `/health` returns 200 OK on both services
- ✅ Health status correctly reflects service state
- ✅ Database writes retry 3x before failing
- ✅ Retry logs visible in service logs
- ✅ Services shut down gracefully (no orphaned processes)

### **Phase 2: Resilience**
- ✅ Duplicate messages detected and skipped (0% duplicates processed)
- ✅ Stale messages detected and skipped (0% stale data in DB)
- ✅ Memory usage remains stable over 24 hours
- ✅ Deduplication logs visible with counts

### **Phase 3: Observability**
- ✅ `/metrics` returns Prometheus-formatted data
- ✅ All defined metrics present in output
- ✅ Metrics update in real-time (< 10s lag)
- ✅ Grafana dashboard imports successfully
- ✅ Railway monitoring shows service health

---

## 🚦 Rollout Plan

### **Pre-Production (Local Testing)**
1. Implement all changes in feature branch
2. Run unit tests (100% pass required)
3. Run integration tests (100% pass required)
4. Run load tests (verify performance)
5. Test health endpoints manually
6. Test metrics scraping manually

### **Staging Deployment**
1. Deploy to Railway staging environment
2. Monitor for 4 hours
3. Verify health endpoints accessible
4. Verify metrics endpoint accessible
5. Test database retry (simulate DB failure)
6. Test deduplication (inject duplicates)
7. Check logs for errors

### **Production Deployment**
1. Merge feature branch to main
2. Deploy to Railway production
3. Monitor for 24 hours
4. Set up Grafana dashboards
5. Configure Railway health checks
6. Set up alerting rules
7. Document runbook procedures

---

## 📈 Monitoring & Alerting

### **Railway Health Checks**
```json
{
  "healthcheckPath": "/health",
  "healthcheckTimeout": 10,
  "healthcheckInterval": 30,
  "restartPolicyType": "ON_FAILURE",
  "restartPolicyMaxRetries": 5
}
```

### **Alert Rules** (for Grafana/PagerDuty)

**Critical Alerts** (Page Ops):
```yaml
- name: Service Down
  condition: up == 0 for 5 minutes
  severity: critical
  
- name: Health Check Failing
  condition: health_status != "healthy" for 10 minutes
  severity: critical
  
- name: High Error Rate
  condition: error_rate > 10% for 5 minutes
  severity: critical
```

**Warning Alerts** (Slack/Email):
```yaml
- name: Service Degraded
  condition: health_status == "degraded" for 5 minutes
  severity: warning
  
- name: High Retry Rate
  condition: db_retry_rate > 20% for 10 minutes
  severity: warning
  
- name: High Duplicate Rate
  condition: duplicate_rate > 5% for 10 minutes
  severity: warning
  
- name: High Stale Message Rate
  condition: stale_message_rate > 10% for 10 minutes
  severity: warning
```

---

## 📝 Documentation Deliverables

### **1. OBSERVABILITY_TESTING.md** [TO BE CREATED]
- Manual testing procedures
- Automated test commands
- Expected outputs and logs
- Troubleshooting guide

### **2. METRICS_CATALOG.md** [TO BE CREATED]
- Complete list of all metrics
- Metric descriptions
- Alert thresholds
- Grafana dashboard JSON

### **3. RUNBOOK.md** [TO BE CREATED]
- Common issues and resolutions
- Health check interpretation
- Metric interpretation
- Escalation procedures

### **4. CHANGELOG.md** [TO BE UPDATED]
- All changes in this release
- Breaking changes (none expected)
- Migration guide (none needed)

---

## 🎯 Timeline

| Phase | Duration | Start | End |
|-------|----------|-------|-----|
| **Phase 1: Foundation** | 2-3 hours | Day 1, 9:00 AM | Day 1, 12:00 PM |
| **Unit Testing (Phase 1)** | 1 hour | Day 1, 1:00 PM | Day 1, 2:00 PM |
| **Phase 2: Resilience** | 1.5-2 hours | Day 1, 2:00 PM | Day 1, 4:00 PM |
| **Unit Testing (Phase 2)** | 45 min | Day 1, 4:00 PM | Day 1, 4:45 PM |
| **Phase 3: Observability** | 1.5-2 hours | Day 1, 5:00 PM | Day 1, 7:00 PM |
| **Unit Testing (Phase 3)** | 30 min | Day 1, 7:00 PM | Day 1, 7:30 PM |
| **Integration Testing** | 2 hours | Day 2, 9:00 AM | Day 2, 11:00 AM |
| **Staging Deployment** | 4 hours | Day 2, 11:00 AM | Day 2, 3:00 PM |
| **Documentation** | 2 hours | Day 2, 3:00 PM | Day 2, 5:00 PM |
| **Production Deployment** | 1 hour | Day 3, 9:00 AM | Day 3, 10:00 AM |
| **Production Monitoring** | 24 hours | Day 3, 10:00 AM | Day 4, 10:00 AM |

**Total Estimated Time:** 16-18 hours (2-3 working days)

---

## 🔒 Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| **Breaking async patterns** | Low | High | Extensive async testing, code review |
| **Performance degradation** | Low | Medium | Load testing, metric overhead checks |
| **Health endpoint conflicts** | Low | Low | Configurable ports, Railway config |
| **Retry loops causing delays** | Medium | Low | Max 3 retries, exponential backoff |
| **Memory leak from dedup cache** | Low | Medium | Fixed-size deque, memory monitoring |
| **Metrics scraping overhead** | Low | Low | Lazy metrics collection |

---

## ✅ Definition of Done

- [ ] All code implemented and committed to feature branch
- [ ] All unit tests passing (100%)
- [ ] All integration tests passing (100%)
- [ ] Code review completed (peer review)
- [ ] Documentation completed (4 docs)
- [ ] Staging deployment successful
- [ ] 24-hour monitoring period completed
- [ ] No critical issues identified
- [ ] Production deployment approved
- [ ] Runbook shared with ops team
- [ ] Grafana dashboards configured
- [ ] Alert rules configured
- [ ] Feature branch merged to main

---

## 📞 Stakeholders

| Role | Name | Responsibility |
|------|------|----------------|
| **Developer** | [You] | Implementation, testing, documentation |
| **Code Reviewer** | [TBD] | Code review, approval |
| **DevOps** | [TBD] | Railway deployment, monitoring setup |
| **Product Owner** | [TBD] | Final approval, production deployment |

---

## 🚀 Next Steps

1. **Review this roadmap** - Confirm approach and timeline
2. **Approve implementation** - Get stakeholder sign-off
3. **Start Phase 1** - Begin coding foundation components
4. **Daily standup updates** - Track progress and blockers
5. **Post-deployment review** - Lessons learned, retrospective

---

**Status:** 📋 **READY FOR IMPLEMENTATION**

**Branch:** `feature/subsquid-observability-improvements`

**Last Updated:** October 23, 2025

---

*This roadmap follows the Technical Audit findings and addresses all identified gaps in the poller and streamer services.*

