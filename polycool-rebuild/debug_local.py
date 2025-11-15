#!/usr/bin/env python3
"""
Polycool Local Debugging Tool
Interactive debugging and testing utilities for local development
"""
import asyncio
import logging
import os
import sys
from pathlib import Path
from typing import Dict, Any, Optional

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
from infrastructure.config.settings import settings
from infrastructure.logging.logger import get_logger
from core.database.connection import get_db
from core.services.user.user_service import UserService
from core.services.wallet.wallet_service import WalletService
from telegram_bot.bot.application import TelegramBotApplication


class LocalDebugger:
    """Local debugging and testing utilities"""

    def __init__(self):
        """Initialize debugger"""
        self.logger = logging.getLogger(__name__)
        self.db = None
        self.user_service = None
        self.wallet_service = None
        self.bot_app = None

    async def setup(self):
        """Setup debugging environment"""
        self.logger.info("🔧 Setting up Local Debugger...")

        # Load environment - prioritize .env.local for development
        load_dotenv('.env.local')
        load_dotenv('.env', override=False)  # Don't override .env.local values
        # Setup logging will be done automatically

        # Initialize database
        from core.database.connection import init_db
        await init_db()
        self.db = next(get_db())

        # Initialize services
        self.user_service = UserService()
        self.wallet_service = WalletService()

        # Initialize bot (without starting)
        self.bot_app = TelegramBotApplication()
        await self.bot_app.initialize()

        self.logger.info("✅ Local Debugger ready")

    async def test_database_connection(self) -> bool:
        """Test database connection"""
        try:
            result = await self.db.execute("SELECT 1 as test")
            row = result.first()
            success = row[0] == 1
            self.logger.info(f"✅ Database connection: {'OK' if success else 'FAILED'}")
            return success
        except Exception as e:
            self.logger.error(f"❌ Database connection failed: {e}")
            return False

    async def test_user_creation(self) -> Optional[Dict[str, Any]]:
        """Test user creation and wallet generation"""
        try:
            # Create test user
            telegram_id = 123456789  # Test ID
            user = await self.user_service.get_by_telegram_id(telegram_id)

            if not user:
                user = await self.user_service.create_user(telegram_id)
                self.logger.info(f"✅ Created test user: {user.telegram_user_id}")

            # Generate wallets
            wallets = await self.wallet_service.generate_user_wallets()
            self.logger.info(f"✅ Generated wallets for user {user.telegram_user_id}")

            return {
                "user_id": user.id,
                "telegram_id": user.telegram_user_id,
                "polygon_address": wallets.get("polygon_address"),
                "solana_address": wallets.get("solana_address"),
                "stage": user.stage
            }
        except Exception as e:
            self.logger.error(f"❌ User creation test failed: {e}")
            return None

    async def test_bot_handlers(self) -> Dict[str, bool]:
        """Test bot command handlers"""
        results = {}

        try:
            # Test /start command
            update_mock = type('MockUpdate', (), {
                'effective_user': type('MockUser', (), {
                    'id': 123456789,
                    'username': 'test_user'
                })(),
                'message': type('MockMessage', (), {
                    'reply_text': lambda text: self.logger.info(f"Bot would reply: {text[:100]}...")
                })()
            })()

            from telegram_bot.bot.handlers.start_handler import handle_start
            await handle_start(update_mock, None)
            results["start_command"] = True
            self.logger.info("✅ /start command handler works")

        except Exception as e:
            self.logger.error(f"❌ /start command test failed: {e}")
            results["start_command"] = False

        try:
            # Test /wallet command
            from telegram_bot.bot.handlers.wallet_handler import handle_wallet
            await handle_wallet(update_mock, None)
            results["wallet_command"] = True
            self.logger.info("✅ /wallet command handler works")

        except Exception as e:
            self.logger.error(f"❌ /wallet command test failed: {e}")
            results["wallet_command"] = False

        return results

    async def show_database_stats(self) -> Dict[str, Any]:
        """Show database statistics"""
        stats = {}

        try:
            # Count users
            result = await self.db.execute("SELECT COUNT(*) FROM users")
            stats["total_users"] = result.scalar()

            # Count markets
            result = await self.db.execute("SELECT COUNT(*) FROM markets")
            stats["total_markets"] = result.scalar()

            # Count positions
            result = await self.db.execute("SELECT COUNT(*) FROM positions")
            stats["total_positions"] = result.scalar()

            # Count active positions
            result = await self.db.execute("SELECT COUNT(*) FROM positions WHERE status = 'active'")
            stats["active_positions"] = result.scalar()

            self.logger.info("📊 Database Stats:")
            for key, value in stats.items():
                self.logger.info(f"   {key}: {value}")

        except Exception as e:
            self.logger.error(f"❌ Failed to get database stats: {e}")

        return stats

    async def cleanup_test_data(self):
        """Clean up test data"""
        try:
            # Remove test user
            await self.db.execute("DELETE FROM users WHERE telegram_user_id = 123456789")
            await self.db.commit()

            self.logger.info("🧹 Cleaned up test data")
        except Exception as e:
            self.logger.error(f"❌ Failed to cleanup test data: {e}")

    async def run_all_tests(self):
        """Run all debugging tests"""
        self.logger.info("🧪 Running Local Debugging Tests...")
        self.logger.info("=" * 50)

        # Test database
        await self.test_database_connection()

        # Show stats
        await self.show_database_stats()

        # Test user creation
        user_data = await self.test_user_creation()
        if user_data:
            self.logger.info(f"📝 Test user data: {user_data}")

        # Test bot handlers
        handler_results = await self.test_bot_handlers()
        self.logger.info(f"🤖 Handler tests: {handler_results}")

        # Final stats
        final_stats = await self.show_database_stats()

        self.logger.info("✅ All debugging tests completed")

    async def interactive_mode(self):
        """Interactive debugging mode"""
        print("\n🔧 Polycool Local Debugger - Interactive Mode")
        print("=" * 50)
        print("Commands:")
        print("  db      - Test database connection")
        print("  user    - Test user creation")
        print("  bot     - Test bot handlers")
        print("  stats   - Show database stats")
        print("  cleanup - Clean test data")
        print("  all     - Run all tests")
        print("  quit    - Exit")
        print()

        while True:
            try:
                cmd = input("debugger> ").strip().lower()

                if cmd == "quit" or cmd == "q":
                    break
                elif cmd == "db":
                    await self.test_database_connection()
                elif cmd == "user":
                    user_data = await self.test_user_creation()
                    if user_data:
                        print(f"User created: {user_data}")
                elif cmd == "bot":
                    results = await self.test_bot_handlers()
                    print(f"Handler tests: {results}")
                elif cmd == "stats":
                    await self.show_database_stats()
                elif cmd == "cleanup":
                    await self.cleanup_test_data()
                elif cmd == "all":
                    await self.run_all_tests()
                else:
                    print("Unknown command. Type 'help' for commands.")

            except KeyboardInterrupt:
                break
            except Exception as e:
                print(f"Error: {e}")

        print("👋 Goodbye!")


async def main():
    """Main debugging function"""
    debugger = LocalDebugger()

    try:
        await debugger.setup()

        if len(sys.argv) > 1 and sys.argv[1] == "--interactive":
            await debugger.interactive_mode()
        else:
            await debugger.run_all_tests()

    except Exception as e:
        logging.error(f"❌ Debugging failed: {e}")
        raise
    finally:
        # Cleanup
        if debugger.db:
            debugger.db.close()


if __name__ == "__main__":
    # Setup basic logging for debugger itself
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    asyncio.run(main())
