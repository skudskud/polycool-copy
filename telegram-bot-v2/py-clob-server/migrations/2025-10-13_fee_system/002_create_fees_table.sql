-- ============================================================================
-- FEES TABLE MIGRATION
-- Created: 2025-10-13
-- Purpose: Track all trading fee collections and referral commission distribution
-- ============================================================================

-- Create fees table
CREATE TABLE IF NOT EXISTS fees (
    id SERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(telegram_user_id) ON DELETE CASCADE,
    transaction_id INTEGER REFERENCES transactions(id) ON DELETE SET NULL,

    -- Fee calculation details
    trade_amount NUMERIC(20, 2) NOT NULL,
    fee_percentage NUMERIC(5, 2) NOT NULL,
    fee_amount NUMERIC(20, 2) NOT NULL,
    minimum_fee_applied BOOLEAN DEFAULT FALSE,

    -- Commission breakdown
    total_commission_paid NUMERIC(20, 2) DEFAULT 0,
    level1_commission NUMERIC(20, 2) DEFAULT 0,
    level2_commission NUMERIC(20, 2) DEFAULT 0,
    level3_commission NUMERIC(20, 2) DEFAULT 0,

    -- Blockchain tracking
    fee_transaction_hash TEXT,
    trade_transaction_hash TEXT,

    -- Status tracking
    status VARCHAR(20) DEFAULT 'pending',  -- pending/collected/failed
    created_at TIMESTAMP DEFAULT NOW(),
    collected_at TIMESTAMP,
    failed_at TIMESTAMP,
    error_message TEXT
);

-- Create indexes for efficient queries
CREATE INDEX idx_fees_user ON fees(user_id, created_at DESC);
CREATE INDEX idx_fees_status ON fees(status);
CREATE INDEX idx_fees_created ON fees(created_at DESC);
CREATE INDEX idx_fees_transaction ON fees(transaction_id);

-- Add comments for documentation
COMMENT ON TABLE fees IS 'Tracks all fee collections and referral commissions';
COMMENT ON COLUMN fees.trade_amount IS 'Original trade amount in USD before fee';
COMMENT ON COLUMN fees.fee_percentage IS 'Applied fee percentage (typically 1.00%)';
COMMENT ON COLUMN fees.fee_amount IS 'Actual fee collected in USDC';
COMMENT ON COLUMN fees.minimum_fee_applied IS 'True if $0.20 minimum was applied';
COMMENT ON COLUMN fees.status IS 'Collection status: pending/collected/failed';

-- Verification query
SELECT 'Fees table created successfully' AS status;
