-- Copy Trading: Add amount_usdc field and migrate leader_transaction_id
-- Date: 2025-10-29
--
-- PROBLEM:
-- 1. tracked_leader_trades needs amount_usdc field for accurate USDC amounts
-- 2. copy_trading_history.leader_transaction_id is INTEGER but should be VARCHAR (tx_id is string)
--
-- SOLUTION:
-- 1. Add amount_usdc column to tracked_leader_trades
-- 2. Migrate leader_transaction_id from INTEGER to VARCHAR(255) in copy_trading_history

-- 1. Add amount_usdc column to tracked_leader_trades
ALTER TABLE tracked_leader_trades
ADD COLUMN IF NOT EXISTS amount_usdc NUMERIC(18, 6);

-- Add comment for clarity
COMMENT ON COLUMN tracked_leader_trades.amount_usdc IS
'Exact USDC amount spent/received (from indexer taking_amount field)';

-- 2. Migrate copy_trading_history transaction IDs to VARCHAR
-- First, drop any constraints that reference this column
ALTER TABLE copy_trading_history
DROP CONSTRAINT IF EXISTS copy_amount_positive;

ALTER TABLE copy_trading_history
DROP CONSTRAINT IF EXISTS actual_amount_positive;

-- Change column types (PostgreSQL handles the conversion)
ALTER TABLE copy_trading_history
ALTER COLUMN leader_transaction_id TYPE VARCHAR(255);

ALTER TABLE copy_trading_history
ALTER COLUMN follower_transaction_id TYPE VARCHAR(255);

-- Recreate constraints
ALTER TABLE copy_trading_history
ADD CONSTRAINT copy_amount_positive CHECK (calculated_copy_amount >= 0);

ALTER TABLE copy_trading_history
ADD CONSTRAINT actual_amount_positive CHECK (actual_copy_amount IS NULL OR actual_copy_amount >= 0);

-- Update comments
COMMENT ON COLUMN copy_trading_history.leader_transaction_id IS
'Leader transaction ID (VARCHAR - matches tracked_leader_trades.id format)';
COMMENT ON COLUMN tracked_leader_trades.amount_usdc IS
'Exact USDC amount spent/received (from indexer taking_amount field)';
