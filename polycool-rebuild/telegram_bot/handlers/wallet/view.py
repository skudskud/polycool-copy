"""
Wallet view handler
Handles /wallet command and wallet display functionality including private key display with auto-destruction
"""

import asyncio
import logging
import os
from datetime import datetime
from typing import Dict, Any, Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from core.services.user.user_helper import get_user_data, get_user_internal_id
from core.services.user.user_service import user_service
from core.services.encryption.encryption_service import EncryptionService
from core.services.balance.balance_service import balance_service
from infrastructure.logging.logger import get_logger

logger = get_logger(__name__)

# Check if bot has DB access
SKIP_DB = os.getenv("SKIP_DB", "true").lower() == "true"

# Import API client if SKIP_DB is true
if SKIP_DB:
    from core.services.api_client import get_api_client


async def handle_wallet_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle /wallet command - Show wallet overview with private key display options
    """
    if not update.effective_user:
        return

    telegram_user_id = update.effective_user.id

    try:
        logger.info(f"💼 /wallet command - User {telegram_user_id}")

        # Get user data (via API or DB)
        user_data = await get_user_data(telegram_user_id)
        if not user_data:
            await update.message.reply_text(
                "❌ No wallet found. Please use /start to create your wallet."
            )
            return

        # Determine user stage for display
        stage = user_data.get('stage', 'onboarding')
        polygon_address = user_data.get('polygon_address')
        solana_address = user_data.get('solana_address')

        # Get USDC.e balance if user has Polygon wallet
        # Force fresh balance fetch (bypass cache) when user requests /wallet
        usdc_balance = None
        if polygon_address and stage == "ready":
            try:
                if SKIP_DB:
                    # Use API client to get balance with cache bypass to force fresh fetch
                    api_client = get_api_client()
                    internal_id = user_data.get('id')
                    if internal_id:
                        balance_data = await api_client.get_wallet_balance(internal_id, use_cache=False)
                        if balance_data:
                            usdc_balance = balance_data.get('usdc_balance')
                else:
                    # Direct DB access - always fresh (no cache)
                    usdc_balance = await balance_service.get_usdc_balance(polygon_address)
            except Exception as e:
                logger.warning(f"Could not fetch USDC.e balance: {e}")

        # Build wallet display message
        message = _build_wallet_message(user_data, stage, usdc_balance)

        # Build keyboard with private key display options
        keyboard = _build_wallet_keyboard(stage)

        await update.message.reply_text(
            message,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )

        logger.info(f"✅ Wallet displayed for user {telegram_user_id}")

    except Exception as e:
        logger.error(f"Error in wallet handler for user {telegram_user_id}: {e}")
        await update.message.reply_text(
            "❌ An error occurred. Please try again."
        )


def _build_wallet_message(user_data: Dict[str, Any], stage: str, usdc_balance: float = None) -> str:
    """Build wallet display message"""
    message = "**💼 YOUR WALLETS**\n\n"

    # Show USDC.e balance if available
    if usdc_balance is not None:
        message += f"{balance_service.format_balance_display(usdc_balance)}\n\n"

    polygon_address = user_data.get('polygon_address')
    solana_address = user_data.get('solana_address')

    # Polygon wallet
    if polygon_address:
        message += f"🔷 **POLYGON WALLET**\n"
        message += f"📍 Address: `{polygon_address[:10]}...{polygon_address[-8:]}`\n"
        message += f"📊 Status: {stage.upper()}\n\n"
    else:
        message += "🔷 **POLYGON WALLET**\n"
        message += "📍 Not created yet\n\n"

    # Solana wallet
    if solana_address:
        message += f"🔶 **SOLANA WALLET**\n"
        message += f"📍 Address: `{solana_address[:10]}...{solana_address[-8:]}`\n"
        message += f"📊 Status: {stage.upper()}\n\n"
    else:
        message += "🔶 **SOLANA WALLET**\n"
        message += "📍 Not created yet\n\n"

    return message


def _build_wallet_keyboard(stage: str) -> list:
    """Build wallet keyboard with private key display options"""
    keyboard = []

    # Private key display buttons (only for ready users)
    if stage == "ready":
        keyboard.append([
            InlineKeyboardButton("🔑 Show Polygon Key", callback_data="show_polygon_key"),
            InlineKeyboardButton("🔑 Show Solana Key", callback_data="show_solana_key")
        ])

    # Action buttons
    if stage == "onboarding":
        keyboard.append([InlineKeyboardButton("🌉 Bridge SOL → USDC", callback_data="bridge_sol")])
    else:
        keyboard.append([
            InlineKeyboardButton("🌉 Bridge SOL → USDC", callback_data="bridge_sol"),
            InlineKeyboardButton("💼 View Details", callback_data="wallet_details")
        ])

    # Navigation
    keyboard.append([InlineKeyboardButton("↩️ Back", callback_data="main_menu")])

    return keyboard


async def handle_show_polygon_key_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle callback to show Polygon private key with auto-destruction after 10 seconds
    """
    if not update.callback_query:
        return

    query = update.callback_query
    telegram_user_id = query.from_user.id

    logger.info(f"🔑 [POLYGON_KEY_DISPLAY_START] user_id={telegram_user_id} | ts={datetime.utcnow().isoformat()} | SKIP_DB={SKIP_DB}")

    try:
        # Answer callback
        await query.answer()
        logger.info(f"✅ [POLYGON_KEY_CALLBACK_ANSWERED] user_id={telegram_user_id}")

        # Get user data (via API or DB)
        user_data = await get_user_data(telegram_user_id)
        if not user_data or not user_data.get('polygon_address'):
            await query.answer("❌ No Polygon wallet found", show_alert=True)
            return

        # Get private key via API (decrypted server-side) or DB fallback
        private_key = None
        if SKIP_DB:
            logger.info(f"🔗 [POLYGON_KEY_API_CALL] user_id={telegram_user_id} - Calling API for private key")
            # Use API client to get decrypted private key
            api_client = get_api_client()
            private_key = await api_client.get_private_key(telegram_user_id, "polygon")
            logger.info(f"📥 [POLYGON_KEY_API_RESPONSE] user_id={telegram_user_id} - API returned: {'YES' if private_key else 'NO'}")
            if not private_key:
                logger.warning(f"⚠️ [POLYGON_KEY_API_EMPTY] user_id={telegram_user_id} - No private key from API")
                await query.answer("❌ Private key not available. Please try again.", show_alert=True)
                return
        else:
            logger.info(f"💾 [POLYGON_KEY_DB_FALLBACK] user_id={telegram_user_id} - Using DB fallback")
            # Direct DB access (for development/testing)
            # Use get_user_data for consistency, then get full user object if needed
            user_data = await get_user_data(telegram_user_id)
            if not user_data:
                logger.warning(f"⚠️ [POLYGON_KEY_DB_MISSING] user_id={telegram_user_id} - No user data found")
                await query.answer("❌ No Polygon wallet found", show_alert=True)
                return

            # Get full user object for private key access
            user = await user_service.get_by_id(user_data.get('id'))
            if not user or not user.polygon_private_key:
                logger.warning(f"⚠️ [POLYGON_KEY_DB_MISSING] user_id={telegram_user_id} - No polygon wallet in DB")
                await query.answer("❌ No Polygon wallet found", show_alert=True)
                return

            # Decrypt private key locally
            encryption_service = EncryptionService()
            try:
                private_key = encryption_service.decrypt_private_key(user.polygon_private_key)
                logger.info(f"✅ [POLYGON_KEY_DB_DECRYPTED] user_id={telegram_user_id}")
            except Exception as e:
                logger.error(f"❌ [POLYGON_DECRYPT_FAILED] user_id={telegram_user_id} | error={str(e)}")
                await query.answer("❌ Failed to decrypt private key", show_alert=True)
                return

            if not private_key:
                logger.warning(f"⚠️ [POLYGON_KEY_DB_EMPTY] user_id={telegram_user_id} - Decryption returned empty")
                await query.answer("❌ Failed to decrypt private key", show_alert=True)
                return

        # Validate key format
        if not private_key or not private_key.startswith('0x') or len(private_key) < 60:
            logger.warning(f"⚠️ [POLYGON_KEY_FORMAT_INVALID] user_id={telegram_user_id} | key_len={len(private_key) if private_key else 0}")
            await query.answer("❌ Invalid key format", show_alert=True)
            return

        logger.info(f"✅ [POLYGON_KEY_DECRYPTED] user_id={telegram_user_id} | key_len={len(private_key)}")

        # Create keyboard to hide key
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Hide Key", callback_data="hide_polygon_key")]
        ])

        # Send key message
        key_msg = await query.message.reply_text(
            f"🔑 **Your Polygon Private Key:**\n\n`{private_key}`\n\n"
            f"⚠️ **KEEP THIS SECRET!**\n"
            f"🚨 This message will self-destruct in 10 seconds.\n"
            f"Click the button below to hide it immediately.",
            parse_mode='Markdown',
            reply_markup=keyboard
        )

        logger.info(f"✅ [POLYGON_KEY_MESSAGE_SENT] user_id={telegram_user_id} | message_id={key_msg.message_id}")

        # Auto-delete after 10 seconds (non-blocking)
        async def auto_delete():
            await asyncio.sleep(10)
            try:
                await key_msg.delete()
                logger.info(f"✅ [POLYGON_KEY_AUTO_DELETED] user_id={telegram_user_id} | message_id={key_msg.message_id}")
            except Exception as e:
                logger.warning(f"⚠️ [POLYGON_KEY_AUTO_DELETE_FAILED] user_id={telegram_user_id} | message_id={key_msg.message_id} | error={str(e)}")

        asyncio.create_task(auto_delete())

    except Exception as e:
        logger.error(f"❌ [POLYGON_KEY_CRITICAL_ERROR] user_id={telegram_user_id} | error={str(e)}", exc_info=True)
        try:
            await query.answer(f"❌ Error: {str(e)[:60]}", show_alert=True)
        except:
            pass


async def handle_show_solana_key_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle callback to show Solana private key with auto-destruction after 10 seconds
    """
    if not update.callback_query:
        return

    query = update.callback_query
    telegram_user_id = query.from_user.id

    logger.info(f"🔑 [SOLANA_KEY_DISPLAY_START] user_id={telegram_user_id} | ts={datetime.utcnow().isoformat()}")

    try:
        # Answer callback
        await query.answer()

        # Get user data (via API or DB)
        user_data = await get_user_data(telegram_user_id)
        if not user_data or not user_data.get('solana_address'):
            await query.answer("❌ No Solana wallet found", show_alert=True)
            return

        # Get private key via API (decrypted server-side) or DB fallback
        private_key = None
        if SKIP_DB:
            # Use API client to get decrypted private key
            api_client = get_api_client()
            private_key = await api_client.get_private_key(telegram_user_id, "solana")
            if not private_key:
                await query.answer("❌ Private key not available. Please try again.", show_alert=True)
                return
        else:
            # Direct DB access (for development/testing)
            # Use get_user_data for consistency, then get full user object if needed
            user_data = await get_user_data(telegram_user_id)
            if not user_data:
                await query.answer("❌ No Solana wallet found", show_alert=True)
                return

            # Get full user object for private key access
            user = await user_service.get_by_id(user_data.get('id'))
            if not user or not user.solana_private_key:
                await query.answer("❌ No Solana wallet found", show_alert=True)
                return

            # Decrypt private key locally
            encryption_service = EncryptionService()
            try:
                private_key = encryption_service.decrypt_private_key(user.solana_private_key)
            except Exception as e:
                logger.error(f"❌ [SOLANA_DECRYPT_FAILED] user_id={telegram_user_id} | error={str(e)}")
                await query.answer("❌ Failed to decrypt private key", show_alert=True)
                return

            if not private_key:
                await query.answer("❌ Failed to decrypt private key", show_alert=True)
                return

        # Validate key format
        if not private_key or len(private_key) < 40:
            logger.warning(f"⚠️ [SOLANA_KEY_FORMAT_INVALID] user_id={telegram_user_id} | key_len={len(private_key) if private_key else 0}")
            await query.answer("❌ Invalid key format", show_alert=True)
            return

        logger.info(f"✅ [SOLANA_KEY_DECRYPTED] user_id={telegram_user_id} | key_len={len(private_key)}")

        # Create keyboard to hide key
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Hide Key", callback_data="hide_solana_key")]
        ])

        # Send key message
        key_msg = await query.message.reply_text(
            f"🔑 **Your Solana Private Key:**\n\n`{private_key}`\n\n"
            f"⚠️ **KEEP THIS SECRET!**\n"
            f"🚨 This message will self-destruct in 10 seconds.\n"
            f"Click the button below to hide it immediately.",
            parse_mode='Markdown',
            reply_markup=keyboard
        )

        logger.info(f"✅ [SOLANA_KEY_MESSAGE_SENT] user_id={telegram_user_id} | message_id={key_msg.message_id}")

        # Auto-delete after 10 seconds (non-blocking)
        async def auto_delete():
            await asyncio.sleep(10)
            try:
                await key_msg.delete()
                logger.info(f"✅ [SOLANA_KEY_AUTO_DELETED] user_id={telegram_user_id} | message_id={key_msg.message_id}")
            except Exception as e:
                logger.warning(f"⚠️ [SOLANA_KEY_AUTO_DELETE_FAILED] user_id={telegram_user_id} | message_id={key_msg.message_id} | error={str(e)}")

        asyncio.create_task(auto_delete())

    except Exception as e:
        logger.error(f"❌ [SOLANA_KEY_CRITICAL_ERROR] user_id={telegram_user_id} | error={str(e)}", exc_info=True)
        try:
            await query.answer(f"❌ Error: {str(e)[:60]}", show_alert=True)
        except:
            pass


async def handle_hide_polygon_key_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle callback to hide Polygon private key message
    """
    if not update.callback_query:
        return

    query = update.callback_query
    telegram_user_id = query.from_user.id

    try:
        await query.answer()
        await query.message.delete()
        logger.info(f"✅ [POLYGON_KEY_MANUALLY_HIDDEN] user_id={telegram_user_id}")
    except Exception as e:
        logger.warning(f"⚠️ [POLYGON_KEY_HIDE_FAILED] user_id={telegram_user_id} | error={str(e)}")


async def handle_hide_solana_key_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle callback to hide Solana private key message
    """
    if not update.callback_query:
        return

    query = update.callback_query
    telegram_user_id = query.from_user.id

    try:
        await query.answer()
        await query.message.delete()
        logger.info(f"✅ [SOLANA_KEY_MANUALLY_HIDDEN] user_id={telegram_user_id}")
    except Exception as e:
        logger.warning(f"⚠️ [SOLANA_KEY_HIDE_FAILED] user_id={telegram_user_id} | error={str(e)}")


# Export all handlers
__all__ = [
    'handle_wallet_command',
    'handle_show_polygon_key_callback',
    'handle_show_solana_key_callback',
    'handle_hide_polygon_key_callback',
    'handle_hide_solana_key_callback'
]
