-- ============================================================================
-- UNIFIED NOTIFICATION SYSTEM: smart_wallet_trades_to_share
-- Created: 2025-11-03
-- Purpose: Single source of truth for ALL notification systems
--          (Twitter, Alert Channel, Push Notifications, /smart_trading)
-- ============================================================================

BEGIN;

-- Create the unified shareable trades table
-- This table contains ONLY qualified trades that should be shared across ALL 4 systems
CREATE TABLE IF NOT EXISTS smart_wallet_trades_to_share (
    id SERIAL PRIMARY KEY,
    trade_id TEXT NOT NULL UNIQUE,  -- References smart_wallet_trades.id (transaction hash)
    
    -- Denormalized wallet data (for fast reads without JOINs)
    wallet_address TEXT NOT NULL,
    wallet_bucket TEXT,  -- 'Very Smart', 'Smart', etc
    wallet_win_rate NUMERIC(5,4),  -- e.g., 0.7250 (72.50%)
    wallet_smartscore NUMERIC(10,2),  -- e.g., 15.50
    wallet_realized_pnl NUMERIC(20,2),  -- e.g., 28750.50
    
    -- Trade data
    side TEXT NOT NULL,  -- 'BUY' or 'SELL'
    outcome TEXT,  -- 'YES' or 'NO'
    price NUMERIC(20,10) NOT NULL,
    size NUMERIC(20,10) NOT NULL,
    value NUMERIC(20,2) NOT NULL,  -- USD value
    
    -- Market data
    market_id TEXT,  -- token_id (numeric string from subsquid)
    condition_id TEXT,  -- 0x... format (for API calls and callbacks)
    market_question TEXT NOT NULL,  -- MUST have title to be shareable
    
    -- Metadata
    timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
    is_first_time BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    -- Tracking columns: which systems have consumed this trade
    tweeted_at TIMESTAMP WITH TIME ZONE,  -- Twitter bot
    alerted_at TIMESTAMP WITH TIME ZONE,  -- Alert channel bot
    push_notification_count INTEGER DEFAULT 0,  -- How many users notified
    last_push_notification_at TIMESTAMP WITH TIME ZONE  -- Last push notification sent
);

-- Performance indexes
CREATE INDEX IF NOT EXISTS idx_swts_timestamp 
    ON smart_wallet_trades_to_share(timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_swts_not_tweeted 
    ON smart_wallet_trades_to_share(tweeted_at) 
    WHERE tweeted_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_swts_not_alerted 
    ON smart_wallet_trades_to_share(alerted_at) 
    WHERE alerted_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_swts_wallet 
    ON smart_wallet_trades_to_share(wallet_address);

CREATE INDEX IF NOT EXISTS idx_swts_condition_id 
    ON smart_wallet_trades_to_share(condition_id);

CREATE INDEX IF NOT EXISTS idx_swts_trade_id 
    ON smart_wallet_trades_to_share(trade_id);

-- Composite index for push notification queries
CREATE INDEX IF NOT EXISTS idx_swts_push_pending 
    ON smart_wallet_trades_to_share(timestamp DESC, push_notification_count);

-- Log migration
DO $$
BEGIN
    RAISE NOTICE '✅ smart_wallet_trades_to_share table created';
    RAISE NOTICE '✅ 7 performance indexes created';
    RAISE NOTICE '✅ UNIFIED notification system ready';
END $$;

COMMIT;

