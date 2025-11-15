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

# Import the new data persistence system
from data_persistence import data_persistence
from postgresql_persistence import postgresql_persistence

logger = logging.getLogger(__name__)

class ApiKeyManager:
    """Manages API key generation and storage for user wallets"""
    
    def __init__(self, storage_file: str = "user_api_keys.json"):
        """Initialize API key manager with deployment-safe persistence"""
        self.storage_file = storage_file
        self._api_keys_data = None  # Lazy loading
        self._initialized = False
        
        # Polymarket CLOB configuration
        self.host = "https://clob.polymarket.com"
        self.chain_id = POLYGON  # Use production Polygon
    
    @property
    def api_keys_data(self) -> Dict:
        """Lazy loading property for API keys data"""
        if not self._initialized:
            self._ensure_initialized()
        return self._api_keys_data
    
    def _ensure_initialized(self):
        """Ensure the API key manager is initialized (lazy loading)"""
        if not self._initialized:
            try:
                logger.info("🔄 Lazy loading API key manager data...")
                self._api_keys_data = self._load_api_keys()
                self._initialized = True
                logger.info(f"✅ API key manager initialized: {len(self._api_keys_data)} API key sets loaded")
            except Exception as e:
                logger.error(f"❌ Failed to initialize API key manager: {e}")
                self._api_keys_data = {}
                self._initialized = True
        
        logger.info(f"API key manager initialized with {len(self.api_keys_data)} API keys")
    
    def _load_api_keys(self) -> Dict:
        """Load existing API key data with automatic recovery from backups"""
        try:
            # Use the new persistence system
            api_keys_data = data_persistence.load_data(self.storage_file, default={})
            
            if api_keys_data:
                logger.info(f"✅ Loaded {len(api_keys_data)} API key sets")
            else:
                logger.info("📝 Starting with empty API key data")
            
            return api_keys_data
            
        except Exception as e:
            logger.error(f"Error loading API keys: {e}")
            return {}
    
    def _save_api_keys(self):
        """Save API key data to PostgreSQL database with file fallback"""
        try:
            # Primary: Save to PostgreSQL
            success = True
            for user_id_str, api_data in self.api_keys_data.items():
                if not postgresql_persistence.save_api_key(int(user_id_str), api_data):
                    success = False
                    logger.error(f"❌ Failed to save API key for user {user_id_str} to PostgreSQL")
                    break
            
            if success:
                logger.info(f"✅ Saved {len(self.api_keys_data)} API key sets to PostgreSQL")
            else:
                logger.error("❌ Failed to save some API keys to PostgreSQL, using file fallback")
                
                # Fallback: Save to file
                file_success = data_persistence.save_data(self.storage_file, self.api_keys_data)
                if not file_success:
                    raise Exception("Both PostgreSQL and file API key saves failed!")
                else:
                    logger.info("✅ Fallback file save successful for API keys")
                    
        except Exception as e:
            logger.error(f"❌ Error during API key save: {e}")
            
            # Final fallback to file-based save
            try:
                file_success = data_persistence.save_data(self.storage_file, self.api_keys_data)
                if not file_success:
                    raise Exception("All API key save methods failed!")
                else:
                    logger.info("✅ Final fallback file save successful for API keys")
            except Exception as fallback_error:
                logger.critical(f"❌ CRITICAL: Final fallback API key save failed: {fallback_error}")
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
                # Validate credentials before storing
                if not all([creds.api_key, creds.api_secret, creds.api_passphrase]):
                    raise ValueError("Generated credentials are incomplete")
                
                # Store credentials
                self.api_keys_data[user_id_str] = {
                    'api_key': creds.api_key,
                    'api_secret': creds.api_secret,
                    'api_passphrase': creds.api_passphrase,
                    'wallet_address': wallet_address,
                    'created_at': time.time(),
                    'last_used': time.time()
                }
                
                # Save with validation
                self._save_api_keys()
                
                # Verify the credentials were actually saved
                saved_creds = self.get_user_api_credentials(user_id)
                if not saved_creds:
                    raise Exception("Credentials were not properly saved - verification failed")
                
                logger.info(f"✅ API credentials generated and verified for user {user_id}")
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
    
    def delete_user_api_keys(self, user_id: int) -> bool:
        """Delete API keys for a user (for wallet reset)"""
        try:
            user_id_str = str(user_id)
            if user_id_str in self.api_keys_data:
                del self.api_keys_data[user_id_str]
                self._save_api_keys()
                logger.info(f"Deleted API keys for user {user_id}")
                return True
            return False
        except Exception as e:
            logger.error(f"Error deleting API keys for user {user_id}: {e}")
            return False

# Global API key manager instance
api_key_manager = ApiKeyManager()

