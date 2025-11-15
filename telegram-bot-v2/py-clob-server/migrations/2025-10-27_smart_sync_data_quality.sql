-- Smart Wallet Sync Data Quality Tables
-- Phase 0.1: Add validation and monitoring for smart wallet trade sync
-- Date: 2025-10-27

-- ============================================================================
-- TABLE 1: smart_wallet_trades_invalid (Dead Letter Queue)
-- ============================================================================
-- Stores invalid trades that couldn't be synced due to data quality issues
-- This prevents bad data from blocking good data inserts

CREATE TABLE IF NOT EXISTS smart_wallet_trades_invalid (
    id SERIAL PRIMARY KEY,
    trade_data JSONB NOT NULL,                 -- Full trade data for investigation
    error_reason TEXT NOT NULL,                -- Why this trade was rejected
    received_at TIMESTAMP DEFAULT NOW(),       -- When we received this invalid trade
    reviewed BOOLEAN DEFAULT FALSE,            -- Has a human reviewed this?
    notes TEXT                                 -- Admin notes after review
);

-- Index for finding unreviewed invalid trades
CREATE INDEX IF NOT EXISTS idx_invalid_trades_reviewed 
    ON smart_wallet_trades_invalid(reviewed) 
    WHERE reviewed = FALSE;

-- Index for finding recent invalid trades
CREATE INDEX IF NOT EXISTS idx_invalid_trades_received 
    ON smart_wallet_trades_invalid(received_at DESC);

-- Index for grouping by error type
CREATE INDEX IF NOT EXISTS idx_invalid_trades_error 
    ON smart_wallet_trades_invalid(error_reason);

COMMENT ON TABLE smart_wallet_trades_invalid IS 
    'Dead letter queue for trades with invalid/missing data that cannot be synced';

COMMENT ON COLUMN smart_wallet_trades_invalid.trade_data IS 
    'Original trade data from tracked_leader_trades (JSONB for flexibility)';

COMMENT ON COLUMN smart_wallet_trades_invalid.error_reason IS 
    'Validation error: NULL price, missing field, invalid format, etc.';

-- ============================================================================
-- TABLE 2: smart_wallet_sync_metrics (Sync Monitoring)
-- ============================================================================
-- Tracks each sync cycle for monitoring data quality and performance

CREATE TABLE IF NOT EXISTS smart_wallet_sync_metrics (
    id SERIAL PRIMARY KEY,
    sync_timestamp TIMESTAMP NOT NULL,         -- When sync cycle started
    trades_received INTEGER NOT NULL,          -- Total trades from source
    trades_valid INTEGER NOT NULL,             -- Trades that passed validation
    trades_invalid INTEGER NOT NULL,           -- Trades that failed validation
    invalid_reasons JSONB,                     -- Breakdown of error types {"NULL price": 5, "Missing field": 2}
    sync_duration_ms INTEGER,                  -- How long sync took (milliseconds)
    error_message TEXT,                        -- If sync crashed, what was the error?
    created_at TIMESTAMP DEFAULT NOW()         -- When this row was created
);

-- Index for finding recent sync cycles
CREATE INDEX IF NOT EXISTS idx_sync_metrics_timestamp 
    ON smart_wallet_sync_metrics(sync_timestamp DESC);

-- Index for finding failed sync cycles
CREATE INDEX IF NOT EXISTS idx_sync_metrics_errors 
    ON smart_wallet_sync_metrics(error_message) 
    WHERE error_message IS NOT NULL;

COMMENT ON TABLE smart_wallet_sync_metrics IS 
    'Logs every sync cycle for data quality monitoring and performance tracking';

COMMENT ON COLUMN smart_wallet_sync_metrics.invalid_reasons IS 
    'JSON object with counts per error type for analysis';

-- ============================================================================
-- VIEW: v_data_quality_24h (Data Quality Dashboard)
-- ============================================================================
-- Aggregated view of data quality metrics over last 24 hours

CREATE OR REPLACE VIEW v_data_quality_24h AS
SELECT 
    DATE_TRUNC('hour', sync_timestamp) as hour,
    SUM(trades_received) as total_received,
    SUM(trades_valid) as total_valid,
    SUM(trades_invalid) as total_invalid,
    ROUND(AVG(trades_invalid::DECIMAL / NULLIF(trades_received, 0) * 100), 2) as invalid_rate_pct,
    AVG(sync_duration_ms) as avg_sync_duration_ms,
    COUNT(*) as sync_cycles,
    COUNT(*) FILTER (WHERE error_message IS NOT NULL) as failed_cycles
FROM smart_wallet_sync_metrics
WHERE sync_timestamp > NOW() - INTERVAL '24 hours'
GROUP BY DATE_TRUNC('hour', sync_timestamp)
ORDER BY hour DESC;

COMMENT ON VIEW v_data_quality_24h IS 
    'Hourly aggregated data quality metrics for the last 24 hours';

-- ============================================================================
-- VIEW: v_invalid_trades_summary (Error Type Analysis)
-- ============================================================================
-- Shows breakdown of invalid trade error types

CREATE OR REPLACE VIEW v_invalid_trades_summary AS
SELECT 
    error_reason,
    COUNT(*) as count,
    MAX(received_at) as most_recent,
    COUNT(*) FILTER (WHERE reviewed = TRUE) as reviewed_count,
    COUNT(*) FILTER (WHERE reviewed = FALSE) as unreviewed_count
FROM smart_wallet_trades_invalid
WHERE received_at > NOW() - INTERVAL '7 days'
GROUP BY error_reason
ORDER BY count DESC;

COMMENT ON VIEW v_invalid_trades_summary IS 
    'Summary of invalid trade types for the last 7 days';

-- ============================================================================
-- VIEW: v_sync_health_status (Current System Health)
-- ============================================================================
-- Real-time view of sync system health

CREATE OR REPLACE VIEW v_sync_health_status AS
WITH recent_syncs AS (
    SELECT *
    FROM smart_wallet_sync_metrics
    WHERE sync_timestamp > NOW() - INTERVAL '10 minutes'
    ORDER BY sync_timestamp DESC
    LIMIT 10
),
recent_invalid AS (
    SELECT COUNT(*) as recent_invalid_count
    FROM smart_wallet_trades_invalid
    WHERE received_at > NOW() - INTERVAL '10 minutes'
)
SELECT 
    MAX(sync_timestamp) as last_sync_time,
    EXTRACT(EPOCH FROM (NOW() - MAX(sync_timestamp))) as seconds_since_last_sync,
    SUM(trades_received) as trades_received_10min,
    SUM(trades_valid) as trades_synced_10min,
    SUM(trades_invalid) as trades_rejected_10min,
    CASE 
        WHEN SUM(trades_received) = 0 THEN 0
        ELSE ROUND(SUM(trades_invalid)::DECIMAL / SUM(trades_received) * 100, 2)
    END as invalid_rate_pct_10min,
    AVG(sync_duration_ms) as avg_sync_duration_ms,
    COUNT(*) FILTER (WHERE error_message IS NOT NULL) as failed_cycles_10min,
    (SELECT recent_invalid_count FROM recent_invalid) as total_invalid_10min,
    CASE 
        WHEN MAX(sync_timestamp) < NOW() - INTERVAL '5 minutes' THEN '🔴 STALE'
        WHEN SUM(trades_invalid)::DECIMAL / NULLIF(SUM(trades_received), 0) > 0.20 THEN '🟡 DEGRADED'
        WHEN COUNT(*) FILTER (WHERE error_message IS NOT NULL) > 0 THEN '🟠 ERRORS'
        ELSE '🟢 HEALTHY'
    END as health_status
FROM recent_syncs;

COMMENT ON VIEW v_sync_health_status IS 
    'Real-time health status of smart wallet sync system (last 10 minutes)';

-- ============================================================================
-- Example Queries for Monitoring
-- ============================================================================

-- Check current system health
-- SELECT * FROM v_sync_health_status;

-- View data quality trends over last 24h
-- SELECT * FROM v_data_quality_24h LIMIT 24;

-- Find most common error types
-- SELECT * FROM v_invalid_trades_summary;

-- Find recent NULL price errors
-- SELECT trade_data->>'tx_id' as tx_id, 
--        trade_data->>'price' as price,
--        error_reason,
--        received_at
-- FROM smart_wallet_trades_invalid
-- WHERE error_reason LIKE '%NULL price%'
--   AND received_at > NOW() - INTERVAL '1 hour'
-- ORDER BY received_at DESC;

-- Check if sync is running
-- SELECT 
--     MAX(sync_timestamp) as last_sync,
--     EXTRACT(EPOCH FROM (NOW() - MAX(sync_timestamp))) as seconds_ago,
--     CASE 
--         WHEN MAX(sync_timestamp) > NOW() - INTERVAL '2 minutes' THEN '✅ Running'
--         WHEN MAX(sync_timestamp) > NOW() - INTERVAL '5 minutes' THEN '⚠️ Slow'
--         ELSE '❌ Stopped'
--     END as status
-- FROM smart_wallet_sync_metrics;


