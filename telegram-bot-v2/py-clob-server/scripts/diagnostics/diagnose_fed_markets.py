#!/usr/bin/env python3
"""
Diagnostic script to check Fed decision markets in Railway DB
"""
import sys
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Add the project root to the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import create_engine, text
from database import DATABASE_URL

print("=" * 80)
print("🔍 DIAGNOSTIC: Fed Decision Markets in Railway DB")
print("=" * 80)

engine = create_engine(DATABASE_URL)

with engine.connect() as conn:
    # 1. Check table structure
    print("\n1️⃣ Checking 'markets' table columns:")
    result = conn.execute(text("""
        SELECT column_name, data_type, is_nullable
        FROM information_schema.columns
        WHERE table_name = 'markets'
        AND column_name IN ('event_id', 'event_slug', 'event_title')
        ORDER BY column_name;
    """))
    columns = result.fetchall()
    
    if columns:
        print("✅ Event columns exist:")
        for col in columns:
            print(f"   - {col[0]}: {col[1]} (nullable: {col[2]})")
    else:
        print("❌ Event columns NOT FOUND in table!")
        sys.exit(1)
    
    # 2. Search for Fed markets
    print("\n2️⃣ Searching for Fed decision markets:")
    result = conn.execute(text("""
        SELECT 
            id,
            question,
            slug,
            volume,
            event_id,
            event_slug,
            event_title,
            active,
            closed
        FROM markets
        WHERE (
            question ILIKE '%fed%october%'
            OR slug ILIKE '%fed%october%'
        )
        AND active = true
        AND closed = false
        ORDER BY volume DESC
        LIMIT 10;
    """))
    
    markets = result.fetchall()
    
    if not markets:
        print("❌ No Fed markets found!")
        sys.exit(1)
    
    print(f"✅ Found {len(markets)} Fed markets:")
    for m in markets:
        print(f"\n   Market ID: {m[0]}")
        print(f"   Question: {m[1][:60]}...")
        print(f"   Slug: {m[2]}")
        print(f"   Volume: ${m[3]:,.2f}")
        print(f"   Event ID: {m[4]}")
        print(f"   Event Slug: {m[5]}")
        print(f"   Event Title: {m[6]}")
        print(f"   Active: {m[7]}, Closed: {m[8]}")
    
    # 3. Check if they have the same event_id or similar slugs
    print("\n3️⃣ Grouping analysis:")
    
    # Group by event_id
    result = conn.execute(text("""
        SELECT 
            event_id,
            COUNT(*) as count,
            STRING_AGG(DISTINCT question, ' | ') as questions
        FROM markets
        WHERE (
            question ILIKE '%fed%october%'
            OR slug ILIKE '%fed%october%'
        )
        AND active = true
        AND closed = false
        GROUP BY event_id
        ORDER BY count DESC;
    """))
    
    groups = result.fetchall()
    print(f"\nGrouping by event_id: {len(groups)} groups")
    for g in groups:
        print(f"   Event ID '{g[0]}': {g[1]} markets")
    
    # Group by slug pattern
    result = conn.execute(text("""
        SELECT 
            SUBSTRING(slug FROM '^[^-]+-[^-]+-[^-]+-[^-]+') as slug_prefix,
            COUNT(*) as count,
            STRING_AGG(slug, ', ') as slugs
        FROM markets
        WHERE (
            question ILIKE '%fed%october%'
            OR slug ILIKE '%fed%october%'
        )
        AND active = true
        AND closed = false
        GROUP BY slug_prefix
        HAVING COUNT(*) >= 2
        ORDER BY count DESC;
    """))
    
    slug_groups = result.fetchall()
    print(f"\nGrouping by slug pattern: {len(slug_groups)} groups")
    for g in slug_groups:
        print(f"   Slug prefix '{g[0]}': {g[1]} markets")
        print(f"      Slugs: {g[2]}")

print("\n" + "=" * 80)
print("✅ Diagnostic complete!")
print("=" * 80)

