-- Unified Smart Trading Standards: 5-min freshness + $400 minimum
-- Date: 2025-10-29
-- Changes:
--   1. Add 5-minute freshness window
--   2. Raise min_value from $350 to $400
--   3. Keep crypto price market exclusions

-- =====================================================================
-- Update alert_bot_pending_trades view with unified standards
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
    -- Unified Standards
    swt.is_first_time = TRUE
    AND swt.value >= 400  -- UNIFIED: $400 minimum (was $350)
    AND swt.timestamp >= NOW() - INTERVAL '5 minutes'  -- NEW: 5-min freshness for copy trading
    AND sw.bucket_smart = 'Very Smart'
    AND swt.market_question IS NOT NULL
    AND swt.market_question != ''
    
    -- Crypto price market exclusions (from Phase 1)
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

COMMENT ON VIEW alert_bot_pending_trades IS 'Quality trades ready to be alerted (5-min fresh, $400+ min, no crypto price markets) - UNIFIED STANDARDS';

-- =====================================================================
-- Verification queries
-- =====================================================================

-- Test 1: All trades should be < 5 minutes old
-- SELECT 
--     market_question, 
--     value, 
--     timestamp,
--     NOW() - timestamp as age
-- FROM alert_bot_pending_trades 
-- LIMIT 10;
-- Expected: age <= '5 minutes' for ALL rows

-- Test 2: All trades should be >= $400
-- SELECT MIN(value) FROM alert_bot_pending_trades;
-- Expected: >= 400

-- Test 3: NO crypto price markets
-- SELECT COUNT(*) FROM alert_bot_pending_trades 
-- WHERE market_question ILIKE '%up or down%';
-- Expected: 0

