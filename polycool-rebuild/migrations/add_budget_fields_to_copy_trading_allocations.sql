-- =================================================
-- MIGRATION: Add Budget Fields to Copy Trading Allocations
-- Date: November 9, 2025
-- Description: Add sophisticated budget management fields to match old system logic
-- Based on old copy_trading_budgets table structure
-- =================================================

-- Add budget management fields to copy_trading_allocations table
-- These fields implement the real-time budget calculation logic from the old system

ALTER TABLE copy_trading_allocations
ADD COLUMN allocation_percentage NUMERIC(5,2) DEFAULT 50.0,
ADD COLUMN total_wallet_balance NUMERIC(20,2) DEFAULT 0,
ADD COLUMN allocated_budget NUMERIC(20,2) DEFAULT 0,
ADD COLUMN budget_remaining NUMERIC(20,2) DEFAULT 0,
ADD COLUMN last_wallet_sync TIMESTAMP WITHOUT TIME ZONE;

-- Add comments to explain the budget logic
COMMENT ON COLUMN copy_trading_allocations.allocation_percentage IS 'Percentage of wallet allocated for copy trading (5-100)';
COMMENT ON COLUMN copy_trading_allocations.total_wallet_balance IS 'Current USDC balance from wallet (refreshed regularly)';
COMMENT ON COLUMN copy_trading_allocations.allocated_budget IS 'Calculated as: total_wallet_balance * (allocation_percentage/100)';
COMMENT ON COLUMN copy_trading_allocations.budget_remaining IS 'Available budget for copy trading (always = allocated_budget in new logic)';
COMMENT ON COLUMN copy_trading_allocations.last_wallet_sync IS 'Timestamp of last wallet balance sync';

-- Add constraints
ALTER TABLE copy_trading_allocations
ADD CONSTRAINT check_allocation_percentage_range
    CHECK (allocation_percentage >= 5.0 AND allocation_percentage <= 100.0),
ADD CONSTRAINT check_total_wallet_balance_positive
    CHECK (total_wallet_balance >= 0),
ADD CONSTRAINT check_allocated_budget_positive
    CHECK (allocated_budget >= 0),
ADD CONSTRAINT check_budget_remaining_positive
    CHECK (budget_remaining >= 0);

-- Create index for efficient budget queries
CREATE INDEX idx_copy_trading_allocations_budget_sync
ON copy_trading_allocations(last_wallet_sync)
WHERE last_wallet_sync IS NOT NULL;

-- Update existing records with default values
-- Set allocation_percentage based on existing allocation_value if it's a percentage
UPDATE copy_trading_allocations
SET allocation_percentage = CASE
    WHEN allocation_type = 'percentage' AND allocation_value BETWEEN 5 AND 100
    THEN allocation_value
    ELSE 50.0  -- Default
END,
budget_remaining = 0,  -- Will be calculated from wallet balance
last_wallet_sync = NOW();

-- =================================================
-- VERIFICATION QUERIES
-- =================================================

-- Check that all required columns were added
-- SELECT column_name, data_type, is_nullable, column_default
-- FROM information_schema.columns
-- WHERE table_name = 'copy_trading_allocations'
-- AND column_name IN ('allocation_percentage', 'total_wallet_balance', 'allocated_budget', 'budget_remaining', 'last_wallet_sync')
-- ORDER BY column_name;

-- Check constraints were added
-- SELECT conname, contype, conkey, confrelid, conrelid
-- FROM pg_constraint
-- WHERE conrelid = 'copy_trading_allocations'::regclass
-- AND conname LIKE '%allocation%' OR conname LIKE '%budget%' OR conname LIKE '%wallet%';

-- Check existing data was migrated
-- SELECT id, allocation_type, allocation_value, allocation_percentage, budget_remaining
-- FROM copy_trading_allocations
-- LIMIT 10;
