#!/usr/bin/env python3
"""
EMERGENCY FIX: Generate new Solana wallet and update Railway database
Fixes the keypair mismatch issue for user 1015699261

CRITICAL: This script MUST use the EncryptionService to encrypt the private key
before storing it in the database, otherwise decryption will fail later!
"""
import os
import sys

# Must set DATABASE_URL before importing anything else
if 'DATABASE_URL' not in os.environ:
    db_url = os.getenv('DATABASE_PUBLIC_URL')
    if db_url:
        os.environ['DATABASE_URL'] = db_url

from solders.keypair import Keypair
import base58
from sqlalchemy import create_engine, text

# Import encryption service (this is the critical part!)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + '/..')
from core.services.encryption_service import encryption_service

def fix_solana_wallet():
    """Generate new Solana wallet and update database WITH PROPER ENCRYPTION"""
    user_id = 1015699261
    
    print(f"🔧 Generating NEW Solana wallet for user {user_id}...")
    
    # Generate NEW keypair
    new_keypair = Keypair()
    new_address = str(new_keypair.pubkey())
    new_private_key = base58.b58encode(bytes(new_keypair)).decode('ascii')
    
    print(f"\n✅ NEW Wallet Generated:")
    print(f"   Address: {new_address}")
    print(f"   Private Key: {new_private_key[:20]}...{new_private_key[-20:]}")
    
    # Verify the keypair is correct
    test_keypair = Keypair.from_bytes(base58.b58decode(new_private_key))
    test_address = str(test_keypair.pubkey())
    
    if test_address != new_address:
        print(f"❌ VERIFICATION FAILED! Address mismatch!")
        sys.exit(1)
    
    print(f"✅ Verification passed: {test_address}")
    
    # CRITICAL: Encrypt the private key using the encryption service
    print(f"\n🔐 Encrypting private key...")
    try:
        encrypted_private_key = encryption_service.encrypt(new_private_key, context="wallet_fix")
        print(f"✅ Encryption successful: {len(encrypted_private_key)} chars")
    except Exception as e:
        print(f"❌ Encryption failed: {e}")
        sys.exit(1)
    
    # Get database URL
    db_url = os.getenv('DATABASE_PUBLIC_URL') or os.getenv('DATABASE_URL')
    if not db_url:
        print("❌ DATABASE_URL not set!")
        sys.exit(1)
    
    print(f"\n📊 Connecting to database...")
    engine = create_engine(db_url)
    
    with engine.begin() as conn:
        # First, get OLD address for user reference
        result = conn.execute(text("""
            SELECT solana_address, solana_private_key_plaintext_backup
            FROM users
            WHERE telegram_user_id = :uid
        """), {"uid": user_id})
        
        row = result.fetchone()
        if row:
            old_address = row[0]
            old_backup = row[1]
            print(f"\n📋 OLD Wallet Info:")
            print(f"   Address: {old_address}")
            print(f"   Has backup: {bool(old_backup)}")
        
        # Update with NEW wallet (ENCRYPTED!)
        # Store encrypted key in solana_private_key column
        # Store plaintext in backup column for emergency recovery
        conn.execute(text("""
            UPDATE users
            SET solana_address = :new_addr,
                solana_private_key = :encrypted_key,
                solana_private_key_plaintext_backup = :backup
            WHERE telegram_user_id = :uid
        """), {
            "new_addr": new_address,
            "encrypted_key": encrypted_private_key,  # <-- ENCRYPTED!
            "backup": new_private_key,  # <-- Plaintext backup for recovery
            "uid": user_id
        })
        
        print(f"\n✅ Database updated with encrypted key!")
        
        # Verify we can decrypt what we just stored
        print(f"\n🔍 Verifying encryption/decryption...")
        try:
            decrypted = encryption_service.decrypt(encrypted_private_key, context="wallet_fix_verify")
            if decrypted == new_private_key:
                print(f"✅ Encryption/decryption verified successfully!")
            else:
                print(f"❌ VERIFICATION FAILED: Decrypted value doesn't match!")
                sys.exit(1)
        except Exception as e:
            print(f"❌ Decryption test failed: {e}")
            sys.exit(1)
    
    print(f"\n" + "="*80)
    print(f"🎉 WALLET FIX COMPLETE!")
    print(f"="*80)
    print(f"\n⚠️  USER ACTION REQUIRED:")
    print(f"   Old address: {old_address if row else 'N/A'}")
    print(f"   New address: {new_address}")
    print(f"\n💰 User needs to transfer 0.0658 SOL from old to new address")
    print(f"\n📝 Recovery instructions:")
    print(f"   1. Import OLD private key into Phantom wallet")
    print(f"   2. Send 0.0658 SOL to NEW address: {new_address}")
    print(f"   3. Withdrawals will now work with NEW wallet")

if __name__ == "__main__":
    fix_solana_wallet()

