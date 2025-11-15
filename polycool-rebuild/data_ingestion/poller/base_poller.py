"""
Base Poller Class - Shared functionality for all poller types
"""
import asyncio
import httpx
import json
from time import time
from datetime import datetime, timezone
from typing import List, Dict, Optional
from dateutil import parser as date_parser
from infrastructure.config.settings import settings
from infrastructure.logging.logger import get_logger
from sqlalchemy import text

logger = get_logger(__name__)


def json_dumps_safe(obj):
    """Safely convert Python object to JSON string"""
    try:
        return json.dumps(obj) if obj is not None else None
    except Exception:
        return None


def safe_float(value):
    """Safely convert to float"""
    try:
        return float(value) if value is not None else None
    except (ValueError, TypeError):
        return None


def safe_json_parse(value):
    """Safely parse JSON string to Python object"""
    if value is None:
        return None
    if not isinstance(value, str):
        return value  # Already parsed
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        logger.warning(f"Failed to parse JSON: {value}")
        return None

def extract_category(market: Dict) -> Optional[str]:
    """
    Extract category from market data
    Priority: tags > category field > event category
    """
    # Priority 1: Tags (most reliable for categorization)
    tags = market.get('tags', [])
    if tags and isinstance(tags, list):
        for tag in tags:
            if isinstance(tag, dict):
                label = tag.get('label')
                if label and label.lower() not in ['all']:  # Exclude generic tags
                    return str(label)

    # Priority 2: Direct category field (string or object)
    category = market.get('category')
    if isinstance(category, dict):
        category = category.get('label')
    if category:
        return str(category)

    # Priority 3: Event category if market has events
    events = market.get('events', [])
    if events and len(events) > 0:
        event = events[0] if isinstance(events[0], dict) else events[0]
        event_category = event.get('category')
        if isinstance(event_category, dict):
            event_category = event_category.get('label')
        if event_category:
            return str(event_category)

    return None


class BaseGammaAPIPoller:
    """
    Base class for Gamma API pollers
    Provides shared functionality for fetching, parsing, and upserting markets
    """

    def __init__(self, poll_interval: int = 60):
        self.api_url = settings.polymarket.gamma_api_base
        self.poll_interval = poll_interval
        self.running = False
        self.client: Optional[httpx.AsyncClient] = None
        self.max_retries = 3

        # Stats
        self.poll_count = 0
        self.market_count = 0
        self.upsert_count = 0
        self.last_poll_time = None
        self.consecutive_errors = 0

    async def start_polling(self) -> None:
        """Main polling loop"""
        self.running = True
        logger.info(f"📊 {self.__class__.__name__} started (interval: {self.poll_interval}s)")

        while self.running:
            try:
                await self._poll_cycle()
                await asyncio.sleep(self.poll_interval)
            except Exception as e:
                logger.error(f"{self.__class__.__name__} error: {e}")
                self.consecutive_errors += 1
                await asyncio.sleep(min(120, self.poll_interval * 2))  # Backoff on error

    async def stop_polling(self) -> None:
        """Stop the polling service"""
        self.running = False
        if self.client:
            await self.client.aclose()
        logger.info(f"📊 {self.__class__.__name__} stopped")

    def get_stats(self) -> Dict:
        """Get current stats"""
        return {
            'poll_count': self.poll_count,
            'market_count': self.market_count,
            'upsert_count': self.upsert_count,
            'last_poll_time': self.last_poll_time.isoformat() if self.last_poll_time else None,
            'consecutive_errors': self.consecutive_errors
        }

    async def _poll_cycle(self) -> None:
        """Single poll cycle - to be implemented by subclasses"""
        raise NotImplementedError("Subclasses must implement _poll_cycle")

    async def _fetch_api(self, endpoint: str, params: Optional[Dict] = None) -> Optional[Dict]:
        """
        Generic API fetch with retry logic
        - 404 errors are not retried (market doesn't exist) - returns None immediately
        - Other HTTP errors are retried with exponential backoff
        - Network errors/timeouts are retried
        """
        if not self.client:
            self.client = httpx.AsyncClient(timeout=30.0)

        for attempt in range(self.max_retries):
            try:
                response = await self.client.get(
                    f"{self.api_url}{endpoint}",
                    params=params or {}
                )
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as e:
                # 404 means market doesn't exist - don't retry, return None immediately
                if e.response.status_code == 404:
                    # Extract market ID from endpoint for cleaner logging
                    market_id = endpoint.split('/')[-1] if '/' in endpoint else endpoint
                    logger.debug(f"Market {market_id} not found (404) - skipping")
                    return None
                # Other HTTP errors (500, 503, etc.) - retry
                if attempt < self.max_retries - 1:
                    logger.debug(f"API fetch attempt {attempt + 1}/{self.max_retries} failed: {e.response.status_code}")
                    await asyncio.sleep(2 ** attempt)  # Exponential backoff
                else:
                    logger.warning(f"API fetch failed after {self.max_retries} attempts: {e.response.status_code} for {endpoint}")
                    return None
            except httpx.TimeoutException as e:
                # Timeout - retry
                if attempt < self.max_retries - 1:
                    logger.debug(f"API fetch timeout attempt {attempt + 1}/{self.max_retries} for {endpoint}")
                    await asyncio.sleep(2 ** attempt)
                else:
                    logger.warning(f"API fetch timeout after {self.max_retries} attempts: {endpoint}")
                    return None
            except Exception as e:
                # Other errors (network, etc.) - retry
                if attempt < self.max_retries - 1:
                    logger.debug(f"API fetch attempt {attempt + 1}/{self.max_retries} failed: {type(e).__name__}")
                    await asyncio.sleep(2 ** attempt)  # Exponential backoff
                else:
                    logger.warning(f"API fetch failed after {self.max_retries} attempts: {type(e).__name__} for {endpoint}")
                    return None

        return None

    async def _upsert_markets(self, markets: List[Dict], allow_resolved: bool = False) -> int:
        """
        Upsert markets to unified table
        Shared upsert logic for all poller types

        Args:
            markets: List of market dicts
            allow_resolved: If True, allow upserting resolved markets (for resolutions poller)
                           If False, filter out resolved markets (default behavior)
        """
        upserted_count = 0
        from core.database.connection import get_db

        # Filter out resolved markets - we stop polling them once resolved
        # UNLESS allow_resolved=True (for resolutions poller to update resolved status)
        if allow_resolved:
            active_markets = markets
        else:
            active_markets = [m for m in markets if not self._is_market_really_resolved(m)]
            if len(active_markets) < len(markets):
                logger.debug(f"Filtered out {len(markets) - len(active_markets)} resolved markets")

        for market in active_markets:
            try:
                async with get_db() as db_tx:
                    await db_tx.execute(text("""
                        INSERT INTO markets (
                            id, source, title, description, category,
                            outcomes, outcome_prices, events,
                            is_event_market, parent_event_id,
                            volume, liquidity, last_trade_price,
                            clob_token_ids, condition_id,
                            is_resolved, resolved_outcome, resolved_at,
                            start_date, end_date, is_active,
                            event_id, event_slug, event_title, polymarket_url,
                            updated_at
                        ) VALUES (
                            :id, 'poll', :title, :description, :category,
                            :outcomes, :outcome_prices, :events,
                            :is_event_market, :parent_event_id,
                            :volume, :liquidity, :last_trade_price,
                            :clob_token_ids, :condition_id,
                            :is_resolved, :resolved_outcome, :resolved_at,
                            :start_date, :end_date, true,
                            :event_id, :event_slug, :event_title, :polymarket_url,
                            now()
                        )
                        ON CONFLICT (id) DO UPDATE SET
                            title = EXCLUDED.title,
                            description = EXCLUDED.description,
                            category = EXCLUDED.category,
                            outcomes = EXCLUDED.outcomes,
                            -- CRITICAL: Preserve WebSocket prices if source is 'ws' (WebSocket has priority)
                            outcome_prices = CASE
                                WHEN markets.source = 'ws' THEN markets.outcome_prices
                                ELSE EXCLUDED.outcome_prices
                            END,
                            events = EXCLUDED.events,
                            is_event_market = EXCLUDED.is_event_market,
                            parent_event_id = EXCLUDED.parent_event_id,
                            volume = EXCLUDED.volume,
                            liquidity = EXCLUDED.liquidity,
                            -- CRITICAL: Preserve WebSocket last_trade_price if source is 'ws'
                            last_trade_price = CASE
                                WHEN markets.source = 'ws' AND markets.last_trade_price IS NOT NULL
                                THEN markets.last_trade_price
                                ELSE EXCLUDED.last_trade_price
                            END,
                            -- CRITICAL: Only update clob_token_ids if new value is not null (preserve existing)
                            clob_token_ids = CASE
                                WHEN EXCLUDED.clob_token_ids IS NOT NULL
                                    AND EXCLUDED.clob_token_ids != '[]'::jsonb
                                    AND EXCLUDED.clob_token_ids != 'null'::jsonb
                                THEN EXCLUDED.clob_token_ids
                                ELSE markets.clob_token_ids
                            END,
                            -- CRITICAL: Only update condition_id if new value is not null (preserve existing)
                            condition_id = CASE
                                WHEN EXCLUDED.condition_id IS NOT NULL AND EXCLUDED.condition_id != ''
                                THEN EXCLUDED.condition_id
                                ELSE markets.condition_id
                            END,
                            is_resolved = EXCLUDED.is_resolved,
                            resolved_outcome = EXCLUDED.resolved_outcome,
                            resolved_at = EXCLUDED.resolved_at,
                            -- CRITICAL: Update dates (especially end_date for resolution detection)
                            start_date = EXCLUDED.start_date,
                            end_date = EXCLUDED.end_date,
                            is_active = EXCLUDED.is_active,
                            -- CRITICAL: Preserve WebSocket source (ws > poll priority)
                            source = CASE
                                WHEN markets.source = 'ws' THEN 'ws'
                                ELSE 'poll'
                            END,
                            -- CRITICAL: Preserve event_id if new value is NULL (prevents overwriting with NULL)
                            event_id = CASE
                                WHEN EXCLUDED.event_id IS NOT NULL AND EXCLUDED.event_id != ''
                                THEN EXCLUDED.event_id
                                ELSE markets.event_id
                            END,
                            event_slug = EXCLUDED.event_slug,
                            -- CRITICAL: Preserve event_title if new value is NULL or empty
                            event_title = CASE
                                WHEN EXCLUDED.event_title IS NOT NULL AND EXCLUDED.event_title != ''
                                THEN EXCLUDED.event_title
                                ELSE markets.event_title
                            END,
                            polymarket_url = EXCLUDED.polymarket_url,
                            updated_at = now()
                    """), {
                        'id': market.get('id'),
                        'title': market.get('question'),
                        'description': market.get('description'),
                        'category': extract_category(market),
                        'outcomes': json_dumps_safe(safe_json_parse(market.get('outcomes')) or []),
                        'outcome_prices': json_dumps_safe(safe_json_parse(market.get('outcomePrices')) or []),
                        'events': json_dumps_safe(safe_json_parse(market.get('events'))),
                        'is_event_market': market.get('is_event_parent', False),
                        'parent_event_id': market.get('event_id') if market.get('event_id') and not market.get('is_event_parent', False) else None,
                        'volume': safe_float(market.get('volume', 0)),
                        'liquidity': safe_float(market.get('liquidity', 0)),
                        'last_trade_price': safe_float(market.get('lastTradePrice')),
                        'clob_token_ids': json_dumps_safe(safe_json_parse(market.get('clobTokenIds')) if market.get('clobTokenIds') else None),
                        'condition_id': market.get('conditionId'),
                        'is_resolved': self._is_market_really_resolved(market),
                        'resolved_outcome': self._calculate_winner(market) if self._is_market_really_resolved(market) else None,
                        'resolved_at': self._parse_resolution_time(market) if self._is_market_really_resolved(market) else None,
                        'start_date': self._parse_date(market.get('startDate')),
                        'end_date': self._parse_date(market.get('endDate')),
                        'event_id': market.get('event_id'),
                        'event_slug': market.get('event_slug'),
                        'event_title': market.get('event_title'),
                        'polymarket_url': self._build_polymarket_url(market)
                    })
                    upserted_count += 1

            except Exception as e:
                logger.error(f"Failed upsert for market {market.get('id')}: {e}")

        logger.info(f"✅ UPSERT: {upserted_count} markets inserted/updated")
        return upserted_count

    def _is_market_really_resolved(self, market: Dict) -> bool:
        """
        Determine if a market is really resolved
        Multiple strategies with fallbacks for better detection

        Strategies (in priority order):
        1. Explicit resolution: resolvedBy + closedTime + winner
        2. Closed status + expired end_date + stable prices
        3. Expired end_date + stable prices (0.0 or 1.0)
        """
        try:
            # Strategy 1: Explicit resolution (resolvedBy + closedTime + winner)
            if market.get('resolvedBy'):
                resolved_at = self._parse_resolution_time(market)
                if resolved_at and resolved_at <= datetime.now(timezone.utc):
                    winner = self._calculate_winner(market)
                    if winner:
                        return True

            # Strategy 2: Closed status + expired end_date + stable prices
            if market.get('closed') and market.get('endDate'):
                end_date = self._parse_date(market.get('endDate'))
                if end_date and end_date < datetime.now(timezone.utc):
                    # Check if prices indicate resolution (0.0 or 1.0)
                    outcome_prices = safe_json_parse(market.get('outcomePrices')) or []
                    if outcome_prices:
                        try:
                            prices = [float(p) for p in outcome_prices if p is not None]
                            # If any price is 1.0 or all are 0.0, market is likely resolved
                            if prices and (any(p == 1.0 for p in prices) or all(p == 0.0 for p in prices)):
                                return True
                        except (ValueError, TypeError):
                            pass

            # Strategy 3: Expired end_date + stable prices (0.0 or 1.0)
            # This catches markets that resolved but don't have explicit resolution fields
            if market.get('endDate'):
                end_date = self._parse_date(market.get('endDate'))
                if end_date and end_date < datetime.now(timezone.utc):
                    outcome_prices = safe_json_parse(market.get('outcomePrices')) or []
                    if outcome_prices:
                        try:
                            prices = [float(p) for p in outcome_prices if p is not None]
                            # Check if prices are at extremes (resolved)
                            if prices:
                                # All prices 0.0 or any price 1.0 indicates resolution
                                if all(p == 0.0 for p in prices) or any(p == 1.0 for p in prices):
                                    return True
                                # Also check if prices sum to 1.0 (normalized) and one is 1.0
                                if abs(sum(prices) - 1.0) < 0.01 and any(p >= 0.99 for p in prices):
                                    return True
                        except (ValueError, TypeError):
                            pass

            return False
        except Exception as e:
            logger.debug(f"Error checking if market {market.get('id')} is resolved: {e}")
            return False

    def _calculate_winner(self, market: Dict) -> Optional[str]:
        """Calculate winning outcome from prices"""
        try:
            outcomes = safe_json_parse(market.get('outcomes')) or []
            outcome_prices = safe_json_parse(market.get('outcomePrices')) or []

            if not outcomes or not outcome_prices or len(outcomes) != len(outcome_prices):
                return None

            max_price = -1
            winner_idx = -1

            for i, price in enumerate(outcome_prices):
                try:
                    price_val = float(price) if isinstance(price, str) else float(price)
                    if price_val > max_price:
                        max_price = price_val
                        winner_idx = i
                except (ValueError, TypeError):
                    continue

            if winner_idx >= 0 and winner_idx < len(outcomes):
                return str(outcomes[winner_idx])

            return None
        except Exception as e:
            logger.warning(f"Error calculating winner: {e}")
            return None

    def _parse_resolution_time(self, market: Dict) -> Optional[datetime]:
        """Parse resolution timestamp from closedTime"""
        closed_time = market.get('closedTime')
        if not closed_time:
            return None

        try:
            return datetime.fromisoformat(closed_time.replace('Z', '+00:00'))
        except Exception:
            return None

    def _parse_date(self, date_str: Optional[str]) -> Optional[datetime]:
        """Parse date string to naive datetime (UTC) using dateutil.parser"""
        if not date_str:
            return None

        try:
            # Use dateutil.parser which handles various ISO formats (same as old code)
            dt = date_parser.parse(date_str)
            # Convert to UTC and make naive for PostgreSQL
            if dt.tzinfo is not None:
                dt = dt.astimezone(timezone.utc)
            dt = dt.replace(tzinfo=None)
            return dt
        except Exception as e:
            logger.debug(f"Failed to parse date '{date_str}': {e}")
            return None

    def _build_polymarket_url(self, market: Dict) -> Optional[str]:
        """Build Polymarket URL for the market"""
        try:
            event_slug = market.get('event_slug')
            if event_slug:
                return f"https://polymarket.com/event/{event_slug}"

            market_slug = market.get('slug')
            if market_slug:
                return f"https://polymarket.com/market/{market_slug}"

            market_id = market.get('id')
            if market_id:
                return f"https://polymarket.com/market/{market_id}"

            return None
        except Exception as e:
            logger.warning(f"Failed to build Polymarket URL: {e}")
            return None
