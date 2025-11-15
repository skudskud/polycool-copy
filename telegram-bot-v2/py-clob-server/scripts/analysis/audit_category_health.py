"""
Category Health Audit Script
Analyzes category coverage for markets, focusing on top markets by volume/liquidity
"""

import os
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from sqlalchemy import create_engine, text
from datetime import datetime, timedelta

# Database connection
DATABASE_URL = os.environ.get('DATABASE_URL')
if not DATABASE_URL:
    print("❌ DATABASE_URL not set")
    sys.exit(1)

engine = create_engine(DATABASE_URL)

print("=" * 80)
print("📊 CATEGORY HEALTH AUDIT")
print("=" * 80)
print(f"🕐 Timestamp: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC\n")

# ========================================
# AUDIT 1: Overall Health
# ========================================
print("\n" + "=" * 80)
print("1️⃣  OVERALL CATEGORY HEALTH")
print("=" * 80)

query = text("""
SELECT 
  COUNT(*) as total_markets,
  COUNT(CASE WHEN category IS NOT NULL AND category != '' THEN 1 END) as markets_with_category,
  COUNT(CASE WHEN category IS NULL OR category = '' THEN 1 END) as markets_without_category,
  ROUND(100.0 * COUNT(CASE WHEN category IS NOT NULL AND category != '' THEN 1 END) / COUNT(*), 2) as pct_with_category,
  COUNT(DISTINCT category) as unique_categories
FROM markets;
""")

with engine.connect() as conn:
    result = conn.execute(query).fetchone()
    print(f"Total Markets:         {result[0]:,}")
    print(f"With Category:         {result[1]:,} ({result[3]}%)")
    print(f"Without Category:      {result[2]:,} ({100-result[3]:.2f}%)")
    print(f"Unique Categories:     {result[4]}")

# ========================================
# AUDIT 2: Top 500 by Volume
# ========================================
print("\n" + "=" * 80)
print("2️⃣  TOP 500 MARKETS BY VOLUME")
print("=" * 80)

query = text("""
SELECT 
  COUNT(*) as total_markets,
  COUNT(CASE WHEN category IS NOT NULL AND category != '' THEN 1 END) as has_category,
  COUNT(CASE WHEN category IS NULL OR category = '' THEN 1 END) as missing_category,
  ROUND(100.0 * COUNT(CASE WHEN category IS NOT NULL AND category != '' THEN 1 END) / COUNT(*), 2) as pct_with_category,
  ROUND(AVG(volume), 2) as avg_volume,
  ROUND(MIN(volume), 2) as min_volume,
  ROUND(MAX(volume), 2) as max_volume
FROM (
  SELECT id, question, category, volume
  FROM markets
  WHERE volume IS NOT NULL
  ORDER BY volume DESC
  LIMIT 500
) top_500;
""")

with engine.connect() as conn:
    result = conn.execute(query).fetchone()
    print(f"Total Markets:         {result[0]}")
    print(f"With Category:         {result[1]} ({result[3]}%)")
    print(f"Missing Category:      {result[2]} ({100-result[3]:.2f}%)")
    print(f"Avg Volume:            ${result[4]:,.2f}")
    print(f"Volume Range:          ${result[5]:,.2f} - ${result[6]:,.2f}")

# ========================================
# AUDIT 3: Top 500 by Liquidity
# ========================================
print("\n" + "=" * 80)
print("3️⃣  TOP 500 MARKETS BY LIQUIDITY")
print("=" * 80)

query = text("""
SELECT 
  COUNT(*) as total_markets,
  COUNT(CASE WHEN category IS NOT NULL AND category != '' THEN 1 END) as has_category,
  COUNT(CASE WHEN category IS NULL OR category = '' THEN 1 END) as missing_category,
  ROUND(100.0 * COUNT(CASE WHEN category IS NOT NULL AND category != '' THEN 1 END) / COUNT(*), 2) as pct_with_category,
  ROUND(AVG(liquidity), 2) as avg_liquidity,
  ROUND(MIN(liquidity), 2) as min_liquidity,
  ROUND(MAX(liquidity), 2) as max_liquidity
FROM (
  SELECT id, question, category, liquidity
  FROM markets
  WHERE liquidity IS NOT NULL
  ORDER BY liquidity DESC
  LIMIT 500
) top_500;
""")

with engine.connect() as conn:
    result = conn.execute(query).fetchone()
    print(f"Total Markets:         {result[0]}")
    print(f"With Category:         {result[1]} ({result[3]}%)")
    print(f"Missing Category:      {result[2]} ({100-result[3]:.2f}%)")
    print(f"Avg Liquidity:         ${result[4]:,.2f}")
    print(f"Liquidity Range:       ${result[5]:,.2f} - ${result[6]:,.2f}")

# ========================================
# AUDIT 4: Top 500 by Combined Score
# ========================================
print("\n" + "=" * 80)
print("4️⃣  TOP 500 MARKETS BY VOLUME + LIQUIDITY")
print("=" * 80)

query = text("""
SELECT 
  COUNT(*) as total_markets,
  COUNT(CASE WHEN category IS NOT NULL AND category != '' THEN 1 END) as has_category,
  COUNT(CASE WHEN category IS NULL OR category = '' THEN 1 END) as missing_category,
  ROUND(100.0 * COUNT(CASE WHEN category IS NOT NULL AND category != '' THEN 1 END) / COUNT(*), 2) as pct_with_category,
  ROUND(AVG(priority_score), 2) as avg_priority_score
FROM (
  SELECT 
    id, 
    question, 
    category,
    (COALESCE(volume, 0) + COALESCE(liquidity, 0)) as priority_score
  FROM markets
  ORDER BY (COALESCE(volume, 0) + COALESCE(liquidity, 0)) DESC
  LIMIT 500
) top_500;
""")

with engine.connect() as conn:
    result = conn.execute(query).fetchone()
    print(f"Total Markets:         {result[0]}")
    print(f"With Category:         {result[1]} ({result[3]}%)")
    print(f"Missing Category:      {result[2]} ({100-result[3]:.2f}%)")
    print(f"Avg Priority Score:    ${result[4]:,.2f}")

# ========================================
# AUDIT 5: Recent Markets (Last 7 Days)
# ========================================
print("\n" + "=" * 80)
print("5️⃣  NEW MARKETS (LAST 7 DAYS)")
print("=" * 80)

query = text("""
SELECT 
  CASE 
    WHEN created_at >= NOW() - INTERVAL '1 day' THEN 'Last 24 hours'
    WHEN created_at >= NOW() - INTERVAL '2 days' THEN '1-2 days ago'
    WHEN created_at >= NOW() - INTERVAL '3 days' THEN '2-3 days ago'
    WHEN created_at >= NOW() - INTERVAL '7 days' THEN '3-7 days ago'
  END as time_period,
  COUNT(*) as total_markets,
  COUNT(CASE WHEN category IS NOT NULL AND category != '' THEN 1 END) as has_category,
  COUNT(CASE WHEN category IS NULL OR category = '' THEN 1 END) as missing_category,
  ROUND(100.0 * COUNT(CASE WHEN category IS NULL OR category = '' THEN 1 END) / COUNT(*), 2) as pct_missing
FROM markets
WHERE created_at >= NOW() - INTERVAL '7 days'
GROUP BY time_period
ORDER BY MIN(created_at) DESC;
""")

with engine.connect() as conn:
    results = conn.execute(query).fetchall()
    for row in results:
        print(f"\n{row[0]}:")
        print(f"  Total:               {row[1]:,}")
        print(f"  With Category:       {row[2]:,}")
        print(f"  Missing Category:    {row[3]:,} ({row[4]}%)")

# ========================================
# AUDIT 6: Category Distribution
# ========================================
print("\n" + "=" * 80)
print("6️⃣  CATEGORY DISTRIBUTION (Markets with Categories)")
print("=" * 80)

query = text("""
SELECT 
  category,
  COUNT(*) as market_count,
  ROUND(AVG(volume), 2) as avg_volume,
  ROUND(SUM(volume), 2) as total_volume,
  ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER(), 2) as pct_of_categorized
FROM markets
WHERE category IS NOT NULL AND category != ''
GROUP BY category
ORDER BY market_count DESC;
""")

with engine.connect() as conn:
    results = conn.execute(query).fetchall()
    for row in results:
        print(f"\n{row[0]}:")
        print(f"  Markets:             {row[1]:,} ({row[4]}%)")
        print(f"  Avg Volume:          ${row[2]:,.2f}")
        print(f"  Total Volume:        ${row[3]:,.2f}")

# ========================================
# AUDIT 7: Top 20 Uncategorized Markets
# ========================================
print("\n" + "=" * 80)
print("7️⃣  TOP 20 UNCATEGORIZED MARKETS (By Volume)")
print("=" * 80)

query = text("""
SELECT 
  id,
  LEFT(question, 60) as question_preview,
  ROUND(volume, 2) as volume,
  ROUND(liquidity, 2) as liquidity,
  status,
  created_at::date as created_date
FROM markets
WHERE (category IS NULL OR category = '')
  AND volume IS NOT NULL
ORDER BY volume DESC
LIMIT 20;
""")

with engine.connect() as conn:
    results = conn.execute(query).fetchall()
    print(f"\n{'ID':<10} {'Question':<62} {'Volume':<12} {'Liquidity':<12} {'Status':<10}")
    print("-" * 120)
    for row in results:
        q = row[1][:60] + "..." if len(row[1]) > 60 else row[1]
        print(f"{row[0]:<10} {q:<62} ${row[2]:<11,.0f} ${row[3]:<11,.0f} {row[4]:<10}")

# ========================================
# SUMMARY & RECOMMENDATIONS
# ========================================
print("\n" + "=" * 80)
print("📋 SUMMARY & RECOMMENDATIONS")
print("=" * 80)

# Get key stats for recommendations
query = text("""
WITH stats AS (
  SELECT 
    COUNT(*) FILTER (WHERE (category IS NULL OR category = '') AND volume > 50000) as high_vol_no_cat,
    COUNT(*) FILTER (WHERE (category IS NULL OR category = '') AND created_at >= NOW() - INTERVAL '7 days') as recent_no_cat,
    COUNT(*) FILTER (WHERE category IS NOT NULL AND category != '') as total_with_cat
  FROM markets
)
SELECT * FROM stats;
""")

with engine.connect() as conn:
    stats = conn.execute(query).fetchone()
    high_vol_uncategorized = stats[0]
    recent_uncategorized = stats[1]
    total_categorized = stats[2]
    
    print(f"\n🔴 CRITICAL ISSUES:")
    print(f"   • {high_vol_uncategorized:,} high-volume markets (>$50K) have no category")
    print(f"   • {recent_uncategorized:,} markets added in last 7 days have no category")
    print(f"   • Only {total_categorized:,} total markets have categories")
    
    print(f"\n✅ RECOMMENDED ACTIONS:")
    print(f"   1. Backfill top 500 markets by volume immediately")
    print(f"   2. Backfill recent markets (last 7 days)")
    print(f"   3. Enable automatic categorization for new markets")
    print(f"   4. Run weekly backfill for markets that got popular")
    
    print(f"\n💰 ESTIMATED COST (OpenAI GPT-4o-mini):")
    total_to_categorize = high_vol_uncategorized + recent_uncategorized
    cost_per_call = 0.0001  # ~$0.0001 per call with gpt-4o-mini
    estimated_cost = total_to_categorize * cost_per_call
    print(f"   • Markets to categorize: ~{total_to_categorize:,}")
    print(f"   • Estimated cost: ~${estimated_cost:.2f}")
    print(f"   • Processing time: ~{total_to_categorize // 60} minutes (1 call/sec)")

print("\n" + "=" * 80)
print("✅ AUDIT COMPLETE")
print("=" * 80 + "\n")

