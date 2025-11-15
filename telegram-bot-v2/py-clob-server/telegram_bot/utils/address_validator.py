#!/usr/bin/env python3
"""
Address Validation Utilities
Validates Solana and Ethereum/Polygon addresses
Prevents wrong-network withdrawal disasters
"""

import logging
import re
from typing import Tuple
from web3 import Web3
import base58

logger = logging.getLogger(__name__)


def validate_solana_address(address: str) -> Tuple[bool, str]:
    """
    Validate Solana address format

    Args:
        address: Solana address to validate

    Returns:
        (is_valid, error_message) - error_message is empty if valid
    """
    try:
        # Check if empty
        if not address or not address.strip():
            return False, "Address cannot be empty"

        address = address.strip()

        # Check length (Solana addresses are typically 32-44 characters)
        if len(address) < 32 or len(address) > 44:
            return False, f"Solana addresses must be 32-44 characters (got {len(address)})"

        # Check if starts with 0x (wrong network!)
        if address.lower().startswith('0x'):
            return False, (
                "🚨 This looks like an Ethereum/Polygon address!\n"
                "Solana addresses don't start with '0x'\n\n"
                "Example Solana address:\n"
                "7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU"
            )

        # Check base58 encoding (Solana uses base58)
        try:
            decoded = base58.b58decode(address)
            if len(decoded) != 32:
                return False, "Invalid Solana address format (wrong decoded length)"
        except Exception as e:
            return False, f"Invalid base58 encoding: {str(e)}"

        # Check not all same character (e.g., 1111...1111)
        if len(set(address)) == 1:
            return False, "Cannot send to zero address"

        # All checks passed!
        return True, ""

    except Exception as e:
        logger.error(f"❌ Error validating Solana address {address}: {e}")
        return False, f"Validation error: {str(e)}"


def validate_ethereum_address(address: str) -> Tuple[bool, str]:
    """
    Validate Ethereum/Polygon address format

    Args:
        address: Ethereum/Polygon address to validate

    Returns:
        (is_valid, error_message) - error_message is empty if valid
    """
    try:
        # Check if empty
        if not address or not address.strip():
            return False, "Address cannot be empty"

        address = address.strip()

        # Check if it's a valid Ethereum address format
        if not Web3.is_address(address):
            # Check if it looks like a Solana address
            if len(address) > 40 and not address.startswith('0x'):
                return False, (
                    "🚨 This looks like a Solana address!\n"
                    "For USDC withdrawals, use a Polygon/Ethereum address\n\n"
                    "Example Ethereum address:\n"
                    "0x742d35Cc6634C0532925a3b844343636E46c7Dd5"
                )
            return False, f"Invalid Ethereum address format: {address}"

        # Check checksum (prevents typos)
        try:
            checksummed = Web3.to_checksum_address(address)
            if address != checksummed and address != address.lower():
                # Address has wrong case
                return False, (
                    f"⚠️ Address checksum error (possible typo)\n\n"
                    f"You entered:\n{address}\n\n"
                    f"Did you mean:\n{checksummed}\n\n"
                    f"This prevents sending to wrong address."
                )
        except Exception:
            # Some addresses don't have checksums, that's OK
            pass

        # Check not zero address
        if address.lower() == '0x0000000000000000000000000000000000000000':
            return False, "❌ Cannot send to zero address (funds will be burned!)"

        # All checks passed!
        return True, ""

    except Exception as e:
        logger.error(f"❌ Error validating Ethereum address {address}: {e}")
        return False, f"Validation error: {str(e)}"


def detect_network_mismatch(token: str, address: str) -> Tuple[bool, str]:
    """
    Detect if user is trying to send to wrong network
    This is CRITICAL - prevents permanent fund loss!

    Args:
        token: Token being withdrawn ('SOL', 'USDC', 'USDC.e')
        address: Destination address

    Returns:
        (is_mismatch, warning_message) - warning_message is empty if no mismatch
    """
    try:
        address = address.strip()

        if token == 'SOL':
            # Withdrawing SOL - should be Solana address
            if address.startswith('0x'):
                return True, (
                    "🚨 **CRITICAL ERROR: NETWORK MISMATCH!**\n\n"
                    "**You're withdrawing:** SOL (Solana network)\n"
                    "**But entered:** Ethereum/Polygon address (0x...)\n\n"
                    "❌ **FUNDS WILL BE LOST FOREVER IF YOU CONTINUE!**\n\n"
                    "✅ **Solana addresses look like:**\n"
                    "`7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU`\n"
                    "• 32-44 characters\n"
                    "• No '0x' prefix\n"
                    "• Base58 encoded\n\n"
                    "Please enter a valid Solana address."
                )

        elif token in ['USDC', 'USDC.e']:
            # Withdrawing USDC - should be Ethereum/Polygon address
            if not address.startswith('0x') and len(address) > 40:
                return True, (
                    "🚨 **CRITICAL ERROR: NETWORK MISMATCH!**\n\n"
                    "**You're withdrawing:** USDC (Polygon network)\n"
                    "**But entered:** Solana address\n\n"
                    "❌ **FUNDS WILL BE LOST FOREVER IF YOU CONTINUE!**\n\n"
                    "✅ **Polygon/Ethereum addresses look like:**\n"
                    "`0x742d35Cc6634C0532925a3b844343636E46c7Dd5`\n"
                    "• Starts with '0x'\n"
                    "• 42 characters total\n"
                    "• Works with any Ethereum-compatible wallet\n\n"
                    "Please enter a valid Ethereum/Polygon address."
                )

        # No mismatch detected
        return False, ""

    except Exception as e:
        logger.error(f"❌ Error detecting network mismatch: {e}")
        return False, ""


def format_address_display(address: str, show_chars: int = 6) -> str:
    """
    Format address for display (shortened with ellipsis)

    Args:
        address: Full address
        show_chars: Number of characters to show on each side

    Returns:
        Formatted address like "0x742d...7Dd5" or "7xKXtg...sgAsU"
    """
    try:
        if not address or len(address) <= (show_chars * 2 + 3):
            return address

        return f"{address[:show_chars]}...{address[-show_chars:]}"

    except Exception:
        return address


def check_same_address(address: str, user_address: str) -> Tuple[bool, str]:
    """
    Check if user is trying to send to their own address (pointless)

    Args:
        address: Destination address
        user_address: User's wallet address

    Returns:
        (is_same, warning_message) - warning_message is empty if different
    """
    try:
        # Normalize addresses for comparison
        address_normalized = address.strip().lower()
        user_address_normalized = user_address.strip().lower()

        if address_normalized == user_address_normalized:
            return True, (
                "⚠️ **Same Address Warning**\n\n"
                "You're trying to withdraw to your own wallet address.\n"
                "Your funds are already there!\n\n"
                "If you want to withdraw to a different wallet, "
                "please enter that address instead."
            )

        return False, ""

    except Exception as e:
        logger.error(f"❌ Error checking same address: {e}")
        return False, ""


# Export functions
__all__ = [
    'validate_solana_address',
    'validate_ethereum_address',
    'detect_network_mismatch',
    'format_address_display',
    'check_same_address'
]
