#!/usr/bin/env python3
"""
Active Markets Category Audit
Focus on ACTIVE markets only - no need to categorize closed/resolved markets
"""

import os
from dotenv import load_dotenv
import psycopg2
from datetime import datetime

load_dotenv()
DATABASE_URL = os.getenv('DATABASE_URL')

if not DATABASE_URL:
    print("❌ DATABASE_URL not found")
    print("💡 Make sure you have a .env file with DATABASE_URL")
    exit(1)

conn = psycopg2.connect(DATABASE_URL)
cur = conn.cursor()

print("=" * 80)
print("📊 ACTIVE MARKETS CATEGORY AUDIT")
print("=" * 80)
print(f"🕐 Timestamp: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC\n")

# ========================================
# AUDIT 1: Overall Market Status Distribution
# ========================================
print("\n" + "=" * 80)
print("1️⃣  MARKET STATUS DISTRIBUTION")
print("=" * 80)

cur.execute("""
SELECT 
  status,
  COUNT(*) as market_count,
  COUNT(CASE WHEN category IS NOT NULL AND category != '' THEN 1 END) as with_category,
  COUNT(CASE WHEN category IS NULL OR category = '' THEN 1 END) as without_category,
  ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER(), 2) as pct_of_total,
  ROUND(100.0 * COUNT(CASE WHEN category IS NOT NULL AND category != '' THEN 1 END) / COUNT(*), 2) as pct_categorized
FROM markets
GROUP BY status
ORDER BY market_count DESC;
""")

results = cur.fetchall()
print(f"\n{'Status':<20} {'Count':<10} {'With Cat':<10} {'No Cat':<10} {'% Total':<10} {'% Cat':<10}")
print("-" * 80)
for row in results:
    status, count, with_cat, without_cat, pct_total, pct_cat = row
    pct_cat_val = pct_cat if pct_cat is not None else 0
    print(f"{status:<20} {count:<10,} {with_cat:<10,} {without_cat:<10,} {pct_total:<10.2f}% {pct_cat_val:<10.2f}%")

# ========================================
# AUDIT 2: Active vs Closed Markets
# ========================================
print("\n" + "=" * 80)
print("2️⃣  ACTIVE vs CLOSED MARKETS (Category Health)")
print("=" * 80)

cur.execute("""
SELECT 
  CASE 
    WHEN active = true THEN 'ACTIVE'
    WHEN closed = true THEN 'CLOSED'
    ELSE 'OTHER'
  END as market_state,
  COUNT(*) as total_markets,
  COUNT(CASE WHEN category IS NOT NULL AND category != '' THEN 1 END) as with_category,
  COUNT(CASE WHEN category IS NULL OR category = '' THEN 1 END) as without_category,
  ROUND(100.0 * COUNT(CASE WHEN category IS NOT NULL AND category != '' THEN 1 END) / COUNT(*), 2) as pct_with_category,
  ROUND(AVG(volume), 2) as avg_volume
FROM markets
GROUP BY market_state
ORDER BY total_markets DESC;
""")

results = cur.fetchall()
for row in results:
    state, total, with_cat, without_cat, pct_with, avg_vol = row
    pct_with_val = pct_with if pct_with is not None else 0
    avg_vol_val = avg_vol if avg_vol is not None else 0
    print(f"\n{state}:")
    print(f"  Total Markets:       {total:,}")
    print(f"  With Category:       {with_cat:,} ({pct_with_val}%)")
    print(f"  Without Category:    {without_cat:,} ({100-pct_with_val:.2f}%)")
    print(f"  Avg Volume:          ${avg_vol_val:,.2f}")

# ========================================
# AUDIT 3: Active Markets Only - Detailed Breakdown
# ========================================
print("\n" + "=" * 80)
print("3️⃣  ACTIVE MARKETS ONLY - Full Breakdown")
print("=" * 80)

cur.execute("""
SELECT 
  COUNT(*) as total_active,
  COUNT(CASE WHEN category IS NOT NULL AND category != '' THEN 1 END) as with_category,
  COUNT(CASE WHEN category IS NULL OR category = '' THEN 1 END) as without_category,
  ROUND(100.0 * COUNT(CASE WHEN category IS NOT NULL AND category != '' THEN 1 END) / COUNT(*), 2) as pct_with_category,
  ROUND(AVG(volume), 2) as avg_volume,
  ROUND(SUM(volume), 2) as total_volume,
  COUNT(CASE WHEN volume > 50000 THEN 1 END) as high_volume_count,
  COUNT(CASE WHEN volume > 50000 AND (category IS NULL OR category = '') THEN 1 END) as high_volume_no_cat
FROM markets
WHERE active = true;
""")

result = cur.fetchone()
total, with_cat, without_cat, pct_with, avg_vol, total_vol, high_vol, high_vol_no_cat = result
pct_with_val = pct_with if pct_with is not None else 0
avg_vol_val = avg_vol if avg_vol is not None else 0
total_vol_val = total_vol if total_vol is not None else 0

print(f"\nTotal Active Markets:              {total:,}")
print(f"With Category:                     {with_cat:,} ({pct_with_val}%)")
print(f"Without Category:                  {without_cat:,} ({100-pct_with_val:.2f}%)")
print(f"Avg Volume:                        ${avg_vol_val:,.2f}")
print(f"Total Volume:                      ${total_vol_val:,.2f}")
print(f"\nHigh-Volume Active (>$50K):        {high_vol:,}")
print(f"High-Volume WITHOUT Category:      {high_vol_no_cat:,}")

# ========================================
# AUDIT 4: Top 500 ACTIVE Markets by Volume
# ========================================
print("\n" + "=" * 80)
print("4️⃣  TOP 500 ACTIVE MARKETS (By Volume)")
print("=" * 80)

cur.execute("""
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
  WHERE active = true AND volume IS NOT NULL
  ORDER BY volume DESC
  LIMIT 500
) top_500;
""")

result = cur.fetchone()
total, has_cat, missing, pct_with, avg_vol, min_vol, max_vol = result
pct_with_val = pct_with if pct_with is not None else 0

print(f"\nTotal Markets:                     {total}")
print(f"With Category:                     {has_cat} ({pct_with_val}%)")
print(f"Missing Category:                  {missing} ({100-pct_with_val:.2f}%)")
print(f"Avg Volume:                        ${avg_vol:,.2f}")
print(f"Volume Range:                      ${min_vol:,.2f} - ${max_vol:,.2f}")

# ========================================
# AUDIT 5: Top 500 ACTIVE Markets by Liquidity
# ========================================
print("\n" + "=" * 80)
print("5️⃣  TOP 500 ACTIVE MARKETS (By Liquidity)")
print("=" * 80)

cur.execute("""
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
  WHERE active = true AND liquidity IS NOT NULL
  ORDER BY liquidity DESC
  LIMIT 500
) top_500;
""")

result = cur.fetchone()
total, has_cat, missing, pct_with, avg_liq, min_liq, max_liq = result
pct_with_val = pct_with if pct_with is not None else 0

print(f"\nTotal Markets:                     {total}")
print(f"With Category:                     {has_cat} ({pct_with_val}%)")
print(f"Missing Category:                  {missing} ({100-pct_with_val:.2f}%)")
print(f"Avg Liquidity:                     ${avg_liq:,.2f}")
print(f"Liquidity Range:                   ${min_liq:,.2f} - ${max_liq:,.2f}")

# ========================================
# AUDIT 6: Active Markets Created in Last 7 Days
# ========================================
print("\n" + "=" * 80)
print("6️⃣  ACTIVE MARKETS CREATED IN LAST 7 DAYS")
print("=" * 80)

cur.execute("""
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
  AND active = true
GROUP BY time_period
ORDER BY MIN(created_at) DESC;
""")

results = cur.fetchall()
for row in results:
    period, total, has_cat, missing, pct_missing = row
    pct_missing_val = pct_missing if pct_missing is not None else 0
    print(f"\n{period}:")
    print(f"  Total:                           {total:,}")
    print(f"  With Category:                   {has_cat:,}")
    print(f"  Missing Category:                {missing:,} ({pct_missing_val}%)")

# ========================================
# AUDIT 7: Sample Top 20 Active Uncategorized Markets
# ========================================
print("\n" + "=" * 80)
print("7️⃣  TOP 20 ACTIVE UNCATEGORIZED MARKETS (By Volume)")
print("=" * 80)

cur.execute("""
SELECT 
  id,
  LEFT(question, 55) as question_preview,
  ROUND(volume::numeric, 2) as volume,
  ROUND(liquidity::numeric, 2) as liquidity,
  status,
  created_at::date as created_date
FROM markets
WHERE (category IS NULL OR category = '')
  AND active = true
  AND volume IS NOT NULL
ORDER BY volume DESC
LIMIT 20;
""")

results = cur.fetchall()
print(f"\n{'ID':<10} {'Question':<57} {'Volume':<12} {'Liquidity':<12}")
print("-" * 110)
for row in results:
    mid, question, vol, liq, status, created = row
    vol_val = float(vol) if vol is not None else 0
    liq_val = float(liq) if liq is not None else 0
    q = question[:55] + "..." if len(question) > 55 else question
    print(f"{mid:<10} {q:<57} ${vol_val:<11,.0f} ${liq_val:<11,.0f}")

# ========================================
# SUMMARY & RECOMMENDATIONS
# ========================================
print("\n" + "=" * 80)
print("📋 SUMMARY & ACTION PLAN")
print("=" * 80)

cur.execute("""
WITH active_stats AS (
  SELECT 
    COUNT(*) as total_active,
    COUNT(CASE WHEN category IS NULL OR category = '' THEN 1 END) as active_no_cat,
    COUNT(CASE WHEN (category IS NULL OR category = '') AND volume > 50000 THEN 1 END) as active_high_vol_no_cat,
    COUNT(CASE WHEN (category IS NULL OR category = '') AND created_at >= NOW() - INTERVAL '7 days' THEN 1 END) as active_recent_no_cat
  FROM markets
  WHERE active = true
)
SELECT * FROM active_stats;
""")

stats = cur.fetchone()
total_active, active_uncategorized, active_high_vol_uncategorized, active_recent_uncategorized = stats

print(f"\n🎯 FOCUS AREAS (Active Markets Only):")
print(f"   • Total Active Markets: {total_active:,}")
print(f"   • Active WITHOUT Category: {active_uncategorized:,} ({100*active_uncategorized/total_active:.1f}%)")
print(f"   • Active High-Volume (>$50K) without category: {active_high_vol_uncategorized:,}")
print(f"   • Active Recent (7 days) without category: {active_recent_uncategorized:,}")

print(f"\n✅ RECOMMENDED CATEGORIZATION TARGETS:")
print(f"   1. Top 500 active markets by volume: ~500 markets")
print(f"   2. Active high-volume markets (>$50K): ~{active_high_vol_uncategorized:,} markets")
print(f"   3. Active recent markets (7 days): ~{active_recent_uncategorized:,} markets")

# Deduplicated total estimate
estimated_total = min(active_uncategorized, 
                     500 + active_high_vol_uncategorized + active_recent_uncategorized)

print(f"\n💰 ESTIMATED COST (Active Markets Only):")
cost_per_call = 0.0001  # GPT-4o-mini
estimated_cost = estimated_total * cost_per_call
print(f"   • Markets to categorize: ~{estimated_total:,}")
print(f"   • Estimated cost: ~${estimated_cost:.2f}")
print(f"   • Processing time: ~{estimated_total // 60} minutes")

print(f"\n🎯 WHY FOCUS ON ACTIVE ONLY:")
print(f"   • Closed/resolved markets don't need categories (static)")
print(f"   • Active markets are what users see and trade")
print(f"   • Saves ~{100*(1 - total_active/26167):.0f}% of categorization effort")

print("\n" + "=" * 80)
print("✅ AUDIT COMPLETE")
print("=" * 80 + "\n")

cur.close()
conn.close()
