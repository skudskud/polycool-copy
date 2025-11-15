"""
Market Enricher - Data Processing Service
Enriches raw market data from Gamma API with additional context
"""
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
import json

from infrastructure.logging.logger import get_logger

logger = get_logger(__name__)


class MarketEnricher:
    """
    Enrich market data with additional context and normalization
    """

    def __init__(self):
        # Category mapping (expanded for better tag coverage)
        self.category_mapping = {
            # Existing mappings
            'Politics': 'politics',
            'Crypto': 'crypto',
            'Sports': 'sports',
            'Finance': 'finance',
            'World': 'geopolitics',
            'US Politics': 'politics',
            'Elections': 'politics',
            'Economy': 'finance',
            'Technology': 'tech',
            'Science': 'science',
            'Entertainment': 'entertainment',
            'Culture': 'culture',
            'Weather': 'weather',
            'Health': 'health',
            'Education': 'education',
            'Environment': 'environment',
            'AI': 'ai',
            'Space': 'space',
            'Gaming': 'gaming',

            # NEW: Common Polymarket tags
            'All': 'other',  # Generic tag to exclude
            'NBA': 'sports',
            'NFL': 'sports',
            'Soccer': 'sports',
            'Football': 'sports',
            'Basketball': 'sports',
            'Baseball': 'sports',
            'Hockey': 'sports',
            'Tennis': 'sports',
            'Golf': 'sports',
            'Formula 1': 'sports',
            'UFC': 'sports',
            'Boxing': 'sports',
            'MMA': 'sports',

            # Politics variations
            'Election': 'politics',
            'Presidential': 'politics',
            'Congress': 'politics',
            'Senate': 'politics',
            'House': 'politics',
            'Government': 'politics',
            'Political': 'politics',

            # Crypto variations
            'Bitcoin': 'crypto',
            'Ethereum': 'crypto',
            'DeFi': 'crypto',
            'NFT': 'crypto',
            'Blockchain': 'crypto',
            'Web3': 'crypto',

            # Finance variations
            'Stock Market': 'finance',
            'Stocks': 'finance',
            'Bonds': 'finance',
            'Commodities': 'finance',
            'Forex': 'finance',
            'Currency': 'finance',

            # Geopolitics variations
            'International': 'geopolitics',
            'Foreign Policy': 'geopolitics',
            'War': 'geopolitics',
            'Conflict': 'geopolitics',
            'Diplomacy': 'geopolitics',
        }

    async def enrich_markets(self, markets: List[Dict]) -> List[Dict]:
        """
        Enrich a batch of markets with additional data

        Args:
            markets: Raw market data from Gamma API

        Returns:
            Enriched market data
        """
        enriched = []

        for market in markets:
            try:
                enriched_market = await self._enrich_single_market(market)
                enriched.append(enriched_market)
            except Exception as e:
                logger.error(f"Error enriching market {market.get('id')}: {e}")
                # Still include the market with basic enrichment
                enriched.append(self._basic_enrichment(market))

        return enriched

    async def _enrich_single_market(self, market: Dict) -> Dict:
        """
        Enrich a single market with additional context
        """
        enriched = market.copy()

        # Basic enrichment
        enriched.update(self._basic_enrichment(market))

        # Category normalization (now using event tags)
        enriched['category_normalized'] = self._normalize_category(market)

        # Tags extraction and processing
        enriched['tags_processed'] = self._process_tags(market)

        # Event processing
        enriched['events_processed'] = self._process_events(market)

        # Market type detection
        enriched['market_type'] = self._detect_market_type(market)

        # Resolution status (if available)
        enriched['resolution_status'] = self._extract_resolution_status(market)

        return enriched

    def _basic_enrichment(self, market: Dict) -> Dict:
        """
        Basic enrichment that always succeeds
        """
        return {
            'enriched_at': datetime.now(timezone.utc),
            'source': 'poll',
            'processing_version': '1.0',
        }

    def _normalize_category(self, market: Dict) -> Optional[str]:
        """
        Normalize category names to standard values using event tags
        NEW: Prioritize event tags over market category for better classification
        """
        try:
            # NEW: First priority - event tags (more reliable than market category)
            event_tags = market.get('event_tags', [])
            if event_tags:
                # Extract tag labels, excluding generic ones like "All"
                tag_labels = [
                    tag.get('label', '').lower().strip()
                    for tag in event_tags
                    if tag.get('label') and tag.get('label', '').lower() not in ['all']
                ]

                # Find first matching tag in our mapping
                for tag_label in tag_labels:
                    if tag_label in self.category_mapping:
                        return self.category_mapping[tag_label]

                    # Special mappings for common tags
                    if 'crypto' in tag_label or 'bitcoin' in tag_label or 'btc' in tag_label:
                        return 'crypto'
                    elif 'politics' in tag_label or 'election' in tag_label or 'political' in tag_label:
                        return 'politics'
                    elif 'sports' in tag_label or 'football' in tag_label or 'basketball' in tag_label:
                        return 'sports'
                    elif 'finance' in tag_label or 'economy' in tag_label or 'economic' in tag_label:
                        return 'finance'

            # Fallback: market tags (less reliable)
            market_tags = market.get('tags', [])
            if market_tags:
                tag_labels = [
                    tag.get('label', '').lower().strip()
                    for tag in market_tags
                    if tag.get('label') and tag.get('label', '').lower() not in ['all']
                ]

                for tag_label in tag_labels:
                    if tag_label in self.category_mapping:
                        return self.category_mapping[tag_label]

            # Last fallback: direct category field
            category_sources = [
                market.get('category'),
                market.get('events', [{}])[0].get('category') if market.get('events') else None,
            ]

            for category in category_sources:
                if category and category in self.category_mapping:
                    return self.category_mapping[category]

                # Legacy fallbacks
                if category:
                    normalized = category.lower().strip()
                    if 'crypto' in normalized or 'bitcoin' in normalized or 'btc' in normalized:
                        return 'crypto'
                    elif 'politics' in normalized or 'election' in normalized:
                        return 'politics'
                    elif 'sports' in normalized:
                        return 'sports'

            return 'other'

        except Exception as e:
            logger.warning(f"Error normalizing category for market {market.get('id')}: {e}")
            return 'other'

    def _process_tags(self, market: Dict) -> List[Dict]:
        """
        Process and extract relevant tags from event and market data
        NEW: Prioritize event tags over market tags for better classification
        """
        try:
            processed_tags = []

            # Priority 1: Event tags (most reliable)
            event_tags = market.get('event_tags', [])
            for tag in event_tags:
                if isinstance(tag, dict) and tag.get('label'):
                    # Skip generic tags like "All"
                    if tag.get('label', '').lower() in ['all']:
                        continue

                    processed_tags.append({
                        'source': 'event',
                        'id': tag.get('id'),
                        'label': tag.get('label'),
                        'slug': tag.get('slug'),
                        'category': self._categorize_tag(tag.get('label', ''))
                    })

            # Priority 2: Market tags (fallback)
            market_tags = market.get('tags', [])
            for tag in market_tags:
                if isinstance(tag, dict) and tag.get('label'):
                    # Skip if we already have this tag from event
                    if any(pt['label'] == tag.get('label') for pt in processed_tags):
                        continue

                    # Skip generic tags
                    if tag.get('label', '').lower() in ['all']:
                        continue

                    processed_tags.append({
                        'source': 'market',
                        'id': tag.get('id'),
                        'label': tag.get('label'),
                        'slug': tag.get('slug'),
                        'category': self._categorize_tag(tag.get('label', ''))
                    })

            return processed_tags

        except Exception as e:
            logger.warning(f"Error processing tags for market {market.get('id')}: {e}")
            return []

    def _categorize_tag(self, tag_label: str) -> str:
        """
        Categorize a tag label into our standard categories
        """
        if not tag_label:
            return 'other'

        normalized = tag_label.lower().strip()

        # Use the same mapping as category normalization (case-insensitive)
        if normalized in self.category_mapping:
            return self.category_mapping[normalized]

        # Also check original case in mapping
        if tag_label in self.category_mapping:
            return self.category_mapping[tag_label]

        # Special cases (keyword matching)
        if 'crypto' in normalized or 'bitcoin' in normalized or 'btc' in normalized:
            return 'crypto'
        elif 'politics' in normalized or 'election' in normalized or 'political' in normalized:
            return 'politics'
        elif 'sports' in normalized or 'football' in normalized or 'basketball' in normalized:
            return 'sports'
        elif 'finance' in normalized or 'economy' in normalized or 'economic' in normalized:
            return 'finance'

        return 'other'

    def _process_events(self, market: Dict) -> List[Dict]:
        """
        Process and normalize event data
        """
        try:
            events = market.get('events', [])
            if not events:
                return []

            processed_events = []
            for event in events:
                processed = {
                    'event_id': event.get('id'),
                    'title': event.get('title'),
                    'slug': event.get('slug'),
                    'category': event.get('category'),
                    'start_date': event.get('startDate'),
                    'end_date': event.get('endDate'),
                    'active': event.get('active', True),
                }
                processed_events.append(processed)

            return processed_events

        except Exception as e:
            logger.warning(f"Error processing events for market {market.get('id')}: {e}")
            return []

    def _detect_market_type(self, market: Dict) -> str:
        """
        Detect if market is standalone or part of an event
        """
        try:
            events = market.get('events', [])
            if events:
                return 'event_market'
            else:
                return 'standalone_market'
        except Exception:
            return 'unknown'

    def _extract_resolution_status(self, market: Dict) -> Optional[str]:
        """
        Extract resolution status if available
        """
        try:
            # Check various resolution indicators
            if market.get('resolvedBy'):
                return 'resolved'
            elif market.get('closed') and not market.get('active'):
                return 'closed'
            elif market.get('active'):
                return 'active'
            else:
                return 'unknown'
        except Exception:
            return 'unknown'

    # Utility methods for data validation
    def validate_market_data(self, market: Dict) -> bool:
        """
        Basic validation of market data
        """
        required_fields = ['id', 'question']
        for field in required_fields:
            if field not in market:
                logger.warning(f"Market missing required field: {field}")
                return False
        return True

    def sanitize_market_data(self, market: Dict) -> Dict:
        """
        Sanitize and clean market data
        """
        sanitized = market.copy()

        # Remove sensitive or unnecessary fields
        fields_to_remove = ['internal_id', 'debug_info', 'temp_data']
        for field in fields_to_remove:
            sanitized.pop(field, None)

        # Ensure data types
        if 'volume' in sanitized:
            try:
                sanitized['volume'] = float(sanitized['volume'] or 0)
            except (ValueError, TypeError):
                sanitized['volume'] = 0.0

        if 'liquidity' in sanitized:
            try:
                sanitized['liquidity'] = float(sanitized['liquidity'] or 0)
            except (ValueError, TypeError):
                sanitized['liquidity'] = 0.0

        return sanitized
