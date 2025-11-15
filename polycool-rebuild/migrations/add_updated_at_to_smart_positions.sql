-- Migration: Add updated_at column to smart_traders_positions table
-- Date: November 10, 2025
-- Description: Add updated_at column used by SmartWalletPositionTracker

-- Add updated_at column to smart_traders_positions table
ALTER TABLE smart_traders_positions
ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP;

-- Add comment
COMMENT ON COLUMN smart_traders_positions.updated_at IS 'Last update timestamp for position tracking';
