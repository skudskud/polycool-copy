"""
REDEMPTION CALLBACK HANDLER
Handles user interactions for redeeming resolved positions
"""

import logging
from telegram import Update, CallbackQuery
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)


async def handle_redeem_position(query: CallbackQuery, resolved_position_id: int) -> None:
    """Handle redemption request for a resolved position"""
    user_id = query.from_user.id

    try:
        # Show confirmation prompt
        from database import SessionLocal, ResolvedPosition

        with SessionLocal() as db:
            resolved_pos = db.query(ResolvedPosition).filter(
                ResolvedPosition.id == resolved_position_id,
                ResolvedPosition.user_id == user_id
            ).first()

            if not resolved_pos:
                await query.answer("❌ Position not found", show_alert=True)
                return

            if resolved_pos.status == 'REDEEMED':
                await query.answer("✅ Already redeemed!", show_alert=True)
                return

            if not resolved_pos.is_winner:
                await query.answer("❌ Cannot redeem losing position", show_alert=True)
                return

            # Check minimum balance (0.5 tokens)
            tokens_held = float(resolved_pos.tokens_held)
            if tokens_held < 0.5:
                await query.answer(
                    f"❌ Balance too low to redeem\n\n"
                    f"You have {tokens_held:.2f} tokens (minimum: 0.5)",
                    show_alert=True
                )
                return

        # Show confirmation message
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup

        title = resolved_pos.market_title
        if len(title) > 60:
            title = title[:57] + "..."

        net_value = float(resolved_pos.net_value)
        fee = float(resolved_pos.fee_amount)
        tokens = float(resolved_pos.tokens_held)
        outcome = resolved_pos.outcome

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
        logger.error(f"❌ Error showing redemption confirmation: {e}")
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
        from core.services import user_service
        user_wallet = user_service.get_user_wallet(user_id)

        if not user_wallet or 'private_key' not in user_wallet:
            await query.edit_message_text(
                "❌ **Redemption Failed**\n\nWallet not found. Use /start to set up your wallet.",
                parse_mode='Markdown'
            )
            return

        private_key = user_wallet['private_key']

        # Execute redemption
        from core.services.redemption_service import get_redemption_service
        redemption_service = get_redemption_service()

        result = await redemption_service.redeem_position(resolved_position_id, private_key)

        if result['success']:
            # Success!
            tx_hash = result['tx_hash']
            net_value = result['net_value']
            gas_used = result['gas_used']

            success_text = f"🎉 **REDEMPTION SUCCESSFUL!**\n\n"
            success_text += f"💰 **Received:** ${net_value:.2f} USDC\n\n"
            success_text += f"📝 **Transaction:**\n"
            success_text += f"`{tx_hash}`\n\n"
            success_text += f"⛽ Gas used: {gas_used:,}\n\n"
            success_text += f"✅ USDC has been sent to your wallet!\n\n"
            success_text += f"🔍 [View on PolygonScan](https://polygonscan.com/tx/{tx_hash})"

            from telegram import InlineKeyboardButton, InlineKeyboardMarkup
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
            except:
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

            from telegram import InlineKeyboardButton, InlineKeyboardMarkup
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
        logger.error(f"❌ Redemption execution error: {e}")
        import traceback
        logger.error(traceback.format_exc())

        await query.edit_message_text(
            f"❌ **Redemption Error**\n\n"
            f"Error: `{str(e)}`\n\n"
            f"Please try again or contact support.",
            parse_mode='Markdown'
        )


async def handle_cancel_redeem(query: CallbackQuery) -> None:
    """Cancel redemption and return to positions"""
    await query.answer("Cancelled")

    # Return to positions view
    from telegram_bot.handlers.positions.core import positions_command

    # Create a fake update object
    update = query._Update__bot._update_queue.get_nowait() if hasattr(query, '_Update__bot') else None

    try:
        # Just go back to positions
        await query.edit_message_text(
            "🔍 Loading positions...",
            parse_mode='Markdown'
        )

        # Trigger positions refresh
        from telegram_bot.handlers.positions.core import handle_positions_refresh
        await handle_positions_refresh(query)

    except Exception as e:
        logger.error(f"Error returning to positions: {e}")
        await query.edit_message_text(
            "Use /positions to view your positions",
            parse_mode='Markdown'
        )
