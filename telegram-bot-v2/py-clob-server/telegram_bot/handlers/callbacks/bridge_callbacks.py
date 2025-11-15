#!/usr/bin/env python3
"""
Bridge Callbacks Module
Handles all bridge-related callbacks (SOL -> USDC bridging)
"""

import logging
import os
import sys

logger = logging.getLogger(__name__)

# Import from callback_handlers for handle_bridge_from_wallet
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from ..callback_handlers import handle_bridge_from_wallet

# Try to import from bridge_handlers module
try:
    # Fixed: Use absolute import instead of relative
    from telegram_bot.handlers.bridge_handlers import (
        handle_fund_bridge_solana,
        handle_confirm_bridge,
        handle_cancel_bridge,
        handle_refresh_sol_balance,
        handle_bridge_auto,
        handle_bridge_custom_amount,
        handle_copy_solana_address,
        handle_back_to_bridge_menu
    )
except ImportError as e:
    # Fallback stubs if module doesn't exist
    logger.error(f"❌ Failed to import bridge_handlers: {e}")
    async def handle_fund_bridge_solana(query, callback_data, *args, kwargs):
        await query.edit_message_text("⚠️ Bridge feature not available")

    async def handle_confirm_bridge(query, callback_data, *args, kwargs):
        await query.edit_message_text("⚠️ Bridge feature not available")

    async def handle_cancel_bridge(query, callback_data, *args, kwargs):
        await query.edit_message_text("⚠️ Bridge feature not available")

    async def handle_refresh_sol_balance(query, callback_data, *args, kwargs):
        await query.edit_message_text("⚠️ Bridge feature not available")

    async def handle_bridge_auto(query, callback_data, *args, kwargs):
        await query.edit_message_text("⚠️ Bridge feature not available")

    async def handle_bridge_custom_amount(query, callback_data, *args, kwargs):
        await query.edit_message_text("⚠️ Bridge feature not available")

    async def handle_copy_solana_address(query, callback_data, *args, kwargs):
        await query.edit_message_text("⚠️ Bridge feature not available")

    async def handle_back_to_bridge_menu(query, callback_data, *args, kwargs):
        await query.edit_message_text("⚠️ Bridge feature not available")

__all__ = [
    'handle_bridge_from_wallet',
    'handle_fund_bridge_solana',
    'handle_confirm_bridge',
    'handle_cancel_bridge',
    'handle_refresh_sol_balance',
    'handle_bridge_auto',
    'handle_bridge_custom_amount',
    'handle_copy_solana_address',
    'handle_back_to_bridge_menu'
]
