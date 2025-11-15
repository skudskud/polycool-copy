-- Twitter Bot Migration
-- Adds tweeted_at column to track which trades have been posted to Twitter

-- Add column to smart_wallet_trades table
ALTER TABLE smart_wallet_trades 
ADD COLUMN IF NOT EXISTS tweeted_at TIMESTAMP DEFAULT NULL;

-- Add index for efficient querying of untweeted trades
CREATE INDEX IF NOT EXISTS idx_tweeted_at 
ON smart_wallet_trades(tweeted_at) 
WHERE tweeted_at IS NULL;

-- Composite index for the main query used by Twitter bot
-- This optimizes the query: WHERE is_first_time = true AND side = 'BUY' AND value >= X AND tweeted_at IS NULL
CREATE INDEX IF NOT EXISTS idx_untweeted_qualifying_trades
ON smart_wallet_trades(is_first_time, side, value, tweeted_at, timestamp)
WHERE is_first_time = true AND side = 'BUY' AND tweeted_at IS NULL;

-- Log completion
DO $$
BEGIN
    RAISE NOTICE '✅ Twitter bot migration completed: tweeted_at column and indexes added';
END $$;

