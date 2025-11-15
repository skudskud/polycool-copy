-- ============================================================================
-- SMART TRADING PUSH NOTIFICATIONS
-- Created: 2025-11-01
-- Purpose: Track sent notifications to prevent duplicates and measure engagement
-- ============================================================================

BEGIN;

-- Create notification tracking table
-- This table stores which trades have been notified to which users
-- UNIQUE constraint prevents duplicate notifications
CREATE TABLE IF NOT EXISTS smart_trade_notifications (
    id SERIAL PRIMARY KEY,
    trade_id VARCHAR(255) NOT NULL,              -- SmartWalletTrade.id (transaction hash)
    user_id BIGINT NOT NULL,                     -- User.telegram_user_id
    notified_at TIMESTAMP NOT NULL DEFAULT NOW(),
    clicked BOOLEAN DEFAULT FALSE,               -- User clicked any button
    action_taken VARCHAR(50),                    -- 'view', 'quick_buy', 'custom_buy', null
    
    -- Prevent duplicate notifications for same trade+user
    CONSTRAINT unique_trade_user_notification UNIQUE(trade_id, user_id)
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_notifications_trade_user 
    ON smart_trade_notifications(trade_id, user_id);
CREATE INDEX IF NOT EXISTS idx_notifications_notified_at 
    ON smart_trade_notifications(notified_at DESC);
CREATE INDEX IF NOT EXISTS idx_notifications_user_recent
    ON smart_trade_notifications(user_id, notified_at DESC);

-- Cleanup function: Delete notifications older than 30 days
CREATE OR REPLACE FUNCTION cleanup_old_smart_notifications()
RETURNS INTEGER AS $$
DECLARE
    deleted_count INTEGER;
BEGIN
    DELETE FROM smart_trade_notifications 
    WHERE notified_at < NOW() - INTERVAL '30 days';
    
    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    RETURN deleted_count;
END;
$$ LANGUAGE plpgsql;

-- Log migration
DO $$
BEGIN
    RAISE NOTICE '✅ Smart trading notifications table created';
    RAISE NOTICE '✅ Indexes created for performance';
    RAISE NOTICE '✅ Cleanup function created';
END $$;

COMMIT;

