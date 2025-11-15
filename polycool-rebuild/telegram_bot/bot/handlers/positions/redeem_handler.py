"""
REDEMPTION CALLBACK HANDLER
Handles user interactions for redeeming resolved positions
"""
import os
from telegram import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from core.services.redeem.redemption_service import get_redemption_service
from core.services.user.user_service import user_service
from core.services.encryption.encryption_service import EncryptionService
from infrastructure.logging.logger import get_logger

logger = get_logger(__name__)

# Check if bot has DB access
SKIP_DB = os.getenv("SKIP_DB", "true").lower() == "true"

# Import API client if SKIP_DB is true
if SKIP_DB:
    from core.services.api_client import get_api_client


async def handle_redeem_position(query: CallbackQuery, resolved_position_id: int) -> None:
    """Handle redemption request for a resolved position"""
    user_id = query.from_user.id

    try:
        # Get resolved position (via API or DB)
        resolved_pos = None
        if SKIP_DB:
            api_client = get_api_client()
            # Get user internal ID
            user_data = await api_client.get_user_by_telegram_id(user_id)
            if not user_data:
                await query.answer("❌ User not found", show_alert=True)
                return

            internal_id = user_data.get('id')
            # Get resolved position via API
            resolved_pos = await api_client.get_resolved_position(internal_id, resolved_position_id)
        else:
            from core.database.connection import get_db
            from core.database.models import ResolvedPosition
            from sqlalchemy import select

            # Get user internal ID
            user = await user_service.get_by_telegram_id(user_id)
            if not user:
                await query.answer("❌ User not found", show_alert=True)
                return

            async with get_db() as db:
                query_db = select(ResolvedPosition).where(
                    ResolvedPosition.id == resolved_position_id,
                    ResolvedPosition.user_id == user.id
                )
                result = await db.execute(query_db)
                resolved_pos_model = result.scalar_one_or_none()
                resolved_pos = resolved_pos_model.to_dict() if resolved_pos_model else None

        if not resolved_pos:
            await query.answer("❌ Position not found", show_alert=True)
            return

        # Handle both dict (from API) and model (from DB) formats
        if isinstance(resolved_pos, dict):
            status = resolved_pos.get('status')
            is_winner = resolved_pos.get('is_winner')
            tokens_held = float(resolved_pos.get('tokens_held', 0))
            title = resolved_pos.get('market_title', 'Unknown Market')
            net_value = float(resolved_pos.get('net_value', 0))
            fee = float(resolved_pos.get('fee_amount', 0))
            outcome = resolved_pos.get('outcome', '')
        else:
            status = resolved_pos.status
            is_winner = resolved_pos.is_winner
            tokens_held = float(resolved_pos.tokens_held)
            title = resolved_pos.market_title
            net_value = float(resolved_pos.net_value)
            fee = float(resolved_pos.fee_amount)
            outcome = resolved_pos.outcome

        if status == 'REDEEMED':
            await query.answer("✅ Already redeemed!", show_alert=True)
            return

        if not is_winner:
            await query.answer("❌ Cannot redeem losing position", show_alert=True)
            return

        # Check minimum balance (0.5 tokens)
        if tokens_held < 0.5:
            await query.answer(
                f"❌ Balance too low to redeem\n\n"
                f"You have {tokens_held:.2f} tokens (minimum: 0.5)",
                show_alert=True
            )
            return

        # Show confirmation message
        if len(title) > 60:
            title = title[:57] + "..."

        tokens = tokens_held  # Use tokens_held for display
        confirmation_text = f"💰 **Redeem Winnings**\n\n"
        confirmation_text += f"📊 Market: {title}\n"
        confirmation_text += f"✅ Outcome: {outcome}\n\n"
        confirmation_text += f"📦 Tokens: {tokens:.2f} {outcome}\n"
        confirmation_text += f"💵 You'll receive: **${net_value:.2f} USDC**\n"
        confirmation_text += f"   └─ Fee: ${fee:.2f} (1%)\n\n"
        confirmation_text += f"⚠️ This will:\n"
        confirmation_text += f"• Call CTF Exchange contract\n"
        confirmation_text += f"• Convert tokens → USDC\n"
        confirmation_text += f"• Send USDC to your wallet\n"
        confirmation_text += f"• Cost ~$0.10-0.30 gas\n\n"
        confirmation_text += f"**Proceed with redemption?**"

        keyboard = [
            [
                InlineKeyboardButton("✅ Yes, Redeem Now", callback_data=f"confirm_redeem_{resolved_position_id}"),
                InlineKeyboardButton("❌ Cancel", callback_data="cancel_redeem")
            ]
        ]

        await query.edit_message_text(
            confirmation_text,
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        await query.answer()

    except Exception as e:
        logger.error(f"❌ Error showing redemption confirmation: {e}", exc_info=True)
        await query.answer(f"❌ Error: {str(e)}", show_alert=True)


async def handle_confirm_redeem(query: CallbackQuery, resolved_position_id: int) -> None:
    """Execute the actual redemption after confirmation"""
    user_id = query.from_user.id

    try:
        await query.answer("🔄 Processing redemption...")

        # Show processing message
        processing_text = f"⏳ **Processing Redemption**\n\n"
        processing_text += f"🔐 Signing transaction...\n"
        processing_text += f"📡 Calling CTF Exchange...\n"
        processing_text += f"⏱️ This may take 30-60 seconds...\n\n"
        processing_text += f"💡 *Do not close this message*"

        await query.edit_message_text(
            processing_text,
            parse_mode='Markdown'
        )

        # Get user's private key
        private_key = None
        if SKIP_DB:
            api_client = get_api_client()
            user_data = await api_client.get_user_by_telegram_id(user_id)
            if not user_data:
                await query.edit_message_text(
                    "❌ **Redemption Failed**\n\nWallet not found. Use /start to set up your wallet.",
                    parse_mode='Markdown'
                )
                return

            # Decrypt private key
            encrypted_key = user_data.get('polygon_private_key')
            if not encrypted_key:
                await query.edit_message_text(
                    "❌ **Redemption Failed**\n\nWallet not found. Use /start to set up your wallet.",
                    parse_mode='Markdown'
                )
                return

            encryption_service = EncryptionService()
            private_key = encryption_service.decrypt(encrypted_key)
        else:
            user = await user_service.get_by_telegram_id(user_id)
            if not user or not user.polygon_private_key:
                await query.edit_message_text(
                    "❌ **Redemption Failed**\n\nWallet not found. Use /start to set up your wallet.",
                    parse_mode='Markdown'
                )
                return

            encryption_service = EncryptionService()
            private_key = encryption_service.decrypt(user.polygon_private_key)

        if not private_key:
            await query.edit_message_text(
                "❌ **Redemption Failed**\n\nCould not decrypt wallet. Please contact support.",
                parse_mode='Markdown'
            )
            return

        # Execute redemption (via API or direct)
        if SKIP_DB:
            api_client = get_api_client()
            # Get user internal ID
            user_data = await api_client.get_user_by_telegram_id(user_id)
            if not user_data:
                await query.edit_message_text(
                    "❌ **Redemption Failed**\n\nUser not found.",
                    parse_mode='Markdown'
                )
                return

            internal_id = user_data.get('id')
            # Execute redemption via API
            result = await api_client.redeem_resolved_position(internal_id, resolved_position_id, private_key)
            if not result:
                result = {'success': False, 'error': 'API call failed'}
        else:
            # Direct service call (when bot has DB access)
            redemption_service = get_redemption_service()
            result = await redemption_service.redeem_position(resolved_position_id, private_key)

        if result['success']:
            # Success!
            tx_hash = result['tx_hash']
            net_value = result['net_value']
            gas_used = result.get('gas_used', 0)

            success_text = f"🎉 **REDEMPTION SUCCESSFUL!**\n\n"
            success_text += f"💰 **Received:** ${net_value:.2f} USDC\n\n"
            success_text += f"📝 **Transaction:**\n"
            success_text += f"`{tx_hash}`\n\n"
            if gas_used > 0:
                success_text += f"⛽ Gas used: {gas_used:,}\n\n"
            success_text += f"✅ USDC has been sent to your wallet!\n\n"
            success_text += f"🔍 [View on PolygonScan](https://polygonscan.com/tx/{tx_hash})"

            keyboard = [[InlineKeyboardButton("📊 View Positions", callback_data="positions")]]

            await query.edit_message_text(
                success_text,
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup(keyboard),
                disable_web_page_preview=True
            )

            # Send notification
            try:
                await query.message.reply_text(
                    f"🎊 **Congratulations!**\n\n"
                    f"${net_value:.2f} USDC has been added to your wallet balance!",
                    parse_mode='Markdown'
                )
            except Exception:
                pass

        else:
            # Failed
            error = result.get('error', 'Unknown error')

            failure_text = f"❌ **REDEMPTION FAILED**\n\n"
            failure_text += f"Error: `{error}`\n\n"

            # Check if it's a gas/balance issue
            if 'insufficient' in error.lower() or 'gas' in error.lower() or 'balance' in error.lower():
                failure_text += f"⛽ **Gas Issue Detected**\n\n"
                failure_text += f"💡 **You need POL (MATIC) to pay for gas fees!**\n\n"
                failure_text += f"• **POL** = Native Polygon token (not USDC)\n"
                failure_text += f"• You need ~0.03-0.05 MATIC for redemption\n"
                failure_text += f"• Get POL via `/bridge` or buy on an exchange\n\n"
                failure_text += f"🔗 **Quick fix:** Transfer MATIC to your Polygon wallet address"
            else:
                failure_text += f"💡 **Common issues:**\n"
                failure_text += f"• Market not fully resolved yet\n"
                failure_text += f"• Insufficient POL for gas (need ~0.03 MATIC)\n"
                failure_text += f"• Network congestion\n\n"
                failure_text += f"Try again in a few minutes, or contact support."

            keyboard = [
                [InlineKeyboardButton("🔄 Try Again", callback_data=f"redeem_position_{resolved_position_id}")],
                [InlineKeyboardButton("📊 Back to Positions", callback_data="positions")]
            ]

            await query.edit_message_text(
                failure_text,
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

    except Exception as e:
        logger.error(f"❌ Redemption execution error: {e}", exc_info=True)
        await query.edit_message_text(
            f"❌ **Redemption Error**\n\n"
            f"Error: `{str(e)}`\n\n"
            f"Please try again or contact support.",
            parse_mode='Markdown'
        )


async def handle_cancel_redeem(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE = None) -> None:
    """Cancel redemption and return to positions"""
    await query.answer("Cancelled")

    # Return to positions view
    try:
        from telegram_bot.bot.handlers.positions.refresh_handler import handle_refresh_positions
        if context is None:
            # Try to get context from query if available
            if hasattr(query, 'bot') and hasattr(query.bot, 'application'):
                context = query.bot.application
        await handle_refresh_positions(query, context)
    except Exception as e:
        logger.error(f"Error returning to positions: {e}")
        await query.edit_message_text(
            "Use /positions to view your positions",
            parse_mode='Markdown'
        )
