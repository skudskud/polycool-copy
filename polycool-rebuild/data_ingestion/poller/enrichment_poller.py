"""
Enrichment Poller - Enriches markets with missing condition_id and clob_token_ids
Fetches individual market details to fill missing fields
"""
import asyncio
from time import time
from datetime import datetime, timezone
from typing import List, Dict
from infrastructure.logging.logger import get_logger
from data_ingestion.poller.base_poller import BaseGammaAPIPoller
from core.database.connection import get_db
from sqlalchemy import text

logger = get_logger(__name__)


class EnrichmentPoller(BaseGammaAPIPoller):
    """
    Poller to enrich markets with missing condition_id and clob_token_ids
    - Finds active markets without these fields
    - Fetches /markets/{id} individually to get complete data
    - Updates only missing fields (preserves existing data)
    - Frequency: 1h
    """

    def __init__(self, interval: int = 3600):  # 1h default
        super().__init__(poll_interval=interval)

    async def _poll_cycle(self) -> None:
        """Single poll cycle - enrich markets with missing data"""
        start_time = time()

        try:
            # 1. Get markets missing condition_id or clob_token_ids
            incomplete_markets = await self._get_incomplete_markets()

            if not incomplete_markets:
                logger.debug("No markets need enrichment")
                return

            logger.info(f"📋 Found {len(incomplete_markets)} markets needing enrichment")

            # 2. Fetch complete data for each market
            enriched_count = 0
            for market_id in incomplete_markets[:200]:  # Limit to 200 per cycle
                try:
                    # Fetch full market details
                    market_data = await self._fetch_api(f"/markets/{market_id}")

                    if not market_data:
                        continue

                    # 3. Update only missing fields
                    updated = await self._enrich_market(market_id, market_data)
                    if updated:
                        enriched_count += 1

                    # Rate limiting
                    await asyncio.sleep(0.2)  # 200ms delay

                except Exception as e:
                    logger.debug(f"Failed to enrich market {market_id}: {e}")
                    continue

            # 4. Update stats
            self.poll_count += 1
            self.market_count = len(incomplete_markets)
            self.upsert_count = enriched_count
            self.last_poll_time = datetime.now(timezone.utc)
            self.consecutive_errors = 0

            duration = time() - start_time
            logger.info(f"✅ Enrichment cycle completed in {duration:.2f}s - {enriched_count}/{len(incomplete_markets)} markets enriched")

        except Exception as e:
            logger.error(f"Enrichment poll cycle error: {e}")
            raise

    async def _get_incomplete_markets(self) -> List[str]:
        """Get market IDs missing condition_id or clob_token_ids"""
        try:
            async with get_db() as db:
                result = await db.execute(text("""
                    SELECT id
                    FROM markets
                    WHERE is_resolved = false
                    AND (
                        condition_id IS NULL
                        OR condition_id = ''
                        OR clob_token_ids IS NULL
                        OR clob_token_ids = '[]'::jsonb
                        OR clob_token_ids = 'null'::jsonb
                    )
                    ORDER BY updated_at DESC
                    LIMIT 500
                """))
                rows = result.fetchall()
                market_ids = [str(row[0]) for row in rows]
                return market_ids
        except Exception as e:
            logger.error(f"Error getting incomplete markets: {e}")
            return []

    async def _enrich_market(self, market_id: str, market_data: Dict) -> bool:
        """Enrich a single market with missing fields"""
        try:
            import json
            from data_ingestion.poller.base_poller import safe_json_parse

            condition_id = market_data.get('conditionId')
            clob_token_ids = market_data.get('clobTokenIds')

            # Check if we have new data to update
            if not condition_id and not clob_token_ids:
                return False

            async with get_db() as db:
                # Update only missing fields (preserve existing if new is NULL)
                # Prepare clob_token_ids as JSON string
                clob_tokens_json = None
                if clob_token_ids:
                    parsed = safe_json_parse(clob_token_ids) if isinstance(clob_token_ids, str) else clob_token_ids
                    if parsed:
                        clob_tokens_json = json.dumps(parsed)

                await db.execute(text("""
                    UPDATE markets
                    SET
                        condition_id = CASE
                            WHEN :condition_id IS NOT NULL AND :condition_id != ''
                            THEN :condition_id
                            ELSE condition_id
                        END,
                        clob_token_ids = CASE
                            WHEN :clob_token_ids IS NOT NULL AND :clob_token_ids != '[]' AND :clob_token_ids != 'null'
                            THEN :clob_token_ids::jsonb
                            ELSE clob_token_ids
                        END,
                        updated_at = now()
                    WHERE id = :market_id
                """), {
                    'market_id': market_id,
                    'condition_id': condition_id,
                    'clob_token_ids': clob_tokens_json
                })

                return True

        except Exception as e:
            logger.error(f"Failed to enrich market {market_id}: {e}")
            return False
