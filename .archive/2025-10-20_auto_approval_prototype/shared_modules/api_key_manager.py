#!/usr/bin/env python3
"""
API Key Manager for Polymarket Trading Bot V2
Handles automatic API key generation for each user's wallet
"""

import time
import json
import logging
from typing import Dict, Optional, Tuple
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds
from py_clob_client.constants import POLYGON

logger = logging.getLogger(__name__)

class ApiKeyManager:
    """Manages API key generation and storage for user wallets"""
    
    def __init__(self, storage_file: str = "user_api_keys.json"):
        """Initialize API key manager"""
        self.storage_file = storage_file
        self.api_keys_data = self._load_api_keys()
        
        # Polymarket CLOB configuration
        self.host = "https://clob.polymarket.com"
        self.chain_id = POLYGON  # Use production Polygon
    
    def _load_api_keys(self) -> Dict:
        """Load existing API key data from storage"""
        try:
            import os
            if os.path.exists(self.storage_file):
                with open(self.storage_file, 'r') as f:
                    return json.load(f)
        except Exception as e:
            logger.error(f"Error loading API keys: {e}")
        return {}
    
    def _save_api_keys(self):
        """Save API key data to storage"""
        try:
            # Create backup first
            import os
            if os.path.exists(self.storage_file):
                backup_file = f"{self.storage_file}.backup"
                with open(self.storage_file, 'r') as src, open(backup_file, 'w') as dst:
                    dst.write(src.read())
            
            # Save current data
            with open(self.storage_file, 'w') as f:
                json.dump(self.api_keys_data, f, indent=2)
                
        except Exception as e:
            logger.error(f"Error saving API keys: {e}")
            raise
    
    def generate_api_credentials(self, user_id: int, private_key: str, wallet_address: str) -> Optional[ApiCreds]:
        """Generate API credentials for a user's wallet"""
        try:
            user_id_str = str(user_id)
            
            # Check if user already has API credentials
            if user_id_str in self.api_keys_data and self.api_keys_data[user_id_str].get('api_key'):
                existing = self.api_keys_data[user_id_str]
                logger.info(f"Using existing API credentials for user {user_id}")
                return ApiCreds(
                    api_key=existing['api_key'],
                    api_secret=existing['api_secret'],
                    api_passphrase=existing['api_passphrase']
                )
            
            # Create CLOB client with user's private key
            client = ClobClient(
                host=self.host,
                key=private_key,
                chain_id=self.chain_id,
                signature_type=0,  # EOA signature type
                funder=None  # User owns their funds directly
            )
            
            logger.info(f"Generating API credentials for user {user_id} with wallet {wallet_address}")
            
            # Generate or derive API credentials
            creds = client.create_or_derive_api_creds()
            
            if creds:
                # Store credentials
                self.api_keys_data[user_id_str] = {
                    'api_key': creds.api_key,
                    'api_secret': creds.api_secret,
                    'api_passphrase': creds.api_passphrase,
                    'wallet_address': wallet_address,
                    'created_at': time.time(),
                    'last_used': time.time()
                }
                
                self._save_api_keys()
                
                logger.info(f"✅ API credentials generated for user {user_id}")
                return creds
            else:
                logger.error(f"Failed to generate API credentials for user {user_id}")
                return None
                
        except Exception as e:
            logger.error(f"Error generating API credentials for user {user_id}: {e}")
            return None
    
    def get_user_api_credentials(self, user_id: int) -> Optional[ApiCreds]:
        """Get existing API credentials for a user"""
        try:
            user_id_str = str(user_id)
            if user_id_str in self.api_keys_data:
                data = self.api_keys_data[user_id_str]
                if data.get('api_key'):
                    # Update last used timestamp
                    data['last_used'] = time.time()
                    self._save_api_keys()
                    
                    return ApiCreds(
                        api_key=data['api_key'],
                        api_secret=data['api_secret'],
                        api_passphrase=data['api_passphrase']
                    )
            return None
        except Exception as e:
            logger.error(f"Error retrieving API credentials for user {user_id}: {e}")
            return None
    
    def create_authenticated_client(self, user_id: int, private_key: str, wallet_address: str) -> Optional[ClobClient]:
        """Create an authenticated CLOB client for a user"""
        try:
            # Get or generate API credentials
            creds = self.get_user_api_credentials(user_id)
            if not creds:
                creds = self.generate_api_credentials(user_id, private_key, wallet_address)
            
            if not creds:
                logger.error(f"Could not obtain API credentials for user {user_id}")
                return None
            
            # Create authenticated client
            client = ClobClient(
                host=self.host,
                key=private_key,
                chain_id=self.chain_id,
                signature_type=0,  # EOA signature type
                funder=None,  # User owns their funds directly
                creds=creds
            )
            
            logger.info(f"✅ Authenticated client created for user {user_id}")
            return client
            
        except Exception as e:
            logger.error(f"Error creating authenticated client for user {user_id}: {e}")
            return None
    
    def test_api_credentials(self, user_id: int, private_key: str, wallet_address: str) -> Tuple[bool, str]:
        """Test if API credentials are working"""
        try:
            client = self.create_authenticated_client(user_id, private_key, wallet_address)
            if not client:
                return False, "Could not create authenticated client"
            
            # Test with a simple API call
            try:
                api_keys = client.get_api_keys()
                return True, f"API credentials working. Found {len(api_keys)} keys."
            except Exception as e:
                return False, f"API test failed: {str(e)}"
                
        except Exception as e:
            logger.error(f"Error testing API credentials for user {user_id}: {e}")
            return False, f"Test error: {str(e)}"
    
    def revoke_user_api_credentials(self, user_id: int, private_key: str = None) -> bool:
        """Revoke and delete API credentials for a user"""
        try:
            user_id_str = str(user_id)
            
            if user_id_str not in self.api_keys_data:
                return True  # Nothing to revoke
            
            # If private key provided, try to revoke on server
            if private_key:
                try:
                    client = ClobClient(
                        host=self.host,
                        key=private_key,
                        chain_id=self.chain_id,
                        signature_type=0
                    )
                    
                    creds = self.get_user_api_credentials(user_id)
                    if creds:
                        client.creds = creds
                        client.delete_api_key()  # Revoke on server
                        logger.info(f"API key revoked on server for user {user_id}")
                except Exception as e:
                    logger.warning(f"Could not revoke API key on server for user {user_id}: {e}")
            
            # Delete locally
            del self.api_keys_data[user_id_str]
            self._save_api_keys()
            
            logger.info(f"🗑️ API credentials deleted for user {user_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error revoking API credentials for user {user_id}: {e}")
            return False
    
    def get_api_key_stats(self) -> Dict:
        """Get statistics about managed API keys"""
        total_keys = len(self.api_keys_data)
        recent_keys = sum(1 for data in self.api_keys_data.values() 
                         if data.get('last_used', 0) > time.time() - 86400)  # Used in last 24h
        
        return {
            'total_api_keys': total_keys,
            'recent_active_keys': recent_keys,
            'storage_file': self.storage_file
        }
    
    def cleanup_old_api_keys(self, max_age_days: int = 30) -> int:
        """Clean up API keys older than specified days"""
        try:
            cutoff_time = time.time() - (max_age_days * 86400)
            old_keys = []
            
            for user_id_str, data in self.api_keys_data.items():
                if data.get('last_used', 0) < cutoff_time:
                    old_keys.append(user_id_str)
            
            for user_id_str in old_keys:
                del self.api_keys_data[user_id_str]
            
            if old_keys:
                self._save_api_keys()
                logger.info(f"Cleaned up {len(old_keys)} old API keys")
            
            return len(old_keys)
            
        except Exception as e:
            logger.error(f"Error cleaning up old API keys: {e}")
            return 0

# Global API key manager instance
api_key_manager = ApiKeyManager()

