-- =================================================
-- MIGRATION: Add is_copy_trade flag to positions
-- Date: November 9, 2025
-- Description: Add flag to differentiate copy trading positions from manual trades
-- =================================================

-- Add is_copy_trade column to positions table
ALTER TABLE positions
ADD COLUMN is_copy_trade BOOLEAN DEFAULT FALSE;

-- Add index for efficient queries
CREATE INDEX idx_positions_is_copy_trade ON positions(is_copy_trade);

-- Add comment explaining the column
COMMENT ON COLUMN positions.is_copy_trade IS 'True if position was created via copy trading, False for manual trades';

-- =================================================
-- VERIFICATION QUERIES
-- =================================================

-- Check column was added
-- SELECT column_name, data_type, is_nullable, column_default
-- FROM information_schema.columns
-- WHERE table_name = 'positions'
-- AND column_name = 'is_copy_trade';

-- Check index was created
-- SELECT indexname, indexdef
-- FROM pg_indexes
-- WHERE tablename = 'positions'
-- AND indexname = 'idx_positions_is_copy_trade';
