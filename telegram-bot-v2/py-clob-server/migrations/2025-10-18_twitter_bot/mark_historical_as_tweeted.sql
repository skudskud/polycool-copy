-- Mark all existing trades as already tweeted
-- This prevents the bot from tweeting historical trades on first run
-- Only new trades (inserted after this migration) will be tweeted

UPDATE smart_wallet_trades 
SET tweeted_at = NOW() 
WHERE tweeted_at IS NULL;

-- Log result
DO $$
DECLARE
    updated_count INTEGER;
BEGIN
    GET DIAGNOSTICS updated_count = ROW_COUNT;
    RAISE NOTICE '✅ Marked % existing trades as already tweeted (prevents historical backfill)', updated_count;
END $$;

