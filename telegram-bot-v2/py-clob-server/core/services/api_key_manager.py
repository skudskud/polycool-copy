#!/usr/bin/env python3
"""
API Key Manager for Polymarket Trading Bot V2
Simplified version that just generates API credentials
Storage is handled by user_service
"""

import logging
from typing import Dict, Optional
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds
from py_clob_client.constants import POLYGON

logger = logging.getLogger(__name__)


class ApiKeyManager:
    """Simplified API key manager - generates credentials only"""
    
    def __init__(self):
        """Initialize API key manager"""
        # Polymarket CLOB configuration
        self.host = "https://clob.polymarket.com"
        self.chain_id = POLYGON  # Use production Polygon
        logger.info("API key manager initialized")
    
    def generate_api_credentials(self, user_id: int, private_key: str, wallet_address: str) -> Optional[Dict]:
        """
        Generate API credentials for a user's wallet
        
        Args:
            user_id: Telegram user ID
            private_key: Wallet private key (hex string without 0x prefix)
            wallet_address: Wallet address
            
        Returns:
            Dict with api_key, api_secret, api_passphrase or None if failed
        """
        try:
            logger.info(f"🔑 Generating API credentials for user {user_id}")
            
            # Ensure private key doesn't have 0x prefix
            if private_key.startswith('0x'):
                private_key = private_key[2:]
            
            # Initialize Polymarket client
            client = ClobClient(
                host=self.host,
                chain_id=self.chain_id,
                key=private_key
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
                    
                    logger.info(f"✅ API credentials generated for user {user_id}")
                    return api_data
                else:
                    logger.error(f"❌ Invalid API credentials returned for user {user_id}")
                    return None
                    
            except Exception as e:
                logger.error(f"❌ Error calling create_or_derive_api_creds for user {user_id}: {e}")
                return None
                
        except Exception as e:
            logger.error(f"❌ Error generating API credentials for user {user_id}: {e}")
            return None


# Global instance
api_key_manager = ApiKeyManager()
