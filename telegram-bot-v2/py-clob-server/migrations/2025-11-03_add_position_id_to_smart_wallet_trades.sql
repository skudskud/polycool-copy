-- Migration: Add position_id to smart_wallet_trades
-- Date: 2025-11-03
-- Purpose: Store real clob_token_id for correct outcome mapping

-- Add position_id column (nullable for backward compatibility)
ALTER TABLE smart_wallet_trades
ADD COLUMN IF NOT EXISTS position_id VARCHAR(100);

-- Add index for faster lookups
CREATE INDEX IF NOT EXISTS idx_smart_wallet_trades_position_id
ON smart_wallet_trades(position_id);

-- Add comment
COMMENT ON COLUMN smart_wallet_trades.position_id IS 'Real clob_token_id from blockchain - source of truth for outcome mapping';
