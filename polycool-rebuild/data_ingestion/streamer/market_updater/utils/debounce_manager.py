"""
Debounce Manager - Debouncing and rate limiting for updates
Accumulates updates and processes them after delay
"""
import asyncio
from typing import Dict, Any, Optional, Callable, Awaitable
from datetime import datetime, timezone
from infrastructure.logging.logger import get_logger

logger = get_logger(__name__)


class DebounceManager:
    """
    Manage debouncing and rate limiting for updates
    Accumulates updates and processes them after delay
    """

    def __init__(
        self,
        delay: float = 0.5,
        max_updates_per_second: int = 10
    ):
        """
        Initialize DebounceManager

        Args:
            delay: Debounce delay in seconds (default: 0.5)
            max_updates_per_second: Maximum updates per second for rate limiting (default: 10)
        """
        self.delay = delay
        self.max_updates_per_second = max_updates_per_second
        self._pending_updates: Dict[str, Dict[str, Any]] = {}
        self._process_task: Optional[asyncio.Task] = None

    async def schedule_update(
        self,
        key: str,
        data: Dict[str, Any],
        callback: Callable[[str, Dict[str, Any]], Awaitable[None]]
    ) -> None:
        """
        Schedule an update with debouncing
        Accumulates updates and processes them after delay

        Args:
            key: Unique key for the update (e.g., market_id)
            data: Update data
            callback: Async callback function to process the update
        """
        try:
            # Store pending update (keep latest data)
            self._pending_updates[key] = {
                'key': key,
                'data': data,
                'callback': callback,
                'timestamp': datetime.now(timezone.utc).timestamp()
            }

            # Cancel existing task if running
            if self._process_task and not self._process_task.done():
                self._process_task.cancel()

            # Schedule new task
            self._process_task = asyncio.create_task(
                self._process_pending_updates()
            )

        except Exception as e:
            logger.error(f"⚠️ Error scheduling update: {e}")

    async def _process_pending_updates(self) -> None:
        """
        Process accumulated updates after debounce delay
        Uses latest data for each key
        """
        try:
            # Wait for debounce delay
            await asyncio.sleep(self.delay)

            if not self._pending_updates:
                return

            # Get all pending updates
            pending = self._pending_updates.copy()
            self._pending_updates.clear()

            # Process updates (use latest data for each key)
            for key, update_data in pending.items():
                try:
                    callback = update_data['callback']
                    data = update_data.get('data', {})

                    # Call the callback
                    await callback(key, data)

                    # Rate limiting: wait between updates (max updates_per_second)
                    if self.max_updates_per_second > 0:
                        wait_time = 1.0 / self.max_updates_per_second
                        await asyncio.sleep(wait_time)

                except Exception as e:
                    logger.error(f"⚠️ Error processing update for {key}: {e}")

        except asyncio.CancelledError:
            # Task was cancelled, ignore
            pass
        except Exception as e:
            logger.error(f"⚠️ Error processing pending updates: {e}")

    def get_pending_count(self) -> int:
        """Get number of pending updates"""
        return len(self._pending_updates)
