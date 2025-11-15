-- Migration: Add amount_usdc column to trades table
-- Date: November 10, 2025
-- Description: Add amount_usdc column to store exact USDC trade amounts from indexer

-- Add amount_usdc column to trades table
ALTER TABLE trades ADD COLUMN IF NOT EXISTS amount_usdc DECIMAL(18,6);

-- Add comment
COMMENT ON COLUMN trades.amount_usdc IS 'Exact USDC amount for the trade (from indexer taking_amount)';

-- Add index for performance on amount_usdc
CREATE INDEX IF NOT EXISTS idx_trades_amount_usdc ON trades(amount_usdc) WHERE amount_usdc IS NOT NULL;
