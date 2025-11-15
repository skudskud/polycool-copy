#!/usr/bin/env python3
"""
Notification Service - Phase 4
Centralized Telegram messaging for progress updates during onboarding
"""

import logging
from typing import Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class NotificationService:
    """
    Centralized service for sending progress notifications to users
    Used during bridge, approval, and API generation processes
    """

    def __init__(self):
        """Initialize notification service"""
        self._bot_app = None
        logger.info("Notification service initialized")

    def set_bot_app(self, bot_app):
        """
        Set the Telegram bot application instance
        Called during bot initialization

        Args:
            bot_app: telegram.ext.Application instance
        """
        self._bot_app = bot_app
        logger.info("✅ Notification service connected to Telegram bot")

    async def send_message(self, user_id: int, message: str, parse_mode: str = 'Markdown', reply_markup=None) -> bool:
        """
        Send a message to a user

        Args:
            user_id: Telegram user ID
            message: Message text
            parse_mode: Message parse mode (default: Markdown)
            reply_markup: Optional inline keyboard markup

        Returns:
            True if sent successfully, False otherwise
        """
        try:
            if not self._bot_app:
                logger.warning(f"Cannot send notification - bot not initialized")
                return False

            await self._bot_app.bot.send_message(
                chat_id=user_id,
                text=message,
                parse_mode=parse_mode,
                reply_markup=reply_markup
            )

            logger.debug(f"✅ Sent notification to user {user_id}")
            return True

        except Exception as e:
            logger.error(f"❌ Error sending notification to user {user_id}: {e}")
            return False

    async def send_progress_update(self, user_id: int, stage: str, percentage: int,
                                   message: str, emoji: str = "⏳") -> bool:
        """
        Send a progress update with percentage

        Args:
            user_id: Telegram user ID
            stage: Stage name (e.g., "Bridge", "Approval", "API Generation")
            percentage: Progress percentage (0-100)
            message: Additional message
            emoji: Emoji to use

        Returns:
            True if sent successfully
        """
        progress_bar = self._create_progress_bar(percentage)

        notification = f"""
{emoji} **{stage} IN PROGRESS**

{progress_bar} **{percentage}%**

{message}
        """

        return await self.send_message(user_id, notification.strip())

    async def send_stage_complete(self, user_id: int, stage: str, duration_seconds: Optional[float] = None) -> bool:
        """
        Send stage completion notification

        Args:
            user_id: Telegram user ID
            stage: Stage name
            duration_seconds: Time taken (optional)

        Returns:
            True if sent successfully
        """
        duration_text = f" (took {duration_seconds:.1f}s)" if duration_seconds else ""

        notification = f"""
✅ **{stage} COMPLETE!**{duration_text}

Moving to next step...
        """

        return await self.send_message(user_id, notification.strip())

    async def send_onboarding_start(self, user_id: int, username: str) -> bool:
        """
        Send onboarding start notification

        Args:
            user_id: Telegram user ID
            username: User's username

        Returns:
            True if sent successfully
        """
        notification = f"""
🚀 **Welcome @{username}!**

Creating your trading wallets...

⏳ **This will take ~30 seconds**
        """

        return await self.send_message(user_id, notification.strip())

    async def send_bridge_started(self, user_id: int, sol_amount: float) -> bool:
        """
        Send bridge start notification

        Args:
            user_id: Telegram user ID
            sol_amount: Amount of SOL being bridged

        Returns:
            True if sent successfully
        """
        notification = f"""
🌉 **BRIDGE STARTED!**

💰 Bridging **{sol_amount:.4f} SOL** to Polygon
🔄 Via **deBridge** (3.5% fee)

⏳ **Steps:**
1. Swap SOL → USDC (~30s)
2. Bridge USDC → Polygon (~2-3 min)
3. Swap to USDC.e + Get POL (~30s)

⏱️ **Total time: ~3-5 minutes**

💡 I'll keep you updated with progress!
        """

        return await self.send_message(user_id, notification.strip())

    async def send_bridge_complete(self, user_id: int, usdc_received: float, pol_received: float) -> bool:
        """
        Send bridge completion notification

        Args:
            user_id: Telegram user ID
            usdc_received: USDC.e received
            pol_received: POL received

        Returns:
            True if sent successfully
        """
        notification = f"""
✅ **BRIDGE COMPLETE!**

💰 **Received:**
• {usdc_received:.2f} USDC.e (for trading)
• {pol_received:.2f} POL (for gas)

⚡ **Next:** Auto-approving contracts...
        """

        return await self.send_message(user_id, notification.strip())

    async def send_approval_started(self, user_id: int) -> bool:
        """Send approval start notification"""
        notification = """
⚡ **AUTO-APPROVAL STARTED!**

Approving contracts:
1. USDC.e spending approval
2. Polymarket contracts approval

⏱️ **Estimated: 30-60 seconds**
        """

        return await self.send_message(user_id, notification.strip())

    async def send_approval_complete(self, user_id: int) -> bool:
        """Send approval completion notification"""
        notification = """
✅ **CONTRACTS APPROVED!**

All required approvals complete:
• USDC.e spending ✅
• Polymarket contracts ✅

🔑 **Next:** Generating API keys...
        """

        return await self.send_message(user_id, notification.strip())

    async def send_api_generation_started(self, user_id: int) -> bool:
        """Send API generation start notification"""
        notification = """
🔑 **GENERATING API KEYS...**

Creating your personal API credentials for:
• Faster order placement
• Better rate limits
• Enhanced trading features

⏱️ **Estimated: 15-30 seconds**
        """

        return await self.send_message(user_id, notification.strip())

    async def send_setup_complete(self, user_id: int) -> bool:
        """Send complete onboarding success notification"""
        notification = """
🎉 **SETUP COMPLETE!**

✨ **Your account is fully configured:**
✅ Wallets created (Polygon + Solana)
✅ Wallet funded
✅ Contracts approved
✅ API keys generated

🚀 **You're ready to trade!**

Use /markets to browse and start trading!
        """

        return await self.send_message(user_id, notification.strip())

    async def send_error_notification(self, user_id: int, stage: str, error: str) -> bool:
        """
        Send error notification with recovery steps

        Args:
            user_id: Telegram user ID
            stage: Stage where error occurred
            error: Error message

        Returns:
            True if sent successfully
        """
        notification = f"""
❌ **ERROR DURING {stage.upper()}**

⚠️ **What happened:**
{error[:200]}

💡 **What to do:**
1. Check /wallet to see current status
2. Try the manual command if available
3. Contact support if issue persists

🔧 **You can continue manually using:**
• /bridge - Manual bridge
• /autoapprove - Manual approval
• /generateapi - Manual API generation
        """

        return await self.send_message(user_id, notification.strip())

    def _create_progress_bar(self, percentage: int, length: int = 10) -> str:
        """
        Create a visual progress bar

        Args:
            percentage: Progress percentage (0-100)
            length: Bar length in characters

        Returns:
            Progress bar string
        """
        filled = int((percentage / 100) * length)
        empty = length - filled

        return f"{'█' * filled}{'░' * empty}"


# Global notification service instance
notification_service = NotificationService()
