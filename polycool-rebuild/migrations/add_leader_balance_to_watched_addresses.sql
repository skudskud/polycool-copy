-- Add USDC balance and last balance sync columns to watched_addresses table
-- This allows storing leader balances to avoid API calls on every copy trade
-- Migration applied via Supabase MCP on 2024

ALTER TABLE watched_addresses
ADD COLUMN IF NOT EXISTS usdc_balance NUMERIC(20, 2) DEFAULT NULL,
ADD COLUMN IF NOT EXISTS last_balance_sync TIMESTAMP WITHOUT TIME ZONE DEFAULT NULL;

-- Add index on last_balance_sync for efficient queries
CREATE INDEX IF NOT EXISTS idx_watched_addresses_last_balance_sync
ON watched_addresses(last_balance_sync)
WHERE address_type = 'copy_leader' AND is_active = true;

-- Add comment for documentation
COMMENT ON COLUMN watched_addresses.usdc_balance IS 'Cached USDC balance for copy leaders (updated hourly via worker)';
COMMENT ON COLUMN watched_addresses.last_balance_sync IS 'Timestamp of last balance sync from blockchain API';
