-- Migration: Add support for external blockchain addresses in copy trading
-- Purpose: Allow users to copy trade ANY blockchain address (not just registered users)
-- Tables: external_leaders (new), copy_trading_subscriptions (updated)

-- ==========================================
-- 1. NEW TABLE: external_leaders
-- ==========================================
-- Stores blockchain addresses that are NOT Telegram users
-- but ARE being followed by users for copy trading

CREATE TABLE IF NOT EXISTS external_leaders (
    virtual_id BIGINT PRIMARY KEY,
    polygon_address VARCHAR(42) UNIQUE NOT NULL,
    last_trade_id VARCHAR DEFAULT '',
    trade_count INTEGER DEFAULT 0,
    last_poll_at TIMESTAMP,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

COMMENT ON TABLE external_leaders IS 'Blockchain addresses (not Telegram users) being followed for copy trading';
COMMENT ON COLUMN external_leaders.virtual_id IS 'Unique ID for this external address (for future linking)';
COMMENT ON COLUMN external_leaders.polygon_address IS 'Blockchain address on Polygon (0x...)';
COMMENT ON COLUMN external_leaders.trade_count IS 'Number of trades indexed for this address';

CREATE INDEX idx_external_leaders_polygon_address ON external_leaders(polygon_address);
CREATE INDEX idx_external_leaders_is_active ON external_leaders(is_active);

-- ==========================================
-- 2. UPDATE: copy_trading_subscriptions
-- ==========================================
-- Add leader_address column for flexibility (allows both user ID and blockchain address)

ALTER TABLE copy_trading_subscriptions
ADD COLUMN IF NOT EXISTS leader_address VARCHAR(42);

COMMENT ON COLUMN copy_trading_subscriptions.leader_address IS 'Blockchain address of leader (fallback if leader_id is not a Telegram user)';

-- Create index for fast lookups
CREATE INDEX IF NOT EXISTS idx_copy_trading_subscriptions_leader_address 
ON copy_trading_subscriptions(leader_address) 
WHERE leader_address IS NOT NULL;

-- ==========================================
-- 3. LOGIC REFERENCE (to be implemented in application)
-- ==========================================
/*
Lookup flow when new transaction is detected:

1. DipDup detects: user_address = 0xABC123
   
2. Bot queries copy_trading_subscriptions:
   SELECT follower_id 
   FROM copy_trading_subscriptions 
   WHERE leader_address = '0xABC123' OR leader_id IN (
     SELECT telegram_user_id FROM users WHERE polygon_address = '0xABC123'
   )

3. If found:
   - Copy trade for each follower
   - Record in copy_trading_history
   
4. If NOT found:
   - Optionally update external_leaders table
   - Track for future reference
   - No copying happens yet
*/

