"""
Subsquid Market Auto-Categorizer
Automatically categorizes NEW markets in subsquid_markets_poll table
Runs as scheduled job (every 5 minutes) when USE_SUBSQUID_MARKETS=true
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Dict
from sqlalchemy import text

from database import db_manager, SubsquidMarketPoll
from core.services.market_categorizer_service import MarketCategorizerService

logger = logging.getLogger(__name__)


class SubsquidMarketCategorizer:
    """
    Auto-categorize new markets in subsquid_markets_poll
    - Only categorizes markets without existing categories
    - Limits to max_per_cycle (default 20) to avoid OpenAI rate limits
    - Focuses on ACTIVE markets with high volume/liquidity
    """

    def __init__(self, categorizer: MarketCategorizerService = None):
        self.categorizer = categorizer or MarketCategorizerService()
        self.last_run = None

    async def categorize_new_markets(self, max_per_cycle: int = 20) -> Dict[str, int]:
        """
        Categorize uncategorized markets in subsquid_markets_poll

        Args:
            max_per_cycle: Max markets to categorize per run (default 20)

        Returns:
            Dict with stats: {'categorized': N, 'skipped': M, 'errors': K}
        """
        stats = {
            'categorized': 0,
            'skipped': 0,
            'errors': 0
        }

        try:
            logger.info(f"🏷️ [CATEGORIZER] Starting auto-categorization cycle (max {max_per_cycle} markets)...")

            with db_manager.get_session() as db:
                # Get uncategorized ACTIVE markets, sorted by volume + liquidity
                markets = db.query(SubsquidMarketPoll).filter(
                    (SubsquidMarketPoll.category == None) | (SubsquidMarketPoll.category == ''),
                    SubsquidMarketPoll.status == 'ACTIVE',
                    SubsquidMarketPoll.archived == False
                ).order_by(
                    (SubsquidMarketPoll.volume + SubsquidMarketPoll.liquidity).desc()
                ).limit(max_per_cycle).all()

                if not markets:
                    logger.debug("[CATEGORIZER] No uncategorized markets found")
                    return stats

                logger.info(f"📋 [CATEGORIZER] Found {len(markets)} uncategorized markets")

                for market in markets:
                    try:
                        # Categorize using OpenAI
                        question = market.title or ""
                        if not question or len(question.strip()) < 5:
                            stats['skipped'] += 1
                            logger.warning(f"⚠️ [CATEGORIZER] Skipped {market.market_id[:10]}... (empty question)")
                            continue

                        category = await self.categorizer.categorize_market(
                            question=question,
                            existing_category=None
                        )

                        if category:
                            # Update market
                            market.category = category
                            db.commit()

                            stats['categorized'] += 1
                            logger.info(f"✅ [CATEGORIZER] {market.market_id[:10]}... → {category} | '{question[:50]}...'")
                        else:
                            stats['skipped'] += 1
                            logger.warning(f"⚠️ [CATEGORIZER] Could not categorize {market.market_id[:10]}...")

                    except Exception as e:
                        stats['errors'] += 1
                        logger.error(f"❌ [CATEGORIZER] Error for {market.market_id}: {e}")
                        db.rollback()
                        continue

            self.last_run = datetime.now(timezone.utc)
            logger.info(f"✅ [CATEGORIZER] Cycle complete: {stats['categorized']} categorized, {stats['skipped']} skipped, {stats['errors']} errors")

        except Exception as e:
            logger.error(f"❌ [CATEGORIZER] Cycle error: {e}", exc_info=True)
            stats['errors'] += 1

        return stats


# Singleton instance
_subsquid_categorizer = None

def get_subsquid_market_categorizer() -> SubsquidMarketCategorizer:
    """Get or create singleton SubsquidMarketCategorizer"""
    global _subsquid_categorizer
    if _subsquid_categorizer is None:
        _subsquid_categorizer = SubsquidMarketCategorizer()
    return _subsquid_categorizer
