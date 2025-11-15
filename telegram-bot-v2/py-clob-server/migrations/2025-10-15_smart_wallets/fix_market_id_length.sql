-- Fix column lengths for smart_wallet_trades
-- Increase from VARCHAR(50) to VARCHAR(100) to accommodate Ethereum hashes
-- Increase outcome from VARCHAR(10) to VARCHAR(50) for team names

ALTER TABLE smart_wallet_trades
ALTER COLUMN market_id TYPE VARCHAR(100);

-- Also fix the id column to accommodate transaction hashes (66 chars)
ALTER TABLE smart_wallet_trades
ALTER COLUMN id TYPE VARCHAR(100);

-- Fix outcome column for long team names (e.g., "Florida International")
ALTER TABLE smart_wallet_trades
ALTER COLUMN outcome TYPE VARCHAR(50);
