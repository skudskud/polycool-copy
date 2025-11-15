#!/usr/bin/env python3
"""
Backfill condition_id with proper 0x format
Converts token_id (decimal) → condition_id (0x hex)
"""

import os
import sys
from sqlalchemy import create_engine, text
from datetime import datetime

# Database URL from environment
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    print("❌ DATABASE_URL not set")
    sys.exit(1)

def token_id_to_condition_id(token_id_str):
    """Convert decimal token_id to 0x condition_id"""
    try:
        token_id_int = int(token_id_str)
        hex_str = hex(token_id_int)[2:]
        return "0x" + hex_str.zfill(64)
    except:
        return None

# Connect to database
engine = create_engine(DATABASE_URL)

with engine.connect() as conn:
    # Get trades with wrong format
    result = conn.execute(text("""
        SELECT id, market_id, condition_id
        FROM smart_wallet_trades
        WHERE created_at >= NOW() - INTERVAL '3 days'
          AND market_id IS NOT NULL
          AND (condition_id IS NULL 
               OR LENGTH(condition_id) != 66 
               OR SUBSTRING(condition_id, 1, 2) != '0x')
        LIMIT 1000
    """))
    
    trades = result.fetchall()
    print(f"Found {len(trades)} trades to fix")
    
    # Update each trade
    fixed = 0
    for trade in trades:
        trade_id, market_id, old_condition_id = trade
        
        # Convert
        new_condition_id = token_id_to_condition_id(market_id)
        
        if new_condition_id:
            conn.execute(text("""
                UPDATE smart_wallet_trades
                SET condition_id = :new_id
                WHERE id = :trade_id
            """), {"new_id": new_condition_id, "trade_id": trade_id})
            
            fixed += 1
            if fixed % 100 == 0:
                print(f"Fixed {fixed}/{len(trades)}...")
                conn.commit()
    
    conn.commit()
    print(f"✅ Fixed {fixed} trades")
    
    # Verify
    result = conn.execute(text("""
        SELECT 
            COUNT(*) as total,
            COUNT(CASE WHEN SUBSTRING(condition_id, 1, 2) = '0x' THEN 1 END) as with_0x
        FROM smart_wallet_trades
        WHERE created_at >= NOW() - INTERVAL '24 hours'
    """))
    
    stats = result.fetchone()
    print(f"📊 Last 24h: {stats[1]}/{stats[0]} ({100*stats[1]/stats[0]:.1f}%) have 0x format")

