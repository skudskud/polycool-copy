-- Migration: Create Alert Bot Tables
-- Description: Isolated tables for Polycool Alert Bot to track sent alerts, rate limiting, and statistics
-- Created: 2025-10-23

-- =====================================================================
-- Table 1: Track sent alerts (prevent duplicates)
-- =====================================================================
CREATE TABLE IF NOT EXISTS alert_bot_sent (
    id SERIAL PRIMARY KEY,
    trade_id VARCHAR(100) NOT NULL,
    wallet_address VARCHAR(42) NOT NULL,
    market_question TEXT,
    value NUMERIC(20, 2),
    telegram_message_id BIGINT,
    telegram_chat_id BIGINT,
    sent_at TIMESTAMP DEFAULT NOW(),
    
    -- Prevent duplicate alerts
    CONSTRAINT unique_trade_alert UNIQUE(trade_id)
);

-- Indexes for fast lookups
CREATE INDEX IF NOT EXISTS idx_alert_sent_at ON alert_bot_sent(sent_at DESC);
CREATE INDEX IF NOT EXISTS idx_alert_wallet ON alert_bot_sent(wallet_address);
CREATE INDEX IF NOT EXISTS idx_alert_trade_id ON alert_bot_sent(trade_id);

COMMENT ON TABLE alert_bot_sent IS 'Tracks all alerts sent by the Polycool Alert Bot to prevent duplicates';
COMMENT ON COLUMN alert_bot_sent.trade_id IS 'References smart_wallet_trades.id (transaction hash)';
COMMENT ON COLUMN alert_bot_sent.telegram_message_id IS 'Telegram message ID for tracking/editing';

-- =====================================================================
-- Table 2: Rate limiting (10 alerts per hour max)
-- =====================================================================
CREATE TABLE IF NOT EXISTS alert_bot_rate_limit (
    id SERIAL PRIMARY KEY,
    hour_bucket TIMESTAMP NOT NULL,
    alerts_sent INTEGER DEFAULT 0,
    alerts_skipped INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    
    -- One record per hour
    CONSTRAINT unique_hour_bucket UNIQUE(hour_bucket)
);

CREATE INDEX IF NOT EXISTS idx_rate_limit_hour ON alert_bot_rate_limit(hour_bucket DESC);

COMMENT ON TABLE alert_bot_rate_limit IS 'Tracks hourly rate limits (max 10 alerts/hour)';
COMMENT ON COLUMN alert_bot_rate_limit.hour_bucket IS 'Hour timestamp (minutes/seconds zeroed)';

-- =====================================================================
-- Table 3: Daily statistics
-- =====================================================================
CREATE TABLE IF NOT EXISTS alert_bot_stats (
    id SERIAL PRIMARY KEY,
    date DATE NOT NULL,
    total_trades_checked INTEGER DEFAULT 0,
    alerts_sent INTEGER DEFAULT 0,
    alerts_skipped_rate_limit INTEGER DEFAULT 0,
    alerts_skipped_filters INTEGER DEFAULT 0,
    last_checked_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    
    CONSTRAINT unique_stats_date UNIQUE(date)
);

CREATE INDEX IF NOT EXISTS idx_stats_date ON alert_bot_stats(date DESC);

COMMENT ON TABLE alert_bot_stats IS 'Daily statistics for monitoring alert bot performance';

-- =====================================================================
-- Table 4: Bot health monitoring
-- =====================================================================
CREATE TABLE IF NOT EXISTS alert_bot_health (
    id SERIAL PRIMARY KEY,
    status VARCHAR(20) NOT NULL DEFAULT 'stopped',
    last_poll_at TIMESTAMP,
    last_alert_at TIMESTAMP,
    errors_last_hour INTEGER DEFAULT 0,
    uptime_seconds INTEGER DEFAULT 0,
    version VARCHAR(20) DEFAULT 'v1.0.0',
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Insert initial health record
INSERT INTO alert_bot_health (status, version, updated_at) 
VALUES ('stopped', 'v1.0.0', NOW())
ON CONFLICT DO NOTHING;

COMMENT ON TABLE alert_bot_health IS 'Real-time health status of the alert bot';

-- =====================================================================
-- View: Pending trades ready to alert
-- =====================================================================
CREATE OR REPLACE VIEW alert_bot_pending_trades AS
SELECT 
    swt.id,
    swt.wallet_address,
    sw.bucket_smart,
    sw.smartscore,
    sw.win_rate,
    swt.side,
    swt.outcome,
    swt.price,
    swt.size,
    swt.value,
    swt.market_id,
    swt.market_question,
    swt.timestamp,
    swt.is_first_time,
    swt.created_at
FROM smart_wallet_trades swt
INNER JOIN smart_wallets sw ON swt.wallet_address = sw.address
WHERE 
    -- Aggressive filters (high volume alerts)
    swt.is_first_time = TRUE
    AND swt.value >= 200
    AND sw.bucket_smart = 'Very Smart'
    AND swt.market_question IS NOT NULL
    AND swt.market_question != ''
    -- Not already alerted
    AND NOT EXISTS (
        SELECT 1 FROM alert_bot_sent abs 
        WHERE abs.trade_id = swt.id
    )
ORDER BY swt.timestamp DESC;

COMMENT ON VIEW alert_bot_pending_trades IS 'Quality trades ready to be alerted (not yet sent)';

-- =====================================================================
-- Grant permissions (if needed for Railway user)
-- =====================================================================
-- GRANT SELECT ON alert_bot_pending_trades TO your_railway_user;
-- GRANT ALL ON alert_bot_sent TO your_railway_user;
-- GRANT ALL ON alert_bot_rate_limit TO your_railway_user;
-- GRANT ALL ON alert_bot_stats TO your_railway_user;
-- GRANT ALL ON alert_bot_health TO your_railway_user;

-- =====================================================================
-- Verification queries
-- =====================================================================

-- Check tables created
-- SELECT table_name FROM information_schema.tables WHERE table_name LIKE 'alert_bot%';

-- Check pending trades
-- SELECT COUNT(*) FROM alert_bot_pending_trades;

-- Check initial health
-- SELECT * FROM alert_bot_health;

