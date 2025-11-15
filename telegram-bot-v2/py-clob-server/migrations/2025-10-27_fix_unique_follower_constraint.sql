-- Fix 1: Replace UNIQUE constraint with partial unique index
-- This allows multiple CANCELLED subscriptions but only ONE ACTIVE subscription per follower

-- Drop the old constraint
ALTER TABLE copy_trading_subscriptions
DROP CONSTRAINT IF EXISTS unique_follower_one_leader;

-- Create partial unique index (only for ACTIVE subscriptions)
CREATE UNIQUE INDEX IF NOT EXISTS unique_active_follower_subscription
ON copy_trading_subscriptions(follower_id)
WHERE status = 'ACTIVE';

-- Verify the change
SELECT
    indexname,
    indexdef
FROM pg_indexes
WHERE tablename = 'copy_trading_subscriptions'
    AND indexname = 'unique_active_follower_subscription';
