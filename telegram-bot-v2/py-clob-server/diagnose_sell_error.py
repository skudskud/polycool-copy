#!/usr/bin/env python3
"""
Diagnostic script for SELL 403 error
Check which columns are actually used and if they have values
"""

import os
import sys
sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv()

from core.services import user_service
from database import SessionLocal, User

def diagnose_user_credentials(user_id: int):
    """Check what credentials exist for a user"""

    print(f"\n🔍 DIAGNOSING SELL ERROR FOR USER {user_id}")
    print("=" * 80)

    # Get user
    user = user_service.get_user(user_id)
    if not user:
        print(f"❌ User {user_id} not found!")
        return

    print(f"✅ User found: {user.telegram_user_id}")
    print(f"   Polygon address: {user.polygon_address}")
    print()

    # Check PLAINTEXT columns
    print("📋 PLAINTEXT COLUMNS (should be in DB directly):")
    print(f"   api_key: {repr(user.api_key)} (len={len(user.api_key) if user.api_key else 0})")
    print(f"   api_passphrase: {repr(user.api_passphrase)} (len={len(user.api_passphrase) if user.api_passphrase else 0})")
    print()

    # Check ENCRYPTED columns (raw)
    print("🔐 ENCRYPTED COLUMNS (raw, from DB):")
    print(f"   _polygon_private_key_encrypted: {repr(user._polygon_private_key_encrypted[:50] if user._polygon_private_key_encrypted else None)}... (len={len(user._polygon_private_key_encrypted) if user._polygon_private_key_encrypted else 0})")
    print(f"   _api_secret_encrypted: {repr(user._api_secret_encrypted[:50] if user._api_secret_encrypted else None)}... (len={len(user._api_secret_encrypted) if user._api_secret_encrypted else 0})")
    print()

    # Check ENCRYPTION_KEY
    from core.services.encryption_service import ENCRYPTION_KEY
    print("🔑 ENCRYPTION SERVICE:")
    print(f"   ENCRYPTION_KEY present: {bool(ENCRYPTION_KEY)}")
    if ENCRYPTION_KEY:
        print(f"   ENCRYPTION_KEY length: {len(ENCRYPTION_KEY)} bytes (should be 32)")
    print()

    # Try to decrypt
    print("🔓 DECRYPTION ATTEMPT:")
    try:
        from core.services.encryption_service import encryption_service

        if user._polygon_private_key_encrypted:
            key = encryption_service.decrypt(user._polygon_private_key_encrypted, context="test_polygon")
            print(f"   ✅ Polygon key decrypted: {key[:20]}...{key[-20:]} (len={len(key)})")
        else:
            print(f"   ❌ No polygon_private_key_encrypted in DB!")

        if user._api_secret_encrypted:
            secret = encryption_service.decrypt(user._api_secret_encrypted, context="test_api_secret")
            print(f"   ✅ API secret decrypted: {secret[:20]}...{secret[-20:]} (len={len(secret)})")
        else:
            print(f"   ❌ No _api_secret_encrypted in DB!")

    except Exception as e:
        print(f"   ❌ Decryption FAILED: {e}")
    print()

    # Check what get_api_credentials returns
    print("📤 GET_API_CREDENTIALS OUTPUT:")
    try:
        creds = user_service.get_api_credentials(user_id)
        if creds:
            print(f"   api_key: {repr(creds['api_key'])} (len={len(creds['api_key']) if creds['api_key'] else 0})")
            print(f"   api_secret: {repr(creds['api_secret'][:20] if creds['api_secret'] else None)}... (len={len(creds['api_secret']) if creds['api_secret'] else 0})")
            print(f"   api_passphrase: {repr(creds['api_passphrase'])} (len={len(creds['api_passphrase']) if creds['api_passphrase'] else 0})")
        else:
            print(f"   ❌ get_api_credentials returned NONE!")
    except Exception as e:
        print(f"   ❌ get_api_credentials FAILED: {e}")
    print()

    # Summary
    print("📊 SUMMARY:")
    has_all = (user.api_key and user.api_passphrase and user._api_secret_encrypted
               and user._polygon_private_key_encrypted and ENCRYPTION_KEY)
    if has_all:
        print("   ✅ ALL REQUIRED FIELDS PRESENT - Should work!")
    else:
        print("   ❌ MISSING FIELDS:")
        if not user.api_key:
            print("      - api_key (plaintext)")
        if not user.api_passphrase:
            print("      - api_passphrase (plaintext)")
        if not user._api_secret_encrypted:
            print("      - _api_secret_encrypted (chiffré)")
        if not user._polygon_private_key_encrypted:
            print("      - _polygon_private_key_encrypted (chiffré)")
        if not ENCRYPTION_KEY:
            print("      - ENCRYPTION_KEY (environment variable)")
    print()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python diagnose_sell_error.py <user_id>")
        print("Example: python diagnose_sell_error.py 123456789")
        sys.exit(1)

    user_id = int(sys.argv[1])
    diagnose_user_credentials(user_id)
