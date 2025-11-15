-- ============================================================================
-- REFERRALS TABLE MIGRATION
-- Created: 2025-10-13
-- Purpose: 3-tier referral system for commission tracking
-- ============================================================================

-- Create referrals table
CREATE TABLE IF NOT EXISTS referrals (
    id SERIAL PRIMARY KEY,
    referrer_user_id BIGINT NOT NULL REFERENCES users(telegram_user_id) ON DELETE CASCADE,
    referred_user_id BIGINT NOT NULL REFERENCES users(telegram_user_id) ON DELETE CASCADE,
    level INTEGER NOT NULL CHECK (level IN (1, 2, 3)),
    created_at TIMESTAMP DEFAULT NOW(),

    -- Ensure each user can only be referred once
    UNIQUE(referred_user_id),

    -- Foreign key constraints
    CONSTRAINT fk_referrer FOREIGN KEY (referrer_user_id) REFERENCES users(telegram_user_id),
    CONSTRAINT fk_referred FOREIGN KEY (referred_user_id) REFERENCES users(telegram_user_id)
);

-- Create indexes for efficient queries
CREATE INDEX idx_referrals_referrer ON referrals(referrer_user_id);
CREATE INDEX idx_referrals_referred ON referrals(referred_user_id);

-- Add comments for documentation
COMMENT ON TABLE referrals IS '3-tier referral system for commission tracking';
COMMENT ON COLUMN referrals.level IS 'Referral level: 1=direct (25%), 2=indirect (5%), 3=extended (3%)';
COMMENT ON COLUMN referrals.referrer_user_id IS 'User who referred someone';
COMMENT ON COLUMN referrals.referred_user_id IS 'User who was referred (can only be referred once)';

-- Verification query
SELECT 'Referrals table created successfully' AS status;
