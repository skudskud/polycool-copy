#!/usr/bin/env python3
"""
Verify keypair mismatch for users
Decrypts stored private keys and derives pubkeys to compare with stored addresses
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'telegram-bot-v2', 'py-clob-server'))

from solders.keypair import Keypair
import base58
from database import User, SessionLocal
from core.services.encryption_service import encryption_service

def derive_pubkey_from_private_key(private_key_str: str) -> str:
    """Derive Solana pubkey from private key string"""
    try:
        # Try base58 first
        keypair = Keypair.from_base58_string(private_key_str)
        return str(keypair.pubkey())
    except Exception:
        try:
            # Try bytes
            keypair = Keypair.from_bytes(base58.b58decode(private_key_str))
            return str(keypair.pubkey())
        except Exception as e:
            return f"ERROR: {e}"

def verify_user(user_id: int, username: str):
    """Verify keypair mismatch for a specific user"""
    print(f"\n{'='*80}")
    print(f"🔍 VERIFYING USER: {username} (ID: {user_id})")
    print(f"{'='*80}")
    
    session = SessionLocal()
    try:
        user = session.query(User).filter(User.telegram_user_id == user_id).first()
        
        if not user:
            print(f"❌ User {user_id} not found!")
            return
        
        # Get stored address
        stored_address = user.solana_address
        print(f"\n📋 STORED DATA:")
        print(f"   solana_address: {stored_address}")
        print(f"   Has encrypted key: {user._solana_private_key_encrypted is not None}")
        print(f"   Has plaintext backup: {user.solana_private_key_plaintext_backup is not None}")
        
        # Try to decrypt
        try:
            decrypted_key = user.solana_private_key  # This uses the property getter which decrypts
            print(f"\n🔓 DECRYPTED PRIVATE KEY:")
            print(f"   Key (first 20 chars): {decrypted_key[:20]}...")
            print(f"   Key (last 20 chars): ...{decrypted_key[-20:]}")
            print(f"   Length: {len(decrypted_key)}")
            
            # Derive pubkey
            derived_pubkey = derive_pubkey_from_private_key(decrypted_key)
            
            print(f"\n🔑 DERIVED PUBKEY:")
            print(f"   From private key: {derived_pubkey}")
            
            print(f"\n✅ COMPARISON:")
            print(f"   Stored address:    {stored_address}")
            print(f"   Derived pubkey:    {derived_pubkey}")
            print(f"   Match:             {stored_address == derived_pubkey}")
            
            if stored_address != derived_pubkey:
                print(f"\n❌ MISMATCH DETECTED!")
                print(f"   The stored solana_address does NOT match the pubkey derived from the stored private key!")
                print(f"   This will cause 'keypair-pubkey mismatch' errors in transactions.")
            else:
                print(f"\n✅ MATCH CONFIRMED!")
                print(f"   The stored address matches the derived pubkey - this user should work correctly.")
                
        except Exception as e:
            print(f"\n❌ DECRYPTION FAILED: {e}")
            print(f"   Cannot verify - decryption error")
            
    finally:
        session.close()

if __name__ == "__main__":
    # Verify both users
    verify_user(6500527972, "kalzerinho (friend)")
    verify_user(1015699261, "diogenicious (you)")
    
    print(f"\n{'='*80}")
    print("✅ VERIFICATION COMPLETE")
    print(f"{'='*80}\n")

