"""
Market Grouping Service
Handles grouping and display logic for multi-outcome markets (Win/Draw/Win)
"""

import logging
from typing import Dict, List, Optional, Tuple
from datetime import datetime

logger = logging.getLogger(__name__)


class MarketGroupingService:
    """
    Service for grouping and managing multi-outcome markets using Polymarket Events API

    Example: Sevilla vs Mallorca match has 3 separate markets grouped by event_id:
    - Sevilla wins (event_id="abc123")
    - Draw (event_id="abc123")
    - Mallorca wins (event_id="abc123")
    """

    def __init__(self):
        logger.info("✅ Market Grouping Service initialized (using Events API)")

    def group_markets_by_event(self, markets: List[Dict]) -> Dict[str, List[Dict]]:
        """
        Group markets by their event_id (Polymarket Events API)

        Args:
            markets: List of market dictionaries

        Returns:
            Dictionary mapping event_id to list of markets
            Example: {"abc123": [market1, market2, market3]}
        """
        grouped = {}

        for market in markets:
            event_id = market.get('event_id')

            if event_id is not None:
                if event_id not in grouped:
                    grouped[event_id] = []
                grouped[event_id].append(market)

        return grouped

    def group_markets_by_market_group(self, markets: List[Dict]) -> Dict[int, List[Dict]]:
        """
        LEGACY: Group markets by their market_group ID

        Use group_markets_by_event() instead for new code

        Args:
            markets: List of market dictionaries

        Returns:
            Dictionary mapping market_group_id to list of markets
            Example: {123: [market1, market2, market3]}
        """
        grouped = {}

        for market in markets:
            market_group = market.get('market_group')

            if market_group is not None:
                if market_group not in grouped:
                    grouped[market_group] = []
                grouped[market_group].append(market)

        return grouped

    def calculate_group_stats(self, grouped_markets: List[Dict]) -> Dict:
        """
        Calculate aggregate statistics for a market group

        Args:
            grouped_markets: List of markets in the same group

        Returns:
            Dictionary with:
            - total_volume: Sum of all markets in group
            - total_liquidity: Sum of all liquidity
            - main_market_id: ID of market with highest volume
            - outcomes: List of outcome info [{title, price, volume, market_id}]
        """
        if not grouped_markets:
            return {
                'total_volume': 0.0,
                'total_liquidity': 0.0,
                'main_market_id': None,
                'outcomes': []
            }

        total_volume = sum(float(m.get('volume', 0)) for m in grouped_markets)
        total_liquidity = sum(float(m.get('liquidity', 0)) for m in grouped_markets)

        # Find main market (highest volume)
        main_market = max(grouped_markets, key=lambda m: float(m.get('volume', 0)))

        # Build outcomes list (sorted by YES price high->low, then volume as tie-breaker)
        outcomes = []

        # First pass: collect all outcomes with their prices
        temp_outcomes = []
        for market in grouped_markets:
            # Extract price (assume Yes outcome for group items)
            outcome_prices = market.get('outcome_prices', [])
            price = None

            # Parse JSON string if needed
            if isinstance(outcome_prices, str):
                import json
                try:
                    outcome_prices = json.loads(outcome_prices)
                except (json.JSONDecodeError, TypeError):
                    outcome_prices = []

            # Extract first price (Yes outcome)
            if outcome_prices and len(outcome_prices) > 0:
                try:
                    price = float(outcome_prices[0]) if outcome_prices[0] else None
                except (ValueError, TypeError, IndexError):
                    price = None

            temp_outcomes.append({
                'title': market.get('group_item_title') or market.get('question', 'Unknown'),
                'price': price,
                'volume': float(market.get('volume', 0)),
                'market_id': market.get('id'),
                'question': market.get('question'),
                'slug': market.get('slug'),
                # ✅ FIX: Include full outcome data for smart display formatting
                'outcome_prices': outcome_prices,  # Full array [0.555, 0.445]
                'outcomes': market.get('outcomes', []),  # Outcome names ["Yes", "No"] or ["Lakers", "Grizzlies"]
                'category': market.get('category', '')  # For emoji selection
            })

        # Second pass: sort by YES price (high to low), then volume (high to low)
        # Put outcomes with no price at the end
        outcomes = sorted(
            temp_outcomes,
            key=lambda o: (
                o['price'] is not None,  # Non-None prices first
                o['price'] if o['price'] is not None else 0,  # Sort by price descending
                o['volume']  # Then by volume descending
            ),
            reverse=True
        )

        return {
            'total_volume': total_volume,
            'total_liquidity': total_liquidity,
            'main_market_id': main_market.get('id'),
            'main_question': main_market.get('question'),
            'outcomes': outcomes
        }

    def format_group_for_display(self, event_id: str, markets: List[Dict]) -> Dict:
        """
        Format a market group for Telegram display (using Events API)

        Args:
            event_id: The event ID from Polymarket Events API (or slug-based ID)
            markets: List of markets in the event

        Returns:
            Formatted display object with event title, outcomes, stats
        """
        stats = self.calculate_group_stats(markets)

        # FIX: Extract event_title from events JSONB array (not root level)
        # The events field contains: [{"event_id": "23246", "event_title": "New York City Mayoral Election", ...}]
        event_title = None
        if markets and markets[0].get('events'):
            events = markets[0].get('events')
            if isinstance(events, list) and len(events) > 0:
                event_title = events[0].get('event_title')
        
        # Fallback to _extract_event_title if not found in JSONB
        if not event_title or event_title == '':
            event_title = self._extract_event_title(markets)

        # Get end date from any market (they should all have same end date)
        end_date = markets[0].get('end_date') if markets else None

        # Store market IDs for quick lookup (critical for slug-based groups)
        market_ids = [str(m.get('id')) for m in markets]

        return {
            'event_id': event_id,
            'event_slug': markets[0].get('event_slug') if markets else None,
            'event_title': event_title,
            'total_volume': stats['total_volume'],
            'total_liquidity': stats['total_liquidity'],
            'end_date': end_date,
            'outcomes': stats['outcomes'],
            'markets': markets,
            'market_ids': market_ids,  # NEW: Store market IDs for quick retrieval
            'display_type': 'event'
        }

    def _extract_event_title(self, markets: List[Dict]) -> str:
        """
        Extract clean event title from market questions

        Examples:
        - "Will Sevilla win on 2025-10-18?" → "Sevilla vs Mallorca"
        - "Fed increases by 25+ bps after October 2025 meeting?" → "Fed decision in October 2025"
        """
        if not markets:
            return "Unknown Event"

        import re

        # Strategy 1: Try to use slug for sports (team codes)
        slug = markets[0].get('slug', '')
        if slug:
            # Example: "lal-sev-mal-2025-10-18-sev" → "Sevilla vs Mallorca"
            parts = slug.split('-')
            team_codes = [p for p in parts if len(p) == 3 and p.isalpha()]
            if len(team_codes) >= 2:
                return f"{team_codes[0].upper()} vs {team_codes[1].upper()}"

        # Strategy 2: Detect common event patterns from questions
        first_question = markets[0].get('question', '')

        # Pattern: "Fed * after/before MONTH YEAR"
        fed_match = re.search(r'Fed\s+.+?\s+(after|before|in)\s+(\w+)\s+(\d{4})', first_question, re.IGNORECASE)
        if fed_match:
            month = fed_match.group(2).capitalize()
            year = fed_match.group(3)
            return f"Fed decision in {month} {year}"

        # Pattern: "Team1 vs Team2" (sports)
        if ' vs ' in first_question.lower() or ' vs. ' in first_question.lower():
            match = re.search(r'(\w+)\s+vs\.?\s+(\w+)', first_question, re.IGNORECASE)
            if match and len(match.group(1)) > 2 and len(match.group(2)) > 2:
                return f"{match.group(1)} vs {match.group(2)}"

        # Pattern: "Election/Vote/Debate * MONTH YEAR"
        event_match = re.search(r'(Election|Vote|Debate|Meeting)\s+.+?\s+(\w+)\s+(\d{4})', first_question, re.IGNORECASE)
        if event_match:
            event_type = event_match.group(1).capitalize()
            month = event_match.group(2).capitalize()
            year = event_match.group(3)
            return f"{event_type} in {month} {year}"

        # Last resort: Clean up the first question
        # Remove "Will" prefix and "?" suffix, take first meaningful part
        clean = re.sub(r'^Will\s+', '', first_question, flags=re.IGNORECASE)
        clean = clean.split('?')[0].strip()

        # Truncate if too long
        if len(clean) > 50:
            clean = clean[:47] + "..."

        return clean

    def separate_grouped_and_individual(self, markets: List[Dict]) -> Tuple[Dict[str, List[Dict]], List[Dict]]:
        """
        Separate markets into grouped (multi-outcome events) and individual markets

        Priority:
        1. Real event_id from Polymarket Events API (preferred)
        2. Legacy market_group (for backward compatibility)
        3. Slug pattern detection (fallback for markets without event_id)

        Args:
            markets: List of all markets

        Returns:
            Tuple of (grouped_dict, individual_list)
            - grouped_dict: {event_id: [markets]}
            - individual_list: List of markets without events
        """
        grouped = {}
        ungrouped = []

        for market in markets:
            # PRIORITY 1: Real event_id from Polymarket Events API
            event_id = market.get('event_id')

            if event_id is not None:
                # Group by real event_id (convert to string for consistency)
                event_key = str(event_id)
                if event_key not in grouped:
                    grouped[event_key] = []
                grouped[event_key].append(market)
            else:
                # PRIORITY 2: Legacy market_group (fallback)
                market_group = market.get('market_group')
                if market_group is not None:
                    group_key = f"legacy_{market_group}"
                    if group_key not in grouped:
                        grouped[group_key] = []
                    grouped[group_key].append(market)
                else:
                    # PRIORITY 3: No explicit grouping - will try slug detection
                    ungrouped.append(market)

        # FALLBACK: Group ungrouped markets by slug pattern (only for markets without event_id)
        # This is less reliable but better than showing 100+ individual markets
        slug_groups = self._group_by_slug_pattern(ungrouped)

        # Add slug-based groups to grouped dict (only if 2+ markets share the pattern)
        for slug_prefix, slug_markets in slug_groups.items():
            if len(slug_markets) >= 2:  # Only group if 2+ markets share the pattern
                group_key = f"slug_{slug_prefix}"
                grouped[group_key] = slug_markets
                logger.debug(f"📦 Created slug-based group: {group_key} with {len(slug_markets)} markets")
            else:
                # Keep as individual if no siblings found
                ungrouped.append(slug_markets[0])

        # Remove slug-grouped markets from ungrouped
        slug_grouped_ids = set()
        for slug_markets in slug_groups.values():
            if len(slug_markets) >= 2:
                for m in slug_markets:
                    slug_grouped_ids.add(m.get('id'))

        individual = [m for m in ungrouped if m.get('id') not in slug_grouped_ids]

        # Log summary
        logger.info(f"📊 Market grouping: {len(grouped)} groups, {len(individual)} individual markets")
        event_groups = sum(1 for k in grouped.keys() if not k.startswith('slug_') and not k.startswith('legacy_'))
        slug_groups_count = sum(1 for k in grouped.keys() if k.startswith('slug_'))
        logger.info(f"   - Real event groups: {event_groups}")
        logger.info(f"   - Slug-based groups: {slug_groups_count}")

        return grouped, individual

    def _group_by_slug_pattern(self, markets: List[Dict]) -> Dict[str, List[Dict]]:
        """
        Group markets by shared slug prefix pattern

        Examples:
        - Sports: "lal-sev-mal-2025-10-18-sev/draw/mal" → "lal-sev-mal-2025-10-18"
        - Fed: "fed-*-after-october-2025-meeting" → "fed-after-october-2025"

        Strategy:
        1. Try removing last segment (for sports: "lal-sev-mal-2025-10-18-sev" → "lal-sev-mal-2025-10-18")
        2. Try extracting common middle pattern (for Fed: detect "after-YYYY-MM" pattern)

        Returns:
            Dict mapping slug_prefix to list of markets
        """
        slug_groups = {}

        for market in markets:
            slug = market.get('slug', '')
            if not slug:
                continue

            # Strategy 1: Remove last segment (works for sports with date patterns)
            # "lal-sev-mal-2025-10-18-sev" → "lal-sev-mal-2025-10-18"
            # Only use this if the slug looks like a sports match (has date in format YYYY-MM-DD)
            import re
            has_date_pattern = re.search(r'\d{4}-\d{2}-\d{2}', slug)

            if has_date_pattern:
                parts = slug.rsplit('-', 1)
                if len(parts) == 2:
                    prefix = parts[0]

                    # Only consider if prefix ends with a date
                    if len(prefix) > 10 and re.search(r'\d{4}-\d{2}-\d{2}$', prefix):
                        if prefix not in slug_groups:
                            slug_groups[prefix] = []
                        slug_groups[prefix].append(market)
                        continue

            # Strategy 2: Extract common date/event pattern (works for Fed, elections, etc)
            # "fed-decreases-by-25-bps-after-october-2025-meeting" → "fed-after-october-2025"
            # "fed-increases-by-50-bps-after-october-2025-meeting" → "fed-after-october-2025"
            # "no-change-in-fed-interest-rates-after-october-2025" → "fed-after-october-2025"

            # Look for "after-MONTH-YEAR" or similar temporal patterns
            temporal_match = re.search(r'(after|before|by|in)-(\w+)-(\d{4})', slug)
            if temporal_match:
                temporal_key = temporal_match.group(0)  # e.g., "after-october-2025"

                # Extract main topic (e.g., "fed", "trump", "election")
                # Look for common keywords in the slug
                topic_keywords = ['fed', 'trump', 'election', 'biden', 'harris', 'debate', 'vote', 'rate']
                topic = None

                for keyword in topic_keywords:
                    if keyword in slug:
                        topic = keyword
                        break

                # If no keyword found, use first word
                if not topic:
                    topic = slug.split('-')[0]

                group_key = f"{topic}-{temporal_key}"

                if group_key not in slug_groups:
                    slug_groups[group_key] = []
                slug_groups[group_key].append(market)

        return slug_groups

    def create_combined_list(self, markets: List[Dict]) -> List[Dict]:
        """
        Create a combined list of groups and individual markets, sorted by volume

        Each item in the list is either:
        - A group: {'type': 'group', 'market_group': X, 'total_volume': Y, ...}
        - An individual: {'type': 'individual', ...original market data...}

        Args:
            markets: List of all markets

        Returns:
            Combined and sorted list ready for display
        """
        grouped, individual = self.separate_grouped_and_individual(markets)

        # Create group items
        group_items = []
        for group_id, group_markets in grouped.items():
            formatted = self.format_group_for_display(group_id, group_markets)
            group_items.append({
                'type': 'event',  # Changed from 'group' to 'event'
                'event_id': formatted.get('event_id', group_id),
                'event_slug': formatted.get('event_slug'),
                'total_volume': formatted['total_volume'],
                'total_liquidity': formatted['total_liquidity'],
                **formatted
            })

        # Create individual items
        individual_items = [
            {
                'type': 'individual',
                'volume': float(m.get('volume', 0)),
                **m
            }
            for m in individual
        ]

        # Combine and sort by volume
        combined = group_items + individual_items
        combined.sort(
            key=lambda x: x.get('total_volume', 0) if x['type'] == 'event' else x.get('volume', 0),
            reverse=True
        )

        return combined
