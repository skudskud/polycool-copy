#!/usr/bin/env python3
"""
Solana Wallet Manager V2
Simple storage in JSON (like Polygon wallets)
"""

import json
import logging
from pathlib import Path
import base58
from solders.keypair import Keypair

logger = logging.getLogger(__name__)

# Storage file
STORAGE_FILE = Path(__file__).parent / 'data' / 'solana_wallets.json'


class SolanaWalletManagerV2:
    """Manage Solana wallets for users - simple JSON storage"""

    def __init__(self):
        self.wallets = self._load_wallets()

    def _load_wallets(self) -> dict:
        """Load wallets from JSON file"""
        try:
            if STORAGE_FILE.exists():
                with open(STORAGE_FILE, 'r') as f:
                    wallets = json.load(f)
                logger.info(f"✅ Loaded {len(wallets)} Solana wallets")
                return wallets
            else:
                logger.info("📁 No existing Solana wallets file, starting fresh")
                return {}
        except Exception as e:
            logger.error(f"❌ Error loading Solana wallets: {e}")
            return {}

    def _save_wallets(self) -> bool:
        """Save wallets to JSON file"""
        try:
            # Create data directory if needed
            STORAGE_FILE.parent.mkdir(parents=True, exist_ok=True)

            with open(STORAGE_FILE, 'w') as f:
                json.dump(self.wallets, f, indent=2)

            logger.info(f"💾 Saved {len(self.wallets)} Solana wallets")
            return True
        except Exception as e:
            logger.error(f"❌ Error saving Solana wallets: {e}")
            return False

    def generate_wallet_for_user(self, user_id: int, username: str = "Unknown") -> tuple:
        """
        Generate Solana wallet for user

        Args:
            user_id: Telegram user ID
            username: Telegram username

        Returns:
            (address, private_key) tuple
        """
        user_key = str(user_id)

        # Check if wallet already exists
        if user_key in self.wallets:
            logger.info(f"ℹ️ User {user_id} already has Solana wallet")
            wallet = self.wallets[user_key]
            return (wallet['address'], wallet['private_key'])

        # Generate new keypair
        keypair = Keypair()

        address = str(keypair.pubkey())
        private_key = base58.b58encode(bytes(keypair)).decode('ascii')

        # Store wallet
        self.wallets[user_key] = {
            'user_id': user_id,
            'username': username,
            'address': address,
            'private_key': private_key,
            'created_at': __import__('time').time()
        }

        # Save to file
        self._save_wallets()

        logger.info(f"✅ Generated Solana wallet for user {user_id} ({username})")
        logger.info(f"   Address: {address}")

        return (address, private_key)

    def get_user_wallet(self, user_id: int) -> dict:
        """Get user's Solana wallet"""
        user_key = str(user_id)
        return self.wallets.get(user_key)
    
    def get_or_create_wallet(self, user_id: int, username: str = "Unknown") -> dict:
        """Get existing wallet or create new one for user"""
        # First try to get existing wallet
        existing_wallet = self.get_user_wallet(user_id)
        if existing_wallet:
            return existing_wallet
        
        # Create new wallet if doesn't exist
        address, private_key = self.generate_wallet_for_user(user_id, username)
        
        # Return the wallet data
        return {
            'user_id': user_id,
            'username': username,
            'address': address,
            'private_key': private_key,
            'created_at': __import__('time').time()
        }

    def get_user_address(self, user_id: int) -> str:
        """Get user's Solana address"""
        wallet = self.get_user_wallet(user_id)
        return wallet['address'] if wallet else None

    def get_user_private_key(self, user_id: int) -> str:
        """Get user's Solana private key"""
        wallet = self.get_user_wallet(user_id)
        return wallet['private_key'] if wallet else None


# Global instance
solana_wallet_manager_v2 = SolanaWalletManagerV2()
