-- Widen Alert Window to 30 Minutes
-- Date: 2025-11-01
-- Reason: 5-minute window too strict with 3-minute sync cycle
--         causing zero alerts when pipeline has any delays
--
-- Changes:
--   - 5 minutes → 30 minutes (more forgiving for sync delays)
--   - Still maintains $400 minimum and quality filters
--   - Trades will be fresh enough for copy trading

-- =====================================================================
-- Update alert_bot_pending_trades view with 30-minute window
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
    -- Quality Filters
    swt.is_first_time = TRUE
    AND swt.value >= 400  -- $400 minimum
    AND swt.timestamp >= NOW() - INTERVAL '30 minutes'  -- ✅ WIDENED: was 5 minutes
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

COMMENT ON VIEW alert_bot_pending_trades IS 'Quality trades ready to be alerted (30-min fresh, $400+ min, no crypto price markets) - WIDENED WINDOW';

-- =====================================================================
-- Verification
-- =====================================================================

-- Test: Should show trades from last 30 minutes
SELECT 
    COUNT(*) as pending_count,
    MIN(NOW() - timestamp) as newest_age,
    MAX(NOW() - timestamp) as oldest_age
FROM alert_bot_pending_trades;

-- Expected: oldest_age should be close to 30 minutes

-- Show sample trades
SELECT 
    market_question, 
    value, 
    timestamp,
    NOW() - timestamp as age
FROM alert_bot_pending_trades 
LIMIT 5;

