"""
Market Fetcher Service - PostgreSQL Version
Fetches markets from Gamma API and stores directly in PostgreSQL
NO JSON file dependencies!
"""

import requests
import logging
from datetime import datetime, timezone
from typing import List, Dict, Optional
from sqlalchemy.dialects.postgresql import insert as pg_insert
from database import db_manager, Market
from config.config import GAMMA_API_URL

logger = logging.getLogger(__name__)


class MarketFetcherService:
    """
    Fetches markets from Gamma API and populates PostgreSQL
    Replaces JSON-based market_database.py
    """

    def __init__(self):
        self.api_url = GAMMA_API_URL
        self.min_volume = 1000  # $1K minimum volume for tradeable markets
        self.min_liquidity = 100  # $100 minimum liquidity
        self.page_size = 100  # Fetch 100 markets per request

    def fetch_and_populate_markets(self, limit: Optional[int] = None) -> Dict:
        """
        Fetch markets from Gamma API with pagination and populate PostgreSQL

        Args:
            limit: Optional limit on number of markets to fetch (for testing)

        Returns:
            Dictionary with statistics about the operation
        """
        try:
            logger.info("🔄 Fetching markets from Gamma API with pagination...")

            # Fetch all markets with pagination
            all_markets = self._fetch_all_markets_paginated(limit)

            logger.info(f"📊 Fetched {len(all_markets)} total markets from Gamma API")

            # Process and save markets
            stats = self._process_and_save_markets(all_markets)

            logger.info(f"✅ Market fetch complete: {stats}")
            return stats

        except requests.RequestException as e:
            logger.error(f"❌ Error fetching from Gamma API: {e}")
            return {'success': False, 'error': str(e)}
        except Exception as e:
            logger.error(f"❌ Unexpected error: {e}")
            return {'success': False, 'error': str(e)}

    def _fetch_all_markets_paginated(self, max_limit: Optional[int] = None) -> List[Dict]:
        """
        Fetch ALL ACTIVE markets using pagination with API filters
        Uses closed=false&archived=false filter to get only active markets

        Args:
            max_limit: Optional maximum number of markets to fetch (for testing)

        Returns:
            List of all active markets
        """
        all_markets = []
        offset = 0
        page = 1

        # API filter for ACTIVE markets only
        filter_params = "closed=false&archived=false"

        logger.info(f"🔄 Fetching ALL ACTIVE markets (using API filter: {filter_params})...")

        while True:
            # Build URL with pagination AND filter
            url = f"{self.api_url}?{filter_params}&limit={self.page_size}&offset={offset}"

            if page == 1 or page % 10 == 0:
                logger.info(f"📄 Fetching page {page} (offset {offset})...")

            try:
                response = requests.get(url, timeout=30)
                response.raise_for_status()
                response_data = response.json()

                # Handle Polymarket API response format: {data: [...], next_cursor: "...", ...}
                if isinstance(response_data, dict) and 'data' in response_data:
                    markets_batch = response_data['data']
                else:
                    # Fallback for direct array format
                    markets_batch = response_data

                # If no markets returned, we're done
                if not markets_batch:
                    logger.info(f"✅ Reached end of results (no more markets)")
                    break

                all_markets.extend(markets_batch)

                # If we got fewer than page_size, we're on the last page
                if len(markets_batch) < self.page_size:
                    logger.info(f"✅ Last page reached at offset {offset} ({len(markets_batch)} markets)")
                    break

                # Check if we've reached the optional limit
                if max_limit and len(all_markets) >= max_limit:
                    all_markets = all_markets[:max_limit]
                    logger.info(f"⚠️ Reached max limit of {max_limit} markets")
                    break

                # Move to next page
                offset += self.page_size
                page += 1

            except requests.RequestException as e:
                logger.error(f"❌ Error fetching page {page}: {e}")
                # Return what we have so far
                break

        logger.info(f"✅ Fetched {len(all_markets)} active markets from Gamma API")
        return all_markets

    def _process_and_save_markets(self, gamma_data: List[Dict]) -> Dict:
        """
        Process Gamma API data and save to PostgreSQL
        Uses UPSERT (INSERT ... ON CONFLICT UPDATE) for efficiency
        """
        active_count = 0
        tradeable_count = 0
        inserted_count = 0
        updated_count = 0

        try:
            with db_manager.get_session() as db:
                for market_data in gamma_data:
                    # Skip inactive/closed/archived markets
                    if not self._is_active_market(market_data):
                        continue

                    active_count += 1

                    # Check if tradeable
                    is_tradeable = self._is_tradeable(market_data)
                    if is_tradeable:
                        tradeable_count += 1

                    # Prepare market object
                    market_dict = self._prepare_market_dict(market_data, is_tradeable)

                    # UPSERT: Insert or update if exists
                    stmt = pg_insert(Market).values(market_dict)
                    stmt = stmt.on_conflict_do_update(
                        index_elements=['id'],
                        set_={
                            'question': stmt.excluded.question,
                            'slug': stmt.excluded.slug,
                            'status': stmt.excluded.status,
                            'volume': stmt.excluded.volume,
                            'liquidity': stmt.excluded.liquidity,
                            'outcomes': stmt.excluded.outcomes,
                            'outcome_prices': stmt.excluded.outcome_prices,
                            'clob_token_ids': stmt.excluded.clob_token_ids,
                            'tokens': stmt.excluded.tokens,
                            'end_date': stmt.excluded.end_date,
                            'last_updated': stmt.excluded.last_updated,
                            'last_fetched': stmt.excluded.last_fetched,
                            'tradeable': stmt.excluded.tradeable,
                            'active': stmt.excluded.active,
                            'closed': stmt.excluded.closed,
                            'accepting_orders': stmt.excluded.accepting_orders,
                            'enable_order_book': stmt.excluded.enable_order_book
                        }
                    )

                    result = db.execute(stmt)

                    # Track if this was insert or update
                    if result.rowcount > 0:
                        # Check if it was an insert (new market)
                        existing = db.query(Market).filter(Market.id == market_dict['id']).first()
                        if existing and existing.created_at == existing.last_updated:
                            inserted_count += 1
                        else:
                            updated_count += 1

                db.commit()

                return {
                    'success': True,
                    'total_processed': len(gamma_data),
                    'active_markets': active_count,
                    'tradeable_markets': tradeable_count,
                    'inserted': inserted_count,
                    'updated': updated_count,
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }

        except Exception as e:
            logger.error(f"❌ Error saving markets to PostgreSQL: {e}")
            return {
                'success': False,
                'error': str(e),
                'active_markets': active_count,
                'tradeable_markets': tradeable_count
            }

    def _is_active_market(self, market: Dict) -> bool:
        """Check if market is active and not closed/archived"""
        return (
            market.get('active', False) and
            not market.get('closed', False) and
            not market.get('archived', False)
        )

    def _is_tradeable(self, market: Dict) -> bool:
        """Determine if market is good for trading"""
        volume = float(market.get('volume', 0))
        liquidity = float(market.get('liquidity', 0))

        return (
            market.get('active', False) and
            market.get('enableOrderBook', False) and
            market.get('acceptingOrders', False) and
            volume >= self.min_volume and
            liquidity >= self.min_liquidity
        )

    def _prepare_market_dict(self, market: Dict, is_tradeable: bool) -> Dict:
        """Prepare market dictionary for PostgreSQL insertion"""
        # Parse end_date if it exists
        end_date = None
        if market.get('endDate'):
            try:
                end_date = datetime.fromisoformat(market['endDate'].replace('Z', '+00:00'))
            except:
                pass

        return {
            'id': market.get('id'),
            'condition_id': market.get('conditionId') or None,  # Convert empty string to NULL for UNIQUE constraint
            'question': market.get('question'),
            'slug': market.get('slug'),
            'status': 'active',  # We only fetch active markets
            'active': market.get('active', False),
            'closed': market.get('closed', False),
            'archived': market.get('archived', False),
            'accepting_orders': market.get('acceptingOrders', False),
            'volume': float(market.get('volume', 0)),
            'liquidity': float(market.get('liquidity', 0)),
            'outcomes': market.get('outcomes', []),
            'outcome_prices': market.get('outcomePrices', []),
            'clob_token_ids': market.get('clobTokenIds', []),
            'tokens': market.get('tokens', []),  # NEW: Store tokens array with outcome matching
            'end_date': end_date,
            'last_updated': datetime.now(timezone.utc),
            'last_fetched': datetime.now(timezone.utc),
            'tradeable': is_tradeable,
            'enable_order_book': market.get('enableOrderBook', False)
        }

    def get_market_stats(self) -> Dict:
        """Get statistics about markets in database"""
        try:
            with db_manager.get_session() as db:
                total = db.query(Market).count()
                active = db.query(Market).filter(Market.active == True).count()
                tradeable = db.query(Market).filter(Market.tradeable == True).count()

                return {
                    'total_markets': total,
                    'active_markets': active,
                    'tradeable_markets': tradeable,
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }
        except Exception as e:
            logger.error(f"❌ Error getting market stats: {e}")
            return {'error': str(e)}

    def cleanup_expired_markets(self) -> int:
        """Remove markets that have ended"""
        try:
            with db_manager.get_session() as db:
                now = datetime.now(timezone.utc)

                # Mark expired markets as closed
                expired = db.query(Market).filter(
                    Market.end_date < now,
                    Market.status == 'active'
                ).all()

                count = 0
                for market in expired:
                    market.status = 'trading_closed'
                    market.closed = True
                    market.active = False
                    count += 1

                db.commit()

                if count > 0:
                    logger.info(f"🗑️ Marked {count} expired markets as closed")

                return count

        except Exception as e:
            logger.error(f"❌ Error cleaning up expired markets: {e}")
            return 0


# Global market fetcher service instance
market_fetcher = MarketFetcherService()


# Convenience functions for backward compatibility
def fetch_and_populate_markets(limit: Optional[int] = None) -> Dict:
    """Fetch markets from API and populate PostgreSQL"""
    return market_fetcher.fetch_and_populate_markets(limit)


def get_market_stats() -> Dict:
    """Get market statistics"""
    return market_fetcher.get_market_stats()


def cleanup_expired_markets() -> int:
    """Clean up expired markets"""
    return market_fetcher.cleanup_expired_markets()
