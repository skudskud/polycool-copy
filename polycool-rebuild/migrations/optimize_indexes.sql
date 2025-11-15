-- Migration: Optimize database indexes for performance
-- Date: December 2024
-- Description: Remove duplicate index and add missing FK index

-- =================================================
-- DUPLICATE INDEX FIX
-- =================================================

-- Issue: Table markets has identical indexes {idx_markets_condition_id, ix_markets_condition_id}
-- Action: Drop the duplicate index, keep ix_markets_condition_id

-- Check if duplicate index exists and drop it
DO $$
BEGIN
    -- Check if idx_markets_condition_id exists
    IF EXISTS (
        SELECT 1 FROM pg_indexes
        WHERE tablename = 'markets'
        AND indexname = 'idx_markets_condition_id'
    ) THEN
        -- Drop the duplicate index
        DROP INDEX IF EXISTS idx_markets_condition_id;
        RAISE NOTICE 'Dropped duplicate index idx_markets_condition_id on markets table';
    END IF;
END $$;

-- =================================================
-- MISSING FOREIGN KEY INDEX FIX
-- =================================================

-- Issue: copy_trading_allocations has FK copy_trading_allocations_leader_address_id_fkey without covering index
-- Action: Add index on leader_address_id column

-- Create index for foreign key if it doesn't exist
CREATE INDEX IF NOT EXISTS idx_copy_allocations_leader_fkey
    ON copy_trading_allocations(leader_address_id);

-- =================================================
-- UNUSED INDEXES CLEANUP (Optional)
-- =================================================

-- These indexes are unused according to Supabase Advisor
-- They can be safely dropped to reduce overhead
-- Uncomment if you want to apply cleanup:

-- DROP INDEX IF EXISTS idx_users_polygon_address;
-- DROP INDEX IF EXISTS idx_markets_category_active;
-- DROP INDEX IF EXISTS idx_markets_events_gin;
-- DROP INDEX IF EXISTS ix_positions_user_id;
-- DROP INDEX IF EXISTS idx_positions_user_market;
-- DROP INDEX IF EXISTS idx_positions_created;
-- DROP INDEX IF EXISTS idx_users_stage;
-- DROP INDEX IF EXISTS idx_users_solana_address;
-- DROP INDEX IF EXISTS idx_trades_tx_hash;
-- DROP INDEX IF EXISTS idx_trades_timestamp;
-- DROP INDEX IF EXISTS idx_trades_market_timestamp;
-- DROP INDEX IF EXISTS idx_trades_watched_address;
-- DROP INDEX IF EXISTS idx_copy_allocations_active;
-- DROP INDEX IF EXISTS idx_copy_allocations_user_leader;

-- =================================================
-- VERIFICATION QUERIES
-- =================================================

-- Query to verify duplicate index is gone:
-- SELECT indexname FROM pg_indexes WHERE tablename = 'markets' AND indexname LIKE '%condition_id%';

-- Query to verify FK index exists:
-- SELECT indexname FROM pg_indexes WHERE tablename = 'copy_trading_allocations' AND indexname = 'idx_copy_allocations_leader_fkey';

-- Query to check remaining unused indexes:
-- SELECT schemaname, tablename, indexname
-- FROM pg_indexes
-- WHERE schemaname = 'public'
-- AND indexname NOT IN (
--     SELECT conname || '_key' FROM pg_constraint WHERE contype = 'p'
--     UNION
--     SELECT conname || '_fkey' FROM pg_constraint WHERE contype = 'f'
-- );

COMMENT ON INDEX ix_markets_condition_id IS 'Index for condition_id lookups (kept after duplicate removal)';
COMMENT ON INDEX idx_copy_allocations_leader_fkey IS 'FK index for copy_trading_allocations.leader_address_id';
