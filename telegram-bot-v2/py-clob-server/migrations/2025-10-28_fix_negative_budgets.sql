-- Migration: Fix Negative Budget Remaining
-- Date: 2025-10-28
-- Description:
--   With the new balance-based budget logic, budget_remaining should equal allocated_budget
--   This migration:
--   1. Removes the old constraint that enforced budget_remaining = allocated_budget - budget_used
--   2. Fixes any negative budget_remaining values
--   3. Adds a new constraint to prevent negative budget_remaining

-- Step 1: Remove old incompatible constraint
ALTER TABLE copy_trading_budgets
DROP CONSTRAINT IF EXISTS budget_remaining_consistent;

-- Step 2: Fix all budgets with negative remaining
UPDATE copy_trading_budgets
SET
    budget_used = 0.00,  -- Reset to 0 (no longer tracked)
    budget_remaining = GREATEST(0, allocated_budget),  -- Never allow negative
    updated_at = NOW()
WHERE budget_remaining < 0;

-- Log the number of fixed budgets
DO $$
DECLARE
    fixed_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO fixed_count
    FROM copy_trading_budgets
    WHERE budget_remaining < 0;

    IF fixed_count > 0 THEN
        RAISE NOTICE '✅ Fixed % budgets with negative remaining', fixed_count;
    ELSE
        RAISE NOTICE '✅ No budgets needed fixing';
    END IF;
END $$;

-- Step 3: Add a CHECK constraint to prevent negative budget_remaining in the future
ALTER TABLE copy_trading_budgets
DROP CONSTRAINT IF EXISTS chk_budget_remaining_non_negative;

ALTER TABLE copy_trading_budgets
ADD CONSTRAINT chk_budget_remaining_non_negative
CHECK (budget_remaining >= 0);

-- Add comment explaining the new logic
COMMENT ON COLUMN copy_trading_budgets.budget_remaining IS
'Budget remaining for copy trading. With balance-based logic, this equals allocated_budget (wallet_balance × allocation_percentage). Never negative.';

COMMENT ON COLUMN copy_trading_budgets.budget_used IS
'Legacy field, no longer actively tracked. Budget is now calculated from current wallet balance.';
