-- ========================================
-- TESTING ONLY: Allow self-following for copy trading testing
-- ========================================
--
-- SIMPLE VERSION: Just drop the constraint without waiting for locks
--
-- ⚠️ Run this in Supabase SQL Editor
-- ⚠️ If it times out, the constraint might already be dropped OR
--    there's an active transaction - wait a moment and retry
-- ========================================

-- Method 1: Try to drop with NOWAIT (fails fast if locked)
DO $$
BEGIN
    ALTER TABLE copy_trading_subscriptions
    DROP CONSTRAINT IF EXISTS follower_not_leader;

    RAISE NOTICE 'Constraint dropped successfully';
EXCEPTION
    WHEN OTHERS THEN
        RAISE NOTICE 'Error or constraint already dropped: %', SQLERRM;
END $$;

-- Check if constraint still exists
SELECT
    CASE
        WHEN COUNT(*) = 0 THEN '✅ Constraint successfully dropped - self-following is now allowed'
        ELSE '❌ Constraint still exists - try again or contact support'
    END as status
FROM pg_constraint
WHERE conrelid = 'copy_trading_subscriptions'::regclass
AND conname = 'follower_not_leader';

-- ========================================
-- IF ABOVE DOESN'T WORK, TRY THIS SIMPLER VERSION:
-- ========================================
--
-- Just run these 2 lines separately:
--
-- 1. First line:
--    ALTER TABLE copy_trading_subscriptions DROP CONSTRAINT follower_not_leader;
--
-- 2. If error "constraint does not exist", it's already dropped! ✅
--
-- ========================================
