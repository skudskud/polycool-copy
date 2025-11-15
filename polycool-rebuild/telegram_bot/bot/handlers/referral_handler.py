"""
Referral command handler
Manages referral program UI, stats display, and commission claims
"""
import os
from typing import Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from core.services.user.user_helper import get_user_data, get_user_internal_id
from core.services.referral.referral_service import get_referral_service
from core.services.referral.commission_service import get_commission_service
from infrastructure.logging.logger import get_logger

logger = get_logger(__name__)

# Check if bot has DB access
SKIP_DB = os.getenv("SKIP_DB", "true").lower() == "true"

# Import API client if SKIP_DB is true
if SKIP_DB:
    from core.services.api_client import get_api_client


async def handle_referral(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle /referral command
    Show user's referral statistics, link, and commission earnings
    """
    if not update.effective_user:
        return

    user_id = update.effective_user.id
    username = update.effective_user.username

    try:
        logger.info(f"👥 REFERRAL command received from user {user_id}")

        # Get user data (via API or DB)
        user_data = await get_user_data(user_id)
        if not user_data:
            await update.message.reply_text(
                "❌ **User Not Found**\n\n"
                "Please use /start to create your account first.",
                parse_mode='Markdown'
            )
            return

        # Get internal user ID
        internal_user_id = user_data.get('id')
        if not internal_user_id:
            await update.message.reply_text(
                "❌ **Error**\n\n"
                "Could not retrieve user ID. Please try again.",
                parse_mode='Markdown'
            )
            return

        # Get referral stats via API or service
        if SKIP_DB:
            api_client = get_api_client()
            stats_response = await api_client._get(
                f"/referral/stats/telegram/{user_id}",
                cache_key=f"api:referral:stats:{user_id}",
                data_type="user_profile"
            )
            if not stats_response:
                stats = None
            else:
                stats = stats_response
        else:
            referral_service = get_referral_service()
            stats = await referral_service.get_user_referral_stats(internal_user_id)

        if not stats:
            await update.message.reply_text(
                "❌ **Error**\n\n"
                "Could not retrieve referral stats. Please try again.",
                parse_mode='Markdown'
            )
            return

        # Check if user has referral code (required for link)
        referral_code = stats.get('referral_code')
        referral_link = stats.get('referral_link')

        if not referral_link:
            await update.message.reply_text(
                "❌ **Referral Link Not Available**\n\n"
                "Your referral link is being generated. Please try again in a moment.",
                parse_mode='Markdown'
            )
            return

        # Build message
        total_referrals = stats.get('total_referrals', {})
        total_commissions = stats.get('total_commissions', {})
        commission_breakdown = stats.get('commission_breakdown', [])

        message = f"""
🎁 **REFERRAL PROGRAM**

🔗 **Your Referral Link:**
`{referral_link}`

👥 **People Referred:**
🥇 Level 1: {total_referrals.get('level_1', 0)} people (25% commission)
🥈 Level 2: {total_referrals.get('level_2', 0)} people (5% commission)
🥉 Level 3: {total_referrals.get('level_3', 0)} people (3% commission)

💰 **Earnings:**
⏳ Pending: ${total_commissions.get('pending', 0.0):.2f}
✅ Paid: ${total_commissions.get('paid', 0.0):.2f}
💎 Total: ${total_commissions.get('total', 0.0):.2f}

📊 **By Level:**
"""
        # Add breakdown by level
        if commission_breakdown:
            for breakdown in commission_breakdown:
                level = breakdown.get('level', 0)
                rate = breakdown.get('rate', 0.0)
                pending = breakdown.get('pending', 0.0)
                paid = breakdown.get('paid', 0.0)
                total_level = pending + paid
                message += f"Level {level} ({rate}%): ${total_level:.2f}\n"
        else:
            message += "No commissions yet.\n"

        message += "\n💡 Share your link → Friends trade → You earn!"

        # Build keyboard
        keyboard = []

        # Show claim button only if there are pending commissions >= $1
        pending_amount = total_commissions.get('pending', 0.0)
        if pending_amount >= 1.00:
            keyboard.append([
                InlineKeyboardButton(
                    f"💰 Claim ${pending_amount:.2f}",
                    callback_data="referral_claim_commissions"
                )
            ])
        elif pending_amount > 0:
            # Show disabled button with hint
            keyboard.append([
                InlineKeyboardButton(
                    f"💰 ${pending_amount:.2f} (min: $1.00)",
                    callback_data="referral_claim_min_not_met"
                )
            ])

        keyboard.extend([
            [InlineKeyboardButton("📋 My Referrals", callback_data="referral_list")],
            [InlineKeyboardButton("🔄 Refresh Stats", callback_data="referral_refresh")],
            [InlineKeyboardButton("📊 Leaderboard", callback_data="referral_leaderboard")]
        ])

        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            message,
            parse_mode='Markdown',
            reply_markup=reply_markup
        )

    except Exception as e:
        logger.error(f"❌ Referral command error: {e}")
        import traceback
        logger.error(traceback.format_exc())
        await update.message.reply_text(
            "❌ **Error**\n\n"
            "An error occurred while retrieving your referral stats. Please try again.",
            parse_mode='Markdown'
        )


async def handle_referral_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle referral callback queries"""
    if not update.callback_query:
        return

    query = update.callback_query
    callback_data = query.data
    user_id = query.from_user.id

    try:
        await query.answer()

        logger.info(f"🔄 REFERRAL callback received: {callback_data} for user {user_id}")

        if callback_data == "referral_claim_commissions":
            await _handle_claim_commissions(query, context)
        elif callback_data == "referral_claim_min_not_met":
            await _handle_claim_min_not_met(query)
        elif callback_data == "referral_refresh":
            await _handle_refresh_stats(query, context)
        elif callback_data == "referral_list":
            await _handle_referrals_list(query, context)
        elif callback_data == "referral_leaderboard":
            await _handle_leaderboard(query, context)
        else:
            logger.warning(f"Unknown referral callback: {callback_data}")
            await query.answer("❌ Unknown action", show_alert=True)

    except Exception as e:
        logger.error(f"Error handling referral callback for user {user_id}: {e}")
        import traceback
        logger.error(traceback.format_exc())
        if query.message:
            await query.edit_message_text("❌ An error occurred. Please try again.")


async def _handle_claim_commissions(query, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle commission claim button click"""
    try:
        user_id = query.from_user.id

        await query.edit_message_text(
            "⏳ **Claiming Commissions...**\n\n"
            "🔐 Signing transaction...\n"
            "📡 Sending payment...\n\n"
            "This may take 10-30 seconds.",
            parse_mode='Markdown'
        )

        # Get user internal ID
        internal_user_id = await get_user_internal_id(user_id)
        if not internal_user_id:
            await query.edit_message_text("❌ User not found. Please use /start")
            return

        # Call API to claim commissions
        if SKIP_DB:
            api_client = get_api_client()
            result = await api_client._post(
                f"/referral/claim/{internal_user_id}",
                {}
            )
            if not result:
                await query.edit_message_text(
                    "❌ **Claim Failed**\n\n"
                    "Could not claim commissions. Please try again later.",
                    parse_mode='Markdown'
                )
                return
            success = result.get('success', False)
            message = result.get('message', '')
            amount_paid = result.get('amount_paid', 0.0)
            tx_hash = result.get('tx_hash')
        else:
            # Direct service call (for testing)
            from core.services.referral.commission_service import get_commission_service
            commission_service = get_commission_service()
            # TODO: Implement claim_commissions method in commission_service
            await query.edit_message_text(
                "⚠️ **Claim Not Implemented**\n\n"
                "Commission claiming is not yet implemented in direct DB mode.",
                parse_mode='Markdown'
            )
            return

        if success and tx_hash:
            # Invalidate cache after successful claim to force stats refresh
            if SKIP_DB:
                api_client = get_api_client()
                await api_client.cache_manager.invalidate(f"api:referral:stats:{user_id}")
                logger.debug(f"✅ Cache invalidated for referral stats after claim: {user_id}")

            result_text = f"""
✅ **COMMISSIONS PAID!**

💰 **Amount:** ${amount_paid:.2f} USDC.e
📍 **To:** Your Polygon wallet
🔗 **Transaction:** `{tx_hash[:20]}...`

[📊 View on PolygonScan](https://polygonscan.com/tx/{tx_hash})

🎉 Funds are now in your wallet!

Use /referral to see updated stats.
            """
        else:
            result_text = f"❌ **Error:**\n\n{message}"

        await query.edit_message_text(result_text, parse_mode='Markdown')

    except Exception as e:
        logger.error(f"❌ Claim commissions error: {e}")
        import traceback
        logger.error(traceback.format_exc())
        await query.edit_message_text(
            f"❌ **Claim Error:**\n\n{str(e)}",
            parse_mode='Markdown'
        )


async def _handle_claim_min_not_met(query) -> None:
    """Handle click on disabled claim button (< $1.00)"""
    await query.answer(
        "⚠️ Minimum $1.00 required to claim commissions",
        show_alert=True
    )


async def _handle_refresh_stats(query, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Refresh referral stats display"""
    try:
        user_id = query.from_user.id

        # Get user data
        user_data = await get_user_data(user_id)
        if not user_data:
            await query.edit_message_text("❌ User not found. Please use /start")
            return

        internal_user_id = user_data.get('id')
        if not internal_user_id:
            await query.edit_message_text("❌ Error retrieving user ID")
            return

        # Get fresh stats
        if SKIP_DB:
            api_client = get_api_client()
            # Invalidate cache first
            await api_client.cache_manager.invalidate(f"api:referral:stats:{user_id}")
            stats_response = await api_client._get(
                f"/referral/stats/telegram/{user_id}",
                cache_key=f"api:referral:stats:{user_id}",
                data_type="user_profile"
            )
            stats = stats_response if stats_response else None
        else:
            referral_service = get_referral_service()
            stats = await referral_service.get_user_referral_stats(internal_user_id)

        if not stats:
            await query.edit_message_text(
                "❌ **Error**\n\n"
                "Could not retrieve referral stats. Please try again.",
                parse_mode='Markdown'
            )
            return

        # Rebuild message (same as handle_referral)
        referral_link = stats.get('referral_link')
        if not referral_link:
            await query.edit_message_text(
                "❌ Referral link not available. Please try again.",
                parse_mode='Markdown'
            )
            return

        total_referrals = stats.get('total_referrals', {})
        total_commissions = stats.get('total_commissions', {})
        commission_breakdown = stats.get('commission_breakdown', [])

        message = f"""
🎁 **REFERRAL PROGRAM**

🔗 **Your Referral Link:**
`{referral_link}`

👥 **People Referred:**
🥇 Level 1: {total_referrals.get('level_1', 0)} people (25% commission)
🥈 Level 2: {total_referrals.get('level_2', 0)} people (5% commission)
🥉 Level 3: {total_referrals.get('level_3', 0)} people (3% commission)

💰 **Earnings:**
⏳ Pending: ${total_commissions.get('pending', 0.0):.2f}
✅ Paid: ${total_commissions.get('paid', 0.0):.2f}
💎 Total: ${total_commissions.get('total', 0.0):.2f}

📊 **By Level:**
"""
        if commission_breakdown:
            for breakdown in commission_breakdown:
                level = breakdown.get('level', 0)
                rate = breakdown.get('rate', 0.0)
                pending = breakdown.get('pending', 0.0)
                paid = breakdown.get('paid', 0.0)
                total_level = pending + paid
                message += f"Level {level} ({rate}%): ${total_level:.2f}\n"
        else:
            message += "No commissions yet.\n"

        message += "\n💡 Share and earn!"

        # Build keyboard
        keyboard = []
        pending_amount = total_commissions.get('pending', 0.0)
        if pending_amount >= 1.00:
            keyboard.append([
                InlineKeyboardButton(
                    f"💰 Claim ${pending_amount:.2f}",
                    callback_data="referral_claim_commissions"
                )
            ])
        elif pending_amount > 0:
            keyboard.append([
                InlineKeyboardButton(
                    f"💰 ${pending_amount:.2f} (min: $1.00)",
                    callback_data="referral_claim_min_not_met"
                )
            ])

        keyboard.extend([
            [InlineKeyboardButton("📋 My Referrals", callback_data="referral_list")],
            [InlineKeyboardButton("🔄 Refresh", callback_data="referral_refresh")],
            [InlineKeyboardButton("📊 Leaderboard", callback_data="referral_leaderboard")]
        ])

        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(message, parse_mode='Markdown', reply_markup=reply_markup)

    except Exception as e:
        logger.error(f"❌ Refresh referral stats error: {e}")
        import traceback
        logger.error(traceback.format_exc())
        await query.edit_message_text(
            f"❌ **Error:**\n\n{str(e)}",
            parse_mode='Markdown'
        )


async def _handle_referrals_list(query, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show list of referrals"""
    try:
        user_id = query.from_user.id
        internal_user_id = await get_user_internal_id(user_id)

        if not internal_user_id:
            await query.edit_message_text("❌ User not found. Please use /start")
            return

        # Get referrals list
        if SKIP_DB:
            api_client = get_api_client()
            referrals_response = await api_client._get(
                f"/referral/referrals/{internal_user_id}",
                cache_key=f"api:referral:list:{internal_user_id}",
                data_type="user_profile"
            )
            referrals_data = referrals_response.get('referrals', []) if referrals_response else []
        else:
            referral_service = get_referral_service()
            referrals_data = await referral_service.get_referrals_list(internal_user_id)

        if not referrals_data:
            await query.edit_message_text(
                "📋 **My Referrals**\n\n"
                "You haven't referred anyone yet.\n\n"
                "Share your referral link to start earning!",
                parse_mode='Markdown'
            )
            return

        # Group by level
        by_level = {1: [], 2: [], 3: []}
        for ref in referrals_data:
            level = ref.get('level', 1)
            if level in by_level:
                by_level[level].append(ref)

        message = "📋 **My Referrals**\n\n"

        for level in [1, 2, 3]:
            refs = by_level[level]
            if refs:
                message += f"**Level {level}** ({len(refs)}):\n"
                for ref in refs[:10]:  # Show max 10 per level
                    username = ref.get('referred_username', 'Unknown')
                    created_at = ref.get('created_at', '')
                    message += f"• @{username}\n"
                if len(refs) > 10:
                    message += f"... and {len(refs) - 10} more\n"
                message += "\n"

        keyboard = [[InlineKeyboardButton("← Back", callback_data="referral_refresh")]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(message, parse_mode='Markdown', reply_markup=reply_markup)

    except Exception as e:
        logger.error(f"❌ Error getting referrals list: {e}")
        await query.edit_message_text(
            "❌ **Error**\n\n"
            "Could not retrieve referrals list. Please try again.",
            parse_mode='Markdown'
        )


async def _handle_leaderboard(query, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show referral leaderboard"""
    try:
        await query.edit_message_text(
            "📊 **Referral Leaderboard**\n\n"
            "⚠️ Leaderboard feature coming soon!\n\n"
            "Check back later to see top referrers.",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("← Back", callback_data="referral_refresh")
            ]])
        )
    except Exception as e:
        logger.error(f"❌ Error showing leaderboard: {e}")
        await query.edit_message_text("❌ Error loading leaderboard")
