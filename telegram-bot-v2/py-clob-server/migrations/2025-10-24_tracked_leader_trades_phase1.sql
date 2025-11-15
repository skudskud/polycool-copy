-- ============================================================================
-- Migration: Tracked Leader Trades Table
-- Date: 2025-10-24
-- Purpose: Phase 1 - Foundation for subsquid migration
-- Description: Create tracked_leader_trades table for filtered on-chain trades
-- ============================================================================

-- Create tracked_leader_trades table
CREATE TABLE IF NOT EXISTS tracked_leader_trades (
    id TEXT PRIMARY KEY,
    tx_id TEXT UNIQUE NOT NULL,
    user_address TEXT NOT NULL,
    market_id TEXT,
    outcome INTEGER CHECK (outcome IN (0, 1)),
    tx_type TEXT CHECK (tx_type IN ('BUY', 'SELL')),
    amount NUMERIC(18,8),
    price NUMERIC(8,4),
    tx_hash TEXT NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,

    -- Metadata
    is_smart_wallet BOOLEAN DEFAULT false,
    is_external_leader BOOLEAN DEFAULT false,

    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Create indexes for performance
CREATE INDEX IF NOT EXISTS idx_tracked_user_timestamp ON tracked_leader_trades(user_address, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_tracked_timestamp ON tracked_leader_trades(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_tracked_market ON tracked_leader_trades(market_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_tracked_tx_hash ON tracked_leader_trades(tx_hash);
CREATE INDEX IF NOT EXISTS idx_tracked_smart_wallet ON tracked_leader_trades(is_smart_wallet) WHERE is_smart_wallet = true;
CREATE INDEX IF NOT EXISTS idx_tracked_external_leader ON tracked_leader_trades(is_external_leader) WHERE is_external_leader = true;

-- Add table comment
COMMENT ON TABLE tracked_leader_trades IS 'Filtered trades from subsquid_user_transactions for watched addresses (smart wallets + external leaders) - FULL HISTORY retained';

-- Add column comments
COMMENT ON COLUMN tracked_leader_trades.tx_id IS 'Unique transaction ID from indexer-ts';
COMMENT ON COLUMN tracked_leader_trades.user_address IS 'Blockchain wallet address';
COMMENT ON COLUMN tracked_leader_trades.outcome IS '0=NO, 1=YES';
COMMENT ON COLUMN tracked_leader_trades.tx_type IS 'BUY or SELL';
COMMENT ON COLUMN tracked_leader_trades.is_smart_wallet IS 'True if user_address is in smart_wallets table';
COMMENT ON COLUMN tracked_leader_trades.is_external_leader IS 'True if user_address is in external_leaders table';

-- ============================================================================
-- Cleanup Policy for subsquid_user_transactions
-- Delete old records (2 days + 1h overlap for filter job safety)
-- ============================================================================

CREATE OR REPLACE FUNCTION cleanup_subsquid_user_transactions()
RETURNS void AS $$
BEGIN
    DELETE FROM subsquid_user_transactions
    WHERE timestamp < NOW() - INTERVAL '2 days 1 hour';
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION cleanup_subsquid_user_transactions() IS 'Cleanup old subsquid_user_transactions - retention: 2 days + 1h overlap';

-- ============================================================================
-- Status message
-- ============================================================================

DO $$
BEGIN
    RAISE NOTICE '✅ Phase 1 Migration Complete: tracked_leader_trades table created with indexes and cleanup policy';
END $$;
