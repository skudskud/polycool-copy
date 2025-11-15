-- ============================================================================
-- WITHDRAWAL FEATURE MIGRATION: Create withdrawals Table
-- ============================================================================
-- Purpose: Add in-bot withdrawal functionality with audit trail
-- Date: 2025-10-08
-- Networks: Solana (SOL) and Polygon (USDC.e)
-- ============================================================================

\echo '🚀 Starting withdrawal feature migration...'
\echo ''

BEGIN;

-- ============================================================================
-- Create withdrawals Table
-- ============================================================================

\echo '🏗️  Creating withdrawals table...'

CREATE TABLE IF NOT EXISTS withdrawals (
    -- Primary key
    id SERIAL PRIMARY KEY,
    
    -- User reference
    user_id BIGINT NOT NULL REFERENCES users(telegram_user_id) ON DELETE CASCADE,
    
    -- Network and token
    network VARCHAR(10) NOT NULL,  -- 'SOL' or 'POLYGON'
    token VARCHAR(10) NOT NULL,    -- 'SOL', 'USDC', 'USDC.e'
    
    -- Amount details
    amount NUMERIC(20, 8) NOT NULL,  -- Withdrawal amount
    gas_cost NUMERIC(20, 8),         -- Gas fee paid
    
    -- Addresses
    from_address TEXT NOT NULL,      -- User's wallet address
    destination_address TEXT NOT NULL,  -- Where funds were sent
    
    -- Transaction details
    tx_hash TEXT,                    -- Blockchain transaction hash
    status VARCHAR(20) DEFAULT 'pending' NOT NULL,  -- 'pending', 'confirmed', 'failed'
    
    -- Timestamps
    created_at TIMESTAMP DEFAULT NOW(),      -- When withdrawal was initiated
    submitted_at TIMESTAMP,                  -- When TX was broadcast
    confirmed_at TIMESTAMP,                  -- When TX was confirmed
    failed_at TIMESTAMP,                     -- When TX failed
    
    -- Error tracking
    error_message TEXT,              -- Error details if failed
    retry_count INT DEFAULT 0,       -- Number of retry attempts
    
    -- Metadata
    estimated_usd_value NUMERIC(10, 2),  -- USD value at time of withdrawal
    
    -- Constraints
    CONSTRAINT check_network CHECK (
        network IN ('SOL', 'POLYGON')
    ),
    CONSTRAINT check_status CHECK (
        status IN ('pending', 'confirmed', 'failed', 'cancelled')
    ),
    CONSTRAINT check_positive_amount CHECK (
        amount > 0
    )
);

\echo '   ✓ Created withdrawals table'

-- ============================================================================
-- Create Indexes for Performance
-- ============================================================================

\echo '🔍 Creating indexes...'

-- Index for finding user's withdrawals (most common query)
CREATE INDEX idx_withdrawals_user_id ON withdrawals(user_id, created_at DESC);

-- Index for tracking pending withdrawals (for monitoring)
CREATE INDEX idx_withdrawals_status ON withdrawals(status, created_at) 
WHERE status = 'pending';

-- Index for looking up by transaction hash
CREATE INDEX idx_withdrawals_tx_hash ON withdrawals(tx_hash) 
WHERE tx_hash IS NOT NULL;

-- Index for rate limiting queries (withdrawals in last 24h)
CREATE INDEX idx_withdrawals_recent ON withdrawals(user_id, created_at) 
WHERE created_at > NOW() - INTERVAL '24 hours';

-- Index for network-specific queries
CREATE INDEX idx_withdrawals_network ON withdrawals(network, status);

\echo '   ✓ Created indexes'

-- ============================================================================
-- Verification
-- ============================================================================

\echo ''
\echo '📊 Verifying table structure...'

SELECT 
    column_name, 
    data_type, 
    is_nullable,
    column_default
FROM information_schema.columns
WHERE table_name = 'withdrawals'
ORDER BY ordinal_position;

\echo ''
\echo '🔍 Verifying indexes...'

SELECT 
    indexname, 
    indexdef
FROM pg_indexes
WHERE tablename = 'withdrawals';

COMMIT;

\echo ''
\echo '✅ Withdrawal feature migration complete!'
\echo ''
\echo '📋 Summary:'
\echo '   • withdrawals table created'
\echo '   • 5 performance indexes created'
\echo '   • Constraints added for data integrity'
\echo ''
\echo '🎯 Next steps:'
\echo '   1. Add Withdrawal model to database.py'
\echo '   2. Create WithdrawalService for execution'
\echo '   3. Build ConversationHandler for UI'
\echo ''

