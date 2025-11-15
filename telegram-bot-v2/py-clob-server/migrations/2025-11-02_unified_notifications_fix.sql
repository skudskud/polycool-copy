-- ============================================================================
-- UNIFIED SMART TRADING NOTIFICATIONS FIX
-- Date: 2025-11-02
-- Issues Fixed:
--   1. Quick Buy/View Market buttons broken (using token_id instead of condition_id)
--   2. Push notifications spamming old trades on restart
--   3. Different freshness standards across systems
-- ============================================================================

-- =====================================================================
-- PART 1: Add condition_id column to smart_wallet_trades
-- =====================================================================

-- Add condition_id column (0x... format, matches subsquid_markets_poll)
ALTER TABLE smart_wallet_trades 
ADD COLUMN IF NOT EXISTS condition_id TEXT;

-- Backfill condition_id from tracked_leader_trades.market_id
-- tracked_leader_trades.market_id contains the condition_id (0x... format)
UPDATE smart_wallet_trades swt
SET condition_id = tlt.market_id
FROM tracked_leader_trades tlt
WHERE swt.id = tlt.tx_id
  AND swt.condition_id IS NULL
  AND tlt.market_id IS NOT NULL;

-- Add index for performance (callback handlers will query by this)
CREATE INDEX IF NOT EXISTS idx_smart_wallet_trades_condition_id 
ON smart_wallet_trades(condition_id);

-- Verify backfill
SELECT 
    COUNT(*) as total_trades,
    COUNT(condition_id) as with_condition_id,
    COUNT(market_question) as with_market_question,
    ROUND(100.0 * COUNT(condition_id) / NULLIF(COUNT(*), 0), 2) as condition_id_coverage,
    ROUND(100.0 * COUNT(market_question) / NULLIF(COUNT(*), 0), 2) as market_question_coverage
FROM smart_wallet_trades;


-- =====================================================================
-- PART 2: Update alert_bot_pending_trades view (unified 5-min standard)
-- =====================================================================

-- Update view to use 5-minute freshness (matches Twitter bot)
-- This ensures all 4 systems (Alert, Twitter, Push, /smart_trading) are unified
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
    swt.condition_id,  -- ✅ Added for webhook integration
    swt.market_question,
    swt.timestamp,
    swt.is_first_time,
    swt.created_at
FROM smart_wallet_trades swt
INNER JOIN smart_wallets sw ON swt.wallet_address = sw.address
WHERE 
    -- UNIFIED STANDARDS (matches Twitter Bot, Push Notifications)
    swt.is_first_time = TRUE
    AND swt.value >= 400  -- $400 minimum
    AND swt.timestamp >= NOW() - INTERVAL '5 minutes'  -- ✅ UNIFIED: 5-min freshness
    AND sw.bucket_smart = 'Very Smart'
    AND swt.market_question IS NOT NULL
    AND swt.market_question != ''
    
    -- Crypto price market exclusions
    AND NOT (
        LOWER(swt.market_question) LIKE '%up or down%'
        OR LOWER(swt.market_question) LIKE '%higher or lower%'
        OR LOWER(swt.market_question) LIKE '%price of bitcoin%'
        OR LOWER(swt.market_question) LIKE '%price of ethereum%'
        OR LOWER(swt.market_question) LIKE '%price of eth %'
        OR LOWER(swt.market_question) LIKE '%price of solana%'
        OR LOWER(swt.market_question) LIKE '%price of sol %'
        OR LOWER(swt.market_question) LIKE '%price of xrp%'
        OR LOWER(swt.market_question) LIKE '%price of bnb%'
        OR LOWER(swt.market_question) LIKE '%price of cardano%'
        OR LOWER(swt.market_question) LIKE '%price of ada %'
        OR LOWER(swt.market_question) LIKE '%price of dogecoin%'
        OR LOWER(swt.market_question) LIKE '%price of doge%'
        OR LOWER(swt.market_question) LIKE '%bitcoin above%'
        OR LOWER(swt.market_question) LIKE '%bitcoin below%'
        OR LOWER(swt.market_question) LIKE '%ethereum above%'
        OR LOWER(swt.market_question) LIKE '%ethereum below%'
        OR LOWER(swt.market_question) LIKE '%eth above%'
        OR LOWER(swt.market_question) LIKE '%eth below%'
        OR LOWER(swt.market_question) LIKE '%solana above%'
        OR LOWER(swt.market_question) LIKE '%solana below%'
        OR LOWER(swt.market_question) LIKE '%sol above%'
        OR LOWER(swt.market_question) LIKE '%sol below%'
        OR LOWER(swt.market_question) LIKE '%xrp above%'
        OR LOWER(swt.market_question) LIKE '%xrp below%'
        OR LOWER(swt.market_question) LIKE '%bnb above%'
        OR LOWER(swt.market_question) LIKE '%bnb below%'
        OR LOWER(swt.market_question) LIKE '%next 15 minutes%'
        OR LOWER(swt.market_question) LIKE '%next 30 minutes%'
        OR LOWER(swt.market_question) LIKE '%next hour%'
        OR LOWER(swt.market_question) LIKE '%next 4 hours%'
        OR LOWER(swt.market_question) LIKE '%in the next hour%'
        OR LOWER(swt.market_question) LIKE '%in the next 4 hours%'
    )
    
    -- Not already alerted
    AND NOT EXISTS (
        SELECT 1 FROM alert_bot_sent abs 
        WHERE abs.trade_id = swt.id
    )
ORDER BY swt.timestamp DESC;


-- =====================================================================
-- VERIFICATION QUERIES
-- =====================================================================

-- Check if condition_id is properly populated
SELECT 
    'condition_id coverage' as metric,
    COUNT(*) as total,
    COUNT(condition_id) as populated,
    COUNT(*) - COUNT(condition_id) as missing,
    ROUND(100.0 * COUNT(condition_id) / NULLIF(COUNT(*), 0), 2) as percentage
FROM smart_wallet_trades
WHERE created_at >= NOW() - INTERVAL '24 hours';

-- Check recent qualifying trades for notifications
SELECT 
    id,
    condition_id,
    market_question,
    value,
    timestamp,
    NOW() - timestamp as age
FROM smart_wallet_trades
WHERE is_first_time = TRUE
  AND value >= 400
  AND timestamp >= NOW() - INTERVAL '5 minutes'
ORDER BY timestamp DESC
LIMIT 5;

