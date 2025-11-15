"""
Encryption Service - AES-256-GCM encryption for sensitive data
Encrypts/decrypts private keys and API secrets
"""
import base64
from typing import Optional
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.backends import default_backend

from infrastructure.config.settings import settings
from infrastructure.logging.logger import get_logger

logger = get_logger(__name__)


class EncryptionService:
    """
    AES-256-GCM encryption service
    - Encrypts private keys and API secrets
    - Secure key management
    """

    def __init__(self):
        """Initialize encryption service with key from settings"""
        key = settings.security.encryption_key
        if len(key) != 32:
            raise ValueError("Encryption key must be exactly 32 bytes for AES-256")
        self.key = key.encode('utf-8') if isinstance(key, str) else key
        self.aesgcm = AESGCM(self.key)

    def encrypt(self, plaintext: str) -> str:
        """
        Encrypt plaintext using AES-256-GCM

        Args:
            plaintext: Plaintext string to encrypt

        Returns:
            Base64-encoded encrypted string (nonce + ciphertext + tag)
        """
        try:
            if not plaintext:
                return ""

            # Generate nonce (12 bytes for GCM)
            import os
            nonce = os.urandom(12)

            # Encrypt
            plaintext_bytes = plaintext.encode('utf-8')
            ciphertext = self.aesgcm.encrypt(nonce, plaintext_bytes, None)

            # Combine nonce + ciphertext (tag is appended by AESGCM)
            encrypted_data = nonce + ciphertext

            # Encode as base64
            return base64.b64encode(encrypted_data).decode('utf-8')

        except Exception as e:
            logger.error(f"❌ Encryption error: {e}")
            raise

    def decrypt(self, ciphertext: str) -> Optional[str]:
        """
        Decrypt ciphertext using AES-256-GCM

        Args:
            ciphertext: Base64-encoded encrypted string

        Returns:
            Decrypted plaintext string or None if error
        """
        try:
            if not ciphertext:
                return ""

            # Decode from base64
            encrypted_data = base64.b64decode(ciphertext.encode('utf-8'))

            # Extract nonce (first 12 bytes) and ciphertext (rest includes tag)
            nonce = encrypted_data[:12]
            ciphertext_bytes = encrypted_data[12:]

            # Decrypt
            plaintext_bytes = self.aesgcm.decrypt(nonce, ciphertext_bytes, None)

            return plaintext_bytes.decode('utf-8')

        except Exception as e:
            logger.error(f"❌ Decryption error: {e}")
            return None

    def encrypt_private_key(self, private_key: str) -> str:
        """
        Encrypt a private key (Polygon or Solana)

        Args:
            private_key: Private key string

        Returns:
            Encrypted private key
        """
        return self.encrypt(private_key)

    def decrypt_private_key(self, encrypted_key: str) -> Optional[str]:
        """
        Decrypt a private key (Polygon or Solana)

        Args:
            encrypted_key: Encrypted private key string

        Returns:
            Decrypted private key or None if error
        """
        return self.decrypt(encrypted_key)

    def encrypt_api_secret(self, api_secret: str) -> str:
        """
        Encrypt API secret

        Args:
            api_secret: API secret string

        Returns:
            Encrypted API secret
        """
        return self.encrypt(api_secret)

    def decrypt_api_secret(self, encrypted_secret: str) -> Optional[str]:
        """
        Decrypt API secret

        Args:
            encrypted_secret: Encrypted API secret string

        Returns:
            Decrypted API secret or None if error
        """
        return self.decrypt(encrypted_secret)


# Global instance
encryption_service = EncryptionService()
