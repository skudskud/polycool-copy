#!/usr/bin/env python3
"""
Validators
Input validation utilities for the bot
"""

import re
from config.config import MIN_TRADE_AMOUNT_USD, MAX_TRADE_AMOUNT_USD


def validate_amount_input(amount_text: str) -> tuple[bool, float, str]:
    """
    Validate user amount input

    Args:
        amount_text: Raw amount text from user

    Returns:
        Tuple of (is_valid, amount, error_message)
    """
    try:
        # Clean the input - remove $ and whitespace
        cleaned = re.sub(r'[\$\s,]', '', amount_text.strip())

        # Try to parse as float
        amount = float(cleaned)

        # Check minimum
        if amount < MIN_TRADE_AMOUNT_USD:
            return False, 0, f"❌ Minimum amount is ${MIN_TRADE_AMOUNT_USD:.2f}"

        # Check maximum
        if amount > MAX_TRADE_AMOUNT_USD:
            return False, 0, f"❌ Maximum amount is ${MAX_TRADE_AMOUNT_USD:.2f}"

        return True, amount, ""

    except ValueError:
        return False, 0, "❌ Please enter a valid number (e.g., 10 or $10.50)"


def validate_wallet_address(address: str) -> tuple[bool, str]:
    """
    Validate Polygon wallet address format

    Args:
        address: Wallet address string

    Returns:
        Tuple of (is_valid, error_message)
    """
    if not address:
        return False, "Address cannot be empty"

    if not address.startswith('0x'):
        return False, "Address must start with 0x"

    if len(address) != 42:
        return False, "Address must be 42 characters long"

    # Check if it's valid hexadecimal
    try:
        int(address[2:], 16)
    except ValueError:
        return False, "Address must be valid hexadecimal"

    return True, ""


def validate_api_credentials(api_key: str, api_secret: str, api_passphrase: str) -> tuple[bool, str]:
    """
    Validate API credentials format

    Args:
        api_key: API key string
        api_secret: API secret string
        api_passphrase: API passphrase string

    Returns:
        Tuple of (is_valid, error_message)
    """
    if not api_key or not api_secret or not api_passphrase:
        return False, "All API credentials are required"

    if len(api_key) < 10:
        return False, "API key seems too short"

    if len(api_secret) < 10:
        return False, "API secret seems too short"

    if len(api_passphrase) < 4:
        return False, "API passphrase seems too short"

    return True, ""


def validate_percentage(percentage_text: str) -> tuple[bool, int, str]:
    """
    Validate percentage input (for sell orders)

    Args:
        percentage_text: Percentage text from user

    Returns:
        Tuple of (is_valid, percentage, error_message)
    """
    try:
        # Remove % sign if present
        cleaned = percentage_text.strip().replace('%', '')
        percentage = int(cleaned)

        if percentage < 1:
            return False, 0, "❌ Percentage must be at least 1%"

        if percentage > 100:
            return False, 0, "❌ Percentage cannot exceed 100%"

        return True, percentage, ""

    except ValueError:
        return False, 0, "❌ Please enter a valid percentage (e.g., 50 or 100)"


def validate_solana_address(address: str) -> tuple[bool, str]:
    """
    Validate Solana wallet address format (base58)

    Args:
        address: Solana address string

    Returns:
        Tuple of (is_valid, error_message)
    """
    if not address:
        return False, "Address cannot be empty"

    # Solana addresses are typically 32-44 characters
    if len(address) < 32 or len(address) > 44:
        return False, "Invalid Solana address length"

    # Check if it contains only valid base58 characters
    base58_chars = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    if not all(c in base58_chars for c in address):
        return False, "Invalid Solana address format"

    return True, ""


def validate_token_amount(tokens_text: str) -> tuple[bool, int, str]:
    """
    Validate token amount input

    Args:
        tokens_text: Token amount text from user

    Returns:
        Tuple of (is_valid, tokens, error_message)
    """
    try:
        tokens = int(tokens_text.strip())

        if tokens < 1:
            return False, 0, "❌ Token amount must be at least 1"

        if tokens > 1000000:
            return False, 0, "❌ Token amount seems unreasonably high"

        return True, tokens, ""

    except ValueError:
        return False, 0, "❌ Please enter a valid token amount (whole number)"
