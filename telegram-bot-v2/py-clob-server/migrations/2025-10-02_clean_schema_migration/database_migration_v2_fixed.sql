-- ============================================================================
-- DATABASE MIGRATION V2: Clean Schema with Single Users Table
-- ============================================================================
-- Purpose: Migrate from 3 separate tables to a single unified 'users' table
-- Date: 2025-10-02
-- ============================================================================

\echo '🚀 Starting database migration...'
\echo ''

BEGIN;

-- ============================================================================
-- STEP 1: Create Backup of Existing Data
-- ============================================================================

\echo '📦 Step 1: Creating backups...'

CREATE TABLE IF NOT EXISTS migration_backup_user_wallets AS 
SELECT * FROM user_wallets;

CREATE TABLE IF NOT EXISTS migration_backup_user_api_keys AS 
SELECT * FROM user_api_keys;

CREATE TABLE IF NOT EXISTS migration_backup_user_positions AS 
SELECT * FROM user_positions;

\echo '✅ Backups created'
\echo ''

-- ============================================================================
-- STEP 2: Create New Clean Schema
-- ============================================================================

\echo '🏗️  Step 2: Creating new schema...'

-- Drop old tables (CASCADE to drop foreign keys)
DROP TABLE IF EXISTS user_wallets CASCADE;
DROP TABLE IF EXISTS user_api_keys CASCADE;
DROP TABLE IF EXISTS user_positions CASCADE;
DROP TABLE IF EXISTS positions CASCADE;  -- Remove positions table completely
DROP TABLE IF EXISTS markets CASCADE;

\echo '   ✓ Dropped old tables'

-- Create unified users table
CREATE TABLE users (
    telegram_user_id BIGINT PRIMARY KEY,
    username VARCHAR(100),
    
    -- Polygon wallet
    polygon_address VARCHAR(42) NOT NULL,
    polygon_private_key VARCHAR(64) NOT NULL,
    
    -- Solana wallet (NEW!)
    solana_address VARCHAR(44),
    solana_private_key TEXT,
    
    -- API credentials
    api_key VARCHAR(100),
    api_secret TEXT,
    api_passphrase VARCHAR(100),
    
    -- Funding status
    funded BOOLEAN DEFAULT FALSE,
    
    -- Contract approvals (3 separate contracts)
    usdc_approved BOOLEAN DEFAULT FALSE,
    pol_approved BOOLEAN DEFAULT FALSE,
    polymarket_approved BOOLEAN DEFAULT FALSE,
    
    -- Auto-approval tracking
    auto_approval_completed BOOLEAN DEFAULT FALSE,
    auto_approval_last_check TIMESTAMP,
    
    -- Metadata
    created_at TIMESTAMP DEFAULT NOW(),
    last_active TIMESTAMP,
    
    -- For /restart command
    wallet_generation_count INTEGER DEFAULT 1,
    last_restart TIMESTAMP
);

CREATE INDEX idx_users_telegram_id ON users(telegram_user_id);
CREATE INDEX idx_users_polygon_address ON users(polygon_address);
CREATE INDEX idx_users_solana_address ON users(solana_address);

\echo '   ✓ Created users table'

-- POSITIONS TABLE REMOVED - Using transaction-based architecture
-- Positions are calculated dynamically from transactions table
-- This provides better data integrity and audit trail

\echo '   ⚠️ Positions table removed - using transaction-based architecture'

-- Create markets table
CREATE TABLE markets (
    id VARCHAR(50) PRIMARY KEY,
    condition_id VARCHAR(100) UNIQUE,
    question TEXT NOT NULL,
    slug VARCHAR(200),
    
    -- Market status
    status VARCHAR(20) NOT NULL DEFAULT 'active',
    active BOOLEAN DEFAULT TRUE,
    closed BOOLEAN DEFAULT FALSE,
    archived BOOLEAN DEFAULT FALSE,
    accepting_orders BOOLEAN DEFAULT TRUE,
    
    -- Resolution data
    resolved_at TIMESTAMP,
    winner VARCHAR(10),
    resolution_source VARCHAR(100),
    
    -- Trading data
    volume NUMERIC(20,2) DEFAULT 0,
    liquidity NUMERIC(20,2) DEFAULT 0,
    outcomes JSONB,
    outcome_prices JSONB,
    clob_token_ids JSONB,
    
    -- Dates
    end_date TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    last_updated TIMESTAMP DEFAULT NOW(),
    last_fetched TIMESTAMP DEFAULT NOW(),
    
    -- Trading eligibility
    tradeable BOOLEAN DEFAULT FALSE,
    enable_order_book BOOLEAN DEFAULT FALSE
);

-- Create indexes for performance
CREATE INDEX idx_markets_id ON markets(id);
CREATE INDEX idx_markets_condition_id ON markets(condition_id);
CREATE INDEX idx_markets_slug ON markets(slug);
CREATE INDEX idx_markets_status ON markets(status);
CREATE INDEX idx_markets_active ON markets(active);
CREATE INDEX idx_markets_tradeable ON markets(tradeable);
CREATE INDEX idx_markets_end_date ON markets(end_date);
CREATE INDEX idx_markets_status_updated ON markets(status, last_updated);
CREATE INDEX idx_markets_tradeable_volume ON markets(status, tradeable, volume);
CREATE INDEX idx_markets_end_date_status ON markets(end_date, status);
CREATE INDEX idx_markets_resolved ON markets(status, resolved_at);

\echo '   ✓ Created markets table'
\echo ''

-- ============================================================================
-- STEP 3: Migrate Existing Data
-- ============================================================================

\echo '🔄 Step 3: Migrating data...'

-- Migrate users
INSERT INTO users (
    telegram_user_id,
    username,
    polygon_address,
    polygon_private_key,
    api_key,
    api_secret,
    api_passphrase,
    funded,
    usdc_approved,
    polymarket_approved,
    auto_approval_completed,
    auto_approval_last_check,
    created_at
)
SELECT 
    w.user_id,
    w.username,
    w.address,
    w.private_key,
    a.api_key,
    a.api_secret,
    a.api_passphrase,
    w.funded,
    w.usdc_approved,
    w.polymarket_approved,
    w.auto_approval_completed,
    w.last_approval_check,
    w.created_at
FROM migration_backup_user_wallets w
LEFT JOIN migration_backup_user_api_keys a ON w.user_id = a.user_id;

\echo '   ✓ Migrated users'

-- Migrate positions
INSERT INTO positions (
    user_id,
    market_id,
    outcome,
    tokens,
    buy_price,
    total_cost,
    token_id,
    market_data,
    is_active,
    buy_time,
    created_at
)
SELECT 
    user_id,
    market_id,
    outcome,
    tokens,
    buy_price,
    total_cost,
    token_id,
    market_data,
    is_active,
    buy_time,
    created_at
FROM migration_backup_user_positions;

\echo '   ✓ Migrated positions'
\echo ''

COMMIT;

-- ============================================================================
-- STEP 4: Verification
-- ============================================================================

\echo '📊 Migration Summary:'
\echo ''

SELECT 
    '✅ MIGRATION COMPLETE!' as status,
    (SELECT COUNT(*) FROM users) as total_users,
    (SELECT COUNT(*) FROM positions) as total_positions,
    (SELECT COUNT(*) FROM markets) as total_markets;

\echo ''
\echo '⚠️  Backup tables retained for safety:'
\echo '   - migration_backup_user_wallets'
\echo '   - migration_backup_user_api_keys'
\echo '   - migration_backup_user_positions'
\echo ''
\echo '✅ Migration complete! New tables ready.'

