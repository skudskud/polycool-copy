"""
Market Repository - PostgreSQL Data Access Layer
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from sqlalchemy import and_, or_, desc
from sqlalchemy.exc import SQLAlchemyError

from .models import Market
from .db_config import db_session

logger = logging.getLogger(__name__)


class MarketRepository:
    """Repository for Market database operations"""

    def __init__(self, session=None):
        self.session = session or db_session

    # ========================================
    # QUERY METHODS (for API endpoints)
    # ========================================

    def get_by_id(self, market_id: str) -> Optional[Market]:
        """Get single market by ID"""
        try:
            return self.session.query(Market).filter(
                Market.id == market_id
            ).first()
        except SQLAlchemyError as e:
            logger.error(f"Error getting market {market_id}: {e}")
            return None

    def get_existing_ids(self, market_ids: List[str]) -> set:
        """
        Batch check which market IDs exist in database

        Args:
            market_ids: List of market IDs to check

        Returns:
            Set of IDs that exist in database

        This is 500x faster than calling get_by_id() in a loop!
        """
        if not market_ids:
            return set()

        try:
            # Single SQL query with IN clause
            results = self.session.query(Market.id).filter(
                Market.id.in_(market_ids)
            ).all()

            # Return as set for O(1) lookups
            return {row[0] for row in results}
        except SQLAlchemyError as e:
            logger.error(f"Error batch checking market IDs: {e}")
            return set()

    def get_markets_by_ids(self, market_ids: List[str]) -> List[Market]:
        """
        Batch load multiple markets by IDs in one query
        
        Args:
            market_ids: List of market IDs to load
            
        Returns:
            List of Market objects (only markets that exist)
            
        PERFORMANCE: This is 100x faster than calling get_by_id() in a loop!
        Use this for bulk loading markets (smart trading, validation, etc.)
        """
        if not market_ids:
            return []
        
        try:
            # Single SQL query with IN clause
            markets = self.session.query(Market).filter(
                Market.id.in_(market_ids)
            ).all()
            
            logger.debug(f"📦 Batch loaded {len(markets)}/{len(market_ids)} markets from DB")
            return markets
        except SQLAlchemyError as e:
            logger.error(f"Error batch loading markets: {e}")
            return []

    def get_all_active(self, limit: Optional[int] = None) -> List[Market]:
        """Get all active AND tradeable markets (not closed, not ended, not resolved)"""
        try:
            now = datetime.utcnow()
            query = self.session.query(Market).filter(
                and_(
                    Market.active == True,
                    Market.closed == False,
                    Market.winner == None,  # Not resolved
                    Market.archived == False,
                    or_(
                        Market.end_date == None,  # No end date set
                        Market.end_date > now     # Or hasn't ended yet
                    )
                )
            ).order_by(desc(Market.volume))

            if limit:
                query = query.limit(limit)

            return query.all()
        except SQLAlchemyError as e:
            logger.error(f"Error getting active markets: {e}")
            return []

    def get_markets_for_display(self, days_window: int = 30) -> List[Market]:
        """
        Get markets for display with 30-day window

        Shows:
        - All active markets
        - Markets finished in last N days
        - Markets resolved in last N days
        """
        try:
            cutoff_date = datetime.utcnow() - timedelta(days=days_window)

            query = self.session.query(Market).filter(
                or_(
                    Market.active == True,
                    Market.end_date > cutoff_date,
                    Market.resolved_at > cutoff_date
                )
            ).order_by(desc(Market.volume))

            return query.all()
        except SQLAlchemyError as e:
            logger.error(f"Error getting markets for display: {e}")
            return []

    def search_by_keyword(self, keyword: str, limit: int = 100) -> List[Market]:
        """
        Search markets by keyword in question

        Used by /search endpoint
        Shows only active, tradeable markets (not closed, not resolved, not archived)
        """
        try:
            keyword_lower = f'%{keyword.lower()}%'
            now = datetime.utcnow()

            query = self.session.query(Market).filter(
                and_(
                    Market.question.ilike(keyword_lower),
                    Market.active == True,
                    Market.closed == False,
                    Market.winner == None,  # Not resolved
                    Market.archived == False,
                    or_(
                        Market.end_date == None,
                        Market.end_date > now
                    )
                )
            ).order_by(desc(Market.volume)).limit(limit)

            return query.all()
        except SQLAlchemyError as e:
            logger.error(f"Error searching markets for '{keyword}': {e}")
            return []

    def get_tradeable_markets(self, limit: Optional[int] = None) -> List[Market]:
        """Get all tradeable markets (active + high volume/liquidity)"""
        try:
            query = self.session.query(Market).filter(
                and_(
                    Market.active == True,
                    Market.tradeable == True
                )
            ).order_by(desc(Market.volume))

            if limit:
                query = query.limit(limit)

            return query.all()
        except SQLAlchemyError as e:
            logger.error(f"Error getting tradeable markets: {e}")
            return []

    # ========================================
    # NEW: PARENT/CHILD MARKET GROUPING QUERIES
    # ========================================

    def get_parent_markets_by_volume(self, limit: int = 20) -> List[Market]:
        """
        Get parent markets (no market_group) OR markets that ARE groups
        Sorted by volume descending

        Used for /markets command to show top-level markets
        """
        try:
            query = self.session.query(Market).filter(
                and_(
                    Market.active == True,
                    Market.market_group == None  # Parent markets have no group
                )
            ).order_by(desc(Market.volume)).limit(limit)

            return query.all()
        except SQLAlchemyError as e:
            logger.error(f"Error getting parent markets: {e}")
            return []

    def get_sub_markets(self, market_group_id: int) -> List[Market]:
        """
        Get all sub-markets (children) of a parent market group
        Sorted by volume descending

        Args:
            market_group_id: The parent market group ID

        Returns:
            List of child markets in that group
        """
        try:
            return self.session.query(Market).filter(
                and_(
                    Market.market_group == market_group_id,
                    Market.active == True
                )
            ).order_by(desc(Market.volume)).all()
        except SQLAlchemyError as e:
            logger.error(f"Error getting sub-markets for group {market_group_id}: {e}")
            return []

    def get_grouped_markets_aggregate(self, limit: int = 20) -> List[Dict]:
        """
        Get parent markets with aggregated data from all sub-markets

        Returns list of dicts with:
        - parent_id: ID of parent market (or market itself if no group)
        - question: Parent question
        - total_volume: Sum of all sub-market volumes
        - sub_market_count: Number of sub-markets
        - markets: List of all markets in group
        """
        try:
            from sqlalchemy import func

            # Query to get market groups with aggregated data
            query = self.session.query(
                Market.id,
                Market.question,
                Market.market_group,
                func.count(Market.id).label('sub_count'),
                func.sum(Market.volume).label('total_volume')
            ).filter(
                Market.active == True
            ).group_by(
                Market.market_group, Market.id, Market.question
            ).order_by(
                desc('total_volume')
            ).limit(limit)

            results = []
            for row in query.all():
                results.append({
                    'id': row.id,
                    'question': row.question,
                    'market_group': row.market_group,
                    'sub_market_count': row.sub_count,
                    'total_volume': float(row.total_volume) if row.total_volume else 0
                })

            return results
        except SQLAlchemyError as e:
            logger.error(f"Error getting grouped market aggregates: {e}")
            return []

    # ========================================
    # NEW: CATEGORY FILTERING QUERIES
    # ========================================

    def get_markets_by_category(self, category: str, limit: int = 20) -> List[Market]:
        """
        Get markets filtered by category (only active/tradeable/not resolved)

        Args:
            category: Category name (Politics, Sports, Crypto, etc.)
            limit: Maximum number of markets to return

        Returns:
            List of markets in that category, sorted by volume
        """
        try:
            now = datetime.utcnow()
            return self.session.query(Market).filter(
                and_(
                    Market.active == True,
                    Market.closed == False,
                    Market.winner == None,  # Not resolved
                    Market.archived == False,
                    or_(
                        Market.end_date == None,
                        Market.end_date > now
                    ),
                    Market.category == category
                )
            ).order_by(desc(Market.volume)).limit(limit).all()
        except SQLAlchemyError as e:
            logger.error(f"Error getting markets for category '{category}': {e}")
            return []

    def get_all_categories(self) -> List[Tuple[str, int]]:
        """
        Get all unique categories with market counts

        Returns:
            List of (category, count) tuples sorted by count descending
        """
        try:
            from sqlalchemy import func

            query = self.session.query(
                Market.category,
                func.count(Market.id).label('count')
            ).filter(
                and_(
                    Market.active == True,
                    Market.category != None
                )
            ).group_by(Market.category).order_by(desc('count'))

            return [(row.category, row.count) for row in query.all()]
        except SQLAlchemyError as e:
            logger.error(f"Error getting categories: {e}")
            return []

    # ========================================
    # NEW: TRENDING & FEATURED QUERIES
    # ========================================

    def get_trending_markets(self, limit: int = 20, period: str = '24hr') -> List[Market]:
        """
        Get trending markets based on price changes (only active/tradeable)

        Args:
            limit: Maximum number of markets
            period: '1hr', '24hr', '1wk', '1mo' (default: '24hr')

        Returns:
            Markets sorted by price change descending
        """
        try:
            now = datetime.utcnow()
            # Select appropriate price change column
            price_change_col = {
                '1hr': Market.one_hour_price_change,
                '24hr': Market.one_day_price_change,
                '1wk': Market.one_week_price_change,
                '1mo': Market.one_month_price_change
            }.get(period, Market.one_day_price_change)

            return self.session.query(Market).filter(
                and_(
                    Market.active == True,
                    Market.closed == False,
                    Market.archived == False,
                    or_(
                        Market.end_date == None,
                        Market.end_date > now
                    ),
                    price_change_col != None
                )
            ).order_by(desc(price_change_col)).limit(limit).all()
        except SQLAlchemyError as e:
            logger.error(f"Error getting trending markets: {e}")
            return []

    def get_featured_markets(self, limit: int = 20) -> List[Market]:
        """
        Get featured markets (only active/tradeable)

        Returns:
            Markets marked as featured, sorted by volume
        """
        try:
            now = datetime.utcnow()
            return self.session.query(Market).filter(
                and_(
                    Market.active == True,
                    Market.closed == False,
                    Market.archived == False,
                    or_(
                        Market.end_date == None,
                        Market.end_date > now
                    ),
                    Market.featured == True
                )
            ).order_by(desc(Market.volume)).limit(limit).all()
        except SQLAlchemyError as e:
            logger.error(f"Error getting featured markets: {e}")
            return []

    def get_new_markets(self, limit: int = 20) -> List[Market]:
        """
        Get newly created markets (only active/tradeable/not resolved)

        Returns:
            Markets marked as new or created recently, sorted by creation date
        """
        try:
            now = datetime.utcnow()
            cutoff_date = now - timedelta(days=7)  # New = last 7 days

            return self.session.query(Market).filter(
                and_(
                    Market.active == True,
                    Market.closed == False,
                    Market.winner == None,  # Not resolved
                    Market.archived == False,
                    or_(
                        Market.end_date == None,
                        Market.end_date > now
                    ),
                    or_(
                        Market.new == True,
                        Market.created_at > cutoff_date
                    )
                )
            ).order_by(desc(Market.created_at)).limit(limit).all()
        except SQLAlchemyError as e:
            logger.error(f"Error getting new markets: {e}")
            return []

    def get_ending_soon_markets(self, hours: int = 24, limit: int = 20) -> List[Market]:
        """
        Get markets ending soon (not resolved)

        Args:
            hours: Number of hours threshold (default: 24)
            limit: Maximum number of markets

        Returns:
            Markets ending within the specified hours, sorted by end date
        """
        try:
            cutoff_date = datetime.utcnow() + timedelta(hours=hours)

            return self.session.query(Market).filter(
                and_(
                    Market.active == True,
                    Market.closed == False,
                    Market.winner == None,  # Not resolved
                    Market.end_date != None,
                    Market.end_date <= cutoff_date,
                    Market.end_date > datetime.utcnow()
                )
            ).order_by(Market.end_date).limit(limit).all()
        except SQLAlchemyError as e:
            logger.error(f"Error getting ending soon markets: {e}")
            return []

    def get_high_liquidity_markets(self, limit: int = 20) -> List[Market]:
        """
        Get markets with highest liquidity (only active/tradeable/not resolved)

        Returns:
            Markets sorted by liquidity descending
        """
        try:
            now = datetime.utcnow()
            return self.session.query(Market).filter(
                and_(
                    Market.active == True,
                    Market.closed == False,
                    Market.winner == None,  # Not resolved
                    Market.archived == False,
                    or_(
                        Market.end_date == None,
                        Market.end_date > now
                    ),
                    Market.liquidity > 0
                )
            ).order_by(desc(Market.liquidity)).limit(limit).all()
        except SQLAlchemyError as e:
            logger.error(f"Error getting high liquidity markets: {e}")
            return []

    def get_competitive_markets(self, limit: int = 20) -> List[Market]:
        """
        Get markets with highest competitive rewards (only active/tradeable/not resolved)

        Returns:
            Markets sorted by competitive score descending
        """
        try:
            now = datetime.utcnow()
            return self.session.query(Market).filter(
                and_(
                    Market.active == True,
                    Market.closed == False,
                    Market.winner == None,  # Not resolved
                    Market.archived == False,
                    or_(
                        Market.end_date == None,
                        Market.end_date > now
                    ),
                    Market.accepting_orders == True,
                    Market.competitive > 0
                )
            ).order_by(desc(Market.competitive)).limit(limit).all()
        except SQLAlchemyError as e:
            logger.error(f"Error getting competitive markets: {e}")
            return []

    # ========================================
    # WRITE METHODS (for updater service)
    # ========================================

    def upsert(self, market_data: Dict) -> Tuple[Market, bool]:
        """
        Insert or update market

        Args:
            market_data: Dictionary with market fields

        Returns:
            (market, was_created)
        """
        try:
            market = self.get_by_id(market_data['id'])

            if market:
                # Update existing market
                for key, value in market_data.items():
                    if hasattr(market, key):
                        setattr(market, key, value)
                        if key == 'winner' and value:
                            logger.info(f"✅ Setting winner for market {market_data['id']}: {value}")
                market.last_updated = datetime.utcnow()
                was_created = False
            else:
                # Create new market
                # Filter kwargs to only include columns that exist in the SQLAlchemy model
                valid_columns = {col.name for col in Market.__table__.columns}
                filtered_data = {k: v for k, v in market_data.items() if k in valid_columns}

                market = Market(**filtered_data)
                market.created_at = datetime.utcnow()
                market.last_updated = datetime.utcnow()
                self.session.add(market)
                was_created = True

            self.session.commit()
            return (market, was_created)

        except SQLAlchemyError as e:
            logger.error(f"Error upserting market {market_data.get('id')}: {e}")
            self.session.rollback()
            raise

    def bulk_upsert(self, markets_data: List[Dict]) -> Dict[str, int]:
        """
        TRUE bulk upsert markets using PostgreSQL INSERT ON CONFLICT
        100x faster than individual updates

        Returns: {'new': X, 'updated': Y, 'errors': Z}
        """
        if not markets_data:
            return {'new': 0, 'updated': 0, 'errors': 0}

        try:
            from sqlalchemy.dialects.postgresql import insert
            from sqlalchemy import Table, MetaData

            # CRITICAL: Create a fresh Table with current DB schema instead of using cached Model
            # This prevents "Unconsumed column names" error when columns were added after startup
            metadata = MetaData()
            markets_table = Table('markets', metadata, autoload_with=self.session.bind)

            # DEBUG: Log which columns are detected
            detected_cols = [col.name for col in markets_table.columns]
            logger.info(f"🔍 Table reflection detected {len(detected_cols)} columns")
            has_event_cols = 'event_id' in detected_cols and 'event_slug' in detected_cols
            if not has_event_cols:
                logger.error(f"⚠️ MISSING event columns in reflection! Detected: {sorted(detected_cols)[:10]}...")

            # Prepare all records
            records_to_insert = []
            for market_data in markets_data:
                # Convert datetime objects to strings if needed
                record = market_data.copy()
                for key, value in record.items():
                    if isinstance(value, datetime):
                        record[key] = value
                records_to_insert.append(record)

            # Single INSERT ... ON CONFLICT query using fresh table definition
            stmt = insert(markets_table).values(records_to_insert)

            # On conflict (duplicate id), update all columns from the fresh table schema
            # CRITICAL FIX: Use COALESCE logic to handle NULL values properly
            from sqlalchemy import case
            update_dict = {}
            for col in markets_table.columns:
                if col.name in ['id', 'created_at']:  # Don't update PK and created_at
                    continue
                
                # Use case: prefer new value, fall back to old value if NULL
                update_dict[col.name] = case(
                    (stmt.excluded[col.name].isnot(None), stmt.excluded[col.name]),
                    else_=col
                )

            stmt = stmt.on_conflict_do_update(
                index_elements=['id'],
                set_=update_dict
            )

            # Execute single query
            self.session.execute(stmt)
            self.session.commit()

            logger.info(f"✅ BULK UPSERT: {len(markets_data)} markets in single query")

            # Return stats (can't distinguish new vs updated with this method, but much faster)
            return {'new': 0, 'updated': len(markets_data), 'errors': 0}

        except Exception as e:
            logger.error(f"❌ Bulk upsert failed: {e}")
            self.session.rollback()

            # Fallback to individual upserts
            logger.warning("⚠️ Falling back to individual upserts")
            stats = {'new': 0, 'updated': 0, 'errors': 0}

            for market_data in markets_data:
                try:
                    _, was_created = self.upsert(market_data)
                    if was_created:
                        stats['new'] += 1
                    else:
                        stats['updated'] += 1
                except Exception as e2:
                    stats['errors'] += 1
                    logger.error(f"Error in fallback upsert for market {market_data.get('id')}: {e2}")

            return stats

    # ========================================
    # STATS METHODS
    # ========================================

    def count_by_status(self) -> Dict[str, int]:
        """Get market counts by status"""
        try:
            total = self.session.query(Market).count()
            active = self.session.query(Market).filter(Market.active == True).count()
            closed = self.session.query(Market).filter(Market.closed == True).count()
            resolved = self.session.query(Market).filter(Market.resolved_at != None).count()
            tradeable = self.session.query(Market).filter(Market.tradeable == True).count()

            return {
                'total': total,
                'active': active,
                'closed': closed,
                'resolved': resolved,
                'tradeable': tradeable
            }
        except SQLAlchemyError as e:
            logger.error(f"Error getting status counts: {e}")
            return {'total': 0, 'active': 0, 'closed': 0, 'resolved': 0, 'tradeable': 0}

    def get_statistics(self) -> Dict:
        """Comprehensive statistics for /markets/stats endpoint"""
        try:
            cutoff_30d = datetime.utcnow() - timedelta(days=30)

            total = self.session.query(Market).count()
            active = self.session.query(Market).filter(Market.active == True).count()
            tradeable = self.session.query(Market).filter(Market.tradeable == True).count()

            resolved_30d = self.session.query(Market).filter(
                Market.resolved_at > cutoff_30d
            ).count()

            finished_30d = self.session.query(Market).filter(
                and_(
                    Market.closed == True,
                    Market.end_date > cutoff_30d,
                    Market.resolved_at == None
                )
            ).count()

            return {
                'total': total,
                'active': active,
                'tradeable': tradeable,
                'resolved_30d': resolved_30d,
                'finished_30d': finished_30d,
                'by_status': self.count_by_status()
            }
        except SQLAlchemyError as e:
            logger.error(f"Error getting statistics: {e}")
            return {
                'total': 0,
                'active': 0,
                'tradeable': 0,
                'resolved_30d': 0,
                'finished_30d': 0,
                'by_status': {}
            }

    # ========================================
    # MARKET GROUPS METHODS
    # ========================================

    def get_markets_by_event(self, event_id: str, market_ids_cache: List[str] = None) -> List[Market]:
        """
        Get all markets in a specific event (Polymarket Events API or slug-based group)

        Args:
            event_id: The event ID to query (real or slug-based like 'slug_will-in-the-2025')
            market_ids_cache: Optional pre-computed list of market IDs for slug-based groups

        Returns:
            List of markets in the event (only active markets)
        """
        try:
            now = datetime.utcnow()

            # OPTIMIZATION: If market_ids are provided (from cache), use direct ID lookup
            if market_ids_cache:
                logger.debug(f"🚀 Using cached market IDs for event {event_id} ({len(market_ids_cache)} markets)")
                return self.session.query(Market).filter(
                    and_(
                        Market.id.in_(market_ids_cache),
                        Market.active == True,
                        Market.closed == False,
                        Market.archived == False,
                        or_(
                            Market.end_date == None,
                            Market.end_date > now
                        )
                    )
                ).order_by(desc(Market.volume)).all()

            # Check if this is a slug-based group (starts with 'slug_')
            if event_id.startswith('slug_'):
                # DEPRECATED: Slug pattern matching is unreliable
                # Slug patterns like 'will-in-the-2025' don't match actual slugs
                # This should only be used as fallback if market_ids_cache is not provided

                logger.warning(f"⚠️ Slug-based lookup for {event_id} without cached market IDs - may fail!")
                logger.warning(f"   This indicates market_ids were not stored during grouping")

                # Extract the slug pattern
                slug_pattern = event_id[5:]  # Remove 'slug_' prefix

                # Try to find markets with this pattern (unreliable!)
                return self.session.query(Market).filter(
                    and_(
                        Market.slug.like(f'%{slug_pattern}%'),
                        Market.active == True,
                        Market.closed == False,
                        Market.archived == False,
                        or_(
                            Market.end_date == None,
                            Market.end_date > now
                        )
                    )
                ).order_by(desc(Market.volume)).all()
            else:
                # Real event_id from Polymarket Events API (numeric like '23656')
                return self.session.query(Market).filter(
                    and_(
                        Market.event_id == str(event_id),
                        Market.active == True,
                        Market.closed == False,
                        Market.archived == False,
                        or_(
                            Market.end_date == None,
                            Market.end_date > now
                        )
                    )
                ).order_by(desc(Market.volume)).all()

        except SQLAlchemyError as e:
            logger.error(f"Error getting markets for event {event_id}: {e}")
            return []

    def get_markets_by_group(self, market_group_id: int) -> List[Market]:
        """
        LEGACY: Get all markets in a specific market group

        Use get_markets_by_event() for new code

        Args:
            market_group_id: The group ID to query

        Returns:
            List of markets in the group (only active markets)
        """
        try:
            now = datetime.utcnow()
            return self.session.query(Market).filter(
                and_(
                    Market.market_group == market_group_id,
                    Market.active == True,
                    Market.closed == False,
                    Market.archived == False,
                    or_(
                        Market.end_date == None,
                        Market.end_date > now
                    )
                )
            ).order_by(desc(Market.volume)).all()
        except SQLAlchemyError as e:
            logger.error(f"Error getting markets for group {market_group_id}: {e}")
            return []

    def get_market_groups_by_volume(self, limit: int = 20) -> List[Tuple[int, List[Market]]]:
        """
        Get market groups sorted by total volume

        Returns top market groups as list of tuples: [(group_id, [markets])]
        Only includes active markets

        Args:
            limit: Maximum number of groups to return

        Returns:
            List of (market_group_id, markets) tuples sorted by total volume
        """
        try:
            from sqlalchemy import func

            now = datetime.utcnow()

            # First, get all market groups with their total volumes
            group_volumes = self.session.query(
                Market.market_group,
                func.sum(Market.volume).label('total_volume')
            ).filter(
                and_(
                    Market.market_group != None,
                    Market.active == True,
                    Market.closed == False,
                    Market.archived == False,
                    or_(
                        Market.end_date == None,
                        Market.end_date > now
                    )
                )
            ).group_by(Market.market_group).order_by(
                desc('total_volume')
            ).limit(limit).all()

            # Then fetch all markets for each group
            result = []
            for group_id, total_vol in group_volumes:
                markets = self.get_markets_by_group(group_id)
                if markets:
                    result.append((group_id, markets))

            return result
        except SQLAlchemyError as e:
            logger.error(f"Error getting market groups by volume: {e}")
            return []

    def get_events_by_volume(self, limit: int = 20) -> List[Tuple[str, List[Market]]]:
        """
        Get events sorted by total volume (Polymarket Events API)

        Returns top events as list of tuples: [(event_id, [markets])]
        Only includes active markets

        Args:
            limit: Maximum number of events to return

        Returns:
            List of (event_id, markets) tuples sorted by total volume
        """
        try:
            from sqlalchemy import func

            now = datetime.utcnow()

            # First, get all event IDs with their total volumes
            event_volumes = self.session.query(
                Market.event_id,
                func.sum(Market.volume).label('total_volume')
            ).filter(
                and_(
                    Market.event_id != None,
                    Market.active == True,
                    Market.closed == False,
                    Market.archived == False,
                    or_(
                        Market.end_date == None,
                        Market.end_date > now
                    )
                )
            ).group_by(Market.event_id).order_by(
                desc('total_volume')
            ).limit(limit).all()

            # Then fetch all markets for each event
            result = []
            for event_id, total_vol in event_volumes:
                markets = self.get_markets_by_event(event_id)
                if markets:
                    result.append((event_id, markets))

            return result
        except SQLAlchemyError as e:
            logger.error(f"Error getting events by volume: {e}")
            return []
