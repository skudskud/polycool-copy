-- ============================================================================
-- TP/SL FEATURE MIGRATION: Create tpsl_orders Table
-- ============================================================================
-- Purpose: Add Take Profit and Stop Loss functionality
-- Date: 2025-10-07
-- ============================================================================

\echo '🚀 Starting TP/SL feature migration...'
\echo ''

BEGIN;

-- ============================================================================
-- Create tpsl_orders Table
-- ============================================================================

\echo '🏗️  Creating tpsl_orders table...'

CREATE TABLE IF NOT EXISTS tpsl_orders (
    -- Primary key
    id SERIAL PRIMARY KEY,
    
    -- User reference
    user_id BIGINT NOT NULL REFERENCES users(telegram_user_id) ON DELETE CASCADE,
    
    -- Position reference
    market_id VARCHAR(100) NOT NULL,
    outcome VARCHAR(10) NOT NULL,  -- 'yes', 'no'
    token_id VARCHAR(100) NOT NULL,
    
    -- TP/SL Configuration
    take_profit_price NUMERIC(10, 4),  -- NULL if not set
    stop_loss_price NUMERIC(10, 4),    -- NULL if not set
    
    -- Position tracking
    monitored_tokens NUMERIC(20, 4) NOT NULL,  -- Tokens being monitored
    entry_price NUMERIC(10, 4) NOT NULL,       -- Position entry price
    
    -- Status tracking
    status VARCHAR(20) DEFAULT 'active' NOT NULL,  -- 'active', 'triggered', 'cancelled'
    triggered_type VARCHAR(15),                     -- 'take_profit', 'stop_loss', NULL
    execution_price NUMERIC(10, 4),                 -- Price at which it was triggered
    
    -- Timestamps
    created_at TIMESTAMP DEFAULT NOW(),
    triggered_at TIMESTAMP,
    cancelled_at TIMESTAMP,
    last_price_check TIMESTAMP,
    
    -- Market data snapshot (for display purposes)
    market_data JSONB,
    
    -- Constraints
    CONSTRAINT check_tpsl_prices CHECK (
        take_profit_price IS NOT NULL OR stop_loss_price IS NOT NULL
    ),
    CONSTRAINT check_status CHECK (
        status IN ('active', 'triggered', 'cancelled')
    ),
    CONSTRAINT check_triggered_type CHECK (
        triggered_type IS NULL OR triggered_type IN ('take_profit', 'stop_loss')
    )
);

\echo '   ✓ Created tpsl_orders table'

-- ============================================================================
-- Create Indexes for Performance
-- ============================================================================

\echo '🔍 Creating indexes...'

-- Index for finding active TP/SL orders (most common query for price monitor)
CREATE INDEX idx_tpsl_active ON tpsl_orders(status, user_id) 
WHERE status = 'active';

-- Index for finding TP/SL by market and outcome
CREATE INDEX idx_tpsl_market_outcome ON tpsl_orders(market_id, outcome);

-- Index for finding all TP/SL for a user
CREATE INDEX idx_tpsl_user ON tpsl_orders(user_id, status);

-- Composite index for user + market + outcome (unique position lookup)
CREATE INDEX idx_tpsl_user_market_outcome ON tpsl_orders(user_id, market_id, outcome);

-- Index for finding triggered orders
CREATE INDEX idx_tpsl_triggered ON tpsl_orders(status, triggered_at) 
WHERE status = 'triggered';

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
WHERE table_name = 'tpsl_orders'
ORDER BY ordinal_position;

\echo ''
\echo '🔍 Verifying indexes...'

SELECT 
    indexname, 
    indexdef
FROM pg_indexes
WHERE tablename = 'tpsl_orders';

COMMIT;

\echo ''
\echo '✅ TP/SL feature migration complete!'
\echo ''
\echo '📋 Summary:'
\echo '   • tpsl_orders table created'
\echo '   • 5 performance indexes created'
\echo '   • Constraints added for data integrity'
\echo ''
\echo '🎯 Next steps:'
\echo '   1. Add TPSLOrder model to database.py'
\echo '   2. Create TPSLService for CRUD operations'
\echo '   3. Build PriceMonitor background task'
\echo ''

