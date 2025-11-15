-- ============================================================================
-- MIGRATION: Add Market Grouping, Categories, and Rich Metadata
-- Date: October 6, 2025
-- Description: Adds ~40 new fields to support parent/child markets, categories,
--              trending indicators, and complete Gamma API data capture
-- ============================================================================

BEGIN;

RAISE NOTICE '🚀 Starting Market Enhancement Migration...';

-- ========================================
-- STEP 1: Add Primary Identifiers
-- ========================================
ALTER TABLE markets 
ADD COLUMN IF NOT EXISTS question_id VARCHAR(100);

RAISE NOTICE '✅ Added primary identifiers';

-- ========================================
-- STEP 2: Add Parent/Child Market Grouping (KEY FEATURE!)
-- ========================================
ALTER TABLE markets 
ADD COLUMN IF NOT EXISTS market_group INTEGER,
ADD COLUMN IF NOT EXISTS group_item_title VARCHAR(200),
ADD COLUMN IF NOT EXISTS group_item_threshold VARCHAR(100),
ADD COLUMN IF NOT EXISTS group_item_range VARCHAR(100);

-- Add indexes for grouping queries
CREATE INDEX IF NOT EXISTS idx_markets_market_group ON markets(market_group);
CREATE INDEX IF NOT EXISTS idx_markets_group_volume ON markets(market_group, volume);

RAISE NOTICE '✅ Added parent/child grouping fields and indexes';

-- ========================================
-- STEP 3: Add Categorization & Organization
-- ========================================
ALTER TABLE markets 
ADD COLUMN IF NOT EXISTS category VARCHAR(100),
ADD COLUMN IF NOT EXISTS tags JSONB,
ADD COLUMN IF NOT EXISTS events JSONB;

-- Add indexes for category filtering
CREATE INDEX IF NOT EXISTS idx_markets_category ON markets(category);
CREATE INDEX IF NOT EXISTS idx_markets_category_volume ON markets(category, volume);

RAISE NOTICE '✅ Added categorization fields and indexes';

-- ========================================
-- STEP 4: Add Visual & Rich Content
-- ========================================
ALTER TABLE markets 
ADD COLUMN IF NOT EXISTS image TEXT,
ADD COLUMN IF NOT EXISTS icon TEXT,
ADD COLUMN IF NOT EXISTS description TEXT,
ADD COLUMN IF NOT EXISTS twitter_card_image TEXT;

RAISE NOTICE '✅ Added visual and rich content fields';

-- ========================================
-- STEP 5: Add Market Classification
-- ========================================
ALTER TABLE markets 
ADD COLUMN IF NOT EXISTS market_type VARCHAR(50),
ADD COLUMN IF NOT EXISTS format_type VARCHAR(50),
ADD COLUMN IF NOT EXISTS featured BOOLEAN DEFAULT FALSE,
ADD COLUMN IF NOT EXISTS new BOOLEAN DEFAULT FALSE;

-- Add index for featured markets
CREATE INDEX IF NOT EXISTS idx_markets_featured ON markets(featured, volume);

RAISE NOTICE '✅ Added market classification fields';

-- ========================================
-- STEP 6: Add Enhanced Market Status
-- ========================================
ALTER TABLE markets 
ADD COLUMN IF NOT EXISTS restricted BOOLEAN DEFAULT FALSE;

RAISE NOTICE '✅ Added enhanced status fields';

-- ========================================
-- STEP 7: Add Enhanced Resolution Data
-- ========================================
ALTER TABLE markets 
ADD COLUMN IF NOT EXISTS resolved_by VARCHAR(100);

RAISE NOTICE '✅ Added enhanced resolution fields';

-- ========================================
-- STEP 8: Add Volume Breakdown (24hr, 1wk, 1mo, 1yr)
-- ========================================
ALTER TABLE markets 
ADD COLUMN IF NOT EXISTS volume_24hr NUMERIC(20,2),
ADD COLUMN IF NOT EXISTS volume_1wk NUMERIC(20,2),
ADD COLUMN IF NOT EXISTS volume_1mo NUMERIC(20,2),
ADD COLUMN IF NOT EXISTS volume_1yr NUMERIC(20,2);

RAISE NOTICE '✅ Added volume breakdown fields';

-- ========================================
-- STEP 9: Add Price Movement & Trending
-- ========================================
ALTER TABLE markets 
ADD COLUMN IF NOT EXISTS one_hour_price_change NUMERIC(10,6),
ADD COLUMN IF NOT EXISTS one_day_price_change NUMERIC(10,6),
ADD COLUMN IF NOT EXISTS one_week_price_change NUMERIC(10,6),
ADD COLUMN IF NOT EXISTS one_month_price_change NUMERIC(10,6),
ADD COLUMN IF NOT EXISTS one_year_price_change NUMERIC(10,6);

-- Add index for trending queries
CREATE INDEX IF NOT EXISTS idx_markets_trending ON markets(one_day_price_change);

RAISE NOTICE '✅ Added price movement fields and trending index';

-- ========================================
-- STEP 10: Add Current Market State
-- ========================================
ALTER TABLE markets 
ADD COLUMN IF NOT EXISTS last_trade_price NUMERIC(10,6),
ADD COLUMN IF NOT EXISTS best_bid NUMERIC(10,6),
ADD COLUMN IF NOT EXISTS best_ask NUMERIC(10,6),
ADD COLUMN IF NOT EXISTS spread NUMERIC(10,6);

RAISE NOTICE '✅ Added current market state fields';

-- ========================================
-- STEP 11: Add Competition & Rewards
-- ========================================
ALTER TABLE markets 
ADD COLUMN IF NOT EXISTS competitive NUMERIC(10,2),
ADD COLUMN IF NOT EXISTS rewards_min_size NUMERIC(10,2),
ADD COLUMN IF NOT EXISTS rewards_max_spread NUMERIC(10,6);

RAISE NOTICE '✅ Added competition and rewards fields';

-- ========================================
-- STEP 12: Add Sports Markets Support
-- ========================================
ALTER TABLE markets 
ADD COLUMN IF NOT EXISTS game_id VARCHAR(100),
ADD COLUMN IF NOT EXISTS game_start_time TIMESTAMP,
ADD COLUMN IF NOT EXISTS sports_market_type VARCHAR(50);

RAISE NOTICE '✅ Added sports market fields';

-- ========================================
-- STEP 13: Add Additional Dates
-- ========================================
ALTER TABLE markets 
ADD COLUMN IF NOT EXISTS start_date TIMESTAMP;

RAISE NOTICE '✅ Added additional date fields';

-- ========================================
-- SUMMARY
-- ========================================
DO $$
DECLARE
    column_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO column_count 
    FROM information_schema.columns 
    WHERE table_name = 'markets';
    
    RAISE NOTICE '════════════════════════════════════════════════════════';
    RAISE NOTICE '✅ MIGRATION COMPLETE!';
    RAISE NOTICE '════════════════════════════════════════════════════════';
    RAISE NOTICE 'Markets table now has % columns', column_count;
    RAISE NOTICE '';
    RAISE NOTICE '🎯 NEW FEATURES ENABLED:';
    RAISE NOTICE '  • Parent/Child Market Grouping';
    RAISE NOTICE '  • Category Filtering';
    RAISE NOTICE '  • Trending Indicators';
    RAISE NOTICE '  • Rich Metadata (images, descriptions)';
    RAISE NOTICE '  • Volume Breakdowns (24hr, 1wk, 1mo, 1yr)';
    RAISE NOTICE '  • Sports Market Support';
    RAISE NOTICE '  • Featured Markets';
    RAISE NOTICE '';
    RAISE NOTICE '📊 NEXT STEPS:';
    RAISE NOTICE '  1. Deploy code changes (market_updater_service.py)';
    RAISE NOTICE '  2. Run market fetch to populate new fields';
    RAISE NOTICE '  3. Test parent/child grouping in Telegram bot';
    RAISE NOTICE '════════════════════════════════════════════════════════';
END $$;

COMMIT;

-- ============================================================================
-- ROLLBACK (if needed)
-- ============================================================================
-- To rollback this migration, run:
--
-- BEGIN;
-- ALTER TABLE markets 
--   DROP COLUMN IF EXISTS question_id,
--   DROP COLUMN IF EXISTS market_group,
--   DROP COLUMN IF EXISTS group_item_title,
--   DROP COLUMN IF EXISTS group_item_threshold,
--   DROP COLUMN IF EXISTS group_item_range,
--   DROP COLUMN IF EXISTS category,
--   DROP COLUMN IF EXISTS tags,
--   DROP COLUMN IF EXISTS events,
--   DROP COLUMN IF EXISTS image,
--   DROP COLUMN IF EXISTS icon,
--   DROP COLUMN IF EXISTS description,
--   DROP COLUMN IF EXISTS twitter_card_image,
--   DROP COLUMN IF EXISTS market_type,
--   DROP COLUMN IF EXISTS format_type,
--   DROP COLUMN IF EXISTS featured,
--   DROP COLUMN IF EXISTS new,
--   DROP COLUMN IF EXISTS restricted,
--   DROP COLUMN IF EXISTS resolved_by,
--   DROP COLUMN IF EXISTS volume_24hr,
--   DROP COLUMN IF EXISTS volume_1wk,
--   DROP COLUMN IF EXISTS volume_1mo,
--   DROP COLUMN IF EXISTS volume_1yr,
--   DROP COLUMN IF EXISTS one_hour_price_change,
--   DROP COLUMN IF EXISTS one_day_price_change,
--   DROP COLUMN IF EXISTS one_week_price_change,
--   DROP COLUMN IF EXISTS one_month_price_change,
--   DROP COLUMN IF EXISTS one_year_price_change,
--   DROP COLUMN IF EXISTS last_trade_price,
--   DROP COLUMN IF EXISTS best_bid,
--   DROP COLUMN IF EXISTS best_ask,
--   DROP COLUMN IF EXISTS spread,
--   DROP COLUMN IF EXISTS competitive,
--   DROP COLUMN IF EXISTS rewards_min_size,
--   DROP COLUMN IF EXISTS rewards_max_spread,
--   DROP COLUMN IF EXISTS game_id,
--   DROP COLUMN IF EXISTS game_start_time,
--   DROP COLUMN IF EXISTS sports_market_type,
--   DROP COLUMN IF EXISTS start_date;
-- COMMIT;
