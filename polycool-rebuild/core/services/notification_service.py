"""
Centralized Notification Service
Handles queuing and processing of all notifications asynchronously
"""
import asyncio
import json
import uuid
from decimal import Decimal
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone

from core.models.notification_models import Notification, NotificationType, NotificationPriority, NotificationResult
from core.services.notification_templates import NotificationTemplates
from core.services.cache_manager import CacheManager
from infrastructure.logging.logger import get_logger

logger = get_logger(__name__)


def convert_decimals_to_floats(obj: Any) -> Any:
    """
    Recursively convert Decimal objects to float for JSON serialization

    Args:
        obj: Object that may contain Decimal values

    Returns:
        Object with all Decimal values converted to float
    """
    if isinstance(obj, Decimal):
        return float(obj)
    elif isinstance(obj, dict):
        return {key: convert_decimals_to_floats(value) for key, value in obj.items()}
    elif isinstance(obj, list):
        return [convert_decimals_to_floats(item) for item in obj]
    else:
        return obj


class RedisNotificationQueue:
    """
    Redis-based queue for notifications
    Uses Redis lists for FIFO queue with priority support
    """

    def __init__(self, cache_manager: CacheManager):
        self.cache_manager = cache_manager
        self.queue_key = "notifications:queue"
        self.processing_key = "notifications:processing"
        self.dead_letter_key = "notifications:dead_letter"

    async def push(self, notification_dict: Dict[str, Any], priority: NotificationPriority = NotificationPriority.NORMAL) -> None:
        """Push notification to queue with priority"""
        try:
            # Add metadata
            notification_dict['id'] = notification_dict.get('id', str(uuid.uuid4()))
            notification_dict['priority'] = priority.value

            # Convert all Decimal values to float for JSON serialization
            notification_dict = convert_decimals_to_floats(notification_dict)

            # Serialize
            data = json.dumps(notification_dict)

            # Push to Redis list (right push for FIFO) - redis operations are synchronous
            self.cache_manager.redis.rpush(self.queue_key, data)

            logger.debug(f"📨 Queued notification {notification_dict['id']} (type: {notification_dict.get('type')})")

        except Exception as e:
            logger.error(f"❌ Failed to queue notification: {e}")

    async def pop(self) -> Optional[Dict[str, Any]]:
        """Pop notification from queue"""
        try:
            # Pop from left (FIFO) - redis operations are synchronous
            data = self.cache_manager.redis.lpop(self.queue_key)
            if data:
                return json.loads(data)
        except Exception as e:
            logger.error(f"❌ Failed to pop notification from queue: {e}")
        return None

    def size(self) -> int:
        """Get queue size"""
        try:
            return self.cache_manager.redis.llen(self.queue_key)
        except Exception:
            return 0

    async def move_to_dead_letter(self, notification_dict: Dict[str, Any]) -> None:
        """Move failed notification to dead letter queue"""
        try:
            data = json.dumps(notification_dict)
            self.cache_manager.redis.rpush(self.dead_letter_key, data)
            logger.warning(f"💀 Moved notification {notification_dict.get('id')} to dead letter queue")
        except Exception as e:
            logger.error(f"❌ Failed to move to dead letter queue: {e}")


class NotificationService:
    """
    Centralized notification service
    Handles queuing, rate limiting, and processing of all notifications
    """

    def __init__(self):
        self.cache_manager = CacheManager()
        self.queue = RedisNotificationQueue(self.cache_manager)
        self.templates = NotificationTemplates()
        self.rate_limiter = NotificationRateLimiter(self.cache_manager)

        # Processing state
        self.is_processing = False
        self.processing_task: Optional[asyncio.Task] = None

    async def queue_notification(self, notification: Notification) -> NotificationResult:
        """
        Queue a notification for processing

        Args:
            notification: Notification to queue

        Returns:
            NotificationResult with success status
        """
        try:
            # Check rate limits
            can_send = await self.rate_limiter.can_send(
                user_id=notification.user_id,
                notification_type=notification.type,
                priority=notification.priority
            )

            if not can_send:
                logger.warning(f"🚫 Rate limit exceeded for user {notification.user_id}, skipping notification")
                return NotificationResult(
                    success=False,
                    error_message="Rate limit exceeded"
                )

            # Queue notification
            await self.queue.push(notification.to_dict(), notification.priority)

            logger.info(f"✅ Queued notification for user {notification.user_id} (type: {notification.type.value})")

            return NotificationResult(
                success=True,
                notification_id=notification.id
            )

        except Exception as e:
            logger.error(f"❌ Failed to queue notification: {e}")
            return NotificationResult(
                success=False,
                error_message=str(e)
            )

    async def start_processing(self) -> None:
        """Start background notification processing"""
        if self.is_processing:
            logger.warning("⚠️ Notification processing already running")
            return

        self.is_processing = True
        self.processing_task = asyncio.create_task(self._process_notifications_loop())
        logger.info("🚀 Started notification processing")

    async def stop_processing(self) -> None:
        """Stop background notification processing"""
        if not self.is_processing:
            return

        self.is_processing = False
        if self.processing_task and not self.processing_task.done():
            self.processing_task.cancel()
            try:
                await self.processing_task
            except asyncio.CancelledError:
                pass

        logger.info("🛑 Stopped notification processing")

    async def _process_notifications_loop(self) -> None:
        """Main processing loop for notifications"""
        logger.info("🔄 Notification processing loop started")

        while self.is_processing:
            try:
                # Get next notification from queue
                notification_dict = await self.queue.pop()
                if notification_dict:
                    # Process notification
                    await self._process_notification(notification_dict)
                else:
                    # Queue is empty, wait a bit
                    await asyncio.sleep(1.0)

            except asyncio.CancelledError:
                logger.info("🛑 Notification processing loop cancelled")
                break
            except Exception as e:
                logger.error(f"❌ Error in notification processing loop: {e}")
                await asyncio.sleep(1.0)

        logger.info("🔄 Notification processing loop ended")

    async def _process_notification(self, notification_dict: Dict[str, Any]) -> None:
        """Process a single notification"""
        try:
            notification = Notification.from_dict(notification_dict)

            # Get formatted message
            message = self.templates.get_template(notification.type, notification.data)
            if not message:
                logger.error(f"❌ No template found for notification type: {notification.type}")
                await self._handle_failed_notification(notification)
                return

            # Send via Telegram
            result = await self._send_telegram_notification(notification.user_id, message)

            if result.success:
                notification.mark_sent()
                logger.info(f"✅ Sent notification {notification.id} to user {notification.user_id}")
            else:
                # Handle failure
                await self._handle_failed_notification(notification, result.error_message)

        except Exception as e:
            logger.error(f"❌ Error processing notification {notification_dict.get('id')}: {e}")
            await self._handle_failed_notification(
                Notification.from_dict(notification_dict),
                str(e)
            )

    async def _send_telegram_notification(self, user_id: int, message: str) -> NotificationResult:
        """
        Send notification via Telegram Bot API

        Uses bot token from environment to send message directly
        """
        try:
            import httpx
            import os

            # Get bot token from environment
            bot_token = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("BOT_TOKEN")
            if not bot_token:
                logger.error("❌ No TELEGRAM_BOT_TOKEN or BOT_TOKEN found in environment")
                return NotificationResult(
                    success=False,
                    error_message="Bot token not configured"
                )

            # Send message via Telegram API
            telegram_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    telegram_url,
                    json={
                        "chat_id": user_id,
                        "text": message,
                        "parse_mode": "Markdown",
                        "disable_web_page_preview": True
                    }
                )

                if response.status_code == 200:
                    result_data = response.json()
                    if result_data.get("ok"):
                        message_id = result_data.get("result", {}).get("message_id")
                        logger.info(f"✅ Sent notification to user {user_id} (message_id: {message_id})")
                        return NotificationResult(
                            success=True,
                            telegram_message_id=message_id
                        )
                    else:
                        error_description = result_data.get("description", "Unknown error")
                        logger.error(f"❌ Telegram API error: {error_description}")
                        return NotificationResult(
                            success=False,
                            error_message=f"Telegram API: {error_description}"
                        )
                else:
                    logger.error(f"❌ HTTP {response.status_code} from Telegram API")
                    return NotificationResult(
                        success=False,
                        error_message=f"HTTP {response.status_code}"
                    )

        except Exception as e:
            logger.error(f"❌ Failed to send Telegram notification: {e}")
            return NotificationResult(
                success=False,
                error_message=str(e)
            )

    async def _handle_failed_notification(self, notification: Notification, error: Optional[str] = None) -> None:
        """Handle failed notification processing"""
        if notification.increment_retry():
            # Can retry - put back in queue with lower priority
            logger.warning(f"🔄 Retrying notification {notification.id} (attempt {notification.retry_count}/{notification.max_retries})")
            await self.queue.push(notification.to_dict(), NotificationPriority.LOW)
        else:
            # Max retries exceeded - move to dead letter queue
            logger.error(f"💀 Max retries exceeded for notification {notification.id}")
            await self.queue.move_to_dead_letter(notification.to_dict())

    async def get_stats(self) -> Dict[str, Any]:
        """Get notification service statistics"""
        return {
            'queue_size': self.queue.size(),
            'is_processing': self.is_processing,
            'rate_limiter_stats': self.rate_limiter.get_stats()
        }


class NotificationRateLimiter:
    """
    Rate limiter for notifications
    Prevents spam and respects Telegram API limits
    """

    def __init__(self, cache_manager: CacheManager):
        self.cache_manager = cache_manager

        # Rate limits (per user per time window)
        self.limits = {
            'per_minute': 10,
            'per_hour': 50,
            'per_day': 200
        }

        # Global rate limits (across all users)
        self.global_limits = {
            'per_second': 5  # Max 5 notifications per second globally
        }

    async def can_send(
        self,
        user_id: int,
        notification_type: NotificationType,
        priority: NotificationPriority
    ) -> bool:
        """
        Check if notification can be sent based on rate limits

        Args:
            user_id: Telegram user ID
            notification_type: Type of notification
            priority: Priority level

        Returns:
            True if can send, False if rate limited
        """
        try:
            # Skip rate limiting for critical notifications
            if priority == NotificationPriority.CRITICAL:
                return True

            # Check global rate limit
            if not await self._check_global_rate_limit():
                return False

            # Check user-specific rate limits
            return await self._check_user_rate_limits(user_id)

        except Exception as e:
            logger.error(f"❌ Error checking rate limits: {e}")
            # Allow notification on rate limit check failure (fail open)
            return True

    async def _check_global_rate_limit(self) -> bool:
        """Check global rate limit (across all users)"""
        try:
            key = "notifications:global:per_second"
            # Use direct Redis operations since CacheManager methods are async but we need sync Redis
            count = int(self.cache_manager.redis.get(key) or 0)

            if count >= self.global_limits['per_second']:
                return False

            # Increment counter with 1-second expiry
            self.cache_manager.redis.setex(key, 1, count + 1)
            return True

        except Exception as e:
            logger.error(f"❌ Error checking global rate limit: {e}")
            return True  # Fail open

    async def _check_user_rate_limits(self, user_id: int) -> bool:
        """Check user-specific rate limits"""
        try:
            # Check per-minute limit
            minute_key = f"notifications:user:{user_id}:per_minute"
            minute_count = int(self.cache_manager.redis.get(minute_key) or 0)
            if minute_count >= self.limits['per_minute']:
                return False

            # Check per-hour limit
            hour_key = f"notifications:user:{user_id}:per_hour"
            hour_count = int(self.cache_manager.redis.get(hour_key) or 0)
            if hour_count >= self.limits['per_hour']:
                return False

            # Check per-day limit
            day_key = f"notifications:user:{user_id}:per_day"
            day_count = int(self.cache_manager.redis.get(day_key) or 0)
            if day_count >= self.limits['per_day']:
                return False

            # Increment counters
            self.cache_manager.redis.setex(minute_key, 60, minute_count + 1)   # 1 minute
            self.cache_manager.redis.setex(hour_key, 3600, hour_count + 1)     # 1 hour
            self.cache_manager.redis.setex(day_key, 86400, day_count + 1)      # 24 hours

            return True

        except Exception as e:
            logger.error(f"❌ Error checking user rate limits: {e}")
            return True  # Fail open

    def get_stats(self) -> Dict[str, Any]:
        """Get rate limiter statistics"""
        return {
            'limits': self.limits,
            'global_limits': self.global_limits
        }


# Global instance
notification_service: Optional[NotificationService] = None


def get_notification_service() -> NotificationService:
    """Get the global notification service instance"""
    global notification_service
    if notification_service is None:
        notification_service = NotificationService()
    return notification_service
