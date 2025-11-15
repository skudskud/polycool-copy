-- Migration: Add Events API support to markets table
-- Date: 2025-10-14 (v2)
-- Purpose: Replace market_group with event_id for Polymarket Events API

-- Add new event columns
ALTER TABLE markets
ADD COLUMN IF NOT EXISTS event_id VARCHAR(50),
ADD COLUMN IF NOT EXISTS event_slug VARCHAR(200),
ADD COLUMN IF NOT EXISTS event_title VARCHAR(500);

-- Create index for efficient event queries
CREATE INDEX IF NOT EXISTS idx_markets_event ON markets(event_id, active);

-- Verify columns were added
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_name = 'markets'
AND column_name IN ('event_id', 'event_slug', 'event_title')
ORDER BY column_name;

-- Check existing event data
SELECT
    COUNT(*) as total_markets,
    COUNT(event_id) as markets_with_event,
    COUNT(DISTINCT event_id) as unique_events
FROM markets
WHERE active = true;
