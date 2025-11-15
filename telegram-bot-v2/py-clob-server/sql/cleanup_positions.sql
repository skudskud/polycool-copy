-- PHASE 1: EMERGENCY CLEANUP - WIPE POSITIONS TABLE
-- This removes all stale position data that doesn't match blockchain reality

-- First, let's see what we're about to delete (for logging)
SELECT 'POSITIONS TO DELETE:' AS info;
SELECT 
    COUNT(*) as total_positions,
    COUNT(DISTINCT user_id) as affected_users
FROM positions 
WHERE is_active = true;

-- Show sample of positions being deleted
SELECT 'SAMPLE POSITIONS:' AS info;
SELECT 
    user_id,
    market_id,
    outcome,
    tokens,
    buy_price,
    created_at
FROM positions 
WHERE is_active = true 
ORDER BY created_at DESC 
LIMIT 10;

-- NUCLEAR OPTION: Delete all positions
-- This is safe because we're rebuilding from blockchain truth
TRUNCATE TABLE positions RESTART IDENTITY CASCADE;

-- Verify cleanup
SELECT 'CLEANUP VERIFICATION:' AS info;
SELECT COUNT(*) as remaining_positions FROM positions;

-- Log the cleanup
INSERT INTO positions_cleanup_log (
    cleanup_date,
    positions_deleted,
    reason,
    performed_by
) VALUES (
    NOW(),
    (SELECT COUNT(*) FROM positions WHERE is_active = true),
    'Architecture overhaul - switching to blockchain-based positions',
    'automated_cleanup'
);

SELECT 'CLEANUP COMPLETE!' AS status;
