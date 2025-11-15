#!/usr/bin/env python3
"""
Solana Wallet Manager for Telegram Trading Bot
Manages Solana wallets for users (distinct from Polygon wallets)
"""

import json
import os
import time
from typing import Dict, Optional, Tuple
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from .config import SOLANA_WALLET_STORAGE_FILE


class SolanaWalletManager:
    """Manages Solana wallets for bridge operations"""

    def __init__(self, storage_file: str = SOLANA_WALLET_STORAGE_FILE):
        """Initialize Solana wallet manager"""
        self.storage_file = storage_file
        self.wallets_data = self._load_wallets()

    def _load_wallets(self) -> Dict:
        """Load existing Solana wallet data from storage"""
        try:
            if os.path.exists(self.storage_file):
                with open(self.storage_file, 'r') as f:
                    return json.load(f)
        except Exception as e:
            print(f"⚠️ Error loading Solana wallets: {e}")
        return {}

    def _save_wallets(self):
        """Save Solana wallet data to storage"""
        try:
            # Create backup first
            if os.path.exists(self.storage_file):
                backup_file = f"{self.storage_file}.backup"
                with open(self.storage_file, 'r') as src, open(backup_file, 'w') as dst:
                    dst.write(src.read())

            # Save current data
            with open(self.storage_file, 'w') as f:
                json.dump(self.wallets_data, f, indent=2)

        except Exception as e:
            print(f"❌ Error saving Solana wallets: {e}")
            raise

    def generate_solana_wallet_for_user(self, user_id: int, username: str = None) -> Tuple[str, str]:
        """Generate a new Solana wallet for a user"""
        try:
            # Check if user already has a Solana wallet
            user_id_str = str(user_id)
            if user_id_str in self.wallets_data:
                existing = self.wallets_data[user_id_str]
                return existing['address'], existing['private_key']

            # Generate new Solana keypair
            keypair = Keypair()

            # Get public key (address) and secret key (private key)
            address = str(keypair.pubkey())
            # Convert secret key bytes to base58 string for storage
            private_key_bytes = bytes(keypair.secret())

            # Store wallet data
            wallet_data = {
                'address': address,
                'private_key': private_key_bytes.hex(),  # Store as hex string
                'username': username,
                'created_at': time.time(),
                'polygon_address': None,  # Will be linked later
            }

            self.wallets_data[user_id_str] = wallet_data
            self._save_wallets()

            print(f"✅ Generated Solana wallet for user {user_id}: {address}")
            return address, private_key_bytes.hex()

        except Exception as e:
            print(f"❌ Error generating Solana wallet: {e}")
            raise

    def get_user_solana_wallet(self, user_id: int) -> Optional[Dict]:
        """Get Solana wallet data for a user"""
        user_id_str = str(user_id)
        return self.wallets_data.get(user_id_str)

    def get_user_solana_address(self, user_id: int) -> Optional[str]:
        """Get Solana wallet address for a user"""
        wallet = self.get_user_solana_wallet(user_id)
        return wallet['address'] if wallet else None

    def get_user_solana_private_key(self, user_id: int) -> Optional[str]:
        """Get Solana private key for a user (use carefully!)"""
        wallet = self.get_user_solana_wallet(user_id)
        return wallet['private_key'] if wallet else None

    def get_solana_keypair(self, user_id: int) -> Optional[Keypair]:
        """Get Solana Keypair object for signing transactions"""
        try:
            private_key_hex = self.get_user_solana_private_key(user_id)
            if not private_key_hex:
                return None

            # Convert hex string back to bytes
            private_key_bytes = bytes.fromhex(private_key_hex)

            # Create Keypair from secret key
            keypair = Keypair.from_bytes(private_key_bytes)
            return keypair

        except Exception as e:
            print(f"❌ Error getting Solana keypair: {e}")
            return None

    def link_polygon_address(self, user_id: int, polygon_address: str):
        """Link Polygon address to Solana wallet for tracking"""
        user_id_str = str(user_id)
        if user_id_str in self.wallets_data:
            self.wallets_data[user_id_str]['polygon_address'] = polygon_address
            self._save_wallets()

    def get_wallet_stats(self) -> Dict:
        """Get statistics about managed Solana wallets"""
        total_wallets = len(self.wallets_data)
        linked_wallets = sum(1 for w in self.wallets_data.values() if w.get('polygon_address'))

        return {
            'total_solana_wallets': total_wallets,
            'linked_to_polygon': linked_wallets,
            'storage_file': self.storage_file
        }

    def delete_user_solana_wallet(self, user_id: int) -> bool:
        """Delete a user's Solana wallet (use with extreme caution!)"""
        user_id_str = str(user_id)
        if user_id_str in self.wallets_data:
            del self.wallets_data[user_id_str]
            self._save_wallets()
            print(f"🗑️ Deleted Solana wallet for user {user_id}")
            return True
        return False


# Global Solana wallet manager instance
solana_wallet_manager = SolanaWalletManager()
