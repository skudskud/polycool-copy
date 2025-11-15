#!/usr/bin/env python3
"""
Check which Solana private key columns have data
"""
import os
import sys

# Must set DATABASE_URL before importing anything else
if 'DATABASE_URL' not in os.environ:
    db_url = os.getenv('DATABASE_PUBLIC_URL')
    if db_url:
        os.environ['DATABASE_URL'] = db_url

from sqlalchemy import create_engine, text

def check_key_columns():
    """Check which columns have data for user"""
    user_id = 1015699261
    
    # Get database URL
    db_url = os.getenv('DATABASE_PUBLIC_URL') or os.getenv('DATABASE_URL')
    if not db_url:
        print("❌ DATABASE_URL not set!")
        sys.exit(1)
    
    print(f"📊 Checking Solana key columns for user {user_id}...")
    engine = create_engine(db_url)
    
    with engine.begin() as conn:
        result = conn.execute(text("""
            SELECT 
                solana_address,
                length(solana_private_key) as key_length,
                length(solana_private_key_encrypted) as key_encrypted_length,
                length(solana_private_key_plaintext_backup) as key_backup_length,
                substring(solana_private_key, 1, 50) as key_preview,
                substring(solana_private_key_encrypted, 1, 50) as key_encrypted_preview,
                substring(solana_private_key_plaintext_backup, 1, 50) as key_backup_preview
            FROM users
            WHERE telegram_user_id = :uid
        """), {"uid": user_id})
        
        row = result.fetchone()
        if not row:
            print(f"❌ User {user_id} not found!")
            return
        
        print(f"\n" + "="*80)
        print(f"📋 SOLANA KEY COLUMNS FOR USER {user_id}")
        print("="*80)
        print(f"\n📍 Address: {row[0]}")
        print(f"\n🔑 Column: solana_private_key")
        print(f"   Length: {row[1] if row[1] else 0} chars")
        print(f"   Preview: {row[4] if row[4] else 'NULL'}...")
        
        print(f"\n🔐 Column: solana_private_key_encrypted")
        print(f"   Length: {row[2] if row[2] else 0} chars")
        print(f"   Preview: {row[5] if row[5] else 'NULL'}...")
        
        print(f"\n📝 Column: solana_private_key_plaintext_backup")
        print(f"   Length: {row[3] if row[3] else 0} chars")
        print(f"   Preview: {row[6] if row[6] else 'NULL'}...")
        
        print(f"\n" + "="*80)
        print(f"💡 ANALYSIS")
        print("="*80)
        
        # Check which column has encrypted data (base64, ~156 chars)
        if row[1] and row[1] > 100:
            print(f"✅ solana_private_key has ENCRYPTED data ({row[1]} chars)")
        elif row[1]:
            print(f"⚠️  solana_private_key has SHORT data ({row[1]} chars) - might be plaintext?")
        else:
            print(f"❌ solana_private_key is EMPTY")
            
        if row[2]:
            print(f"⚠️  solana_private_key_encrypted has data ({row[2]} chars) - DUPLICATE COLUMN!")
        else:
            print(f"✅ solana_private_key_encrypted is empty (good)")
            
        if row[3]:
            print(f"✅ solana_private_key_plaintext_backup has backup ({row[3]} chars)")
        else:
            print(f"⚠️  solana_private_key_plaintext_backup is empty")

if __name__ == "__main__":
    check_key_columns()

