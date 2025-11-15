-- Fix Copy Trading History Constraint
-- Date: 2025-10-27
--
-- PROBLEM: When a trade is skipped due to insufficient budget,
--          the code inserts with calculated_copy_amount=0,
--          but the constraint required > 0
--
-- SOLUTION: Allow calculated_copy_amount >= 0 (0 = skipped trade)

-- Drop old constraint (calculated_copy_amount > 0)
ALTER TABLE copy_trading_history
DROP CONSTRAINT IF EXISTS copy_amount_positive;

-- Add new constraint (calculated_copy_amount >= 0)
-- 0 means trade was skipped (insufficient budget, below minimum, etc.)
ALTER TABLE copy_trading_history
ADD CONSTRAINT copy_amount_positive CHECK (calculated_copy_amount >= 0);

-- Also fix actual_copy_amount constraint
ALTER TABLE copy_trading_history
DROP CONSTRAINT IF EXISTS actual_amount_positive;

ALTER TABLE copy_trading_history
ADD CONSTRAINT actual_amount_positive CHECK (actual_copy_amount IS NULL OR actual_copy_amount >= 0);

-- Comment for clarity
COMMENT ON COLUMN copy_trading_history.calculated_copy_amount IS
'Calculated copy amount (can be 0 if trade was skipped due to insufficient budget or below minimum)';
