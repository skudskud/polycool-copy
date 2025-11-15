#!/usr/bin/env python3
"""
Referral Handlers
Manages referral program UI, stats display, and commission claims
"""

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler

from core.services import user_service

logger = logging.getLogger(__name__)


async def referral_command(update: Update, context):
    """
    Show user's referral statistics, link, and commission earnings
    """
    try:
        user_id = update.effective_user.id

        # Check if user has a username (required for referral links)
        user = user_service.get_user(user_id)

        if not user or not user.username:
            no_username_text = """
❌ Username Required

To create your referral link, you need a Telegram username.

How to add one:
1. Open Telegram Settings
2. Go to Edit Profile
3. Add a Username

Once done, use /referral again!
            """
            await update.message.reply_text(no_username_text, parse_mode='Markdown')
            return

        # Get referral stats
        from telegram_bot.services.referral_service import get_referral_service
        referral_service = get_referral_service()

        stats = referral_service.get_user_referral_stats(user_id)

        # Build message
        message = f"""
🎁 REFERRAL PROGRAM

🔗 Your Link:
`{stats['referral_link']}`

👥 People Referred:
🥇 Level 1: {stats['total_referrals']['level_1']} people
🥈 Level 2: {stats['total_referrals']['level_2']} people
🥉 Level 3: {stats['total_referrals']['level_3']} people

💰 Earnings:
⏳ Pending: ${stats['total_commissions']['pending']:.2f}
✅ Paid: ${stats['total_commissions']['paid']:.2f}
💎 Total: ${stats['total_commissions']['total']:.2f}

📊 By Level:
Level 1 (25%): ${stats['commission_breakdown'][0]['pending'] + stats['commission_breakdown'][0]['paid']:.2f}
Level 2 (5%): ${stats['commission_breakdown'][1]['pending'] + stats['commission_breakdown'][1]['paid']:.2f}
Level 3 (3%): ${stats['commission_breakdown'][2]['pending'] + stats['commission_breakdown'][2]['paid']:.2f}

💡 Share → Friends trade → You earn!
        """

        # Build keyboard
        keyboard = []

        # Show claim button only if there are pending commissions >= $1
        if stats['total_commissions']['pending'] >= 1.00:
            keyboard.append([
                InlineKeyboardButton(
                    f"💰 Claim ${stats['total_commissions']['pending']:.2f}",
                    callback_data="claim_commissions"
                )
            ])
        elif stats['total_commissions']['pending'] > 0:
            # Show disabled button with hint
            keyboard.append([
                InlineKeyboardButton(
                    f"💰 ${stats['total_commissions']['pending']:.2f} (min: $1.00)",
                    callback_data="claim_min_not_met"
                )
            ])

        keyboard.append([
            InlineKeyboardButton("🔄 Refresh Stats", callback_data="refresh_referral_stats")
        ])

        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            message,
            parse_mode='Markdown',
            reply_markup=reply_markup
        )

    except Exception as e:
        logger.error(f"❌ Referral command error: {e}")
        await update.message.reply_text(f"❌ Error: {str(e)}", parse_mode='Markdown')


async def handle_claim_commissions(query):
    """Handle commission claim button click"""
    try:
        user_id = query.from_user.id

        await query.edit_message_text(
            "⏳ Claiming commissions...\n\n"
            "🔐 Signing transaction...\n"
            "📡 Sending payment...\n\n"
            "This may take 10-30 seconds.",
            parse_mode='Markdown'
        )

        from telegram_bot.services.referral_service import get_referral_service
        referral_service = get_referral_service()

        success, message, amount_paid, tx_hash = await referral_service.claim_commissions(user_id)

        if success and tx_hash:
            result_text = f"""
✅ COMMISSIONS PAID!

💰 Amount: ${amount_paid:.2f} USDC.e
📍 To: Your Polygon wallet
🔗 Transaction: `{tx_hash[:20]}...`

[📊 View on PolygonScan](https://polygonscan.com/tx/{tx_hash})

🎉 Funds are now in your wallet!

Use /referral to see updated stats.
            """
        else:
            result_text = f"❌ Error:\n\n{message}"

        await query.edit_message_text(result_text, parse_mode='Markdown')

    except Exception as e:
        logger.error(f"❌ Claim commissions error: {e}")
        await query.edit_message_text(
            f"❌ Claim error:\n\n{str(e)}",
            parse_mode='Markdown'
        )


async def handle_refresh_referral_stats(query):
    """Refresh referral stats display"""
    try:
        user_id = query.from_user.id

        # Get fresh stats
        from telegram_bot.services.referral_service import get_referral_service
        referral_service = get_referral_service()

        stats = referral_service.get_user_referral_stats(user_id)

        if not stats['user_username']:
            await query.edit_message_text(
                "❌ Username Required\n\n"
                "Add a Telegram username to use the referral system.",
                parse_mode='Markdown'
            )
            return

        # Build updated message
        message = f"""
🎁 REFERRAL PROGRAM

🔗 Your Link:
`{stats['referral_link']}`

👥 People Referred:
🥇 Level 1: {stats['total_referrals']['level_1']} people
🥈 Level 2: {stats['total_referrals']['level_2']} people
🥉 Level 3: {stats['total_referrals']['level_3']} people

💰 Earnings:
⏳ Pending: ${stats['total_commissions']['pending']:.2f}
✅ Paid: ${stats['total_commissions']['paid']:.2f}
💎 Total: ${stats['total_commissions']['total']:.2f}

📊 By Level:
Level 1 (25%): ${stats['commission_breakdown'][0]['pending'] + stats['commission_breakdown'][0]['paid']:.2f}
Level 2 (5%): ${stats['commission_breakdown'][1]['pending'] + stats['commission_breakdown'][1]['paid']:.2f}
Level 3 (3%): ${stats['commission_breakdown'][2]['pending'] + stats['commission_breakdown'][2]['paid']:.2f}

💡 Share and earn!
        """

        # Build keyboard
        keyboard = []

        if stats['total_commissions']['pending'] >= 1.00:
            keyboard.append([
                InlineKeyboardButton(
                    f"💰 Claim ${stats['total_commissions']['pending']:.2f}",
                    callback_data="claim_commissions"
                )
            ])
        elif stats['total_commissions']['pending'] > 0:
            keyboard.append([
                InlineKeyboardButton(
                    f"💰 ${stats['total_commissions']['pending']:.2f} (min: $1.00)",
                    callback_data="claim_min_not_met"
                )
            ])

        keyboard.append([
            InlineKeyboardButton("🔄 Refresh", callback_data="refresh_referral_stats")
        ])

        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(message, parse_mode='Markdown', reply_markup=reply_markup)

    except Exception as e:
        logger.error(f"❌ Refresh referral stats error: {e}")
        await query.edit_message_text(
            f"❌ Error:\n\n{str(e)}",
            parse_mode='Markdown'
        )


async def handle_claim_min_not_met(query):
    """Handle click on disabled claim button (< $1.00)"""
    await query.answer(
        "⚠️ Minimum $1.00 required to claim commissions",
        show_alert=True
    )


def register(app: Application):
    """Register referral command handler"""
    app.add_handler(CommandHandler("referral", referral_command))
    logger.info("✅ Referral handlers registered")
