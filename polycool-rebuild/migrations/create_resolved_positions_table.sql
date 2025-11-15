-- =================================================
-- MIGRATION: Create resolved_positions table
-- Date: January 2025
-- Description: Table to track positions that are redeemable after market resolution
--              Stores positions in RESOLVED markets with winning tokens
-- =================================================

CREATE TABLE resolved_positions (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    market_id VARCHAR(100) NOT NULL REFERENCES markets(id) ON DELETE CASCADE,
    condition_id VARCHAR(100) NOT NULL, -- For matching with blockchain positions

    -- Position details
    position_id VARCHAR(100), -- clob_token_id from blockchain
    outcome VARCHAR(100) NOT NULL, -- 'YES' or 'NO'
    tokens_held NUMERIC(20, 6) NOT NULL, -- Quantity of tokens
    total_cost NUMERIC(20, 6) NOT NULL, -- Total entry cost
    avg_buy_price NUMERIC(20, 6) NOT NULL, -- Average buy price

    -- Market resolution
    market_title TEXT NOT NULL, -- Market title for display
    winning_outcome VARCHAR(100) NOT NULL, -- 'YES' or 'NO'
    is_winner BOOLEAN NOT NULL, -- True if user's outcome matches winning outcome
    resolved_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, -- When market was resolved

    -- Redemption value calculation
    gross_value NUMERIC(20, 6) NOT NULL DEFAULT 0, -- Value before fees (tokens * 1.0)
    fee_amount NUMERIC(20, 6) NOT NULL DEFAULT 0, -- Redemption fee (1%)
    net_value NUMERIC(20, 6) NOT NULL DEFAULT 0, -- Value after fees
    pnl NUMERIC(20, 6) NOT NULL DEFAULT 0, -- Profit/loss
    pnl_percentage NUMERIC(10, 2) NOT NULL DEFAULT 0, -- P&L percentage

    -- Redemption status
    status VARCHAR(20) NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING', 'PROCESSING', 'REDEEMED', 'FAILED')),
    notified BOOLEAN NOT NULL DEFAULT FALSE, -- If notification was sent

    -- Transaction details
    redemption_tx_hash VARCHAR(255),
    redemption_block_number INTEGER,
    redemption_gas_used INTEGER,
    redemption_gas_price NUMERIC(20, 6),
    redeemed_at TIMESTAMP WITHOUT TIME ZONE,

    -- Error handling
    last_redemption_error TEXT,
    redemption_attempt_count INTEGER NOT NULL DEFAULT 0,
    processing_started_at TIMESTAMP WITHOUT TIME ZONE,

    -- Timestamps
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
);

-- Indexes for performance
CREATE INDEX idx_resolved_positions_user_status ON resolved_positions(user_id, status);
CREATE INDEX idx_resolved_positions_condition_id ON resolved_positions(condition_id);
CREATE INDEX idx_resolved_positions_status ON resolved_positions(status);
CREATE INDEX idx_resolved_positions_market_id ON resolved_positions(market_id);
CREATE INDEX idx_resolved_positions_user_winner ON resolved_positions(user_id, is_winner) WHERE is_winner = true;

-- Comments
COMMENT ON TABLE resolved_positions IS 'Tracks positions that are redeemable after market resolution. Only winning positions (is_winner=true) can be redeemed.';
COMMENT ON COLUMN resolved_positions.condition_id IS 'Condition ID from blockchain - used for matching with positions from Polymarket API';
COMMENT ON COLUMN resolved_positions.position_id IS 'Token ID (clob_token_id) from blockchain - for precise position identification';
COMMENT ON COLUMN resolved_positions.status IS 'Redemption status: PENDING (ready to redeem), PROCESSING (tx sent), REDEEMED (completed), FAILED (error)';
COMMENT ON COLUMN resolved_positions.net_value IS 'Value user will receive after redemption fees (1% fee deducted from gross_value)';
COMMENT ON COLUMN resolved_positions.is_winner IS 'True if user outcome matches winning outcome - only winners can be redeemed';
