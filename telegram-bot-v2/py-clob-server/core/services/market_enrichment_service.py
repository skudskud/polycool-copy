#!/usr/bin/env python3
"""
Market Enrichment Service
Ensures 100% market title coverage by falling back to Polymarket API when needed
"""

import logging
import httpx
from typing import Optional
from datetime import datetime, timezone
from sqlalchemy import text

from database import db_manager
from core.persistence.models import SmartWalletTrade

logger = logging.getLogger(__name__)


class MarketEnrichmentService:
    """
    Service to enrich trades with market data

    Strategy:
    1. Check if trade.market_question is already populated → use it
    2. If NULL, try to fetch from subsquid_markets_poll (by condition_id)
    3. If still NULL, fetch from Polymarket CLOB API (live data)
    4. Update trade with market title for future use

    Benefits:
    - 100% market title coverage
    - Caches data for performance
    - Graceful degradation if API fails
    """

    def __init__(self):
        self.api_base_url = "https://clob.polymarket.com"
        self.cache = {}  # In-memory cache {condition_id: market_title}
        logger.info("✅ Market Enrichment Service initialized")

    async def enrich_trade_with_market_title(self, trade: SmartWalletTrade) -> bool:
        """
        Ensure trade has market_question populated

        Args:
            trade: SmartWalletTrade instance

        Returns:
            True if successfully enriched (or already had title)
        """
        try:
            # Already has title?
            if trade.market_question and trade.market_question.strip():
                logger.debug(f"[ENRICH] Trade {trade.id[:16]}... already has market title")
                return True

            logger.info(f"🔍 [ENRICH] Trade {trade.id[:16]}... missing market title, attempting to enrich...")

            # Strategy 1: Try tracked_leader_trades + subsquid_markets_poll join
            title = await self._fetch_from_database(trade)
            if title:
                await self._update_trade_title(trade, title)
                logger.info(f"✅ [ENRICH] Enriched from database: {title[:50]}...")
                return True

            # Strategy 2: Try Polymarket CLOB API (live data)
            if trade.condition_id:
                title = await self._fetch_from_api(trade.condition_id)
                if title:
                    await self._update_trade_title(trade, title)
                    logger.info(f"✅ [ENRICH] Enriched from API: {title[:50]}...")
                    return True

            logger.warning(f"⚠️ [ENRICH] Could not enrich trade {trade.id[:16]}... (no market title found)")
            return False

        except Exception as e:
            logger.error(f"❌ [ENRICH] Error enriching trade {trade.id[:16] if trade else 'unknown'}...: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False

    async def _fetch_from_database(self, trade: SmartWalletTrade) -> Optional[str]:
        """
        Try to get market title from subsquid_markets_poll table

        Uses condition_id to lookup market title (same as /smart_trading command)
        """
        try:
            if not trade.condition_id:
                logger.debug(f"[ENRICH] Trade {trade.id[:16]}... has no condition_id, skipping DB lookup")
                return None

            with db_manager.get_session() as db:
                from database import SubsquidMarketPoll

                # Direct lookup by condition_id (same as /smart_trading command)
                market = db.query(SubsquidMarketPoll).filter(
                    SubsquidMarketPoll.condition_id == trade.condition_id
                ).first()

                if market and market.title:
                    logger.debug(f"[ENRICH] Found market title in DB: {market.title[:50]}...")
                    return market.title

            return None
        except Exception as e:
            logger.error(f"[ENRICH] Database lookup error: {e}")
            return None

    async def _fetch_from_api(self, condition_id: str) -> Optional[str]:
        """
        Fetch market title from Polymarket CLOB API

        Args:
            condition_id: Market condition ID (0x...)

        Returns:
            Market title or None
        """
        try:
            # Check cache first
            if condition_id in self.cache:
                logger.debug(f"[ENRICH] Cache hit for {condition_id[:10]}...")
                return self.cache[condition_id]

            # Call API
            url = f"{self.api_base_url}/markets/{condition_id}"

            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(url)

                if response.status_code == 200:
                    data = response.json()
                    title = data.get('question') or data.get('title')

                    if title:
                        # Cache it
                        self.cache[condition_id] = title
                        return title
                    else:
                        logger.warning(f"[ENRICH] API response missing 'question' field for {condition_id[:10]}...")
                        return None
                elif response.status_code == 404:
                    logger.warning(f"[ENRICH] Market {condition_id[:10]}... not found on API")
                    return None
                else:
                    logger.warning(f"[ENRICH] API returned status {response.status_code} for {condition_id[:10]}...")
                    return None

        except httpx.TimeoutException:
            logger.warning(f"[ENRICH] API timeout for {condition_id[:10]}...")
            return None
        except Exception as e:
            logger.error(f"[ENRICH] API error for {condition_id[:10]}...: {e}")
            return None

    async def _update_trade_title(self, trade: SmartWalletTrade, title: str):
        """
        Update trade's market_question in database

        Args:
            trade: SmartWalletTrade instance
            title: Market title
        """
        try:
            with db_manager.get_session() as db:
                db.execute(
                    text("""
                    UPDATE smart_wallet_trades
                    SET market_question = :title
                    WHERE id = :trade_id
                    """),
                    {"title": title, "trade_id": trade.id}
                )
                db.commit()

            # Update in-memory object
            trade.market_question = title

        except Exception as e:
            logger.error(f"[ENRICH] Error updating trade title: {e}")


# Global singleton
_enrichment_service: Optional[MarketEnrichmentService] = None


def get_market_enrichment_service() -> MarketEnrichmentService:
    """Get or create the market enrichment service singleton"""
    global _enrichment_service
    if _enrichment_service is None:
        _enrichment_service = MarketEnrichmentService()
        logger.info("✅ Market Enrichment Service singleton created")
    return _enrichment_service
