-- =================================================
-- MIGRATION: Add position_id to positions table
-- Date: November 14, 2025
-- Description: Add position_id (clob_token_id) to positions table for precise position lookup
--              This simplifies copy trading by using position_id as primary identifier
-- =================================================

-- Add position_id column to positions table
ALTER TABLE positions
ADD COLUMN position_id VARCHAR(100);

-- Add comment explaining the column
COMMENT ON COLUMN positions.position_id IS 'Token ID from blockchain (clob_token_id) - for precise position lookup. Enables direct market resolution via clob_token_ids in markets table.';

-- Create index for fast position_id lookups
CREATE INDEX idx_positions_position_id ON positions(position_id);

-- Create composite index for active positions (most common query pattern)
CREATE INDEX idx_positions_user_position_id_active ON positions(user_id, position_id)
WHERE status = 'active';

-- =================================================
-- VERIFICATION QUERIES
-- =================================================

-- Check column was added
-- SELECT column_name, data_type, is_nullable, column_default
-- FROM information_schema.columns
-- WHERE table_name = 'positions'
-- AND column_name = 'position_id';

-- Check indexes were created
-- SELECT indexname, indexdef
-- FROM pg_indexes
-- WHERE tablename = 'positions'
-- AND indexname LIKE '%position_id%';
