"""
Copy Trading Notification Service
Sends Telegram push notifications when follower executes a copy trade
"""

import logging
from typing import Dict, Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class CopyTradingNotificationService:
    """Handles push notifications for copy trading events"""

    def __init__(self):
        self.notification_service = None

    def set_notification_service(self, notification_service):
        """Set the notification service (called at startup)"""
        self.notification_service = notification_service
        logger.info("✅ Copy trading notification service initialized")

    async def send_message(self, user_id: int, message: str, reply_markup=None, parse_mode: str = 'Markdown') -> bool:
        """
        Send a message to a user (wrapper for notification service)

        Args:
            user_id: Telegram user ID
            message: Message text
            reply_markup: Optional inline keyboard markup
            parse_mode: Message parse mode (default: Markdown)

        Returns:
            True if sent successfully, False otherwise
        """
        if not self.notification_service:
            logger.warning("[COPY_NOTIF] Notification service not initialized")
            return False

        return await self.notification_service.send_message(
            user_id,
            message,
            parse_mode=parse_mode,
            reply_markup=reply_markup
        )

    async def notify_copy_trade_executed(
        self,
        follower_id: int,
        leader_username: str,
        trade_data: Dict[str, Any],
        calculated_amount: float,
        actual_amount: float,
        execution_price: Optional[float] = None,
        tokens_executed: Optional[float] = None,
        success: bool = True,
        failure_reason: Optional[str] = None
    ):
        """
        Send push notification when a copy trade is executed

        Args:
            follower_id: Telegram user ID of follower
            leader_username: Username of leader being copied
            trade_data: Dict with market_id, outcome, tx_type, etc.
            calculated_amount: Amount calculated by copy algorithm
            actual_amount: Amount actually executed
            execution_price: Real execution price per token (optional)
            tokens_executed: Real number of tokens executed (optional)
            success: Whether the trade succeeded
        """
        if not self.notification_service:
            logger.warning("[COPY_NOTIF] Notification service not initialized")
            return

        try:
            # Build notification message
            if success:
                emoji = "✅" if trade_data['transaction_type'] == 'BUY' else "💰"
                status = "EXECUTED"
            elif failure_reason == "INSUFFICIENT_BUDGET":
                # Special handling for budget issues - actionable notification
                emoji = "❌"
                status = "FAILED"
                # Will use special message format below
            else:
                emoji = "❌"
                status = "FAILED"

            # Get market details
            # ✅ NEW: Extract market_title from market_title field or market_data
            market_title = trade_data.get('market_title', 'Unknown Market')
            if not market_title or market_title == 'Unknown Market':
                # Fallback to market_data
                if trade_data.get('market_data'):
                    market_title = trade_data['market_data'].get('title') or trade_data['market_data'].get('question', 'Unknown Market')

            outcome = trade_data.get('outcome', 'unknown').upper()
            tx_type = trade_data['transaction_type']

            # Calculate potential profit (for display purposes)
            # This is approximate based on entry price
            # ✅ NEW: Get price from trade_data (price_per_token)
            entry_price = trade_data.get('price_per_token', 0)
            potential_profit_pct = self._calculate_potential_profit(
                tx_type, entry_price
            )

            # ✅ CRITICAL FIX: Escape ONLY problematic characters for Telegram Markdown
            def escape_markdown(text: str) -> str:
                """Escape special characters for Telegram Markdown (only those that break parsing)"""
                if not text:
                    return ""
                # Only escape characters that commonly break Telegram Markdown parsing
                # DO NOT escape * _ ` as they are used for formatting
                chars_to_escape = ['[', ']', '(', ')', '~', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
                for char in chars_to_escape:
                    text = text.replace(char, f'\\{char}')
                return text

            # Escape market title and other text fields
            safe_market_title = escape_markdown(market_title[:60])
            if len(market_title) > 60:
                safe_market_title += "..."
            safe_outcome = escape_markdown(outcome.upper())

            # Special message for insufficient budget
            if failure_reason == "INSUFFICIENT_BUDGET":
                from telegram import InlineKeyboardButton, InlineKeyboardMarkup

                message = f"""{emoji} **COPY TRADE FAILED**

📊 **Market:** {safe_market_title}
🎯 **Position:** {safe_outcome}
{'💰' if tx_type == 'BUY' else '💵'} **Action:** {tx_type}

**Reason:** Insufficient copy trading budget
💰 **Needed:** \\${calculated_amount:.2f}
💰 **Available:** \\${actual_amount:.2f}

_Failed to copy this trade due to budget limits._
                """.strip()

                # Create inline keyboard with action buttons
                keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton("💰 Fund Wallet", callback_data="fund_wallet")],
                    [InlineKeyboardButton("🛑 Stop Following", callback_data="stop_copy_trading")]
                ])

                # Send notification with buttons
                success = await self.notification_service.send_message(
                    follower_id,
                    message,
                    reply_markup=keyboard
                )

            else:
                # Standard success/failure message
                # Format message with escaped content (keep ** for bold, * for italic)
                # Pre-format strings with backslashes to avoid f-string issues
                amount_str = f"\\${actual_amount:.2f}"
                avg_price_str = f"\\${execution_price:.4f}/token" if execution_price else ""
                entry_price_str = f"\\${entry_price:.4f}" if entry_price and not execution_price else ""

                message = f"""{emoji} **COPY TRADE {status}**

📊 **Market:** {safe_market_title}
🎯 **Position:** {safe_outcome}
{'💰' if tx_type == 'BUY' else '💵'} **Action:** {tx_type}
💵 **Amount:** {amount_str}
{f'📊 **Avg Price:** {avg_price_str}' if execution_price else ''}
{f'🎫 **Tokens:** {tokens_executed:.2f}' if tokens_executed else ''}

{f'📊 **Entry Price:** {entry_price_str}' if entry_price and not execution_price else ''}
{f'📈 **Potential Profit:** {potential_profit_pct}' if potential_profit_pct else ''}

Use /copy\\_trading to manage your settings
Use /positions to view all positions
                """.strip()

                # Send notification
                success = await self.notification_service.send_message(
                    follower_id,
                    message
                )

            if success:
                logger.info(
                    f"✅ [COPY_NOTIF] Sent to follower {follower_id}: "
                    f"{tx_type} {outcome} ${actual_amount:.2f}"
                )
            else:
                logger.warning(f"⚠️ [COPY_NOTIF] Failed to send to {follower_id}")

            return success

        except Exception as e:
            logger.error(f"❌ [COPY_NOTIF] Error sending notification: {e}")
            return False

    # notify_copy_trade_skipped removed - no notifications for skips

    def _calculate_potential_profit(
        self,
        tx_type: str,
        entry_price: float
    ) -> Optional[str]:
        """
        Calculate potential profit range based on entry price
        This is an estimate for display purposes
        """
        if not entry_price or entry_price == 0:
            return None

        if tx_type == 'BUY':
            # For BUY: Show potential profit if price goes to $1.00
            potential_exit = 1.0
            profit_pct = ((potential_exit - entry_price) / entry_price) * 100
            return f"+{profit_pct:.0f}% (if resolves YES)"
        else:
            # For SELL: Show realized profit (will be calculated from actual trade)
            return None

    # _format_skip_reason removed - no skip notifications needed


# Global singleton
_copy_trading_notification_service = None


def get_copy_trading_notification_service() -> CopyTradingNotificationService:
    """Get or create the copy trading notification service singleton"""
    global _copy_trading_notification_service
    if _copy_trading_notification_service is None:
        _copy_trading_notification_service = CopyTradingNotificationService()
    return _copy_trading_notification_service
