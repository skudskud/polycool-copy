"""
Copy Trading Subscription Flow
Handles leader search, address validation, and confirmation
"""
import logging
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes, ConversationHandler

from core.services.copy_trading import get_copy_trading_service
from .constants import ASKING_POLYGON_ADDRESS, CONFIRMING_LEADER
from .helpers import get_leader_stats
from .formatters import format_leader_stats, format_error_message

logger = logging.getLogger(__name__)


async def handle_leader_address(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Process entered Polygon address and validate leader"""
    # Check if we're actually in copy trading flow
    if not context.user_data.get('expecting_polygon_address'):
        # User is typing in another flow (like /markets custom amount)
        logger.debug(f"[COPY_TRADING] User input not expected, exiting conversation")
        return ConversationHandler.END

    user_id = update.effective_user.id
    polygon_address = update.message.text.strip()
    service = get_copy_trading_service()

    try:
        # Validate address format (basic check)
        if not polygon_address.startswith('0x') or len(polygon_address) < 10:
            await update.message.reply_text(
                "❌ *Invalid Address Format*\n\n"
                "Please enter a valid Polygon address starting with 0x",
                parse_mode='Markdown'
            )
            return ASKING_POLYGON_ADDRESS

        # Resolve address using LeaderResolver
        from core.services.copy_trading import get_leader_resolver
        leader_resolver = get_leader_resolver()

        try:
            leader_info = await leader_resolver.resolve_leader_by_address(polygon_address)
        except Exception as e:
            logger.error(f"Error resolving leader: {e}")
            # Use escape_markdown to prevent parsing issues with addresses containing special chars
            from telegram.helpers import escape_markdown
            escaped_address = escape_markdown(polygon_address, version=2)
            escaped_error = escape_markdown(str(e), version=2)
            await update.message.reply_text(
                f"❌ *Error*\n\n"
                f"Could not resolve address:\n`{escaped_address}`\n\n"
                f"Error: {escaped_error}",
                parse_mode='MarkdownV2'
            )
            return ASKING_POLYGON_ADDRESS

        # Get leader stats for confirmation (via API or DB)
        leader_stats = await get_leader_stats(leader_info.watched_address_id, polygon_address)

        confirm_text = format_leader_stats(leader_stats)

        keyboard = [
            [InlineKeyboardButton("✅ Follow This Leader", callback_data=f"copy_trading:confirm_{leader_info.watched_address_id}")],
            [InlineKeyboardButton("❌ Cancel", callback_data="copy_trading:cancel_search")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(confirm_text, reply_markup=reply_markup, parse_mode='Markdown')

        # Store pending leader in context
        context.user_data['pending_leader_info'] = {
            'address': polygon_address,
            'watched_address_id': leader_info.watched_address_id,
            'leader_type': leader_info.leader_type
        }

        # Clear the flag
        context.user_data.pop('expecting_polygon_address', None)

        return CONFIRMING_LEADER

    except Exception as e:
        logger.error(f"Error processing leader address: {e}", exc_info=True)
        # Use escape_markdown to prevent parsing issues with error messages
        from telegram.helpers import escape_markdown
        escaped_error = escape_markdown(str(e), version=2)
        await update.message.reply_text(f"❌ *Error:* {escaped_error}", parse_mode='MarkdownV2')
        return ASKING_POLYGON_ADDRESS


async def handle_search_leader_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle search leader callback and transition to asking address state"""
    from .callbacks import handle_search_leader

    logger.info(f"🔍 ConversationHandler: Handling search_leader callback")

    # Call the existing handler which will update context.user_data
    await handle_search_leader(update, context)

    logger.info(f"✅ ConversationHandler: Transitioning to ASKING_POLYGON_ADDRESS state")

    return ASKING_POLYGON_ADDRESS


async def handle_confirm_leader_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle leader confirmation callback and transition to budget entry state"""
    from .callbacks import handle_confirm_leader

    # Call the existing handler which will update context.user_data
    result = await handle_confirm_leader(update, context)

    # Return the state to transition to (should be SELECTING_BUDGET_PERCENTAGE)
    return result


async def handle_cancel_search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Wrapper for handle_cancel_search from callbacks"""
    from .callbacks import handle_cancel_search as handler

    result = await handler(update, context)
    return result
