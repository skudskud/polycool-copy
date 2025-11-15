-- Migration: Add market_numeric_id to smart_wallet_trades
-- Date: 2025-10-16
-- Purpose: Store numeric market ID alongside conditionId for efficient lookups

-- Add the new column
ALTER TABLE smart_wallet_trades
ADD COLUMN IF NOT EXISTS market_numeric_id VARCHAR(50);

-- Create index for fast lookups
CREATE INDEX IF NOT EXISTS idx_smart_wallet_trades_market_numeric_id
ON smart_wallet_trades(market_numeric_id);

-- Populate existing records by joining with markets table
-- This maps conditionId (0x...) to numeric ID
UPDATE smart_wallet_trades swt
SET market_numeric_id = m.id
FROM markets m
WHERE swt.market_id = m.condition_id
AND swt.market_numeric_id IS NULL;

-- Log results
DO $$
DECLARE
    total_trades INTEGER;
    mapped_trades INTEGER;
    unmapped_trades INTEGER;
BEGIN
    SELECT COUNT(*) INTO total_trades FROM smart_wallet_trades;
    SELECT COUNT(*) INTO mapped_trades FROM smart_wallet_trades WHERE market_numeric_id IS NOT NULL;
    SELECT COUNT(*) INTO unmapped_trades FROM smart_wallet_trades WHERE market_numeric_id IS NULL;

    RAISE NOTICE '✅ Migration complete:';
    RAISE NOTICE '   Total trades: %', total_trades;
    RAISE NOTICE '   Mapped trades: %', mapped_trades;
    RAISE NOTICE '   Unmapped trades: %', unmapped_trades;
END $$;
