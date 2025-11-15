-- =================================================
-- REFERRAL SYSTEM & FEES MIGRATION
-- Date: December 2024
-- Description: Create tables for referral system (3-tier) and trade fees tracking
-- =================================================

-- =================================================
-- 1. TRADE FEES TABLE
-- =================================================

CREATE TABLE IF NOT EXISTS trade_fees (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    trade_id INTEGER,  -- Référence au trade (peut être NULL si trade externe)
    market_id VARCHAR(100),

    -- Fee details
    trade_amount NUMERIC(20, 6) NOT NULL,  -- Montant du trade en USDC
    fee_rate NUMERIC(5, 4) NOT NULL DEFAULT 0.01,  -- 1% = 0.01
    fee_amount NUMERIC(20, 6) NOT NULL,  -- Fee calculée (1% du trade)
    minimum_fee NUMERIC(20, 6) DEFAULT 0.1,  -- $0.1 minimum
    final_fee_amount NUMERIC(20, 6) NOT NULL,  -- Fee finale (max entre 1% et $0.1)

    -- Discount
    has_referral_discount BOOLEAN DEFAULT FALSE,
    discount_percentage NUMERIC(5, 2) DEFAULT 0.0,  -- 10% = 10.0
    discount_amount NUMERIC(20, 6) DEFAULT 0.0,
    final_fee_after_discount NUMERIC(20, 6) NOT NULL,  -- Fee après discount

    -- Trade type
    trade_type VARCHAR(10) NOT NULL,  -- 'BUY' or 'SELL'

    -- Status
    is_paid BOOLEAN DEFAULT FALSE,
    paid_at TIMESTAMP,

    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_trade_fees_user ON trade_fees(user_id);
CREATE INDEX IF NOT EXISTS idx_trade_fees_trade ON trade_fees(trade_id);
CREATE INDEX IF NOT EXISTS idx_trade_fees_created ON trade_fees(created_at);
CREATE INDEX IF NOT EXISTS idx_trade_fees_market ON trade_fees(market_id);

-- =================================================
-- 2. REFERRALS TABLE (3-tier system)
-- =================================================

CREATE TABLE IF NOT EXISTS referrals (
    id SERIAL PRIMARY KEY,
    referrer_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    referred_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    level INTEGER NOT NULL CHECK (level IN (1, 2, 3)),
    created_at TIMESTAMP DEFAULT NOW(),

    -- Un user ne peut être référé qu'une fois (UNIQUE sur referred_user_id)
    CONSTRAINT unique_referred_user UNIQUE(referred_user_id)
);

CREATE INDEX IF NOT EXISTS idx_referrals_referrer ON referrals(referrer_user_id);
CREATE INDEX IF NOT EXISTS idx_referrals_referred ON referrals(referred_user_id);
CREATE INDEX IF NOT EXISTS idx_referrals_level ON referrals(level);
CREATE INDEX IF NOT EXISTS idx_referrals_referrer_level ON referrals(referrer_user_id, level);

-- =================================================
-- 3. REFERRAL COMMISSIONS TABLE
-- =================================================

CREATE TABLE IF NOT EXISTS referral_commissions (
    id SERIAL PRIMARY KEY,
    referral_id INTEGER REFERENCES referrals(id) ON DELETE CASCADE,
    referrer_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    referred_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    level INTEGER NOT NULL CHECK (level IN (1, 2, 3)),

    -- Commission details
    trade_fee_id INTEGER REFERENCES trade_fees(id) ON DELETE CASCADE,
    fee_amount NUMERIC(20, 6) NOT NULL,  -- Fee générée par le trade
    commission_rate NUMERIC(5, 2) NOT NULL,  -- 25.00, 5.00, 3.00
    commission_amount NUMERIC(20, 6) NOT NULL,  -- Commission calculée

    -- Status
    status VARCHAR(20) NOT NULL DEFAULT 'pending',  -- 'pending', 'paid', 'claimed'
    paid_at TIMESTAMP,
    claim_tx_hash VARCHAR(100),

    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_commissions_referrer ON referral_commissions(referrer_user_id, status);
CREATE INDEX IF NOT EXISTS idx_commissions_referred ON referral_commissions(referred_user_id);
CREATE INDEX IF NOT EXISTS idx_commissions_status ON referral_commissions(status);
CREATE INDEX IF NOT EXISTS idx_commissions_trade_fee ON referral_commissions(trade_fee_id);
CREATE INDEX IF NOT EXISTS idx_commissions_level ON referral_commissions(level);

-- =================================================
-- 4. ADD COLUMNS TO USERS TABLE
-- =================================================

-- Add fees_enabled column (toggle fees on/off per user)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'users' AND column_name = 'fees_enabled'
    ) THEN
        ALTER TABLE users ADD COLUMN fees_enabled BOOLEAN DEFAULT TRUE;
        RAISE NOTICE 'Added fees_enabled column to users table';
    END IF;
END $$;

-- Add referral_code column (unique code for referral link)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'users' AND column_name = 'referral_code'
    ) THEN
        ALTER TABLE users ADD COLUMN referral_code VARCHAR(50) UNIQUE;
        CREATE INDEX IF NOT EXISTS idx_users_referral_code ON users(referral_code);
        RAISE NOTICE 'Added referral_code column to users table';
    END IF;
END $$;

-- =================================================
-- 5. ENABLE RLS ON NEW TABLES
-- =================================================

ALTER TABLE trade_fees ENABLE ROW LEVEL SECURITY;
ALTER TABLE referrals ENABLE ROW LEVEL SECURITY;
ALTER TABLE referral_commissions ENABLE ROW LEVEL SECURITY;

-- =================================================
-- 6. RLS POLICIES
-- =================================================

-- Trade fees: Users can view their own fees
CREATE POLICY IF NOT EXISTS "Users can view own trade fees" ON trade_fees
    FOR SELECT USING (
        user_id IN (SELECT id FROM users WHERE telegram_user_id::text = current_setting('request.jwt.claims', true)::json->>'telegram_user_id')
    );

-- Referrals: Users can view their own referral relationships
CREATE POLICY IF NOT EXISTS "Users can view own referrals" ON referrals
    FOR SELECT USING (
        referrer_user_id IN (SELECT id FROM users WHERE telegram_user_id::text = current_setting('request.jwt.claims', true)::json->>'telegram_user_id')
        OR referred_user_id IN (SELECT id FROM users WHERE telegram_user_id::text = current_setting('request.jwt.claims', true)::json->>'telegram_user_id')
    );

-- Referral commissions: Users can view their own commissions
CREATE POLICY IF NOT EXISTS "Users can view own commissions" ON referral_commissions
    FOR SELECT USING (
        referrer_user_id IN (SELECT id FROM users WHERE telegram_user_id::text = current_setting('request.jwt.claims', true)::json->>'telegram_user_id')
    );

-- Admin can view all (for admin panel)
CREATE POLICY IF NOT EXISTS "Admin can view all fees" ON trade_fees
    FOR SELECT USING (
        current_setting('request.jwt.claims', true)::json->>'role' = 'admin'
    );

CREATE POLICY IF NOT EXISTS "Admin can view all referrals" ON referrals
    FOR SELECT USING (
        current_setting('request.jwt.claims', true)::json->>'role' = 'admin'
    );

CREATE POLICY IF NOT EXISTS "Admin can view all commissions" ON referral_commissions
    FOR SELECT USING (
        current_setting('request.jwt.claims', true)::json->>'role' = 'admin'
    );

-- =================================================
-- VERIFICATION
-- =================================================

DO $$
BEGIN
    RAISE NOTICE '✅ Referral system migration completed successfully';
    RAISE NOTICE '   - Created trade_fees table';
    RAISE NOTICE '   - Created referrals table';
    RAISE NOTICE '   - Created referral_commissions table';
    RAISE NOTICE '   - Added fees_enabled and referral_code columns to users';
    RAISE NOTICE '   - Enabled RLS and created policies';
END $$;
