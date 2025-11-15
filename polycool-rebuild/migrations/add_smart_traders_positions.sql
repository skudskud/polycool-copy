-- Add smart traders positions table
-- Migration: add_smart_traders_positions.sql

CREATE TABLE IF NOT EXISTS smart_traders_positions (
    id SERIAL PRIMARY KEY,
    market_id VARCHAR(100) NOT NULL,
    smart_wallet_address VARCHAR(100) NOT NULL,
    outcome VARCHAR(100) NOT NULL,
    entry_price DECIMAL(8,4) NOT NULL,
    size DECIMAL(18,8) NOT NULL,
    amount_usdc DECIMAL(18,6) NOT NULL,
    timestamp TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    is_active BOOLEAN DEFAULT TRUE,

    -- Indexes for performance
    INDEX idx_smart_positions_market (market_id),
    INDEX idx_smart_positions_wallet (smart_wallet_address),
    INDEX idx_smart_positions_timestamp (timestamp DESC),
    INDEX idx_smart_positions_active (is_active, timestamp DESC),
    INDEX idx_smart_positions_wallet_market (smart_wallet_address, market_id, outcome)
);

-- Add comment
COMMENT ON TABLE smart_traders_positions IS 'Positions held by smart trading wallets for recommendation system';
