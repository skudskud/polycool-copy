"""
RESOLUTION NOTIFICATION SERVICE
Sends Telegram notifications when markets resolve
"""

import logging
import asyncio
from datetime import datetime
from telegram import Bot
from telegram.error import TelegramError, RetryAfter
from telegram.constants import ParseMode

from database import ResolvedPosition
from config.config import BOT_TOKEN

logger = logging.getLogger(__name__)


async def send_resolution_notification(user_id: int, position: ResolvedPosition) -> bool:
    """
    Send notification when market resolves
    Format: Winner with P&L, Loser brief
    """
    try:
        bot = Bot(token=BOT_TOKEN)

        if position.is_winner:
            # Winner notification: Include P&L
            net_value = float(position.net_value)
            pnl = float(position.pnl)
            message = f"""🎉 **You Won!**

💰 Redeem **${net_value:.2f} USDC** (+${pnl:.2f} P&L)

/positions"""
        else:
            # Loser notification: Brief
            loss = abs(float(position.pnl))
            message = f"""😔 **Market Resolved**

You lost **${loss:.2f}**

/positions"""

        await bot.send_message(
            chat_id=user_id,
            text=message,
            parse_mode='Markdown'
        )

        logger.info(f"✅ [NOTIFICATION] Sent to user {user_id} (winner={position.is_winner})")
        return True

    except Exception as e:
        logger.error(f"❌ [NOTIFICATION] Error sending to user {user_id}: {e}")
        return False


def _escape(text: str) -> str:
    """Escape markdown special chars"""
    chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    for c in chars:
        text = text.replace(c, f'\\{c}')
    return text
