-- Migration: Add tokens field to markets table
-- Date: 2025-10-27
-- Purpose: Store tokens array from Gamma API for outcome-based token matching (fixes token lookup bug)

ALTER TABLE markets
ADD COLUMN tokens JSONB;

-- Create index for queries
CREATE INDEX idx_markets_tokens ON markets USING GIN (tokens);

-- Log the migration
SELECT 'Migration complete: Added tokens column to markets table' AS status;
