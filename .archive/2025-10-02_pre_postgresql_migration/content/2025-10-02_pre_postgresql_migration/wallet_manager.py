#!/usr/bin/env python3
"""
Wallet Manager for Telegram Trading Bot V2
Handles automatic wallet generation and management for users
"""

import json
import os
import hashlib
from typing import Dict, Optional, Tuple
from eth_account import Account
from eth_keys import keys
import secrets
import logging

# Import the new data persistence system
from data_persistence import data_persistence
from postgresql_persistence import postgresql_persistence

logger = logging.getLogger(__name__)

class WalletManager:
    """Manages user wallets for the Telegram trading bot"""
    
    def __init__(self, storage_file: str = "user_wallets.json"):
        """Initialize wallet manager with deployment-safe persistence"""
        self.storage_file = storage_file
        self._wallets_data = None  # Lazy loading
        self._initialized = False
        
        # Enable unaudited HD wallet features for key generation
        Account.enable_unaudited_hdwallet_features()
    
    @property
    def wallets_data(self) -> Dict:
        """Lazy loading property for wallets data"""
        if not self._initialized:
            self._ensure_initialized()
        return self._wallets_data
    
    def _ensure_initialized(self):
        """Ensure the wallet manager is initialized (lazy loading)"""
        if not self._initialized:
            try:
                logger.info("🔄 Lazy loading wallet manager data...")
                self._wallets_data = self._load_wallets()
                self._initialized = True
                logger.info(f"✅ Wallet manager initialized: {len(self._wallets_data)} wallets loaded")
            except Exception as e:
                logger.error(f"❌ Failed to initialize wallet manager: {e}")
                self._wallets_data = {}
                self._initialized = True
        
        logger.info(f"Wallet manager initialized with {len(self.wallets_data)} wallets")
    
    def _load_wallets(self) -> Dict:
        """Load existing wallet data with automatic recovery from backups"""
        try:
            # Use the new persistence system
            wallets_data = data_persistence.load_data(self.storage_file, default={})
            
            if wallets_data:
                logger.info(f"✅ Loaded {len(wallets_data)} user wallets")
            else:
                logger.info("📝 Starting with empty wallet data")
            
            return wallets_data
            
        except Exception as e:
            logger.error(f"⚠️ Error loading wallets: {e}")
            return {}
    
    def _save_wallets(self):
        """Save wallet data to PostgreSQL database with file fallback"""
        try:
            # Primary: Save to PostgreSQL
            success = True
            for user_id_str, wallet_data in self.wallets_data.items():
                if not postgresql_persistence.save_wallet(int(user_id_str), wallet_data):
                    success = False
                    logger.error(f"❌ Failed to save wallet for user {user_id_str} to PostgreSQL")
                    break
            
            if success:
                logger.info(f"✅ Saved {len(self.wallets_data)} user wallets to PostgreSQL")
            else:
                logger.error("❌ Failed to save some wallets to PostgreSQL, using file fallback")
                
                # Fallback: Save to file
                file_success = data_persistence.save_data(self.storage_file, self.wallets_data)
                if not file_success:
                    raise Exception("Both PostgreSQL and file wallet saves failed!")
                else:
                    logger.info("✅ Fallback file save successful for wallets")
                    
        except Exception as e:
            logger.error(f"❌ Error during wallet save: {e}")
            
            # Final fallback to file-based save
            try:
                file_success = data_persistence.save_data(self.storage_file, self.wallets_data)
                if not file_success:
                    raise Exception("All wallet save methods failed!")
                else:
                    logger.info("✅ Final fallback file save successful for wallets")
            except Exception as fallback_error:
                logger.critical(f"❌ CRITICAL: Final fallback wallet save failed: {fallback_error}")
                raise
    
    def generate_wallet_for_user(self, user_id: int, username: str = None) -> Tuple[str, str]:
        """Generate a new wallet for a user"""
        try:
            # Check if user already has a wallet
            user_id_str = str(user_id)
            if user_id_str in self.wallets_data:
                existing = self.wallets_data[user_id_str]
                return existing['address'], existing['private_key']
            
            # Generate new wallet
            account = Account.create()
            
            # Store wallet data
            wallet_data = {
                'address': account.address,
                'private_key': account.key.hex(),
                'username': username,
                'created_at': __import__('time').time(),
                'funded': False,
                'usdc_approved': False,
                'polymarket_approved': False,
                'api_credentials_generated': False,
                'auto_approval_completed': False,
                'last_approval_check': None,
                # Auto-approval tracking fields
                'auto_approval_attempted': False,
                'auto_approval_in_progress': False,
                'auto_approval_last_attempt': None,
                'auto_approval_failure_count': 0,
                'auto_api_generated': False
            }
            
            self.wallets_data[user_id_str] = wallet_data
            self._save_wallets()
            
            print(f"✅ Generated wallet for user {user_id}: {account.address}")
            return account.address, account.key.hex()
            
        except Exception as e:
            print(f"❌ Error generating wallet: {e}")
            raise
    
    def get_user_wallet(self, user_id: int) -> Optional[Dict]:
        """Get wallet data for a user"""
        user_id_str = str(user_id)
        return self.wallets_data.get(user_id_str)
    
    def get_user_address(self, user_id: int) -> Optional[str]:
        """Get wallet address for a user"""
        wallet = self.get_user_wallet(user_id)
        return wallet['address'] if wallet else None
    
    def get_user_private_key(self, user_id: int) -> Optional[str]:
        """Get private key for a user (use carefully!)"""
        wallet = self.get_user_wallet(user_id)
        return wallet['private_key'] if wallet else None
    
    def update_funding_status(self, user_id: int, funded: bool = True):
        """Update funding status for a user"""
        user_id_str = str(user_id)
        if user_id_str in self.wallets_data:
            self.wallets_data[user_id_str]['funded'] = funded
            self._save_wallets()
    
    def update_approval_status(self, user_id: int, usdc_approved: bool = None, polymarket_approved: bool = None, auto_approval_completed: bool = None):
        """Update approval status for a user"""
        user_id_str = str(user_id)
        if user_id_str in self.wallets_data:
            if usdc_approved is not None:
                self.wallets_data[user_id_str]['usdc_approved'] = usdc_approved
            if polymarket_approved is not None:
                self.wallets_data[user_id_str]['polymarket_approved'] = polymarket_approved
            if auto_approval_completed is not None:
                self.wallets_data[user_id_str]['auto_approval_completed'] = auto_approval_completed
            
            # Update last approval check timestamp
            self.wallets_data[user_id_str]['last_approval_check'] = __import__('time').time()
            self._save_wallets()
    
    def update_api_credentials_status(self, user_id: int, generated: bool = True):
        """Update API credentials generation status"""
        user_id_str = str(user_id)
        if user_id_str in self.wallets_data:
            self.wallets_data[user_id_str]['api_credentials_generated'] = generated
            self._save_wallets()
    
    def is_wallet_ready(self, user_id: int) -> Tuple[bool, str]:
        """Check if wallet is ready for trading"""
        wallet = self.get_user_wallet(user_id)
        if not wallet:
            return False, "No wallet found. Use /start to create one."
        
        if not wallet.get('funded', False):
            return False, "Wallet needs funding (USDC.e + POL)"
        
        if not wallet.get('usdc_approved', False):
            return False, "USDC.e approval needed"
        
        if not wallet.get('polymarket_approved', False):
            return False, "Polymarket contract approval needed"
        
        return True, "Wallet ready for trading!"
    
    def get_wallet_stats(self) -> Dict:
        """Get statistics about managed wallets"""
        total_wallets = len(self.wallets_data)
        funded_wallets = sum(1 for w in self.wallets_data.values() if w.get('funded', False))
        ready_wallets = sum(1 for w in self.wallets_data.values() 
                          if w.get('funded', False) and w.get('usdc_approved', False) and w.get('polymarket_approved', False))
        
        return {
            'total_wallets': total_wallets,
            'funded_wallets': funded_wallets,
            'ready_wallets': ready_wallets,
            'storage_file': self.storage_file
        }
    
    def delete_user_wallet(self, user_id: int) -> bool:
        """Delete a user's wallet (use with extreme caution!)"""
        user_id_str = str(user_id)
        if user_id_str in self.wallets_data:
            del self.wallets_data[user_id_str]
            self._save_wallets()
            print(f"🗑️ Deleted wallet for user {user_id}")
            return True
        return False

# Global wallet manager instance
wallet_manager = WalletManager()
