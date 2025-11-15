-- ========================================
-- Redeem Bot Queries
-- ========================================

-- Query 1: Get positions ready for redeem (RESOLVED markets)
-- Use this in the redeem bot to find positions that can be redeemed
SELECT
    rp.id as position_id,
    rp.user_id,
    rp.market_id,
    rp.condition_id,
    rp.tokens_held,
    rp.outcome,  -- "YES" ou "NO"
    rp.total_cost,
    rp.avg_buy_price,
    mp.winning_outcome,  -- 0 ou 1
    mp.resolution_status,
    mp.resolution_date,
    mp.polymarket_url,
    mp.title as market_title,
    mp.category,
    -- Calculate if user won
    CASE
        WHEN (rp.outcome = 'YES' AND mp.winning_outcome = 1) OR
             (rp.outcome = 'NO' AND mp.winning_outcome = 0)
        THEN true
        ELSE false
    END as is_winner,
    -- Calculate payout (1 USDC per token if winner, 0 if loser)
    CASE
        WHEN (rp.outcome = 'YES' AND mp.winning_outcome = 1) OR
             (rp.outcome = 'NO' AND mp.winning_outcome = 0)
        THEN rp.tokens_held * 1.0
        ELSE 0
    END as expected_payout
FROM resolved_positions rp
JOIN subsquid_markets_poll mp ON rp.market_id = mp.market_id
WHERE rp.status = 'PENDING'
  AND mp.resolution_status = 'RESOLVED'  -- ✅ Market fully resolved
  AND mp.winning_outcome IS NOT NULL
ORDER BY mp.resolution_date ASC
LIMIT 100;


-- Query 2: Stats on resolution status
-- Monitor how many markets are in each resolution state
SELECT
    resolution_status,
    status,
    COUNT(*) as count,
    SUM(volume) as total_volume,
    MIN(resolution_date) as earliest_resolution,
    MAX(resolution_date) as latest_resolution
FROM subsquid_markets_poll
WHERE resolution_status != 'PENDING'
GROUP BY resolution_status, status
ORDER BY count DESC;


-- Query 3: Markets ready for resolution (expired but not resolved yet)
-- These are markets that should have an outcome soon
SELECT
    market_id,
    title,
    status,
    resolution_status,
    end_date,
    NOW() - end_date as time_since_expiry,
    volume,
    polymarket_url
FROM subsquid_markets_poll
WHERE status = 'CLOSED'
  AND resolution_status = 'PROPOSED'  -- Outcome proposed but not confirmed
  AND end_date < NOW() - INTERVAL '1 hour'  -- Expired more than 1h ago
ORDER BY end_date DESC
LIMIT 20;


-- Query 4: Check for markets with contradictory states
-- Useful for debugging API inconsistencies
SELECT
    market_id,
    title,
    status,
    tradeable,
    accepting_orders,
    resolution_status,
    winning_outcome,
    end_date,
    polymarket_url
FROM subsquid_markets_poll
WHERE (
    -- Case 1: ACTIVE but expired
    (status = 'ACTIVE' AND end_date < NOW() - INTERVAL '1 hour') OR
    -- Case 2: CLOSED but tradeable
    (status = 'CLOSED' AND tradeable = true AND accepting_orders = true) OR
    -- Case 3: RESOLVED without winning_outcome
    (resolution_status = 'RESOLVED' AND winning_outcome IS NULL)
)
ORDER BY volume DESC
LIMIT 20;


-- Query 5: User positions summary (for notifications)
-- Show users which of their positions are ready for redeem
SELECT
    u.telegram_user_id,
    u.username,
    COUNT(*) as total_resolved_positions,
    COUNT(*) FILTER (
        WHERE (rp.outcome = 'YES' AND mp.winning_outcome = 1) OR
              (rp.outcome = 'NO' AND mp.winning_outcome = 0)
    ) as winning_positions,
    COUNT(*) FILTER (
        WHERE (rp.outcome = 'YES' AND mp.winning_outcome = 0) OR
              (rp.outcome = 'NO' AND mp.winning_outcome = 1)
    ) as losing_positions,
    SUM(
        CASE
            WHEN (rp.outcome = 'YES' AND mp.winning_outcome = 1) OR
                 (rp.outcome = 'NO' AND mp.winning_outcome = 0)
            THEN rp.tokens_held * 1.0
            ELSE 0
        END
    ) as total_payout
FROM resolved_positions rp
JOIN subsquid_markets_poll mp ON rp.market_id = mp.market_id
JOIN users u ON rp.user_id = u.telegram_user_id
WHERE rp.status = 'PENDING'
  AND mp.resolution_status = 'RESOLVED'
  AND mp.winning_outcome IS NOT NULL
GROUP BY u.telegram_user_id, u.username
ORDER BY total_payout DESC;


-- Query 6: Validation - Check events field corruption
-- Should return 0 rows if events are clean
SELECT
    market_id,
    title,
    events::text as events_preview
FROM subsquid_markets_poll
WHERE events::text LIKE '%\\\\\\%'  -- Multiple escaped backslashes = corruption
LIMIT 10;


-- Query 7: URL coverage stats
-- Check how many markets have Polymarket URLs
SELECT
    COUNT(*) FILTER (WHERE polymarket_url IS NOT NULL AND polymarket_url != '') as has_url,
    COUNT(*) FILTER (WHERE polymarket_url IS NULL OR polymarket_url = '') as missing_url,
    COUNT(*) as total
FROM subsquid_markets_poll
WHERE status = 'ACTIVE';
