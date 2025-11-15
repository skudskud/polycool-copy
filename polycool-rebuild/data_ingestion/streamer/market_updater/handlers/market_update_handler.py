"""
Market Update Handler - Unified market price updates (DB/API)
Handles both database and API updates transparently based on SKIP_DB
"""
import os
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from core.database.connection import get_db
from core.database.models import Market
from core.services.cache_manager import CacheManager
from infrastructure.logging.logger import get_logger

logger = get_logger(__name__)

# Check if bot has DB access
SKIP_DB = os.getenv("SKIP_DB", "false").lower() == "true"

# Import API client if SKIP_DB is true
if SKIP_DB:
    from core.services.api_client import get_api_client

cache_manager = CacheManager()


class MarketUpdateHandler:
    """
    Unified handler for market price updates
    Supports both DB and API modes transparently
    """

    def __init__(self, market_service=None, api_client=None):
        """
        Initialize MarketUpdateHandler

        Args:
            market_service: Optional MarketService instance
            api_client: Optional APIClient instance (required if SKIP_DB=true)
        """
        self.market_service = market_service
        self.api_client = api_client
        if SKIP_DB and not self.api_client:
            from core.services.api_client import get_api_client
            self.api_client = get_api_client()

    async def update_prices(
        self,
        market_id: Optional[str],
        token_id: Optional[str],
        prices: List[float],
        data: Dict[str, Any]
    ) -> None:
        """
        Update market prices (unified DB/API)

        Args:
            market_id: Market ID (optional)
            token_id: Token ID (optional, used if market_id not available)
            prices: List of prices [YES_price, NO_price]
            data: Original WebSocket message data
        """
        if SKIP_DB:
            await self._update_prices_via_api(market_id, token_id, prices, data)
        else:
            async with get_db() as db:
                await self._update_prices_db(db, market_id, token_id, prices, data)

        # Invalidate cache
        if market_id:
            await cache_manager.delete(f"price:{market_id}")
            await cache_manager.delete(f"market:{market_id}")
            await cache_manager.delete(f"market_detail:{market_id}")

    async def _update_prices_db(
        self,
        db: AsyncSession,
        market_id: Optional[str],
        token_id: Optional[str],
        prices: List[float],
        data: Dict[str, Any]
    ) -> None:
        """Update market prices in database"""
        try:
            # Find market by ID or token_id
            if market_id:
                query = select(Market).where(Market.id == market_id)
            elif token_id:
                # Find market by token_id in clob_token_ids JSONB
                query = select(Market).where(
                    Market.clob_token_ids.contains([token_id])
                )
            else:
                return

            result = await db.execute(query)
            market = result.scalar_one_or_none()

            if not market:
                logger.debug(f"⚠️ Market not found for update: {market_id or token_id}")
                return

            # Update prices (source: 'ws' takes precedence)
            # ✅ CRITICAL: Ensure prices are stored as numbers (not strings) in JSONB
            # Convert to list of floats explicitly to avoid string serialization
            prices_as_numbers = [float(p) for p in prices] if prices else []

            update_data = {
                "source": "ws",
                "outcome_prices": prices_as_numbers,  # Explicitly numbers, not strings
                "last_mid_price": sum(prices_as_numbers) / len(prices_as_numbers) if prices_as_numbers else None,
                "updated_at": datetime.now(timezone.utc)
            }

            # Update last trade price if available
            if "last_trade_price" in data:
                update_data["last_trade_price"] = float(data["last_trade_price"])

            logger.info(f"📝 Updating market {market.id} with source='ws', prices={prices}")

            await db.execute(
                update(Market)
                .where(Market.id == market.id)
                .values(**update_data)
            )

            await db.commit()
            logger.info(f"✅ Updated market {market.id} with source='ws' in database")

        except Exception as e:
            logger.error(f"⚠️ Error updating market prices: {e}")
            await db.rollback()

    async def _update_prices_via_api(
        self,
        market_id: Optional[str],
        token_id: Optional[str],
        prices: List[float],
        data: Dict[str, Any]
    ) -> None:
        """Update market prices via API when SKIP_DB=true"""
        try:
            # If we only have token_id, find market_id first
            if not market_id and token_id:
                # Use identifier resolver to find market_id
                from ..extractors.identifier_resolver import IdentifierResolver
                resolver = IdentifierResolver()
                market_id = await resolver.get_market_id_from_token_id(token_id)
                if not market_id:
                    logger.warning(f"⚠️ Could not find market_id for token_id {token_id}")
                    return

            if not market_id:
                logger.warning(f"⚠️ No market_id available for update")
                return

            # Prepare update data
            # ✅ CRITICAL: Ensure prices are stored as numbers (not strings) in JSONB
            prices_as_numbers = [float(p) for p in prices] if prices else []

            update_data = {
                "outcome_prices": prices_as_numbers,  # Explicitly numbers, not strings
                "source": "ws",
                "last_mid_price": sum(prices_as_numbers) / len(prices_as_numbers) if prices_as_numbers else None
            }

            if "last_trade_price" in data:
                update_data["last_trade_price"] = float(data["last_trade_price"])

            logger.debug(f"📝 Updating market {market_id} via API with source='ws', prices={prices}")
            logger.debug(f"   Update data: {update_data}")

            # Call API to update market (base_url already contains /api/v1)
            url = f"{self.api_client.base_url}/markets/{market_id}"
            logger.debug(f"   Calling PUT {url}")
            response = await self.api_client.client.put(
                url,
                json=update_data,
                timeout=5.0
            )

            if response.status_code == 200:
                logger.debug(f"✅ Updated market {market_id} with source='ws' via API")
                try:
                    response_data = response.json()
                    logger.debug(
                        f"   Response: market_id={response_data.get('id')}, "
                        f"source={response_data.get('source', 'N/A')}"
                    )
                except:
                    pass
            elif response.status_code == 404:
                logger.warning(f"⚠️ Market {market_id} not found via API")
            else:
                logger.error(f"❌ API update failed for market {market_id}: {response.status_code}")
                try:
                    logger.error(f"   Response text: {response.text[:200]}")
                except:
                    pass

        except Exception as e:
            logger.error(f"⚠️ Error updating market prices via API: {e}")
            import traceback
            logger.debug(f"Traceback: {traceback.format_exc()}")
