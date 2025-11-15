-- Update Alert Bot Filters: Crypto Price Markets + Higher Min Value
-- Date: 2025-10-28
-- Changes:
--   1. Raise min_value from $200 to $350
--   2. Exclude crypto price prediction markets

-- =====================================================================
-- Update alert_bot_pending_trades view
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
    -- Filters
    swt.is_first_time = TRUE
    AND swt.value >= 350  -- RAISED from 200 to 350
    AND sw.bucket_smart = 'Very Smart'
    AND swt.market_question IS NOT NULL
    AND swt.market_question != ''
    
    -- NEW: Exclude crypto price markets
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

COMMENT ON VIEW alert_bot_pending_trades IS 'Quality trades ready to be alerted (excludes crypto price markets, min $350)';

-- =====================================================================
-- Verification queries
-- =====================================================================

-- Check how many pending trades now
-- SELECT COUNT(*) FROM alert_bot_pending_trades;

-- Check if crypto markets are excluded
-- SELECT market_question, value 
-- FROM smart_wallet_trades 
-- WHERE market_question ILIKE '%up or down%' 
--   AND is_first_time = TRUE 
--   AND value >= 350
-- LIMIT 10;

-- Should return 0 rows (all excluded)


