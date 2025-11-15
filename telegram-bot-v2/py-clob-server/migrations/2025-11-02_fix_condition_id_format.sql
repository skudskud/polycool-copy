-- ============================================================================
-- HOTFIX: Convert token_id to condition_id for all existing trades
-- Date: 2025-11-02
-- Issue: condition_id was being set to token_id (numeric) instead of 0x format
-- ============================================================================

-- Function to convert decimal to hex (PostgreSQL)
CREATE OR REPLACE FUNCTION decimal_to_hex(decimal_value TEXT) 
RETURNS TEXT AS $$
BEGIN
    -- Convert decimal string to bigint, then to hex with 0x prefix
    RETURN '0x' || LPAD(to_hex(decimal_value::numeric::bigint), 64, '0');
EXCEPTION
    WHEN OTHERS THEN
        RETURN NULL;
END;
$$ LANGUAGE plpgsql;

-- Backfill condition_id for recent trades (last 7 days)
UPDATE smart_wallet_trades
SET condition_id = (
    -- Convert market_id (token_id in decimal) to condition_id (0x format)
    '0x' || LPAD(to_hex(market_id::numeric::bigint), 64, '0')
)
WHERE created_at >= NOW() - INTERVAL '7 days'
  AND market_id IS NOT NULL
  AND (condition_id IS NULL OR LENGTH(condition_id) != 66 OR SUBSTRING(condition_id, 1, 2) != '0x');

-- Verify the conversion
SELECT 
    COUNT(*) as total_recent,
    COUNT(CASE WHEN condition_id IS NOT NULL AND SUBSTRING(condition_id, 1, 2) = '0x' THEN 1 END) as has_0x_format,
    ROUND(100.0 * COUNT(CASE WHEN condition_id IS NOT NULL AND SUBSTRING(condition_id, 1, 2) = '0x' THEN 1 END) / COUNT(*), 2) as pct_correct
FROM smart_wallet_trades
WHERE created_at >= NOW() - INTERVAL '24 hours';

-- Drop the helper function
DROP FUNCTION IF EXISTS decimal_to_hex(TEXT);

