"""
API Key Manager - Generate Polymarket API Credentials
Handles creation of API keys for enhanced trading rates
Adapted from telegram-bot-v2 for new architecture
"""
import os
import sys
from typing import Dict, Optional
from pathlib import Path

# Add py_clob_client to path (same as clob_service)
project_root = Path(__file__).parent.parent.parent.parent
py_clob_client_path = os.path.join(project_root, 'py_clob_client')
if py_clob_client_path not in sys.path:
    sys.path.insert(0, py_clob_client_path)

try:
    from py_clob_client.client import ClobClient
except ImportError:
    try:
        from polycool.py_clob_client.client import ClobClient
    except ImportError:
        raise ImportError("py_clob_client not found. Please ensure it's installed or in the project path.")

from py_clob_client.constants import POLYGON

from infrastructure.logging.logger import get_logger

logger = get_logger(__name__)


class ApiKeyManager:
    """Manages API key generation for Polymarket trading"""

    def __init__(self):
        """Initialize API key manager"""
        self.host = "https://clob.polymarket.com"
        self.chain_id = POLYGON
        logger.info("ApiKeyManager initialized")

    def generate_api_credentials(
        self,
        telegram_user_id: int,
        polygon_private_key: str,
        polygon_address: str
    ) -> Optional[Dict]:
        """
        Generate API credentials for a user's wallet

        Args:
            telegram_user_id: Telegram user ID
            polygon_private_key: Polygon private key (decrypted, hex string without 0x prefix)
            polygon_address: Polygon wallet address

        Returns:
            Dict with api_key, api_secret, api_passphrase or None if failed
        """
        try:
            logger.info(f"🔑 Generating API credentials for user {telegram_user_id}")

            # Ensure private key doesn't have 0x prefix
            if polygon_private_key.startswith('0x'):
                polygon_private_key = polygon_private_key[2:]

            # Initialize Polymarket client
            client = ClobClient(
                host=self.host,
                chain_id=self.chain_id,
                key=polygon_private_key
            )

            # Derive and create API key
            try:
                creds = client.create_or_derive_api_creds()

                if creds and hasattr(creds, 'api_key'):
                    # Extract credentials
                    api_data = {
                        'api_key': creds.api_key,
                        'api_secret': creds.api_secret,
                        'api_passphrase': creds.api_passphrase
                    }

                    logger.info(f"✅ API credentials generated for user {telegram_user_id}")
                    return api_data
                else:
                    logger.error(f"❌ Invalid API credentials returned for user {telegram_user_id}")
                    return None

            except Exception as e:
                logger.error(f"❌ Error calling create_or_derive_api_creds for user {telegram_user_id}: {e}")
                import traceback
                logger.error(traceback.format_exc())
                return None

        except Exception as e:
            logger.error(f"❌ Error generating API credentials for user {telegram_user_id}: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return None


# Global instance
_api_key_manager: Optional[ApiKeyManager] = None


def get_api_key_manager() -> ApiKeyManager:
    """Get or create ApiKeyManager instance"""
    global _api_key_manager
    if _api_key_manager is None:
        _api_key_manager = ApiKeyManager()
    return _api_key_manager

