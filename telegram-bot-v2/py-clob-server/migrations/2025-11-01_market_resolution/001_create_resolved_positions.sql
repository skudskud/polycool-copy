-- MARKET RESOLUTION SYSTEM - Database Schema
-- Created: 2025-11-01

CREATE TABLE IF NOT EXISTS resolved_positions (
    id SERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(telegram_user_id) ON DELETE CASCADE,
    market_id TEXT NOT NULL,
    condition_id TEXT NOT NULL,
    market_title TEXT NOT NULL,
    market_slug TEXT,
    market_end_date TIMESTAMP,
    outcome TEXT NOT NULL CHECK (outcome IN ('YES', 'NO')),
    token_id TEXT NOT NULL,
    tokens_held NUMERIC(20, 8) NOT NULL CHECK (tokens_held > 0),
    total_cost NUMERIC(20, 8) NOT NULL,
    avg_buy_price NUMERIC(10, 8) NOT NULL,
    transaction_count INT NOT NULL DEFAULT 0,
    winning_outcome TEXT NOT NULL CHECK (winning_outcome IN ('YES', 'NO', 'INVALID')),
    is_winner BOOLEAN NOT NULL,
    resolved_at TIMESTAMP NOT NULL,
    gross_value NUMERIC(20, 8) NOT NULL DEFAULT 0,
    fee_percentage NUMERIC(5, 2) NOT NULL DEFAULT 1.00,
    fee_amount NUMERIC(20, 8) NOT NULL DEFAULT 0,
    net_value NUMERIC(20, 8) NOT NULL DEFAULT 0,
    pnl NUMERIC(20, 8) NOT NULL,
    pnl_percentage NUMERIC(10, 2) NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING', 'PROCESSING', 'REDEEMED', 'FAILED', 'EXPIRED')),
    redemption_tx_hash TEXT,
    redemption_block_number BIGINT,
    redemption_gas_used BIGINT,
    redemption_gas_price BIGINT,
    redemption_attempt_count INT DEFAULT 0,
    last_redemption_error TEXT,
    fee_collected BOOLEAN DEFAULT FALSE,
    fee_tx_hash TEXT,
    fee_collected_at TIMESTAMP,
    notified BOOLEAN DEFAULT FALSE,
    notification_sent_at TIMESTAMP,
    redemption_notified BOOLEAN DEFAULT FALSE,
    redemption_notification_sent_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    processing_started_at TIMESTAMP,
    redeemed_at TIMESTAMP,
    expires_at TIMESTAMP,
    referrer_level1_id BIGINT,
    referrer_level2_id BIGINT,
    referrer_level3_id BIGINT,
    CONSTRAINT unique_user_market_outcome UNIQUE(user_id, market_id, outcome)
);

CREATE INDEX idx_resolved_positions_user_status ON resolved_positions(user_id, status);
CREATE INDEX idx_resolved_positions_status_winner ON resolved_positions(status, is_winner) WHERE status = 'PENDING';
CREATE INDEX idx_resolved_positions_expires ON resolved_positions(expires_at) WHERE expires_at IS NOT NULL;
CREATE INDEX idx_resolved_positions_market ON resolved_positions(market_id);
CREATE INDEX idx_resolved_positions_resolved_at ON resolved_positions(resolved_at DESC);

CREATE OR REPLACE FUNCTION update_resolved_positions_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_update_resolved_positions_timestamp
    BEFORE UPDATE ON resolved_positions
    FOR EACH ROW
    EXECUTE FUNCTION update_resolved_positions_updated_at();

