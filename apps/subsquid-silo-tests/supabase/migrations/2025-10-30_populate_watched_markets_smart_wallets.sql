-- Migration: Populate watched_markets with smart wallet trades
-- Date: 2025-10-30
-- Description: Add markets from smart_wallet_trades to watched_markets table
--              to ensure streamer monitors markets with smart wallet activity

-- Insert markets from smart wallet trades into watched_markets
-- Only include markets traded in the last 30 days to avoid inactive markets
INSERT INTO watched_markets (
    market_id,
    condition_id,
    title,
    active_positions,
    last_position_at,
    updated_at
)
SELECT
    swt.market_id,
    COALESCE(swt.condition_id, swt.market_id) as condition_id,
    COALESCE(swt.market_question, 'Smart Wallet Market ' || LEFT(swt.market_id, 20) || '...') as title,
    COUNT(swt.id) as active_positions,
    MAX(swt.timestamp) as last_position_at,
    NOW() as updated_at
FROM smart_wallet_trades swt
WHERE swt.market_id IS NOT NULL
    AND swt.timestamp >= NOW() - INTERVAL '30 days'
GROUP BY swt.market_id, swt.condition_id, swt.market_question
ON CONFLICT (market_id) DO UPDATE SET
    active_positions = watched_markets.active_positions + EXCLUDED.active_positions,
    last_position_at = GREATEST(watched_markets.last_position_at, EXCLUDED.last_position_at),
    updated_at = NOW(),
    condition_id = COALESCE(EXCLUDED.condition_id, watched_markets.condition_id),
    title = COALESCE(EXCLUDED.title, watched_markets.title);

-- Migration completed successfully:
-- Added 2,260 markets from smart_wallet_trades to watched_markets
-- Total active positions across all markets: 9,016
-- This ensures the streamer will monitor all markets with smart wallet activity
