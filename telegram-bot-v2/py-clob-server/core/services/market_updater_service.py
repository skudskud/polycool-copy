"""
Market Updater Service
Fetches markets from Gamma API and updates PostgreSQL database every 60 seconds
"""

import logging
import requests
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
from .market_categorizer_service import MarketCategorizerService

logger = logging.getLogger(__name__)

# Reduce external logging noise (Railway rate limit)
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('urllib3').setLevel(logging.WARNING)
logging.getLogger('asyncio').setLevel(logging.WARNING)


class MarketUpdaterService:
    """
    Fetches markets from Gamma API and updates PostgreSQL
    Runs every 60 seconds via scheduler
    """

    def __init__(self, market_repository, gamma_api_url: str, categorizer: Optional[MarketCategorizerService] = None):
        self.repository = market_repository
        self.gamma_api_url = gamma_api_url
        self.categorizer = categorizer or MarketCategorizerService()
        self.last_update = None
        self.last_stats = {}
        self.consecutive_errors = 0
        self.MAX_RETRIES = 3

        logger.info("✅ Market Updater Service initialized")

    # ========================================
    # MAIN UPDATE CYCLE
    # ========================================

    async def run_high_priority_update_cycle(self) -> Dict[str, int]:
        """
        High priority update - runs every 5 minutes

        Fetches 20 pages (~2,000 markets) to capture ALL new markets
        Updates top 500 markets + all their complete events

        Returns statistics: {'new': X, 'updated': Y, 'resolved': Z, 'finished': W}
        """
        start_time = datetime.utcnow()
        stats = {
            'new': 0,
            'updated': 0,
            'resolved': 0,
            'finished': 0,
            'errors': 0,
            'total_processed': 0,
            'priority': 'high'
        }

        try:
            logger.info(f"🔥 {start_time.strftime('%H:%M:%S')} - HIGH PRIORITY update from Events API...")

            # 1. Fetch 20 pages of events (~2,000 markets to catch ALL new ones)
            events = await self.fetch_events_from_gamma(max_pages=20)
            gamma_markets = self.extract_markets_from_events(events)

            if not gamma_markets:
                logger.warning("⚠️ No markets fetched from Gamma API")
                return stats

            logger.info(f"📊 Fetched {len(gamma_markets)} markets, sorting by priority...")

            # 2. Sort by priority score (volume + liquidity)
            sorted_markets = sorted(
                gamma_markets,
                key=lambda m: self.calculate_priority_score(m),
                reverse=True
            )

            # 3. Smart selection: Take top 500 markets + ALL markets from their events
            # This ensures complete event coverage (e.g., Poker event with 104 outcomes)
            top_count = min(500, len(sorted_markets))
            top_markets_initial = sorted_markets[:top_count]

            # Get all event_ids from top markets
            event_ids_in_top = set()
            for market in top_markets_initial:
                event_id = market.get('event_id')
                if event_id:
                    event_ids_in_top.add(str(event_id))

            # Now include ALL markets from these events (complete event coverage)
            top_markets = []
            included_ids = set()

            for market in gamma_markets:
                market_id = str(market.get('id', ''))
                event_id = str(market.get('event_id', ''))

                # Include if:
                # 1. In top 500 individually, OR
                # 2. Part of an event that has a top 500 market
                if market_id in [str(m.get('id', '')) for m in top_markets_initial]:
                    if market_id not in included_ids:
                        top_markets.append(market)
                        included_ids.add(market_id)
                elif event_id in event_ids_in_top:
                    if market_id not in included_ids:
                        top_markets.append(market)
                        included_ids.add(market_id)

            logger.info(f"🎯 Updating {len(top_markets)} markets (top 500 + complete events from {len(event_ids_in_top)} events)")

            # 4. Process high-priority markets (OPTIMIZED - batch queries)
            markets_to_upsert = []
            categorized_count = 0
            max_categorizations_per_cycle = 20  # Limit to avoid performance hit

            # OPTIMIZATION 1: Batch check existing markets (1 query instead of 777)
            market_ids = [str(m.get('id')) for m in top_markets]
            existing_ids = self.repository.get_existing_ids(market_ids)
            logger.info(f"📊 Batch check: {len(existing_ids)} existing, {len(market_ids) - len(existing_ids)} new")

            for gamma_market in top_markets:
                try:
                    db_market_data = self.transform_gamma_to_db(gamma_market)
                    market_id = db_market_data['id']
                    is_existing = market_id in existing_ids

                    # NEW: Auto-categorize NEW markets only (limit to 20 per cycle)
                    if not is_existing and categorized_count < max_categorizations_per_cycle:
                        if not db_market_data.get('category'):
                            try:
                                question = db_market_data.get('question', '')
                                category = await self.categorizer.categorize_market(question)
                                if category:
                                    db_market_data['category'] = category
                                    categorized_count += 1
                                    logger.info(f"✅ Auto-categorized new market {market_id[:10]}... → {category}")
                            except Exception as cat_error:
                                logger.warning(f"⚠️ Categorization failed for {market_id[:10]}...: {cat_error}")
                                # Continue without category - not critical

                    # Detect resolution
                    resolved_at, winner = self.detect_resolution(gamma_market)
                    if resolved_at:
                        db_market_data['resolved_at'] = resolved_at
                        db_market_data['winner'] = winner
                        if not is_existing:
                            stats['resolved'] += 1

                    # Check if finished
                    if self.check_if_finished(db_market_data.get('end_date')):
                        db_market_data['closed'] = True
                        db_market_data['active'] = False
                        if is_existing:
                            stats['finished'] += 1

                    markets_to_upsert.append(db_market_data)
                    stats['total_processed'] += 1

                    if not is_existing:
                        stats['new'] += 1
                    else:
                        stats['updated'] += 1

                except Exception as e:
                    stats['errors'] += 1
                    logger.error(f"Error processing market {gamma_market.get('id')}: {e}")

            # 5. Bulk upsert
            if markets_to_upsert:
                try:
                    self.repository.bulk_upsert(markets_to_upsert)
                    logger.info(f"✅ HIGH PRIORITY: {stats['new']} new, {stats['updated']} updated, {categorized_count} auto-categorized")
                except Exception as e:
                    logger.error(f"❌ Bulk upsert failed: {e}")
                    stats['errors'] += 1

            self.last_update = datetime.utcnow()
            self.last_stats = stats
            self.consecutive_errors = 0

            duration = (datetime.utcnow() - start_time).total_seconds()
            logger.info(f"⏱️ HIGH PRIORITY cycle completed in {duration:.2f}s")

            return stats

        except Exception as e:
            logger.error(f"❌ HIGH PRIORITY cycle failed: {e}")
            self.consecutive_errors += 1
            stats['errors'] += 1
            return stats

    async def run_low_priority_update_cycle(self) -> Dict[str, int]:
        """
        Low priority update - runs every hour

        Updates ALL markets with full pagination
        Takes ~50 seconds but runs hourly so no user impact

        Returns statistics: {'new': X, 'updated': Y, 'resolved': Z, 'finished': W}
        """
        start_time = datetime.utcnow()
        stats = {
            'new': 0,
            'updated': 0,
            'resolved': 0,
            'finished': 0,
            'errors': 0,
            'total_processed': 0,
            'priority': 'low'
        }

        try:
            logger.info(f"🌐 {start_time.strftime('%H:%M:%S')} - LOW PRIORITY (full update) from Events API...")

            # 1. Fetch ALL events with full pagination
            events = await self.fetch_events_from_gamma(max_pages=None)
            gamma_markets = self.extract_markets_from_events(events)

            if not gamma_markets:
                logger.warning("⚠️ No markets fetched from Gamma API")
                return stats

            logger.info(f"📊 Fetched {len(gamma_markets)} markets for full update")

            # 2. Process ALL markets (OPTIMIZED - batch queries)
            markets_to_upsert = []

            # OPTIMIZATION 1: Batch check existing markets (1 query instead of thousands)
            market_ids = [str(m.get('id')) for m in gamma_markets]
            existing_ids = self.repository.get_existing_ids(market_ids)
            logger.info(f"📊 Batch check: {len(existing_ids)} existing, {len(market_ids) - len(existing_ids)} new")

            for gamma_market in gamma_markets:
                try:
                    db_market_data = self.transform_gamma_to_db(gamma_market)
                    market_id = db_market_data['id']
                    is_existing = market_id in existing_ids

                    # OPTIMIZATION 2: Skip AI categorization even for new markets in low-priority
                    # (Use backfill endpoint instead to avoid blocking)
                    # This saves potentially hours of API calls!

                    # Detect resolution
                    resolved_at, winner = self.detect_resolution(gamma_market)
                    if resolved_at:
                        db_market_data['resolved_at'] = resolved_at
                        db_market_data['winner'] = winner
                        if not is_existing:
                            stats['resolved'] += 1

                    # Check if finished
                    if self.check_if_finished(db_market_data.get('end_date')):
                        db_market_data['closed'] = True
                        db_market_data['active'] = False
                        if is_existing:
                            stats['finished'] += 1

                    markets_to_upsert.append(db_market_data)
                    stats['total_processed'] += 1

                    if not is_existing:
                        stats['new'] += 1
                    else:
                        stats['updated'] += 1

                except Exception as e:
                    stats['errors'] += 1
                    logger.error(f"Error processing market {gamma_market.get('id')}: {e}")

            # 3. Bulk upsert
            if markets_to_upsert:
                try:
                    self.repository.bulk_upsert(markets_to_upsert)
                    logger.info(f"✅ LOW PRIORITY: {stats['new']} new, {stats['updated']} updated, {stats['resolved']} resolved")
                except Exception as e:
                    logger.error(f"❌ Bulk upsert failed: {e}")
                    stats['errors'] += 1

            self.last_update = datetime.utcnow()
            self.last_stats = stats
            self.consecutive_errors = 0

            duration = (datetime.utcnow() - start_time).total_seconds()
            logger.info(f"⏱️ LOW PRIORITY cycle completed in {duration:.2f}s")

            return stats

        except Exception as e:
            logger.error(f"❌ LOW PRIORITY cycle failed: {e}")
            self.consecutive_errors += 1
            stats['errors'] += 1
            return stats

    async def run_update_cycle(self) -> Dict[str, int]:
        """
        Wrapper for backwards compatibility (used by force_update endpoint)
        Calls high priority update by default
        """
        return await self.run_high_priority_update_cycle()

    # ========================================
    # GAMMA API INTEGRATION
    # ========================================

    async def fetch_events_from_gamma(self, max_pages: Optional[int] = None) -> List[Dict]:
        """
        Fetch events from Gamma Events API with pagination

        Events contain multiple markets grouped together (e.g., Win/Draw/Win)

        Args:
            max_pages: Maximum number of pages to fetch (None = fetch all)

        Returns: List of event dictionaries with embedded markets
        """
        all_events = []
        offset = 0
        limit = 100  # Events API recommended limit
        page = 1

        # Use Events endpoint instead of Markets
        # Ensure we build the correct URL (gamma_api_url might not have /markets)
        if '/markets' in self.gamma_api_url:
            base_url = self.gamma_api_url.replace('/markets', '/events')
        else:
            base_url = f"{self.gamma_api_url.rstrip('/')}/events"

        while True:
            # Check if we've reached max_pages limit
            if max_pages and page > max_pages:
                logger.info(f"📚 Events: Reached max_pages limit: {len(all_events)} events across {page-1} pages")
                return all_events

            for attempt in range(self.MAX_RETRIES):
                try:
                    # Fetch events with markets included
                    # Sort by volume to get most popular events first
                    url = f"{base_url}?closed=false&order=volume&ascending=false&limit={limit}&offset={offset}"
                    response = requests.get(url, timeout=30)
                    response.raise_for_status()

                    events = response.json()

                    if not isinstance(events, list):
                        logger.error(f"Unexpected response format: {type(events)}")
                        return all_events

                    # If no events returned, we've reached the end
                    if not events:
                        logger.info(f"📚 Events: Pagination complete: {len(all_events)} total events across {page-1} pages")
                        return all_events

                    # Add events to collection
                    all_events.extend(events)

                    logger.debug(f"📄 Events: Page {page} fetched: {len(events)} events (total: {len(all_events)})")

                    # If less than limit returned, we've reached the end
                    if len(events) < limit:
                        logger.info(f"📚 Events: Last page reached: {len(all_events)} total events across {page} pages")
                        return all_events

                    # Move to next page
                    offset += limit
                    page += 1
                    break  # Success, exit retry loop

                except requests.exceptions.RequestException as e:
                    if attempt < self.MAX_RETRIES - 1:
                        logger.warning(f"⚠️ Events API request failed (attempt {attempt + 1}/{self.MAX_RETRIES}): {e}")
                        continue
                    else:
                        logger.error(f"❌ Events API request failed after {self.MAX_RETRIES} attempts: {e}")
                        return all_events
                except Exception as e:
                    logger.error(f"❌ Unexpected error fetching events: {e}")
                    return all_events

        return all_events

    def extract_markets_from_events(self, events: List[Dict]) -> List[Dict]:
        """
        Extract all markets from events and add event metadata

        Args:
            events: List of event dictionaries from Gamma API

        Returns: List of market dictionaries with event_id, event_slug, event_title added
        """
        all_markets = []

        for event in events:
            event_id = str(event.get('id', ''))
            event_slug = event.get('slug', '')
            event_title = event.get('title', '')

            # Extract markets from event
            markets = event.get('markets', [])

            for market in markets:
                # Add event metadata to each market
                market['event_id'] = event_id
                market['event_slug'] = event_slug
                market['event_title'] = event_title

                all_markets.append(market)

        logger.info(f"📦 Extracted {len(all_markets)} markets from {len(events)} events")
        return all_markets

    def calculate_priority_score(self, market: Dict) -> float:
        """
        Calculate priority score based on volume and liquidity

        Score = (volume + liquidity) / 2
        Higher score = higher priority for real-time updates
        """
        try:
            volume = float(market.get('volume', 0))
            liquidity = float(market.get('liquidity', 0))
            return (volume + liquidity) / 2
        except Exception:
            return 0.0

    async def fetch_markets_from_gamma(self, max_pages: Optional[int] = None) -> List[Dict]:
        """
        Fetch markets from Gamma API with pagination

        Args:
            max_pages: Maximum number of pages to fetch (None = fetch all)

        Gamma API limits responses to 500 markets per request.
        This method fetches pages until complete or max_pages reached.

        Returns: List of market dictionaries from Gamma API
        """
        all_markets = []
        offset = 0
        limit = 500  # Gamma API's max per request
        page = 1

        while True:
            # Check if we've reached max_pages limit
            if max_pages and page > max_pages:
                logger.info(f"📚 Reached max_pages limit: {len(all_markets)} markets across {page-1} pages")
                return all_markets

            for attempt in range(self.MAX_RETRIES):
                try:
                    # Fetch one page of markets - sorted by ID descending (newest first)
                    # Using closed=false per Polymarket API best practices
                    url = f"{self.gamma_api_url}?closed=false&order=id&ascending=false&limit={limit}&offset={offset}"
                    response = requests.get(url, timeout=30)
                    response.raise_for_status()

                    markets = response.json()

                    if not isinstance(markets, list):
                        logger.error(f"Unexpected response format: {type(markets)}")
                        return all_markets

                    # If no markets returned, we've reached the end
                    if not markets:
                        logger.info(f"📚 Pagination complete: {len(all_markets)} total markets across {page-1} pages")
                        return all_markets

                    # Add this page's markets to our collection
                    all_markets.extend(markets)

                    # If we got less than the limit, we're done
                    if len(markets) < limit:
                        logger.info(f"📚 Pagination complete: {len(all_markets)} total markets across {page} pages")
                        return all_markets

                    # Move to next page
                    offset += limit
                    page += 1
                    break  # Success, move to next page

                except requests.Timeout:
                    logger.warning(f"⏱️ Gamma API timeout on page {page} (attempt {attempt + 1}/{self.MAX_RETRIES})")
                    if attempt < self.MAX_RETRIES - 1:
                        import asyncio
                        await asyncio.sleep(2 ** attempt)  # Exponential backoff
                    else:
                        logger.error(f"❌ Gamma API timeout after all retries on page {page}")
                        return all_markets  # Return what we got so far

                except requests.RequestException as e:
                    logger.error(f"❌ Gamma API request failed on page {page}: {e}")
                    return all_markets  # Return what we got so far

        return all_markets

    # ========================================
    # DATA TRANSFORMATION
    # ========================================

    def transform_gamma_to_db(self, gamma_market: Dict) -> Dict:
        """
        Transform Gamma API format to PostgreSQL format
        ENHANCED: Now captures ALL Gamma API fields for parent/child markets, categories, and rich metadata

        Gamma API → PostgreSQL field mapping
        """
        try:
            # Helper function to safely parse dates
            def parse_date(date_str):
                if not date_str:
                    return None
                try:
                    return datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                except Exception as e:
                    logger.warning(f"Failed to parse date '{date_str}': {e}")
                    return None

            # Helper function to safely convert to float
            def safe_float(value):
                try:
                    return float(value) if value is not None else None
                except (ValueError, TypeError):
                    return None

            # Helper function to safely convert to int
            def safe_int(value):
                try:
                    return int(value) if value is not None else None
                except (ValueError, TypeError):
                    return None

            # Parse dates
            end_date = parse_date(gamma_market.get('endDate'))
            start_date = parse_date(gamma_market.get('startDate'))
            created_at = parse_date(gamma_market.get('createdAt'))
            game_start_time = parse_date(gamma_market.get('gameStartTime'))

            # Calculate if tradeable
            tradeable = self._is_tradeable(gamma_market)

            # Build COMPLETE database format with ALL fields
            db_market = {
                # ========================================
                # PRIMARY IDENTIFIERS
                # ========================================
                'id': str(gamma_market.get('id', '')),
                'condition_id': gamma_market.get('conditionId') or None,  # Convert empty string to NULL for UNIQUE constraint
                'question': gamma_market.get('question', 'Unknown'),
                'slug': gamma_market.get('slug'),
                'question_id': gamma_market.get('questionID'),

                # ========================================
                # EVENT GROUPING (Polymarket Events API)
                # ========================================
                'event_id': gamma_market.get('event_id'),  # Added by extract_markets_from_events()
                'event_slug': gamma_market.get('event_slug'),
                'event_title': gamma_market.get('event_title'),

                # Legacy grouping fields (kept for backward compatibility)
                'market_group': safe_int(gamma_market.get('marketGroup')),
                'group_item_title': gamma_market.get('groupItemTitle'),
                'group_item_threshold': gamma_market.get('groupItemThreshold'),
                'group_item_range': gamma_market.get('groupItemRange'),

                # ========================================
                # CATEGORIZATION & ORGANIZATION
                # ========================================
                'category': gamma_market.get('category'),  # Will be enhanced with AI if missing
                'tags': gamma_market.get('tags'),  # JSONB array
                'events': gamma_market.get('events'),  # JSONB array

                # ========================================
                # VISUAL & RICH CONTENT
                # ========================================
                'image': gamma_market.get('image'),
                'icon': gamma_market.get('icon'),
                'description': gamma_market.get('description'),
                'twitter_card_image': gamma_market.get('twitterCardImage'),

                # ========================================
                # MARKET CLASSIFICATION
                # ========================================
                'market_type': gamma_market.get('marketType'),
                'format_type': gamma_market.get('formatType'),
                'featured': gamma_market.get('featured', False),
                'new': gamma_market.get('new', False),

                # ========================================
                # MARKET STATUS
                # ========================================
                'status': 'active' if gamma_market.get('active') else 'closed',
                'active': gamma_market.get('active', False),
                'closed': gamma_market.get('closed', False),
                'archived': gamma_market.get('archived', False),
                'accepting_orders': gamma_market.get('acceptingOrders', True),
                'restricted': gamma_market.get('restricted', False),

                # ========================================
                # RESOLUTION DATA
                # ========================================
                'resolution_source': gamma_market.get('resolutionSource'),
                'resolved_by': gamma_market.get('resolvedBy'),

                # ========================================
                # TRADING DATA - BASE
                # ========================================
                'volume': safe_float(gamma_market.get('volume')) or 0,
                'liquidity': safe_float(gamma_market.get('liquidity')) or 0,
                'outcomes': gamma_market.get('outcomes', []),
                'outcome_prices': gamma_market.get('outcomePrices', []),
                'clob_token_ids': gamma_market.get('clobTokenIds', []),
                
                # NOTE: 'tokens' field not added yet - need database migration first
                # Will add in future update after column is created

                # ========================================
                # TRADING DATA - VOLUME BREAKDOWN
                # ========================================
                'volume_24hr': safe_float(gamma_market.get('volume24hr')),
                'volume_1wk': safe_float(gamma_market.get('volume1wk')),
                'volume_1mo': safe_float(gamma_market.get('volume1mo')),
                'volume_1yr': safe_float(gamma_market.get('volume1yr')),

                # ========================================
                # PRICE MOVEMENT & TRENDING
                # ========================================
                'one_hour_price_change': safe_float(gamma_market.get('oneHourPriceChange')),
                'one_day_price_change': safe_float(gamma_market.get('oneDayPriceChange')),
                'one_week_price_change': safe_float(gamma_market.get('oneWeekPriceChange')),
                'one_month_price_change': safe_float(gamma_market.get('oneMonthPriceChange')),
                'one_year_price_change': safe_float(gamma_market.get('oneYearPriceChange')),

                # ========================================
                # CURRENT MARKET STATE
                # ========================================
                'last_trade_price': safe_float(gamma_market.get('lastTradePrice')),
                'best_bid': safe_float(gamma_market.get('bestBid')),
                'best_ask': safe_float(gamma_market.get('bestAsk')),
                'spread': safe_float(gamma_market.get('spread')),

                # ========================================
                # COMPETITION & REWARDS
                # ========================================
                'competitive': safe_float(gamma_market.get('competitive')),
                'rewards_min_size': safe_float(gamma_market.get('rewardsMinSize')),
                'rewards_max_spread': safe_float(gamma_market.get('rewardsMaxSpread')),

                # ========================================
                # SPORTS MARKETS
                # ========================================
                'game_id': gamma_market.get('gameId'),
                'game_start_time': game_start_time,
                'sports_market_type': gamma_market.get('sportsMarketType'),

                # ========================================
                # DATES
                # ========================================
                'created_at': created_at,
                'end_date': end_date,
                'start_date': start_date,
                'last_fetched': datetime.utcnow(),

                # ========================================
                # TRADING ELIGIBILITY
                # ========================================
                'tradeable': tradeable,
                'enable_order_book': gamma_market.get('enableOrderBook', False)
            }

            return db_market

        except Exception as e:
            logger.error(f"Error transforming market {gamma_market.get('id')}: {e}")
            raise

    def _is_tradeable(self, market: Dict) -> bool:
        """
        Determine if market is good for trading

        Criteria:
        - Active and accepting orders
        - Order book enabled
        - Minimum volume: $1,000
        - Minimum liquidity: $100
        """
        try:
            volume = float(market.get('volume', 0))
            liquidity = float(market.get('liquidity', 0))

            return (
                market.get('active', False) and
                market.get('enableOrderBook', False) and
                market.get('acceptingOrders', False) and
                volume >= 1000 and  # $1K minimum volume
                liquidity >= 100    # $100 minimum liquidity
            )
        except Exception:
            return False

    # ========================================
    # RESOLUTION DETECTION
    # ========================================

    def detect_resolution(self, gamma_market: Dict) -> Tuple[Optional[datetime], Optional[str]]:
        """
        Detect if market is resolved and calculate winner

        Gamma API signals:
        - resolvedBy: who resolved it (string or null)
        - closedTime: when it closed/resolved
        - outcomePrices: array of prices ["0.01", "0.99"]
        - outcomes: array of outcome names ["YES", "NO"]

        Returns:
            (resolved_at_timestamp, winner_outcome)
        """
        try:
            # Check if market has been resolved
            resolved_by = gamma_market.get('resolvedBy')
            if not resolved_by:
                return (None, None)  # Not resolved yet

            # Get resolution timestamp from closedTime
            resolved_at = None
            closed_time = gamma_market.get('closedTime')
            if closed_time:
                try:
                    resolved_at = datetime.fromisoformat(closed_time.replace('Z', '+00:00'))
                except Exception as e:
                    logger.warning(f"Failed to parse closedTime: {e}")
                    resolved_at = datetime.utcnow()  # Fallback to now
            else:
                resolved_at = datetime.utcnow()  # Fallback if no closedTime

            # Calculate winner from outcome prices
            winner = self.calculate_winner(
                gamma_market.get('outcomes', []),
                gamma_market.get('outcomePrices', [])
            )

            return (resolved_at, winner)

        except Exception as e:
            logger.error(f"Error detecting resolution: {e}")
            return (None, None)

    def calculate_winner(self, outcomes: List, outcome_prices: List) -> Optional[str]:
        """
        Find winning outcome (price ~1.0 or 100%)

        Args:
            outcomes: ["YES", "NO"] or similar
            outcome_prices: ["0.01", "0.99"] or ["0.05", "0.95"] or similar

        Returns:
            Winning outcome name or None
        """
        try:
            if not outcomes or not outcome_prices:
                return None

            if len(outcomes) != len(outcome_prices):
                logger.debug(f"Outcomes/prices length mismatch: {len(outcomes)} vs {len(outcome_prices)}")
                return None

            # Find outcome with price >= 0.95 (95% = winner, some variation in prices)
            for i in range(len(outcomes)):
                try:
                    if i >= len(outcome_prices):
                        break

                    price_str = outcome_prices[i]
                    # Handle both string and numeric prices
                    if isinstance(price_str, str):
                        price = float(price_str)
                    else:
                        price = float(price_str)

                    if price >= 0.95:  # 95% or higher = winner
                        return str(outcomes[i])
                except (ValueError, IndexError, TypeError) as e:
                    logger.warning(f"Error parsing price at index {i}: {e}")
                    continue

            # If no clear winner, return None
            return None

        except Exception as e:
            logger.error(f"Error calculating winner: {e}")
            return None

    def check_if_finished(self, end_date: Optional[datetime]) -> bool:
        """
        Check if market's end_date has passed

        Args:
            end_date: Market end date (datetime object)

        Returns:
            True if market is finished (end_date passed)
        """
        if not end_date:
            return False

        try:
            return end_date < datetime.utcnow()
        except Exception:
            return False

    # ========================================
    # HELPER METHODS
    # ========================================

    def get_health_status(self) -> Dict:
        """Get health status for monitoring"""
        return {
            'last_update': self.last_update.isoformat() if self.last_update else None,
            'last_stats': self.last_stats,
            'consecutive_errors': self.consecutive_errors,
            'status': 'healthy' if self.consecutive_errors < 5 else 'degraded'
        }
