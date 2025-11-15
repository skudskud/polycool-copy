#!/usr/bin/env python3
"""
Quick test script - Test core functionality without database
Run: python scripts/dev/quick_test.py
"""
import sys
import traceback

def test_encryption():
    """Test encryption service"""
    print("🔐 Testing EncryptionService...")
    try:
        from core.services.encryption.encryption_service import EncryptionService
        service = EncryptionService()

        plaintext = "test_private_key_12345"
        encrypted = service.encrypt(plaintext)
        decrypted = service.decrypt(encrypted)

        if decrypted == plaintext:
            print("   ✅ Encryption/Decryption OK")
            return True
        else:
            print(f"   ❌ Decryption failed: expected '{plaintext}', got '{decrypted}'")
            return False
    except Exception as e:
        print(f"   ❌ Encryption test failed: {e}")
        traceback.print_exc()
        return False

def test_wallet_generation():
    """Test wallet generation"""
    print("💼 Testing WalletService...")
    try:
        from core.services.wallet.wallet_service import WalletService
        service = WalletService()

        # Test Polygon wallet
        polygon_addr, polygon_key = service.generate_polygon_wallet()
        if polygon_addr.startswith("0x") and len(polygon_addr) == 42:
            print("   ✅ Polygon wallet generation OK")
        else:
            print(f"   ❌ Invalid Polygon address: {polygon_addr}")
            return False

        # Test Solana wallet
        solana_addr, solana_key = service.generate_solana_wallet()
        if len(solana_addr) >= 32:
            print("   ✅ Solana wallet generation OK")
        else:
            print(f"   ❌ Invalid Solana address: {solana_addr}")
            return False

        # Test user wallets
        wallets = service.generate_user_wallets()
        required_keys = ["polygon_address", "polygon_private_key", "solana_address", "solana_private_key"]
        if all(key in wallets for key in required_keys):
            print("   ✅ User wallet generation OK")
            return True
        else:
            print(f"   ❌ Missing keys in user wallets: {wallets.keys()}")
            return False

    except Exception as e:
        print(f"   ❌ Wallet generation test failed: {e}")
        traceback.print_exc()
        return False

def test_imports():
    """Test critical imports"""
    print("📦 Testing imports...")
    imports_to_test = [
        ("infrastructure.config.settings", "settings"),
        ("infrastructure.logging.logger", "get_logger"),
        ("core.database.models", "User"),
        ("core.database.models", "Market"),
        ("core.database.models", "Position"),
        ("core.services.user.user_service", "UserService"),
        ("core.services.wallet.wallet_service", "WalletService"),
        ("core.services.encryption.encryption_service", "EncryptionService"),
        ("core.services.position.position_service", "PositionService"),
        ("data_ingestion.streamer.websocket_client", "WebSocketClient"),
        ("data_ingestion.streamer.market_updater", "MarketUpdater"),
        ("data_ingestion.streamer.subscription_manager", "SubscriptionManager"),
    ]

    failed = []
    for module_name, attr_name in imports_to_test:
        try:
            module = __import__(module_name, fromlist=[attr_name])
            getattr(module, attr_name)
        except Exception as e:
            failed.append(f"{module_name}.{attr_name}: {e}")

    if failed:
        print(f"   ❌ {len(failed)} import(s) failed:")
        for error in failed:
            print(f"      - {error}")
        return False
    else:
        print(f"   ✅ All {len(imports_to_test)} imports OK")
        return True

def main():
    """Run all quick tests"""
    print("🚀 Quick Test Suite\n")
    print("="*50)

    results = []

    # Test imports first
    results.append(("Imports", test_imports()))
    print()

    # Test encryption
    results.append(("Encryption", test_encryption()))
    print()

    # Test wallet generation
    results.append(("Wallet Generation", test_wallet_generation()))
    print()

    # Summary
    print("="*50)
    print("\n📊 Results:")
    passed = sum(1 for _, result in results if result)
    total = len(results)

    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"   {status}: {name}")

    print(f"\n✅ {passed}/{total} tests passed")

    if passed == total:
        print("\n🎉 All tests passed!")
        return 0
    else:
        print(f"\n⚠️  {total - passed} test(s) failed")
        return 1

if __name__ == "__main__":
    sys.exit(main())
