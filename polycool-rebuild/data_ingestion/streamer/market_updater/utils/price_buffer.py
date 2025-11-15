"""
Price Buffer - Accumulate partial price updates for binary markets
Handles WebSocket messages that send one price at a time instead of both prices together
"""
import asyncio
from typing import Dict, Optional, List, Set
from datetime import datetime, timezone, timedelta
from infrastructure.logging.logger import get_logger

logger = get_logger(__name__)


class PriceBuffer:
    """
    Buffer to accumulate partial price updates for markets
    For binary markets, WebSocket may send one price at a time
    This buffer accumulates them and emits complete price sets
    """

    def __init__(
        self,
        buffer_timeout: float = 2.0,
        max_buffer_size: int = 1000
    ):
        """
        Initialize PriceBuffer

        Args:
            buffer_timeout: Maximum time to wait for complete prices (seconds)
            max_buffer_size: Maximum number of markets to buffer
        """
        self.buffer_timeout = buffer_timeout
        self.max_buffer_size = max_buffer_size

        # Buffer structure: market_id -> {token_id -> price, ...}
        self._buffer: Dict[str, Dict[str, float]] = {}

        # Track when prices were added (for timeout)
        self._buffer_timestamps: Dict[str, datetime] = {}

        # Track expected number of outcomes per market
        self._expected_outcomes: Dict[str, int] = {}

        # Track token_id -> outcome_index mapping
        self._token_to_outcome: Dict[str, Dict[str, int]] = {}  # market_id -> {token_id -> outcome_index}

        # Cleanup task
        self._cleanup_task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self) -> None:
        """Start the price buffer (starts cleanup task)"""
        self._running = True
        if not self._cleanup_task or self._cleanup_task.done():
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    async def stop(self) -> None:
        """Stop the price buffer"""
        self._running = False
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

    def add_price(
        self,
        market_id: str,
        token_id: Optional[str],
        price: float,
        outcome_index: Optional[int] = None,
        expected_outcomes: Optional[int] = None,
        token_to_outcome_map: Optional[Dict[str, int]] = None
    ) -> Optional[List[float]]:
        """
        Add a price to the buffer and return complete prices if available

        Args:
            market_id: Market ID
            token_id: Token ID (CLOB token ID)
            price: Price value (0-1)
            outcome_index: Optional outcome index (0 for YES, 1 for NO)
            expected_outcomes: Expected number of outcomes (2 for binary)
            token_to_outcome_map: Optional mapping of token_id -> outcome_index

        Returns:
            Complete list of prices if buffer is complete, None otherwise
        """
        if not market_id:
            return None

        # Initialize buffer entry if needed
        if market_id not in self._buffer:
            if len(self._buffer) >= self.max_buffer_size:
                # Remove oldest entry
                oldest_market = min(
                    self._buffer_timestamps.items(),
                    key=lambda x: x[1]
                )[0]
                self._remove_market(oldest_market)

            self._buffer[market_id] = {}
            self._buffer_timestamps[market_id] = datetime.now(timezone.utc)

        # Store expected outcomes count
        if expected_outcomes is not None:
            self._expected_outcomes[market_id] = expected_outcomes

        # Store token_id -> outcome mapping
        if token_to_outcome_map:
            self._token_to_outcome[market_id] = token_to_outcome_map

        # Determine outcome index
        if outcome_index is None and token_id:
            # Try to get from mapping
            if market_id in self._token_to_outcome:
                outcome_index = self._token_to_outcome[market_id].get(token_id)

        # Store price by outcome index or token_id
        if outcome_index is not None:
            # Store by outcome index (preferred)
            self._buffer[market_id][f"outcome_{outcome_index}"] = price
        elif token_id:
            # Store by token_id (fallback)
            self._buffer[market_id][token_id] = price
        else:
            # No identifier, can't store properly
            logger.warning(f"⚠️ Cannot buffer price for market {market_id}: no token_id or outcome_index")
            return None

        # Check if we have complete prices
        return self._check_complete(market_id)

    def _check_complete(self, market_id: str) -> Optional[List[float]]:
        """
        Check if buffer has complete prices for a market

        Args:
            market_id: Market ID

        Returns:
            Complete list of prices if available, None otherwise
        """
        if market_id not in self._buffer:
            return None

        buffer_entry = self._buffer[market_id]
        expected_count = self._expected_outcomes.get(market_id, 2)  # Default to 2 for binary

        # Try to extract prices by outcome index
        prices_by_outcome = {}
        for key, price in buffer_entry.items():
            if key.startswith("outcome_"):
                try:
                    outcome_idx = int(key.split("_")[1])
                    prices_by_outcome[outcome_idx] = price
                except (ValueError, IndexError):
                    pass

        # If we have prices by outcome index, use them
        if len(prices_by_outcome) >= expected_count:
            # Sort by outcome index
            complete_prices = [
                prices_by_outcome[i] for i in sorted(prices_by_outcome.keys())
            ]
            if len(complete_prices) == expected_count:
                logger.debug(
                    f"✅ Buffer complete for market {market_id}: {complete_prices}"
                )
                self._remove_market(market_id)
                return complete_prices

        # For binary markets (expected_count == 2), try to calculate missing price
        if expected_count == 2 and len(prices_by_outcome) == 1:
            # We have one price, calculate the other (YES + NO = 1.0)
            outcome_idx = list(prices_by_outcome.keys())[0]
            known_price = prices_by_outcome[outcome_idx]
            other_price = 1.0 - known_price

            # Validate calculated price
            if 0 <= other_price <= 1:
                complete_prices = [None, None]
                complete_prices[outcome_idx] = known_price
                complete_prices[1 - outcome_idx] = other_price

                logger.debug(
                    f"✅ Buffer complete for market {market_id} (calculated): "
                    f"outcome[{outcome_idx}]={known_price:.4f}, "
                    f"outcome[{1-outcome_idx}]={other_price:.4f}"
                )
                self._remove_market(market_id)
                return complete_prices

        # Not complete yet
        return None

    def _remove_market(self, market_id: str) -> None:
        """Remove a market from the buffer (internal method)"""
        self._buffer.pop(market_id, None)
        self._buffer_timestamps.pop(market_id, None)
        self._expected_outcomes.pop(market_id, None)
        self._token_to_outcome.pop(market_id, None)

    def remove_market(self, market_id: str) -> None:
        """
        Remove a market from the buffer (public method)
        Called when unsubscribing from a market to prevent processing stale price updates

        Args:
            market_id: Market ID to remove from buffer
        """
        if market_id in self._buffer:
            logger.debug(f"🧹 Removing market {market_id} from price buffer (unsubscribe)")
            self._remove_market(market_id)

    async def _cleanup_loop(self) -> None:
        """Periodic cleanup of expired buffer entries"""
        while self._running:
            try:
                await asyncio.sleep(self.buffer_timeout)

                if not self._running:
                    break

                # Remove expired entries
                now = datetime.now(timezone.utc)
                expired_markets = [
                    market_id
                    for market_id, timestamp in self._buffer_timestamps.items()
                    if (now - timestamp).total_seconds() > self.buffer_timeout
                ]

                for market_id in expired_markets:
                    logger.debug(
                        f"🧹 Removing expired buffer entry for market {market_id}"
                    )
                    self._remove_market(market_id)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"⚠️ Error in cleanup loop: {e}")

    def get_buffer_stats(self) -> Dict[str, any]:
        """Get buffer statistics"""
        return {
            "buffered_markets": len(self._buffer),
            "max_size": self.max_buffer_size,
            "timeout": self.buffer_timeout,
        }
