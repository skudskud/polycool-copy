-- Fix Copy Trading: Support External Leaders (No FK Constraint)
-- Date: 2025-10-27
--
-- PROBLEM: copy_trading_subscriptions.leader_id has FK to users.telegram_user_id
--          but external leaders use virtual_id which doesn't exist in users
--
-- SOLUTION OPTIONS:
-- A) Drop FK constraint (clean but requires table lock)
-- B) Auto-create phantom users (hacky but works immediately)
--
-- We use B for now (no downtime), then apply A later during maintenance window

-- ============================================================================
-- FUNCTION: Auto-create phantom user for external leaders
-- ============================================================================
CREATE OR REPLACE FUNCTION ensure_external_leader_user()
RETURNS TRIGGER AS $$
BEGIN
    -- Check if leader_id is negative (virtual_id for external leaders)
    IF NEW.leader_id < 0 THEN
        -- Insert phantom user if doesn't exist
        INSERT INTO users (
            telegram_user_id,
            username,
            polygon_address,
            polygon_private_key_plaintext_backup
        )
        VALUES (
            NEW.leader_id,
            'external_leader_' || NEW.leader_id,
            'EXTERNAL_PLACEHOLDER',
            'EXTERNAL_LEADER_NO_KEY'
        )
        ON CONFLICT (telegram_user_id) DO NOTHING;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- TRIGGER: Auto-create phantom user BEFORE INSERT
-- ============================================================================
DROP TRIGGER IF EXISTS ensure_external_leader_user_trigger ON copy_trading_subscriptions;

CREATE TRIGGER ensure_external_leader_user_trigger
BEFORE INSERT ON copy_trading_subscriptions
FOR EACH ROW
EXECUTE FUNCTION ensure_external_leader_user();

-- ============================================================================
-- BACKFILL: Create phantom users for existing external leaders
-- ============================================================================
INSERT INTO users (
    telegram_user_id,
    username,
    polygon_address,
    polygon_private_key_plaintext_backup
)
SELECT DISTINCT
    virtual_id as telegram_user_id,
    'external_leader_' || virtual_id as username,
    polygon_address,
    'EXTERNAL_LEADER_NO_KEY' as polygon_private_key_plaintext_backup
FROM external_leaders
WHERE virtual_id NOT IN (SELECT telegram_user_id FROM users)
ON CONFLICT (telegram_user_id) DO NOTHING;

-- ============================================================================
-- FUTURE: Drop FK constraints during maintenance window
-- ============================================================================
-- Uncomment when ready (requires table lock, do during low traffic):
--
-- ALTER TABLE copy_trading_subscriptions
-- DROP CONSTRAINT IF EXISTS copy_trading_subscriptions_leader_id_fkey;
--
-- ALTER TABLE copy_trading_history
-- DROP CONSTRAINT IF EXISTS copy_trading_history_leader_id_fkey;
--
-- ALTER TABLE copy_trading_stats
-- DROP CONSTRAINT IF EXISTS copy_trading_stats_leader_id_fkey;
--
-- -- Then drop the trigger (no longer needed)
-- DROP TRIGGER IF EXISTS ensure_external_leader_user_trigger ON copy_trading_subscriptions;
-- DROP FUNCTION IF EXISTS ensure_external_leader_user();

-- ============================================================================
-- DONE
-- ============================================================================
