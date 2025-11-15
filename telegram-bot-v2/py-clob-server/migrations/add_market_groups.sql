-- Migration: Add market_group columns to markets table
-- Date: 2025-10-14
-- Purpose: Enable grouping of multi-outcome markets (Win/Draw/Win)

-- Add new columns
ALTER TABLE markets
ADD COLUMN IF NOT EXISTS market_group INTEGER,
ADD COLUMN IF NOT EXISTS group_item_title VARCHAR(100),
ADD COLUMN IF NOT EXISTS group_item_threshold VARCHAR(50),
ADD COLUMN IF NOT EXISTS group_item_range VARCHAR(50);

-- Create index for efficient querying of market groups
CREATE INDEX IF NOT EXISTS idx_markets_group ON markets(market_group, active);

-- Verify columns were added
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_name = 'markets'
AND column_name IN ('market_group', 'group_item_title', 'group_item_threshold', 'group_item_range')
ORDER BY column_name;
