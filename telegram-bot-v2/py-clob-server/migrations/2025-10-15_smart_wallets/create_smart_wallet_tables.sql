-- Smart Wallet Tables Migration
-- Creates tables for tracking smart trader wallets and their trades

-- Create smart_wallets table
CREATE TABLE IF NOT EXISTS smart_wallets (
    address VARCHAR(42) PRIMARY KEY,
    smartscore NUMERIC(20, 10),
    win_rate NUMERIC(10, 8),
    markets_count INTEGER,
    realized_pnl NUMERIC(20, 2),
    bucket_smart VARCHAR(50),
    bucket_last_date VARCHAR(50),
    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create smart_wallet_trades table
CREATE TABLE IF NOT EXISTS smart_wallet_trades (
    id VARCHAR(100) PRIMARY KEY,  -- transactionHash (66 chars)
    wallet_address VARCHAR(42) NOT NULL,
    market_id VARCHAR(100) NOT NULL,  -- conditionId (66 chars)
    side VARCHAR(10) NOT NULL,
    outcome VARCHAR(50),  -- Outcome name (team names can be long)
    price NUMERIC(20, 10) NOT NULL,
    size NUMERIC(20, 10) NOT NULL,
    value NUMERIC(20, 2) NOT NULL,
    timestamp TIMESTAMP NOT NULL,
    is_first_time BOOLEAN DEFAULT FALSE,
    market_question TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes for smart_wallet_trades
CREATE INDEX IF NOT EXISTS idx_smart_trades_wallet ON smart_wallet_trades(wallet_address);
CREATE INDEX IF NOT EXISTS idx_smart_trades_market ON smart_wallet_trades(market_id);
CREATE INDEX IF NOT EXISTS idx_smart_trades_timestamp ON smart_wallet_trades(timestamp);
CREATE INDEX IF NOT EXISTS idx_smart_trades_wallet_timestamp ON smart_wallet_trades(wallet_address, timestamp);
CREATE INDEX IF NOT EXISTS idx_smart_trades_first_time_value ON smart_wallet_trades(is_first_time, value);

-- Add foreign key constraint (optional, for data integrity)
-- ALTER TABLE smart_wallet_trades
-- ADD CONSTRAINT fk_wallet_address
-- FOREIGN KEY (wallet_address) REFERENCES smart_wallets(address) ON DELETE CASCADE;
