-- =================================================
-- MIGRATION: Add User Stats Columns
-- Date: November 9, 2025
-- Description: Add columns to track user trading statistics (balance, profit, volume)
-- Good practice: Cache stats to avoid complex queries, update periodically
-- =================================================

-- Add user stats columns
ALTER TABLE users
ADD COLUMN IF NOT EXISTS usdc_balance NUMERIC(20, 2) DEFAULT 0.0,
ADD COLUMN IF NOT EXISTS total_profit NUMERIC(20, 2) DEFAULT 0.0,
ADD COLUMN IF NOT EXISTS total_volume NUMERIC(20, 2) DEFAULT 0.0,
ADD COLUMN IF NOT EXISTS last_balance_sync TIMESTAMP WITHOUT TIME ZONE;

-- Add index for efficient queries
CREATE INDEX IF NOT EXISTS idx_users_usdc_balance ON users(usdc_balance);
CREATE INDEX IF NOT EXISTS idx_users_total_profit ON users(total_profit);
CREATE INDEX IF NOT EXISTS idx_users_total_volume ON users(total_volume);

-- Add comments
COMMENT ON COLUMN users.usdc_balance IS 'Cached USDC balance (updated periodically, not real-time)';
COMMENT ON COLUMN users.total_profit IS 'Total realized profit/loss from all closed positions';
COMMENT ON COLUMN users.total_volume IS 'Total trading volume (sum of all trade amounts)';
COMMENT ON COLUMN users.last_balance_sync IS 'Last time balance was synced from blockchain/CLOB';

-- =================================================
-- VERIFICATION QUERIES
-- =================================================

-- Check columns were added
-- SELECT column_name, data_type, is_nullable, column_default
-- FROM information_schema.columns
-- WHERE table_name = 'users'
-- AND column_name IN ('usdc_balance', 'total_profit', 'total_volume', 'last_balance_sync')
-- ORDER BY column_name;

-- Check indexes were created
-- SELECT indexname, indexdef
-- FROM pg_indexes
-- WHERE tablename = 'users'
-- AND indexname IN ('idx_users_usdc_balance', 'idx_users_total_profit', 'idx_users_total_volume');
