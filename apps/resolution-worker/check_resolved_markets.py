"""
Quick script to check how many resolved markets are available to process
Run this before deploying to verify there's data to work with
"""

import os
import sys
from sqlalchemy import create_engine, text

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    print("❌ DATABASE_URL environment variable not set")
    sys.exit(1)

db = create_engine(DATABASE_URL, pool_pre_ping=True)

print("🔍 Checking resolved markets status...\n")

# Check 1: Recently resolved markets
query1 = text("""
    SELECT COUNT(*) as count
    FROM subsquid_markets_poll
    WHERE resolution_status = 'RESOLVED'
      AND resolution_date > NOW() - INTERVAL '24 hours'
""")

with db.connect() as conn:
    result = conn.execute(query1).fetchone()
    count_24h = result[0]
    print(f"📊 Markets resolved in last 24 hours: {count_24h}")

# Check 2: All resolved markets
query2 = text("""
    SELECT COUNT(*) as count
    FROM subsquid_markets_poll
    WHERE resolution_status = 'RESOLVED'
""")

with db.connect() as conn:
    result = conn.execute(query2).fetchone()
    count_total = result[0]
    print(f"📊 Total resolved markets: {count_total}")

# Check 3: Sample of recently resolved markets
query3 = text("""
    SELECT
        market_id,
        title,
        winning_outcome,
        resolution_date
    FROM subsquid_markets_poll
    WHERE resolution_status = 'RESOLVED'
      AND resolution_date > NOW() - INTERVAL '7 days'
    ORDER BY resolution_date DESC
    LIMIT 5
""")

print(f"\n📋 Sample of recently resolved markets:")
print("-" * 80)

with db.connect() as conn:
    results = conn.execute(query3).fetchall()
    for row in results:
        market_id = row[0]
        title = row[1][:60] + "..." if len(row[1]) > 60 else row[1]
        outcome = "YES" if row[2] == 1 else "NO" if row[2] == 0 else "UNKNOWN"
        resolved_at = row[3].strftime("%Y-%m-%d %H:%M") if row[3] else "N/A"
        print(f"  {market_id[:8]}... | {outcome:3} | {resolved_at} | {title}")

# Check 4: Users with positions in resolved markets
query4 = text("""
    SELECT COUNT(DISTINCT u.telegram_user_id) as user_count
    FROM subsquid_user_transactions_v2 t
    JOIN users u ON t.user_address = u.polygon_address
    JOIN subsquid_markets_poll m ON t.market_id = m.market_id
    WHERE m.resolution_status = 'RESOLVED'
      AND m.resolution_date > NOW() - INTERVAL '24 hours'
      AND u.telegram_user_id IS NOT NULL
""")

with db.connect() as conn:
    result = conn.execute(query4).fetchone()
    user_count = result[0]
    print(f"\n👥 Users with positions in recently resolved markets: {user_count}")

# Check 5: Already processed positions
query5 = text("""
    SELECT COUNT(*) as count
    FROM resolved_positions
    WHERE created_at > NOW() - INTERVAL '24 hours'
""")

with db.connect() as conn:
    result = conn.execute(query5).fetchone()
    processed_count = result[0]
    print(f"✅ Already processed positions (last 24h): {processed_count}")

print("\n" + "="*80)
if count_24h > 0 and user_count > 0:
    print("✅ System ready! There are markets to process.")
    if processed_count > 0:
        print(f"ℹ️  Note: {processed_count} positions already processed (worker may have run)")
else:
    print("⚠️  No recently resolved markets found.")
    print("   Either wait for markets to resolve, or increase lookback window for testing.")
