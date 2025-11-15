"""
Wallet Service - Wallet generation and management
Generates Polygon and Solana wallets
Encrypts private keys before storage
"""
from typing import Tuple, Optional
from eth_account import Account
from solders.keypair import Keypair
import base58

from core.services.encryption.encryption_service import encryption_service
from infrastructure.logging.logger import get_logger

logger = get_logger(__name__)

# Enable HD wallet features for Ethereum wallet generation
Account.enable_unaudited_hdwallet_features()


class WalletService:
    """
    Wallet Service - Generates and manages wallets
    - Polygon (Ethereum) wallet generation
    - Solana wallet generation
    - Private key encryption
    """

    def generate_polygon_wallet(self) -> Tuple[str, str]:
        """
        Generate a new Polygon (Ethereum) wallet

        Returns:
            Tuple of (address, private_key_hex)
        """
        try:
            account = Account.create()
            address = account.address
            private_key_hex = account.key.hex()

            logger.info(f"✅ Generated Polygon wallet: {address}")
            return address, private_key_hex

        except Exception as e:
            logger.error(f"❌ Error generating Polygon wallet: {e}")
            raise

    def generate_solana_wallet(self) -> Tuple[str, str]:
        """
        Generate a new Solana wallet

        Returns:
            Tuple of (address, private_key_base58)
        """
        try:
            keypair = Keypair()
            address = str(keypair.pubkey())
            private_key_bytes = bytes(keypair)
            private_key_base58 = base58.b58encode(private_key_bytes).decode('ascii')

            logger.info(f"✅ Generated Solana wallet: {address}")
            return address, private_key_base58

        except Exception as e:
            logger.error(f"❌ Error generating Solana wallet: {e}")
            raise

    def generate_user_wallets(self) -> dict:
        """
        Generate both Polygon and Solana wallets for a user
        Returns encrypted private keys ready for storage

        Returns:
            Dictionary with wallet addresses and encrypted private keys
        """
        try:
            # Generate Polygon wallet
            polygon_address, polygon_private_key = self.generate_polygon_wallet()
            encrypted_polygon_key = encryption_service.encrypt_private_key(polygon_private_key)

            # Generate Solana wallet
            solana_address, solana_private_key = self.generate_solana_wallet()
            encrypted_solana_key = encryption_service.encrypt_private_key(solana_private_key)

            return {
                "polygon_address": polygon_address,
                "polygon_private_key": encrypted_polygon_key,
                "solana_address": solana_address,
                "solana_private_key": encrypted_solana_key,
            }

        except Exception as e:
            logger.error(f"❌ Error generating user wallets: {e}")
            raise

    def decrypt_polygon_key(self, encrypted_key: str) -> Optional[str]:
        """
        Decrypt Polygon private key

        Args:
            encrypted_key: Encrypted private key

        Returns:
            Decrypted private key hex or None if error
        """
        return encryption_service.decrypt_private_key(encrypted_key)

    def decrypt_solana_key(self, encrypted_key: str) -> Optional[str]:
        """
        Decrypt Solana private key

        Args:
            encrypted_key: Encrypted private key

        Returns:
            Decrypted private key base58 or None if error
        """
        return encryption_service.decrypt_private_key(encrypted_key)

    def get_solana_keypair(self, encrypted_key: str) -> Optional[Keypair]:
        """
        Get Solana Keypair object from encrypted private key

        Args:
            encrypted_key: Encrypted Solana private key

        Returns:
            Keypair object or None if error
        """
        try:
            private_key_base58 = self.decrypt_solana_key(encrypted_key)
            if not private_key_base58:
                return None

            private_key_bytes = base58.b58decode(private_key_base58)
            keypair = Keypair.from_bytes(private_key_bytes)
            return keypair

        except Exception as e:
            logger.error(f"❌ Error creating Solana keypair: {e}")
            return None

    def validate_polygon_address(self, address: str) -> bool:
        """
        Validate Polygon address format

        Args:
            address: Address to validate

        Returns:
            True if valid, False otherwise
        """
        try:
            # Basic validation: should be 42 chars, start with 0x
            if not address or len(address) != 42 or not address.startswith("0x"):
                return False
            # Check if it's a valid hex string
            int(address[2:], 16)
            return True
        except Exception:
            return False

    def validate_solana_address(self, address: str) -> bool:
        """
        Validate Solana address format

        Args:
            address: Address to validate

        Returns:
            True if valid, False otherwise
        """
        try:
            # Basic validation: should be base58 encoded, 32-44 chars
            if not address or len(address) < 32 or len(address) > 44:
                return False
            # Try to decode as base58
            base58.b58decode(address)
            return True
        except Exception:
            return False


# Global instance
wallet_service = WalletService()
