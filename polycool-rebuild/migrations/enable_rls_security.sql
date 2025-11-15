-- =================================================
-- SECURITY MIGRATION: Enable Row Level Security (RLS)
-- Date: November 2025
-- Description: Enable RLS on all public tables and create security policies
-- CRITICAL: This fixes 6 Supabase Advisor security errors
-- =================================================

-- =================================================
-- 1. ENABLE RLS ON ALL PUBLIC TABLES
-- =================================================

-- Enable RLS on all tables (fixes Supabase Advisor errors)
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE markets ENABLE ROW LEVEL SECURITY;
ALTER TABLE positions ENABLE ROW LEVEL SECURITY;
ALTER TABLE watched_addresses ENABLE ROW LEVEL SECURITY;
ALTER TABLE trades ENABLE ROW LEVEL SECURITY;
ALTER TABLE copy_trading_allocations ENABLE ROW LEVEL SECURITY;

-- =================================================
-- 2. USERS TABLE POLICIES
-- =================================================

-- Users can read/update their own data
CREATE POLICY "Users can view own profile" ON users
    FOR SELECT USING (telegram_user_id::text = current_setting('request.jwt.claims', true)::json->>'telegram_user_id');

CREATE POLICY "Users can update own profile" ON users
    FOR UPDATE USING (telegram_user_id::text = current_setting('request.jwt.claims', true)::json->>'telegram_user_id');

-- Admin can read all users (for admin panel)
CREATE POLICY "Admin can view all users" ON users
    FOR SELECT USING (
        current_setting('request.jwt.claims', true)::json->>'role' = 'admin'
    );

-- =================================================
-- 3. MARKETS TABLE POLICIES (READ-ONLY FOR ALL)
-- =================================================

-- Everyone can read markets (public data)
CREATE POLICY "Anyone can view markets" ON markets
    FOR SELECT USING (true);

-- Admin can update markets
CREATE POLICY "Admin can manage markets" ON markets
    FOR ALL USING (
        current_setting('request.jwt.claims', true)::json->>'role' = 'admin'
    );

-- =================================================
-- 4. POSITIONS TABLE POLICIES
-- =================================================

-- Users can view their own positions
CREATE POLICY "Users can view own positions" ON positions
    FOR SELECT USING (
        user_id IN (
            SELECT id FROM users
            WHERE telegram_user_id::text = current_setting('request.jwt.claims', true)::json->>'telegram_user_id'
        )
    );

-- Users can create their own positions
CREATE POLICY "Users can create own positions" ON positions
    FOR INSERT WITH CHECK (
        user_id IN (
            SELECT id FROM users
            WHERE telegram_user_id::text = current_setting('request.jwt.claims', true)::json->>'telegram_user_id'
        )
    );

-- Users can update their own positions
CREATE POLICY "Users can update own positions" ON positions
    FOR UPDATE USING (
        user_id IN (
            SELECT id FROM users
            WHERE telegram_user_id::text = current_setting('request.jwt.claims', true)::json->>'telegram_user_id'
        )
    );

-- Admin can view all positions
CREATE POLICY "Admin can view all positions" ON positions
    FOR SELECT USING (
        current_setting('request.jwt.claims', true)::json->>'role' = 'admin'
    );

-- =================================================
-- 5. WATCHED_ADDRESSES TABLE POLICIES
-- =================================================

-- Users can view their own watched addresses
CREATE POLICY "Users can view own watched addresses" ON watched_addresses
    FOR SELECT USING (
        user_id IN (
            SELECT id FROM users
            WHERE telegram_user_id::text = current_setting('request.jwt.claims', true)::json->>'telegram_user_id'
        )
    );

-- Users can manage their own watched addresses
CREATE POLICY "Users can manage own watched addresses" ON watched_addresses
    FOR ALL USING (
        user_id IN (
            SELECT id FROM users
            WHERE telegram_user_id::text = current_setting('request.jwt.claims', true)::json->>'telegram_user_id'
        )
    );

-- Admin can view all watched addresses
CREATE POLICY "Admin can view all watched addresses" ON watched_addresses
    FOR SELECT USING (
        current_setting('request.jwt.claims', true)::json->>'role' = 'admin'
    );

-- =================================================
-- 6. TRADES TABLE POLICIES
-- =================================================

-- Users can view trades from their watched addresses
CREATE POLICY "Users can view trades from own watched addresses" ON trades
    FOR SELECT USING (
        watched_address_id IN (
            SELECT wa.id FROM watched_addresses wa
            JOIN users u ON wa.user_id = u.id
            WHERE u.telegram_user_id::text = current_setting('request.jwt.claims', true)::json->>'telegram_user_id'
        )
    );

-- System can insert trades (from indexer/data ingestion)
CREATE POLICY "System can insert trades" ON trades
    FOR INSERT WITH CHECK (true);

-- Admin can view all trades
CREATE POLICY "Admin can view all trades" ON trades
    FOR SELECT USING (
        current_setting('request.jwt.claims', true)::json->>'role' = 'admin'
    );

-- =================================================
-- 7. COPY_TRADING_ALLOCATIONS TABLE POLICIES
-- =================================================

-- Users can view their own allocations
CREATE POLICY "Users can view own allocations" ON copy_trading_allocations
    FOR SELECT USING (
        user_id IN (
            SELECT id FROM users
            WHERE telegram_user_id::text = current_setting('request.jwt.claims', true)::json->>'telegram_user_id'
        )
    );

-- Users can manage their own allocations
CREATE POLICY "Users can manage own allocations" ON copy_trading_allocations
    FOR ALL USING (
        user_id IN (
            SELECT id FROM users
            WHERE telegram_user_id::text = current_setting('request.jwt.claims', true)::json->>'telegram_user_id'
        )
    );

-- Admin can view all allocations
CREATE POLICY "Admin can view all allocations" ON copy_trading_allocations
    FOR SELECT USING (
        current_setting('request.jwt.claims', true)::json->>'role' = 'admin'
    );

-- =================================================
-- 8. VERIFICATION QUERIES
-- =================================================

-- Verify RLS is enabled on all tables:
-- SELECT schemaname, tablename, rowsecurity
-- FROM pg_tables
-- WHERE schemaname = 'public'
-- AND tablename IN ('users', 'markets', 'positions', 'watched_addresses', 'trades', 'copy_trading_allocations');

-- List all RLS policies:
-- SELECT schemaname, tablename, policyname, permissive, roles, cmd, qual
-- FROM pg_policies
-- WHERE schemaname = 'public'
-- ORDER BY tablename, policyname;

-- =================================================
-- 9. ROLLBACK (IF NEEDED)
-- =================================================

-- To rollback this migration, run:
-- DROP POLICY IF EXISTS "Users can view own profile" ON users;
-- DROP POLICY IF EXISTS "Users can update own profile" ON users;
-- DROP POLICY IF EXISTS "Admin can view all users" ON users;
-- DROP POLICY IF EXISTS "Anyone can view markets" ON markets;
-- DROP POLICY IF EXISTS "Admin can manage markets" ON markets;
-- DROP POLICY IF EXISTS "Users can view own positions" ON positions;
-- DROP POLICY IF EXISTS "Users can create own positions" ON positions;
-- DROP POLICY IF EXISTS "Users can update own positions" ON positions;
-- DROP POLICY IF EXISTS "Admin can view all positions" ON positions;
-- DROP POLICY IF EXISTS "Users can view own watched addresses" ON watched_addresses;
-- DROP POLICY IF EXISTS "Users can manage own watched addresses" ON watched_addresses;
-- DROP POLICY IF EXISTS "Admin can view all watched addresses" ON watched_addresses;
-- DROP POLICY IF EXISTS "Users can view trades from own watched addresses" ON trades;
-- DROP POLICY IF EXISTS "System can insert trades" ON trades;
-- DROP POLICY IF EXISTS "Admin can view all trades" ON trades;
-- DROP POLICY IF EXISTS "Users can view own allocations" ON copy_trading_allocations;
-- DROP POLICY IF EXISTS "Users can manage own allocations" ON copy_trading_allocations;
-- DROP POLICY IF EXISTS "Admin can view all allocations" ON copy_trading_allocations;
--
-- ALTER TABLE users DISABLE ROW LEVEL SECURITY;
-- ALTER TABLE markets DISABLE ROW LEVEL SECURITY;
-- ALTER TABLE positions DISABLE ROW LEVEL SECURITY;
-- ALTER TABLE watched_addresses DISABLE ROW LEVEL SECURITY;
-- ALTER TABLE trades DISABLE ROW LEVEL SECURITY;
-- ALTER TABLE copy_trading_allocations DISABLE ROW LEVEL SECURITY;
