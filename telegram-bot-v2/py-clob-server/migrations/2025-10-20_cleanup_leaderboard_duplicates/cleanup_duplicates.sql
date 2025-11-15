-- Cleanup Leaderboard Duplicates
-- Removes duplicate leaderboard entries that were created during refresh operations
-- Keeps only the most recent entry for each user/period/week combination

BEGIN;

-- Step 1: Delete duplicates, keeping only the most recent (highest calculated_at)
DELETE FROM leaderboard_entries
WHERE id NOT IN (
    SELECT DISTINCT ON (user_id, period, week_start_date) id
    FROM leaderboard_entries
    ORDER BY user_id, period, week_start_date, calculated_at DESC NULLS LAST
);

-- Step 2: Verify final state
SELECT period, COUNT(*) as total_entries, COUNT(DISTINCT user_id) as unique_users
FROM leaderboard_entries
GROUP BY period
ORDER BY period;

COMMIT;
