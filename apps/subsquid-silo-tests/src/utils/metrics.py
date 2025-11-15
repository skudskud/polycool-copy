"""
Prometheus Metrics for Subsquid Silo Tests
Tracks performance, errors, and operational metrics for poller and streamer services.
"""

from prometheus_client import Counter, Gauge, Histogram

# ========================================
# Poller Metrics
# ========================================

# Counters (monotonically increasing)
poll_cycles_total = Counter(
    'subsquid_poller_cycles_total',
    'Total number of polling cycles completed'
)

poll_markets_fetched_total = Counter(
    'subsquid_poller_markets_fetched_total',
    'Total number of markets fetched from Gamma API'
)

poll_errors_total = Counter(
    'subsquid_poller_errors_total',
    'Total polling errors by type',
    ['error_type']  # Labels: connection, parse, db, rate_limit
)

# Gauges (current state)
poll_last_cycle_duration_seconds = Gauge(
    'subsquid_poller_last_cycle_duration_seconds',
    'Duration of the last polling cycle in seconds'
)

poll_markets_count = Gauge(
    'subsquid_poller_markets_count',
    'Number of markets fetched in last cycle'
)

poll_consecutive_errors = Gauge(
    'subsquid_poller_consecutive_errors',
    'Number of consecutive polling errors'
)

# Histograms (distribution tracking)
poll_cycle_duration_seconds = Histogram(
    'subsquid_poller_cycle_duration_seconds',
    'Distribution of polling cycle durations',
    buckets=[1, 5, 10, 30, 60, 120, 300]  # 1s to 5min
)

# ========================================
# Streamer Metrics
# ========================================

# Counters
stream_messages_total = Counter(
    'subsquid_streamer_messages_total',
    'Total WebSocket messages received by type',
    ['message_type']  # Labels: trade, orderbook, snapshot, delta
)

stream_duplicates_total = Counter(
    'subsquid_streamer_duplicates_total',
    'Total duplicate messages detected and skipped'
)

stream_stale_messages_total = Counter(
    'subsquid_streamer_stale_messages_total',
    'Total stale messages skipped (timestamp too old)'
)

stream_reconnections_total = Counter(
    'subsquid_streamer_reconnections_total',
    'Total WebSocket reconnection attempts'
)

# Gauges
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
    'Number of consecutive WebSocket errors'
)

# Histograms
stream_message_processing_seconds = Histogram(
    'subsquid_streamer_message_processing_seconds',
    'Distribution of message processing durations',
    buckets=[0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0]  # 1ms to 1s
)

# ========================================
# Database Metrics
# ========================================

# Counters
db_upserts_total = Counter(
    'subsquid_db_upserts_total',
    'Total database upsert operations by table',
    ['table']  # Labels: markets_poll, markets_ws, markets_wh
)

db_retries_total = Counter(
    'subsquid_db_retries_total',
    'Total database retry attempts by table',
    ['table']
)

db_errors_total = Counter(
    'subsquid_db_errors_total',
    'Total database errors after all retries by table',
    ['table']
)

# Histograms
db_upsert_duration_seconds = Histogram(
    'subsquid_db_upsert_duration_seconds',
    'Distribution of database upsert durations',
    buckets=[0.01, 0.05, 0.1, 0.5, 1.0, 5.0, 10.0]  # 10ms to 10s
)

