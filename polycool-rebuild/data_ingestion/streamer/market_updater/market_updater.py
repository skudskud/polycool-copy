"""
Market Updater - Updates markets table from WebSocket data
Source priority: 'ws' > 'poll' (WebSocket data takes precedence)

Refactored to use modular components:
- Extractors: Price extraction and identifier resolution
- Handlers: Market, orderbook, and trade updates
- Position: Position updates and TP/SL triggers
- Utils: Debouncing, validation
"""
import json
import os
from typing import Dict, Any, Optional
from infrastructure.logging.logger import get_logger

from .extractors.price_extractor import PriceExtractor
from .extractors.identifier_resolver import IdentifierResolver
from .handlers.market_update_handler import MarketUpdateHandler
from .handlers.orderbook_handler import OrderbookHandler
from .handlers.trade_handler import TradeHandler
from .position.position_update_handler import PositionUpdateHandler
from .position.tpsl_trigger import TPSLTrigger
from .utils.debounce_manager import DebounceManager
from .utils.price_validator import validate_prices
from .utils.price_buffer import PriceBuffer

logger = get_logger(__name__)

# Check if bot has DB access
SKIP_DB = os.getenv("SKIP_DB", "false").lower() == "true"


class MarketUpdater:
    """
    Updates markets table from WebSocket data
    - Source priority: 'ws' > 'poll'
    - Updates prices, orderbook, last trade
    - Invalidates cache
    - Automatically updates positions when prices change (with debouncing)
    """

    def __init__(self):
        """Initialize MarketUpdater with modular components"""
        self.update_count = 0

        # Initialize extractors
        self.identifier_resolver = IdentifierResolver()
        self.price_extractor = PriceExtractor()

        # Initialize handlers
        self.market_handler = MarketUpdateHandler()
        self.orderbook_handler = OrderbookHandler()
        self.trade_handler = TradeHandler()

        # Initialize position handlers
        self.position_handler = PositionUpdateHandler()
        self.tpsl_trigger = TPSLTrigger()

        # Initialize debounce managers - increased delays to prevent API spam
        self.market_debounce = DebounceManager(delay=5.0, max_updates_per_second=2)  # 5s delay, max 2/sec
        self.position_debounce = DebounceManager(delay=10.0, max_updates_per_second=5)  # 10s delay, max 5/sec

        # Initialize price buffer for accumulating partial price updates
        self.price_buffer = PriceBuffer(buffer_timeout=2.0, max_buffer_size=1000)

    async def start(self) -> None:
        """Start the market updater (starts price buffer)"""
        await self.price_buffer.start()

    async def stop(self) -> None:
        """Stop the market updater (stops price buffer)"""
        await self.price_buffer.stop()

    async def handle_price_update(self, data: Dict[str, Any]) -> None:
        """
        Handle price update from WebSocket

        Args:
            data: WebSocket message data with price information
        """
        try:
            logger.info(
                f"📊 Processing price update: {data.get('type', 'unknown')} - "
                f"event_type: {data.get('event_type')} - keys: {list(data.keys())[:10]}"
            )

            # Step 1: Resolve market_id from WebSocket data
            logger.info(f"🔍 Resolving market identifier from message: market={data.get('market')}, event_type={data.get('event_type')}")
            market_id = await self.identifier_resolver.resolve_market_identifier(data)
            token_id = (
                data.get("token_id") or
                data.get("asset_id") or
                data.get("assetId") or
                data.get("asset")
            )

            # Also check in price_changes for asset_id
            if not token_id:
                price_changes = data.get("price_changes")
                if price_changes and isinstance(price_changes, list) and len(price_changes) > 0:
                    first_change = price_changes[0]
                    if isinstance(first_change, dict):
                        token_id = first_change.get("asset_id") or first_change.get("asset")

            logger.info(f"🔍 Resolved identifiers: market_id={market_id}, token_id={token_id[:30] if token_id else None}...")

            if not market_id and not token_id:
                logger.warning(f"⚠️ Price update without market_id or token_id: {json.dumps(data)[:300]}")
                return

            # Step 2: Get market data for price mapping (if market_id available)
            market_data = None
            if market_id:
                try:
                    if SKIP_DB:
                        from core.services.api_client import get_api_client
                        api_client = get_api_client()
                        # Use get_market() which uses Redis cache instead of direct client.get()
                        market_data = await api_client.get_market(market_id)
                    else:
                        from core.database.connection import get_db
                        from core.database.models import Market
                        from sqlalchemy import select
                        async with get_db() as db:
                            result = await db.execute(
                                select(Market).where(Market.id == market_id)
                            )
                            market = result.scalar_one_or_none()
                            if market:
                                from core.services.market_service.market_service import _market_to_dict
                                market_data = _market_to_dict(market)
                except Exception as e:
                    logger.debug(f"Could not fetch market data for mapping: {e}")

            # Step 3: Extract prices with proper outcome mapping
            # Try to extract complete prices first
            logger.info(f"🔍 Extracting prices from message (has market_data: {market_data is not None})")
            if market_data:
                logger.info(f"   Market outcomes: {market_data.get('outcomes')}, clob_token_ids: {market_data.get('clob_token_ids')[:2] if market_data.get('clob_token_ids') else None}...")
            prices = await self.price_extractor.extract_prices(data, market_data)
            logger.info(f"🔍 Extracted prices: {prices}")

            # Get expected outcomes count from market_data
            expected_outcomes = None
            if market_data:
                outcomes = market_data.get("outcomes")
                if outcomes and isinstance(outcomes, list):
                    expected_outcomes = len(outcomes)

            # Get token_id to outcome mapping from market_data
            token_to_outcome_map = None
            if market_data:
                clob_token_ids = market_data.get("clob_token_ids")
                outcomes = market_data.get("outcomes")
                if clob_token_ids and outcomes and isinstance(clob_token_ids, list):
                    # Parse if string
                    if isinstance(clob_token_ids, str):
                        import json
                        try:
                            clob_token_ids = json.loads(clob_token_ids)
                        except:
                            pass
                    if isinstance(clob_token_ids, list):
                        token_to_outcome_map = {
                            str(tid): idx
                            for idx, tid in enumerate(clob_token_ids)
                            if idx < len(outcomes)
                        }

            # Step 3.5: Handle partial prices using buffer
            # If we have partial prices (1 price for binary market), use buffer
            if prices and len(prices) == 1 and expected_outcomes == 2:
                # This is a partial update - add to buffer
                logger.debug(
                    f"📦 Partial price update for market {market_id}: {prices[0]} "
                    f"(expected {expected_outcomes} prices)"
                )

                # Extract token_id and outcome_index from price_changes if available
                price_changes = data.get("price_changes")
                outcome_index = None
                price_token_id = token_id

                if price_changes and isinstance(price_changes, list) and len(price_changes) > 0:
                    first_change = price_changes[0]
                    if isinstance(first_change, dict):
                        price_token_id = (
                            first_change.get("asset_id") or
                            first_change.get("asset") or
                            token_id
                        )
                        # Try to get outcome_index from mapping
                        if price_token_id and token_to_outcome_map:
                            outcome_index = token_to_outcome_map.get(str(price_token_id))

                # Add to buffer
                complete_prices = self.price_buffer.add_price(
                    market_id=market_id,
                    token_id=price_token_id,
                    price=prices[0],
                    outcome_index=outcome_index,
                    expected_outcomes=expected_outcomes,
                    token_to_outcome_map=token_to_outcome_map
                )

                if complete_prices:
                    # Buffer returned complete prices
                    logger.debug(
                        f"✅ Buffer returned complete prices for market {market_id}: {complete_prices}"
                    )
                    prices = complete_prices
                else:
                    # Still waiting for more prices
                    logger.debug(
                        f"⏳ Buffer accumulating prices for market {market_id} "
                        f"(have {len(prices)}/{expected_outcomes})"
                    )
                    return  # Wait for more prices

            if not prices:
                logger.warning(
                    f"⚠️ No prices found in price update for {market_id or token_id}"
                )
                logger.warning(f"   Message keys: {list(data.keys())[:20]}")
                logger.warning(f"   Message sample: {json.dumps(data)[:500]}")
                return

            logger.debug(f"✅ Extracted prices {prices} for market {market_id or token_id}")

            # Step 4: Validate prices before updating
            logger.info(f"🔍 Validating prices: {prices} for market {market_id}")
            if not validate_prices(prices, market_data):
                logger.warning(
                    f"⚠️ Invalid prices {prices} for market {market_id} (outcomes: {market_data.get('outcomes') if market_data else 'unknown'}) - skipping update"
                )
                return
            logger.info(f"✅ Prices validated successfully: {prices}")

            # Step 5: Schedule market update with debouncing
            if market_id:
                logger.info(f"⏱️ Scheduling market update for {market_id} with debounce (delay={self.market_debounce.delay}s), prices={prices}")
                await self.market_debounce.schedule_update(
                    key=market_id,
                    data={
                        'market_id': market_id,
                        'token_id': token_id,
                        'prices': prices,
                        'original_data': data
                    },
                    callback=self._process_market_update
                )
            else:
                # If no market_id, update immediately (shouldn't happen often)
                await self.market_handler.update_prices(
                    market_id=market_id,
                    token_id=token_id,
                    prices=prices,
                    data=data
                )

            # Step 6: Trigger position updates (with debouncing)
            if market_id and prices:
                await self.position_debounce.schedule_update(
                    key=market_id,
                    data={
                        'market_id': market_id,
                        'prices': prices
                    },
                    callback=self._process_position_update
                )

            self.update_count += 1

        except Exception as e:
            logger.error(f"⚠️ Error handling price update: {e}")

    async def _process_market_update(self, key: str, data: Dict[str, Any]) -> None:
        """
        Process market update callback (called by debounce manager)

        Args:
            key: Market ID
            data: Update data with prices and original WebSocket data
        """
        market_id = data.get('market_id')
        token_id = data.get('token_id')
        prices = data.get('prices')
        original_data = data.get('original_data', {})

        logger.info(f"✅ Processing debounced market update for {market_id} with prices={prices}")
        await self.market_handler.update_prices(
            market_id=market_id,
            token_id=token_id,
            prices=prices,
            data=original_data
        )

    async def _process_position_update(self, key: str, data: Dict[str, Any]) -> None:
        """
        Process position update callback (called by debounce manager)

        Args:
            key: Market ID
            data: Update data with prices
        """
        market_id = data.get('market_id')
        prices = data.get('prices')

        # Update positions
        positions = await self.position_handler.update_positions_for_market(
            market_id=market_id,
            prices=prices
        )

        # Check TP/SL triggers if positions were updated
        if positions:
            await self.tpsl_trigger.check_triggers_for_market(market_id, positions)

    async def handle_orderbook_update(self, data: Dict[str, Any]) -> None:
        """
        Handle orderbook update from WebSocket

        Args:
            data: WebSocket message data with orderbook information
        """
        try:
            market_id = data.get("market_id") or data.get("market")
            token_id = data.get("token_id") or data.get("asset_id")

            if not market_id and not token_id:
                logger.debug("⚠️ Orderbook update without market_id or token_id")
                return

            # Extract orderbook data
            orderbook = data.get("orderbook") or data.get("book")
            if not orderbook:
                logger.debug(f"⚠️ No orderbook data in update for {market_id or token_id}")
                return

            # Calculate mid price from orderbook
            mid_price = self.orderbook_handler.calculate_mid_price(orderbook)

            # Update market
            await self.orderbook_handler.update_market_orderbook(
                market_id=market_id,
                token_id=token_id,
                orderbook=orderbook,
                mid_price=mid_price
            )

        except Exception as e:
            logger.error(f"⚠️ Error handling orderbook update: {e}")

    async def handle_trade_update(self, data: Dict[str, Any]) -> None:
        """
        Handle trade update from WebSocket

        Args:
            data: WebSocket message data with trade information
        """
        try:
            market_id = data.get("market_id") or data.get("market")
            token_id = data.get("token_id") or data.get("asset_id")

            if not market_id and not token_id:
                logger.debug("⚠️ Trade update without market_id or token_id")
                return

            # Extract trade data
            trade_price = data.get("price") or data.get("trade_price")
            trade_size = data.get("size") or data.get("trade_size")

            if not trade_price:
                logger.debug(f"⚠️ No price in trade update for {market_id or token_id}")
                return

            # Update market last trade price
            await self.trade_handler.update_market_trade(
                market_id=market_id,
                token_id=token_id,
                trade_price=trade_price,
                trade_size=trade_size
            )

        except Exception as e:
            logger.error(f"⚠️ Error handling trade update: {e}")

    def on_market_unsubscribed(self, market_id: str) -> None:
        """
        Called when a market is unsubscribed
        Cleans up the price buffer for this market to prevent processing stale updates

        Args:
            market_id: Market ID that was unsubscribed
        """
        if market_id:
            self.price_buffer.remove_market(market_id)
            logger.debug(f"🧹 Cleaned up price buffer for unsubscribed market {market_id}")

    def get_stats(self) -> Dict[str, Any]:
        """Get updater statistics"""
        return {
            "update_count": self.update_count,
            "pending_market_updates": self.market_debounce.get_pending_count(),
            "pending_position_updates": self.position_debounce.get_pending_count(),
            "price_buffer": self.price_buffer.get_buffer_stats(),
        }
