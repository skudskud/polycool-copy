# Market Grouping & Categorization Enhancement

**Date:** October 6, 2025  
**Branch:** `markets`  
**Status:** ✅ Ready for deployment

---

## 🎯 Purpose

This migration enhances the `markets` table to support:
- **Parent/Child Market Grouping** (e.g., NYC Mayor Election → Eric Adams, Andrew Yang, etc.)
- **Category Filtering** (Politics, Sports, Crypto, etc.)
- **Trending Indicators** (price changes, hot markets)
- **Rich Metadata** (images, descriptions, volume breakdowns)
- **Complete Gamma API Data Capture** (~40 new fields)

---

## 📊 What's Added

### **1. Parent/Child Market Grouping** ⭐ KEY FEATURE
```sql
market_group           -- Parent market group ID
group_item_title       -- Sub-market title (e.g., "Eric Adams")
group_item_threshold   -- Threshold value
group_item_range       -- Range value
```

**Example:**
- Parent: "NYC Mayoral Election 2025" (market_group = 123)
- Child: "Will Eric Adams win?" (market_group = 123, group_item_title = "Eric Adams")
- Child: "Will Andrew Yang win?" (market_group = 123, group_item_title = "Andrew Yang")

### **2. Categorization**
```sql
category               -- Politics, Sports, Crypto, Pop Culture, etc.
tags                   -- JSONB array of tag objects
events                 -- JSONB array of event objects
```

### **3. Visual & Rich Content**
```sql
image                  -- Market image URL
icon                   -- Market icon URL
description            -- Full market description
twitter_card_image     -- Social media preview image
```

### **4. Market Classification**
```sql
market_type            -- Type classification
format_type            -- Format type
featured               -- Featured markets flag (indexed)
new                    -- New markets flag
```

### **5. Volume Breakdown**
```sql
volume_24hr            -- 24 hour volume
volume_1wk             -- 1 week volume
volume_1mo             -- 1 month volume
volume_1yr             -- 1 year volume
```

### **6. Price Movement & Trending**
```sql
one_hour_price_change  -- 1 hour price change (indexed)
one_day_price_change   -- 24 hour price change (indexed for trending)
one_week_price_change  -- 7 day price change
one_month_price_change -- 30 day price change
one_year_price_change  -- 365 day price change
```

### **7. Current Market State**
```sql
last_trade_price       -- Last executed trade price
best_bid               -- Highest buy order
best_ask               -- Lowest sell order
spread                 -- Bid-ask spread
```

### **8. Competition & Rewards**
```sql
competitive            -- Competitive score
rewards_min_size       -- Minimum reward size
rewards_max_spread     -- Maximum reward spread
```

### **9. Sports Markets**
```sql
game_id                -- Game identifier
game_start_time        -- Game start timestamp
sports_market_type     -- Sports market type
```

---

## 🚀 How to Deploy

### **Step 1: Run Migration on Railway**

```bash
# Connect to Railway PostgreSQL
railway connect

# Run the migration
\i migrations/2025-10-06_market_grouping_enhancement/add_market_metadata.sql
```

Or use Railway's built-in query editor:
1. Go to Railway Dashboard → PostgreSQL Database
2. Open Query tab
3. Copy/paste the contents of `add_market_metadata.sql`
4. Execute

### **Step 2: Deploy Code Changes**

The migration is backward compatible, but you need to deploy code changes to populate the new fields:

1. ✅ `core/persistence/models.py` - Enhanced Market model
2. ✅ `core/services/market_updater_service.py` - Updated transformer
3. ✅ `core/persistence/market_repository.py` - New query methods
4. ✅ `telegram_bot/handlers/trading_handlers.py` - Enhanced UI

```bash
git add .
git commit -m "feat: Add market grouping, categories, and rich metadata"
git push origin markets
```

### **Step 3: Trigger Market Refresh**

After deployment, trigger a market fetch to populate new fields:

```bash
# Using the API
curl -X POST https://your-railway-app.railway.app/markets/force-update

# Or wait for next scheduled update (runs every 60 seconds)
```

---

## 📈 New Indexes Added

For optimal query performance:

```sql
-- Parent/child grouping
idx_markets_market_group           ON markets(market_group)
idx_markets_group_volume           ON markets(market_group, volume)

-- Category filtering
idx_markets_category               ON markets(category)
idx_markets_category_volume        ON markets(category, volume)

-- Featured markets
idx_markets_featured               ON markets(featured, volume)

-- Trending indicators
idx_markets_trending               ON markets(one_day_price_change)
```

---

## 🧪 Testing

After migration, verify:

```sql
-- Check column count (should be ~60+ columns now)
SELECT COUNT(*) FROM information_schema.columns 
WHERE table_name = 'markets';

-- Check indexes
SELECT indexname FROM pg_indexes 
WHERE tablename = 'markets';

-- Verify grouping works
SELECT market_group, COUNT(*) as sub_markets, SUM(volume) as total_volume
FROM markets 
WHERE market_group IS NOT NULL
GROUP BY market_group
ORDER BY total_volume DESC
LIMIT 10;

-- Check categories
SELECT category, COUNT(*) as count
FROM markets 
WHERE category IS NOT NULL
GROUP BY category
ORDER BY count DESC;
```

---

## ♻️ Rollback (if needed)

If you need to rollback this migration:

```sql
-- See rollback section at bottom of add_market_metadata.sql
-- WARNING: This will delete data in the new columns!
```

---

## 🎯 Expected Results

After migration and market fetch:

1. **Parent Markets Identified:** Markets with `market_group = NULL` or unique group IDs
2. **Child Markets Linked:** Markets with same `market_group` ID grouped together
3. **Categories Populated:** Politics, Sports, Crypto, etc.
4. **Trending Data Available:** Price changes for trending indicators
5. **Rich Metadata:** Images, descriptions, volume breakdowns

---

## 📝 Notes

- ✅ **Backward Compatible:** Existing code continues to work
- ✅ **Zero Downtime:** Can be applied while system is running
- ✅ **Safe:** All new columns are nullable
- ✅ **Performance Optimized:** Strategic indexes added
- ✅ **Tested:** Follows PostgreSQL best practices

---

## 🔗 Related Files

- `add_market_metadata.sql` - Main migration file
- `../../core/persistence/models.py` - Enhanced model definition
- `../../core/services/market_updater_service.py` - Updated transformer logic
- `../../MARKETS_POSTGRESQL_MIGRATION.md` - Original migration docs

---

**Questions?** Check the main project README or commit messages for more details.
