#!/usr/bin/env python3
"""
Decrypt encrypted private keys from database and verify pubkey derivation
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'telegram-bot-v2', 'py-clob-server'))

from solders.keypair import Keypair
import base58
from core.services.encryption_service import encryption_service

# Encrypted key from kalzerinho's database record
KALZERINHO_ENCRYPTED_KEY = "SQc5IO1kzLOOPajzP71bi77Db3r5uEOKzqY+3d4O+4hHq7AFX8BaVsYIlrHYpDaxHIPI09h5EK/03yOX66lpw3Z9OwjddmHLhJtemb5V0/X99g5aenMUBCeR/AUMinsCxzJz5a3uFZrOmrcDDq/WvAfNGmVOHDatJ+F5trdFumjW3sWIsPaiVo9KLYrM2CFYsl6TnFdklbbEHOzupG7xYtOIrukpEge7mT+S69Erkve4W1wj1hZn+g=="

# Stored solana_address from database
KALZERINHO_STORED_ADDRESS = "CwQ6dqwT2TFuftYpf2isA7HMRSzZbVQLF95EmU8Noyz"

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

def main():
    print("="*80)
    print("🔐 KALZERINHO'S KEYPAIR VERIFICATION")
    print("="*80)

    # Step 1: Decrypt the encrypted key
    print("\n1️⃣ DECRYPTING ENCRYPTED PRIVATE KEY:")
    try:
        decrypted_key = encryption_service.decrypt(KALZERINHO_ENCRYPTED_KEY, context="verify_kalzerinho_key")
        print(f"✅ Decryption successful!")
        print(f"   Decrypted key length: {len(decrypted_key)}")
        print(f"   First 20 chars: {decrypted_key[:20]}...")
        print(f"   Last 20 chars: ...{decrypted_key[-20:]}")
    except Exception as e:
        print(f"❌ Decryption failed: {e}")
        return

    # Step 2: Derive pubkey from decrypted key
    print("\n2️⃣ DERIVING PUBKEY FROM PRIVATE KEY:")
    derived_pubkey = derive_pubkey_from_private_key(decrypted_key)
    print(f"   Derived pubkey: {derived_pubkey}")

    # Step 3: Compare with stored address
    print("\n3️⃣ COMPARISON:")
    print(f"   Stored solana_address: {KALZERINHO_STORED_ADDRESS}")
    print(f"   Derived pubkey:        {derived_pubkey}")
    print(f"   Match:                 {KALZERINHO_STORED_ADDRESS == derived_pubkey}")

    if KALZERINHO_STORED_ADDRESS != derived_pubkey:
        print("\n❌ MISMATCH CONFIRMED!")
        print("   The stored solana_address does NOT match the pubkey derived from the stored private key!")
        print("   This is the root cause of the 'keypair-pubkey mismatch' error.")
        print(f"   Jupiter expects transactions signed by: {KALZERINHO_STORED_ADDRESS}")
        print(f"   But your keypair signs as: {derived_pubkey}")
    else:
        print("\n✅ MATCH CONFIRMED!")
        print("   Everything looks correct.")

    print("\n" + "="*80)
    print("✅ VERIFICATION COMPLETE")
    print("="*80)

if __name__ == "__main__":
    main()
