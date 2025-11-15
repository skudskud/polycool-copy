"""
Identifier Resolver - Resolve market identifiers (condition_id, market_id, token_id)
Uses MarketService for lookups with caching support
"""
import os
from typing import Dict, Any, Optional
from infrastructure.logging.logger import get_logger

logger = get_logger(__name__)

# Check if bot has DB access
SKIP_DB = os.getenv("SKIP_DB", "false").lower() == "true"

# Import API client if SKIP_DB is true
if SKIP_DB:
    from core.services.api_client import get_api_client


class IdentifierResolver:
    """
    Resolve market identifiers from WebSocket messages
    Converts condition_id (hex hash) to market_id (numeric)
    Uses MarketService for lookups with caching
    """

    def __init__(self, market_service=None):
        """
        Initialize IdentifierResolver

        Args:
            market_service: Optional MarketService instance (will create if None)
        """
        self.market_service = market_service
        if not self.market_service:
            from core.services.market_service.market_service import get_market_service
            from core.services.cache_manager import CacheManager
            cache_manager = CacheManager()
            self.market_service = get_market_service(cache_manager=cache_manager)

    async def resolve_market_identifier(self, data: Dict[str, Any]) -> Optional[str]:
        """
        Resolve market_id from WebSocket message data
        Handles condition_id, market_id, and token_id

        Args:
            data: WebSocket message data

        Returns:
            Market ID (numeric) or None if not found
        """
        # Extract market identifier from message
        market_identifier = data.get("market_id") or data.get("market")
        token_id = data.get("token_id") or data.get("asset_id") or data.get("assetId") or data.get("asset")

        # Also check in price_changes array for asset_id
        if not token_id:
            price_changes = data.get("price_changes")
            if price_changes and isinstance(price_changes, list) and len(price_changes) > 0:
                first_change = price_changes[0]
                if isinstance(first_change, dict):
                    token_id = first_change.get("asset_id") or first_change.get("asset")

        # Handle Polymarket format with "market" field
        condition_id = None
        market_id = None

        if market_identifier:
            if isinstance(market_identifier, dict):
                # market might be an object, extract ID
                market_identifier = market_identifier.get("id") or market_identifier.get("market_id")

            if isinstance(market_identifier, str):
                # Check if it's a condition_id (hex hash starting with 0x) or market_id (numeric)
                if market_identifier.startswith("0x") or len(market_identifier) > 20:
                    # This is a condition_id (hash hex), need to convert to market_id
                    condition_id = market_identifier
                    logger.debug(f"🔍 WebSocket sent condition_id: {condition_id}")
                elif market_identifier.isdigit():
                    # This is already a market_id (numeric)
                    market_id = market_identifier
                    logger.debug(f"🔍 WebSocket sent market_id: {market_id}")
                else:
                    # Try as condition_id first
                    condition_id = market_identifier
                    logger.debug(f"🔍 Treating as condition_id: {condition_id}")

        # Convert condition_id to market_id if needed
        if condition_id and not market_id:
            logger.info(f"🔍 Converting condition_id to market_id: {condition_id[:30]}...")
            market_id = await self.get_market_id_from_condition_id(condition_id)
            if not market_id:
                logger.warning(f"⚠️ Could not find market_id for condition_id {condition_id[:30]}...")
            else:
                logger.info(f"✅ Found market_id {market_id} for condition_id {condition_id[:30]}...")

        # If we only have token_id, find market_id from database
        if not market_id and token_id:
            logger.info(f"🔍 Looking up market_id from token_id: {token_id[:30]}...")
            market_id = await self.get_market_id_from_token_id(token_id)
            if not market_id:
                logger.warning(f"⚠️ Could not find market_id for token_id {token_id[:30]}...")
            else:
                logger.info(f"✅ Found market_id {market_id} for token_id {token_id[:30]}...")

        return market_id

    async def get_market_id_from_condition_id(self, condition_id: str) -> Optional[str]:
        """
        Get market_id from condition_id by searching in markets table
        Uses APIClient with Redis cache to avoid repeated API calls

        Args:
            condition_id: Condition ID (hash hex from WebSocket)

        Returns:
            Market ID (numeric) or None if not found
        """
        try:
            # Use API if SKIP_DB=true
            if SKIP_DB:
                try:
                    api_client = get_api_client()
                    # Use get_market() which automatically handles condition_id and uses Redis cache
                    market = await api_client.get_market(condition_id)

                    if market:
                        market_id = market.get('id')
                        return market_id
                    return None
                except Exception as api_error:
                    logger.debug(f"Error getting market by condition_id via API: {api_error}")
                    return None

            # Use MarketService (which uses DB)
            market_data = await self.market_service.get_market_by_condition_id(condition_id)
            if market_data:
                market_id = market_data.get('id')
                if market_id:
                    logger.debug(
                        f"✅ Found market_id {market_id} for condition_id "
                        f"{condition_id[:20]}..."
                    )
                return market_id

            return None
        except Exception as e:
            logger.error(f"⚠️ Error getting market_id for condition_id {condition_id[:20]}...: {e}")
            return None

    async def get_market_id_from_token_id(self, token_id: str) -> Optional[str]:
        """
        Get market_id from token_id by searching in markets table
        Uses APIClient with Redis cache to avoid repeated API calls

        Args:
            token_id: CLOB token ID

        Returns:
            Market ID or None if not found
        """
        try:
            # Use API if SKIP_DB=true
            if SKIP_DB:
                try:
                    api_client = get_api_client()
                    # Use _get() with cache for token_id endpoint
                    market = await api_client._get(
                        f"/markets/by-token-id/{token_id}",
                        f"api:market:token:{token_id}",
                        'market_detail'
                    )

                    if market:
                        market_id = market.get('id')
                        return market_id
                    return None
                except Exception as api_error:
                    logger.debug(f"Error getting market by token_id via API: {api_error}")
                    return None

            # Use DB if SKIP_DB=false
            from core.database.connection import get_db
            from core.database.models import Market
            from sqlalchemy import select

            async with get_db() as db:
                result = await db.execute(
                    select(Market.id).where(
                        Market.clob_token_ids.contains([token_id])
                    )
                )
                market = result.scalar_one_or_none()
                if market:
                    logger.debug(f"✅ Found market_id {market} for token_id {token_id[:20]}...")
                return market
        except Exception as e:
            logger.error(f"⚠️ Error getting market_id for token_id {token_id[:20]}...: {e}")
            return None
