#!/usr/bin/env python3
"""
Cleanup Legacy TP/SL Orders with Invalid Market IDs
"""

import os
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from dotenv import load_dotenv
import psycopg2

load_dotenv()

DATABASE_URL = os.getenv('DATABASE_URL')

if not DATABASE_URL:
    print("❌ DATABASE_URL not found in environment")
    sys.exit(1)

print("="*80)
print("🧹 Cleanup Legacy TP/SL Orders Migration")
print("="*80)

conn = psycopg2.connect(DATABASE_URL)
cursor = conn.cursor()

# Step 1: Count legacy orders
print("\n📊 Step 1: Counting legacy TP/SL orders...")
cursor.execute("""
    SELECT COUNT(*)
    FROM tpsl_orders
    WHERE market_id LIKE '0x%' AND LENGTH(market_id) > 50
""")

legacy_count = cursor.fetchone()[0]
print(f"   Found {legacy_count} legacy orders with hash market_ids")

if legacy_count == 0:
    print("   ✅ No legacy orders to clean up!")
    cursor.close()
    conn.close()
    sys.exit(0)

# Step 2: Show examples
print("\n📋 Step 2: Examples of legacy orders:")
cursor.execute("""
    SELECT id, user_id, market_id, outcome, status, created_at
    FROM tpsl_orders
    WHERE market_id LIKE '0x%' AND LENGTH(market_id) > 50
    ORDER BY created_at DESC
    LIMIT 5
""")

for order_id, user_id, market_id, outcome, status, created_at in cursor.fetchall():
    print(f"   Order {order_id}: market_id={market_id[:30]}... status={status} created={created_at}")

# Step 3: Ask for confirmation
print("\n⚠️  Step 3: Confirmation")
print(f"   This will DELETE {legacy_count} legacy TP/SL orders")
print(f"   These orders reference markets that no longer exist")

response = input("\n   Continue? (yes/no): ")

if response.lower() != 'yes':
    print("   ❌ Cancelled by user")
    cursor.close()
    conn.close()
    sys.exit(0)

# Step 4: Optional - Archive first
print("\n💾 Step 4: Archive legacy orders (optional)")
archive_response = input("   Archive before deletion? (yes/no): ")

if archive_response.lower() == 'yes':
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tpsl_orders_archive AS
        SELECT * FROM tpsl_orders WHERE market_id LIKE '0x%' AND LENGTH(market_id) > 50
    """)
    conn.commit()
    print(f"   ✅ Archived {legacy_count} orders to tpsl_orders_archive")

# Step 5: Delete legacy orders
print("\n🧹 Step 5: Deleting legacy orders...")
cursor.execute("""
    DELETE FROM tpsl_orders
    WHERE market_id LIKE '0x%' AND LENGTH(market_id) > 50
""")

deleted_count = cursor.rowcount
conn.commit()

print(f"   ✅ Deleted {deleted_count} legacy orders")

# Step 6: Verify
print("\n✅ Step 6: Verification")
cursor.execute("SELECT COUNT(*) FROM tpsl_orders WHERE market_id LIKE '0x%' AND LENGTH(market_id) > 50")
remaining = cursor.fetchone()[0]

cursor.execute("SELECT COUNT(*) FROM tpsl_orders WHERE status = 'active'")
active_count = cursor.fetchone()[0]

print(f"   Legacy orders remaining: {remaining}")
print(f"   Active TP/SL orders: {active_count}")

cursor.close()
conn.close()

print("\n" + "="*80)
print("✅ Cleanup migration completed successfully!")
print("="*80)
