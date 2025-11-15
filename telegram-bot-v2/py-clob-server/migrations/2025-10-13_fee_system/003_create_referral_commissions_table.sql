-- ============================================================================
-- REFERRAL COMMISSIONS TABLE MIGRATION
-- Created: 2025-10-13
-- Purpose: Individual commission records for each referrer in the chain
-- ============================================================================

-- Create referral_commissions table
CREATE TABLE IF NOT EXISTS referral_commissions (
    id SERIAL PRIMARY KEY,
    fee_id INTEGER NOT NULL REFERENCES fees(id) ON DELETE CASCADE,
    referrer_user_id BIGINT NOT NULL REFERENCES users(telegram_user_id) ON DELETE CASCADE,
    referred_user_id BIGINT NOT NULL REFERENCES users(telegram_user_id) ON DELETE CASCADE,

    -- Commission details
    level INTEGER NOT NULL CHECK (level IN (1, 2, 3)),
    commission_percentage NUMERIC(5, 2) NOT NULL,
    commission_amount NUMERIC(20, 2) NOT NULL,

    -- Payment tracking
    status VARCHAR(20) DEFAULT 'pending',  -- pending/paid/failed
    paid_at TIMESTAMP,
    payment_transaction_hash TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Create indexes for efficient queries
CREATE INDEX idx_commissions_referrer ON referral_commissions(referrer_user_id, created_at DESC);
CREATE INDEX idx_commissions_fee ON referral_commissions(fee_id);

-- Add comments for documentation
COMMENT ON TABLE referral_commissions IS 'Individual commission records for each referrer in the chain';
COMMENT ON COLUMN referral_commissions.level IS 'Referral level: 1=25%, 2=5%, 3=3%';
COMMENT ON COLUMN referral_commissions.commission_percentage IS 'Commission rate applied';
COMMENT ON COLUMN referral_commissions.commission_amount IS 'Commission amount in USDC';
COMMENT ON COLUMN referral_commissions.status IS 'Payment status: pending/paid/failed';

-- Verification query
SELECT 'Referral commissions table created successfully' AS status;
