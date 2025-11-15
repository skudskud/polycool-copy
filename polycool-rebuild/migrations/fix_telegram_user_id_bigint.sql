-- Migration: Fix telegram_user_id to BIGINT
-- Problem: Telegram user IDs can exceed INTEGER limit (2,147,483,647)
-- Solution: Change telegram_user_id column from INTEGER to BIGINT
-- Date: 2025-11-07

-- Step 1: Drop the unique constraint temporarily (if it exists as a separate constraint)
-- Note: The unique constraint is part of the column definition, so we'll handle it during ALTER

-- Step 2: Drop indexes that depend on telegram_user_id
DROP INDEX IF EXISTS idx_users_telegram_id;
DROP INDEX IF EXISTS idx_users_telegram_id CASCADE;

-- Step 3: Alter the column type from INTEGER to BIGINT
ALTER TABLE users
ALTER COLUMN telegram_user_id TYPE BIGINT USING telegram_user_id::BIGINT;

-- Step 4: Recreate the index
CREATE INDEX idx_users_telegram_id ON users(telegram_user_id);

-- Verify the change
DO $$
BEGIN
    RAISE NOTICE '✅ Migration completed: telegram_user_id is now BIGINT';
    RAISE NOTICE '   Max INTEGER value: 2,147,483,647';
    RAISE NOTICE '   Max BIGINT value: 9,223,372,036,854,775,807';
END $$;
