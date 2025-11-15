-- ============================================================================
-- MIGRATION: Add Market Grouping, Categories, and Rich Metadata (CLEAN VERSION)
-- Date: October 6, 2025
-- Description: Adds ~40 new fields to support parent/child markets, categories,
--              trending indicators, and complete Gamma API data capture
-- ============================================================================

-- Add Primary Identifiers
ALTER TABLE markets ADD COLUMN IF NOT EXISTS question_id VARCHAR(100);

-- Add Parent/Child Market Grouping
ALTER TABLE markets ADD COLUMN IF NOT EXISTS market_group INTEGER;
ALTER TABLE markets ADD COLUMN IF NOT EXISTS group_item_title VARCHAR(200);
ALTER TABLE markets ADD COLUMN IF NOT EXISTS group_item_threshold VARCHAR(100);
ALTER TABLE markets ADD COLUMN IF NOT EXISTS group_item_range VARCHAR(100);

-- Add Categorization & Organization
ALTER TABLE markets ADD COLUMN IF NOT EXISTS category VARCHAR(100);
ALTER TABLE markets ADD COLUMN IF NOT EXISTS tags JSONB;
ALTER TABLE markets ADD COLUMN IF NOT EXISTS events JSONB;

-- Add Visual & Rich Content
ALTER TABLE markets ADD COLUMN IF NOT EXISTS image TEXT;
ALTER TABLE markets ADD COLUMN IF NOT EXISTS icon TEXT;
ALTER TABLE markets ADD COLUMN IF NOT EXISTS description TEXT;
ALTER TABLE markets ADD COLUMN IF NOT EXISTS twitter_card_image TEXT;

-- Add Market Classification
ALTER TABLE markets ADD COLUMN IF NOT EXISTS market_type VARCHAR(50);
ALTER TABLE markets ADD COLUMN IF NOT EXISTS format_type VARCHAR(50);
ALTER TABLE markets ADD COLUMN IF NOT EXISTS featured BOOLEAN DEFAULT FALSE;
ALTER TABLE markets ADD COLUMN IF NOT EXISTS new BOOLEAN DEFAULT FALSE;

-- Add Enhanced Market Status
ALTER TABLE markets ADD COLUMN IF NOT EXISTS restricted BOOLEAN DEFAULT FALSE;

-- Add Enhanced Resolution Data
ALTER TABLE markets ADD COLUMN IF NOT EXISTS resolved_by VARCHAR(100);

-- Add Volume Breakdown
ALTER TABLE markets ADD COLUMN IF NOT EXISTS volume_24hr NUMERIC(20,2);
ALTER TABLE markets ADD COLUMN IF NOT EXISTS volume_1wk NUMERIC(20,2);
ALTER TABLE markets ADD COLUMN IF NOT EXISTS volume_1mo NUMERIC(20,2);
ALTER TABLE markets ADD COLUMN IF NOT EXISTS volume_1yr NUMERIC(20,2);

-- Add Price Movement & Trending
ALTER TABLE markets ADD COLUMN IF NOT EXISTS one_hour_price_change NUMERIC(10,6);
ALTER TABLE markets ADD COLUMN IF NOT EXISTS one_day_price_change NUMERIC(10,6);
ALTER TABLE markets ADD COLUMN IF NOT EXISTS one_week_price_change NUMERIC(10,6);
ALTER TABLE markets ADD COLUMN IF NOT EXISTS one_month_price_change NUMERIC(10,6);
ALTER TABLE markets ADD COLUMN IF NOT EXISTS one_year_price_change NUMERIC(10,6);

-- Add Current Market State
ALTER TABLE markets ADD COLUMN IF NOT EXISTS last_trade_price NUMERIC(10,6);
ALTER TABLE markets ADD COLUMN IF NOT EXISTS best_bid NUMERIC(10,6);
ALTER TABLE markets ADD COLUMN IF NOT EXISTS best_ask NUMERIC(10,6);
ALTER TABLE markets ADD COLUMN IF NOT EXISTS spread NUMERIC(10,6);

-- Add Competition & Rewards
ALTER TABLE markets ADD COLUMN IF NOT EXISTS competitive NUMERIC(10,2);
ALTER TABLE markets ADD COLUMN IF NOT EXISTS rewards_min_size NUMERIC(10,2);
ALTER TABLE markets ADD COLUMN IF NOT EXISTS rewards_max_spread NUMERIC(10,6);

-- Add Sports Markets Support
ALTER TABLE markets ADD COLUMN IF NOT EXISTS game_id VARCHAR(100);
ALTER TABLE markets ADD COLUMN IF NOT EXISTS game_start_time TIMESTAMP;
ALTER TABLE markets ADD COLUMN IF NOT EXISTS sports_market_type VARCHAR(50);

-- Add Additional Dates
ALTER TABLE markets ADD COLUMN IF NOT EXISTS start_date TIMESTAMP;

-- Add indexes for grouping queries
CREATE INDEX IF NOT EXISTS idx_markets_market_group ON markets(market_group);
CREATE INDEX IF NOT EXISTS idx_markets_group_volume ON markets(market_group, volume);

-- Add indexes for category filtering
CREATE INDEX IF NOT EXISTS idx_markets_category ON markets(category);
CREATE INDEX IF NOT EXISTS idx_markets_category_volume ON markets(category, volume);

-- Add index for featured markets
CREATE INDEX IF NOT EXISTS idx_markets_featured ON markets(featured, volume);

-- Add index for trending queries
CREATE INDEX IF NOT EXISTS idx_markets_trending ON markets(one_day_price_change);
