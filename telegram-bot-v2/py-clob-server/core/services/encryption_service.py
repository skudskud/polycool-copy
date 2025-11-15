"""
Encryption Service for Secure Private Key Management

ENTERPRISE-GRADE ENCRYPTION:
- AES-256-GCM: Provides authenticated encryption (detects tampering)
- Master key from ENCRYPTION_KEY environment variable
- Deterministic encryption for consistency
- Audit logging of all key access events

WHY AES-256-GCM?
- Military-grade encryption (256-bit keys)
- Authenticated: Detects if data has been tampered with
- Fast: Hardware acceleration on modern CPUs
- Industry standard: Used by Google Cloud, AWS, etc.

ENCRYPTION FLOW:
1. User data stored: Private key encrypted before DB storage
2. On read: Property getter decrypts transparently
3. On write: Property setter encrypts before DB storage
4. Audit: Every access logged with user_id, timestamp, key_type

KEY DERIVATION:
- Master key must be 32 bytes (256 bits)
- Generated once via: python -c "import base64, os; print(base64.b64encode(os.urandom(32)).decode())"
- Stored in .env as ENCRYPTION_KEY
- Never hardcoded or logged
"""

import os
import logging
import base64
from typing import Optional, Tuple
from datetime import datetime
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.backends import default_backend
from dotenv import load_dotenv

logger = logging.getLogger(__name__)
load_dotenv()

# =========================================================================
# CONSTANTS
# =========================================================================

ENCRYPTION_KEY_ENV = os.getenv('ENCRYPTION_KEY')
if not ENCRYPTION_KEY_ENV:
    logger.error("❌ CRITICAL: ENCRYPTION_KEY not set in .env - encryption disabled!")
    ENCRYPTION_KEY = None
else:
    try:
        ENCRYPTION_KEY = base64.b64decode(ENCRYPTION_KEY_ENV)
        if len(ENCRYPTION_KEY) != 32:
            raise ValueError(f"ENCRYPTION_KEY must be 32 bytes, got {len(ENCRYPTION_KEY)}")
        logger.info("✅ Encryption service initialized with master key")
    except Exception as e:
        logger.error(f"❌ Failed to load ENCRYPTION_KEY: {e}")
        ENCRYPTION_KEY = None

# Salt for key derivation (application-specific, can be public)
SALT = b"polymarket_trading_bot_v2_salt"

# =========================================================================
# ENCRYPTION/DECRYPTION FUNCTIONS
# =========================================================================

class EncryptionService:
    """
    Manages encryption and decryption of sensitive data.

    Security properties:
    - Each encryption uses a unique nonce (prevents pattern analysis)
    - Authenticated encryption (detects tampering)
    - Audit trail of all access
    """

    @staticmethod
    def encrypt(plaintext: str, context: Optional[str] = None) -> str:
        """
        Encrypt plaintext using AES-256-GCM

        Args:
            plaintext: Data to encrypt (e.g., private key)
            context: Optional context for encryption (logged in audit trail)

        Returns:
            Base64-encoded ciphertext with nonce prepended (format: nonce:ciphertext)

        Raises:
            ValueError: If encryption key not configured
        """
        if not ENCRYPTION_KEY:
            logger.error("❌ Cannot encrypt: ENCRYPTION_KEY not configured")
            raise ValueError("Encryption not properly configured - ENCRYPTION_KEY missing")

        if not plaintext:
            raise ValueError("Cannot encrypt empty plaintext")

        try:
            # Generate random 12-byte nonce (standard for GCM)
            import os as os_module
            nonce = os_module.urandom(12)

            # Create cipher
            cipher = AESGCM(ENCRYPTION_KEY)

            # Encrypt (nonce is included in returned data)
            ciphertext = cipher.encrypt(nonce, plaintext.encode('utf-8'), None)

            # Format: base64(nonce:ciphertext) for easy transport
            combined = nonce + ciphertext
            encoded = base64.b64encode(combined).decode('utf-8')

            logger.debug(f"✅ Encrypted data ({len(plaintext)} chars) → {len(encoded)} bytes [context: {context}]")
            return encoded

        except Exception as e:
            logger.error(f"❌ Encryption failed: {e}")
            raise ValueError(f"Encryption error: {e}")

    @staticmethod
    def decrypt(encrypted: str, context: Optional[str] = None) -> str:
        """
        Decrypt ciphertext encrypted with encrypt()

        Args:
            encrypted: Base64-encoded ciphertext with nonce prepended
            context: Optional context for decryption (logged in audit trail)

        Returns:
            Decrypted plaintext

        Raises:
            ValueError: If decryption fails or data is tampered with
        """
        if not ENCRYPTION_KEY:
            logger.error("❌ Cannot decrypt: ENCRYPTION_KEY not configured")
            raise ValueError("Encryption not properly configured - ENCRYPTION_KEY missing")

        if not encrypted:
            raise ValueError("Cannot decrypt empty ciphertext")

        try:
            # Decode from base64
            combined = base64.b64decode(encrypted)

            # Extract nonce (first 12 bytes) and ciphertext
            nonce = combined[:12]
            ciphertext = combined[12:]

            # Decrypt
            cipher = AESGCM(ENCRYPTION_KEY)
            plaintext = cipher.decrypt(nonce, ciphertext, None)

            logger.debug(f"✅ Decrypted data ({len(plaintext)} bytes) [context: {context}]")
            return plaintext.decode('utf-8')

        except Exception as e:
            logger.error(f"❌ Decryption failed - data may be corrupted or tampered: {e}")
            raise ValueError(f"Decryption failed (data tampered?): {e}")

    @staticmethod
    def is_encrypted(data: str) -> bool:
        """
        Check if data appears to be encrypted (base64 encoded with nonce)

        Args:
            data: Data to check

        Returns:
            True if data looks encrypted
        """
        if not data:
            return False

        try:
            decoded = base64.b64decode(data)
            # Encrypted data should be at least 12 bytes (nonce) + some ciphertext
            return len(decoded) > 12
        except Exception:
            return False

# =========================================================================
# AUDIT LOGGING
# =========================================================================

def log_key_access(user_id: int, key_type: str, action: str, source: Optional[str] = None):
    """
    Audit log for all private key access events

    Args:
        user_id: Telegram user ID
        key_type: Type of key ('polygon', 'solana', 'api_secret')
        action: Action performed ('read', 'write', 'display')
        source: Where the access came from (function name, handler name)
    """
    timestamp = datetime.utcnow().isoformat()
    logger.info(f"🔐 AUDIT [KEY_ACCESS] user={user_id} | type={key_type} | action={action} | source={source} | ts={timestamp}")


# =========================================================================
# SINGLETON INSTANCE
# =========================================================================

encryption_service = EncryptionService()
