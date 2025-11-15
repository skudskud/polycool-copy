-- Migration: Expand resolution_source column to handle long URLs
-- Date: 2025-10-07
-- Issue: resolution_source VARCHAR(100) is too short for some URLs
-- Solution: Change to TEXT for unlimited length

BEGIN;

-- Expand resolution_source column from VARCHAR(100) to TEXT
ALTER TABLE markets 
ALTER COLUMN resolution_source TYPE TEXT;

-- Verify the change
SELECT 
    column_name, 
    data_type, 
    character_maximum_length
FROM information_schema.columns 
WHERE table_name = 'markets' 
  AND column_name = 'resolution_source';

COMMIT;

-- ✅ Migration complete!
-- This allows resolution_source to store URLs of any length.
-- No data loss, backward compatible change.

