"""
Markets API Routes
Endpoints for market discovery and data
"""
import json
import httpx
import time
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel

from core.services.market_service import get_market_service
from core.database.connection import get_db
from infrastructure.config.settings import settings
from infrastructure.logging.logger import get_logger

logger = get_logger(__name__)

router = APIRouter()

# Simple in-memory cache to prevent API spam (market_id -> (timestamp, data))
_market_cache: Dict[str, tuple] = {}
_CACHE_TTL = 30  # 30 seconds TTL


class MarketResponse(BaseModel):
    """Market response model"""
    id: str
    title: str
    description: Optional[str] = None
    category: Optional[str] = None
    outcomes: Optional[List[str]] = None
    outcome_prices: Optional[List[float]] = None
    active: bool = True
    volume: Optional[float] = None
    liquidity: Optional[float] = None
    clob_token_ids: Optional[List[str]] = None
    source: Optional[str] = None  # 'ws' for WebSocket, 'poll' for poller
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    polymarket_url: Optional[str] = None  # Polymarket URL for the market
    event_slug: Optional[str] = None  # Event slug for URL construction

    class Config:
        from_attributes = True


class MarketGroupResponse(BaseModel):
    """Market group response model for event-based grouping"""
    type: str  # 'event_group' or 'individual'
    event_id: Optional[str] = None
    event_title: Optional[str] = None
    event_slug: Optional[str] = None
    market_count: Optional[int] = None
    total_volume: Optional[float] = None
    total_liquidity: Optional[float] = None
    # For individual markets
    id: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    active: Optional[bool] = None
    volume: Optional[float] = None
    liquidity: Optional[float] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    class Config:
        from_attributes = True


class TrendingMarketsResponse(BaseModel):
    """Response wrapper for trending markets with total count"""
    markets: List[MarketGroupResponse]
    total_count: Optional[int] = None


class SearchMarketsResponse(BaseModel):
    """Response wrapper for search markets with total count"""
    markets: List[MarketGroupResponse]
    total_count: Optional[int] = None


class EventMarketsResponse(BaseModel):
    """Response wrapper for event markets with pagination info"""
    markets: List[MarketResponse]
    total_count: int
    page: int
    page_size: int
    has_more_pages: bool


@router.get("/trending", response_model=TrendingMarketsResponse)
async def get_trending_markets(
    page: int = Query(0, ge=0),
    page_size: int = Query(10, ge=1, le=50),
    group_by_events: bool = Query(True),
    filter_type: Optional[str] = Query(None, description="Filter type: 'yes', 'no', or None")
):
    """
    Get trending markets

    Args:
        page: Page number (0-based)
        page_size: Number of markets per page
        group_by_events: Whether to group markets by events
        filter_type: Filter by outcome type

    Returns:
        TrendingMarketsResponse with markets list and total_count
    """
    try:
        market_service = get_market_service()
        markets, total_count = await market_service.get_trending_markets(
            page=page,
            page_size=page_size,
            group_by_events=group_by_events,
            filter_type=filter_type
        )

        # Convert to response format (supports both event groups and individual markets)
        response_items = []
        for item in markets:
            if item.get('type') == 'event_group':
                # Event group
                response_items.append(MarketGroupResponse(
                    type='event_group',
                    event_id=item.get('event_id'),
                    event_title=item.get('event_title'),
                    event_slug=item.get('event_slug'),
                    market_count=item.get('market_count'),
                    total_volume=item.get('total_volume'),
                    total_liquidity=item.get('total_liquidity')
                ))
            else:
                # Individual market
                response_items.append(MarketGroupResponse(
                    type='individual',
                    id=item.get('id', ''),
                    title=item.get('title', ''),
                    description=item.get('description'),
                    category=item.get('category'),
                    active=item.get('active', True),
                    volume=item.get('volume'),
                    liquidity=item.get('liquidity'),
                    created_at=item.get('created_at'),
                    updated_at=item.get('updated_at')
                ))

        return TrendingMarketsResponse(
            markets=response_items,
            total_count=total_count if total_count >= 0 else None
        )

    except Exception as e:
        logger.error(f"Error getting trending markets: {e}")
        raise HTTPException(status_code=500, detail=f"Error getting trending markets: {str(e)}")


@router.get("/categories/{category}", response_model=List[MarketResponse])
async def get_category_markets(
    category: str,
    page: int = Query(0, ge=0),
    page_size: int = Query(10, ge=1, le=50),
    filter_type: Optional[str] = Query(None, description="Filter type: 'yes', 'no', or None")
):
    """
    Get markets by category

    Args:
        category: Market category
        page: Page number (0-based)
        page_size: Number of markets per page
        filter_type: Filter by outcome type

    Returns:
        List of markets in the category
    """
    try:
        market_service = get_market_service()
        markets, _ = await market_service.get_category_markets(
            category=category,
            page=page,
            page_size=page_size,
            filter_type=filter_type
        )

        # Convert to response format
        response_markets = []
        for market in markets:
            response_markets.append(MarketResponse(
                id=market.get('id', ''),
                title=market.get('title', ''),
                description=market.get('description'),
                category=market.get('category'),
                active=market.get('active', True),
                volume=market.get('volume'),
                liquidity=market.get('liquidity'),
                created_at=market.get('created_at'),
                updated_at=market.get('updated_at'),
                polymarket_url=market.get('polymarket_url'),
                event_slug=market.get('event_slug')
            ))

        return response_markets

    except Exception as e:
        logger.error(f"Error getting category markets: {e}")
        raise HTTPException(status_code=500, detail=f"Error getting category markets: {str(e)}")


@router.get("/search", response_model=SearchMarketsResponse)
async def search_markets(
    query_text: str = Query(..., min_length=1, max_length=100),
    page: int = Query(0, ge=0),
    page_size: int = Query(10, ge=1, le=50),
    group_by_events: bool = Query(True)
):
    """
    Search markets by title (all terms must be in title)

    Args:
        query_text: Search query (all terms must be in title)
        page: Page number (0-based)
        page_size: Number of markets per page
        group_by_events: Whether to group markets by events

    Returns:
        SearchMarketsResponse with markets and total_count
    """
    try:
        market_service = get_market_service()
        markets, total_count = await market_service.search_markets(
            query_text=query_text,
            page=page,
            page_size=page_size,
            group_by_events=group_by_events
        )

        # Convert to response format (markets can be event groups or individual markets)
        response_markets = []
        for item in markets:
            if item.get('type') == 'event_group':
                # Event group
                response_markets.append(MarketGroupResponse(
                    type='event_group',
                    event_id=item.get('event_id'),
                    event_title=item.get('event_title'),
                    event_slug=item.get('event_slug'),
                    market_count=item.get('market_count'),
                    total_volume=item.get('total_volume'),
                    total_liquidity=item.get('total_liquidity')
                ))
            else:
                # Individual market
                response_markets.append(MarketGroupResponse(
                    type='individual',
                    id=item.get('id', ''),
                    title=item.get('title', ''),
                    description=item.get('description'),
                    category=item.get('category'),
                    active=item.get('active', True),
                    volume=item.get('volume'),
                    liquidity=item.get('liquidity'),
                    created_at=item.get('created_at'),
                    updated_at=item.get('updated_at')
                ))

        return SearchMarketsResponse(
            markets=response_markets,
            total_count=total_count
        )

    except Exception as e:
        logger.error(f"Error searching markets: {e}")
        raise HTTPException(status_code=500, detail=f"Error searching markets: {str(e)}")


@router.get("/events/{event_id}", response_model=EventMarketsResponse)
async def get_event_markets(
    event_id: str,
    page: int = Query(0, ge=0),
    page_size: int = Query(12, ge=1, le=50)
):
    """
    Get all markets for a specific event, sorted by YES probability then volume

    Args:
        event_id: Event identifier
        page: Page number (0-based)
        page_size: Number of markets per page

    Returns:
        EventMarketsResponse with markets for the requested page and pagination info
    """
    try:
        market_service = get_market_service()

        # Get ALL markets for this event first (limited to reasonable number for performance)
        async with get_db() as db:
            from core.database.models import Market
            from sqlalchemy import select

            # Limit total markets fetched to avoid performance issues
            # Most events shouldn't have more than 100-200 markets
            MAX_MARKETS = 500

            # First try to get markets by event_id
            result = await db.execute(
                select(Market)
                .where(Market.event_id == event_id)
                .where(Market.is_event_market == False)  # Only get child markets, not parent events
                .where(Market.is_active == True)
                .where(Market.is_resolved == False)
                .limit(MAX_MARKETS)
            )
            event_markets_db = result.scalars().all()

            # Fallback: If no markets found by event_id, try to find parent event and use event_title
            if not event_markets_db:
                logger.debug(f"No markets found for event_id {event_id}, trying fallback with event_title")
                # Find parent event market to get event_title
                parent_result = await db.execute(
                    select(Market)
                    .where(Market.event_id == event_id)
                    .where(Market.is_event_market == True)
                    .limit(1)
                )
                parent_market = parent_result.scalar_one_or_none()

                if parent_market and parent_market.event_title:
                    # Use event_title to find child markets
                    logger.info(f"Using fallback: searching by event_title '{parent_market.event_title}'")
                    result = await db.execute(
                        select(Market)
                        .where(Market.event_title == parent_market.event_title)
                        .where(Market.is_event_market == False)  # Only get child markets
                        .where(Market.is_active == True)
                        .where(Market.is_resolved == False)
                        .limit(MAX_MARKETS)
                    )
                    event_markets_db = result.scalars().all()
                    if event_markets_db:
                        logger.info(f"Fallback successful: found {len(event_markets_db)} markets by event_title")

        # Convert to response format
        response_markets = []
        for market in event_markets_db:
            # Parse clob_token_ids if it's a JSON string
            clob_token_ids = market.clob_token_ids
            if isinstance(clob_token_ids, str):
                try:
                    clob_token_ids = json.loads(clob_token_ids)
                except (json.JSONDecodeError, TypeError):
                    clob_token_ids = None

            # Filter out markets without valid outcome prices
            outcome_prices = market.outcome_prices
            if not outcome_prices or not isinstance(outcome_prices, list) or len(outcome_prices) < 2:
                continue  # Skip markets without valid outcome prices

            # Filter out markets with placeholder prices [0.5, 0.5]
            try:
                price_0 = float(outcome_prices[0])
                price_1 = float(outcome_prices[1])
                # Skip markets with [0.5, 0.5] placeholder prices
                if abs(price_0 - 0.5) < 0.01 and abs(price_1 - 0.5) < 0.01:
                    continue  # Skip this market
            except (ValueError, TypeError, IndexError):
                continue  # Skip markets with unparseable prices

            # Extract YES price for sorting
            yes_price = None
            if outcome_prices and isinstance(outcome_prices, list) and len(outcome_prices) > 0:
                try:
                    yes_price = float(outcome_prices[0])
                except (ValueError, TypeError, IndexError):
                    yes_price = None

            response_markets.append({
                'market': MarketResponse(
                    id=market.id,
                    title=market.title,
                    description=market.description,
                    category=market.category,
                    outcomes=market.outcomes,
                    outcome_prices=market.outcome_prices,
                    active=market.is_active,
                    volume=float(market.volume) if market.volume else 0.0,
                    liquidity=float(market.liquidity) if market.liquidity else 0.0,
                    clob_token_ids=clob_token_ids if isinstance(clob_token_ids, list) else None,
                    polymarket_url=market.polymarket_url,
                    event_slug=market.event_slug,
                    created_at=market.created_at.isoformat() if market.created_at else None,
                    updated_at=market.updated_at.isoformat() if market.updated_at else None
                ),
                'yes_price': yes_price,
                'volume': float(market.volume) if market.volume else 0.0
            })

        # Sort by YES price DESC (most probable first), then volume DESC
        # Markets without YES price go to the end
        response_markets.sort(
            key=lambda x: (
                x['yes_price'] is not None,  # Non-None prices first
                x['yes_price'] if x['yes_price'] is not None else 0,  # Sort by price descending (higher = more probable YES)
                x['volume']  # Then by volume descending
            ),
            reverse=True
        )

        # Apply pagination on sorted results
        total_count = len(response_markets)
        start_idx = page * page_size
        end_idx = start_idx + page_size
        paginated_markets = response_markets[start_idx:end_idx]
        has_more_pages = end_idx < total_count

        # Extract just the MarketResponse objects
        sorted_markets = [item['market'] for item in paginated_markets]

        return EventMarketsResponse(
            markets=sorted_markets,
            total_count=total_count,
            page=page,
            page_size=page_size,
            has_more_pages=has_more_pages
        )

    except Exception as e:
        logger.error(f"Error getting event markets for event {event_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Error getting event markets: {str(e)}")


@router.get("/events/by-title/{event_title:path}", response_model=List[MarketResponse])
async def get_event_markets_by_title(
    event_title: str,
    page: int = Query(0, ge=0),
    page_size: int = Query(20, ge=1, le=50)
):
    """
    Get all markets for a specific event by title (more robust than ID)

    Args:
        event_title: Event title (URL decoded)
        page: Page number (0-based)
        page_size: Number of markets per page

    Returns:
        List of markets in the event
    """
    try:
        # URL decode the title if needed
        from urllib.parse import unquote
        decoded_title = unquote(event_title)

        # Get markets for this event title
        async with get_db() as db:
            from core.database.models import Market
            from sqlalchemy import select
            result = await db.execute(
                select(Market)
                .where(Market.event_title == decoded_title)
                .where(Market.is_event_market == False)  # Only get child markets, not parent events
                .where(Market.is_active == True)
                .where(Market.is_resolved == False)
                .order_by(Market.volume.desc())
                .limit(page_size)
                .offset(page * page_size)
            )
            event_markets_db = result.scalars().all()

        # Convert to response format
        response_markets = []
        for market in event_markets_db:
            # Parse clob_token_ids if it's a JSON string
            clob_token_ids = market.clob_token_ids
            if isinstance(clob_token_ids, str):
                try:
                    clob_token_ids = json.loads(clob_token_ids)
                except (json.JSONDecodeError, TypeError):
                    clob_token_ids = None

            response_markets.append(MarketResponse(
                id=market.id,
                title=market.title,
                description=market.description,
                category=market.category,
                outcomes=market.outcomes,
                outcome_prices=market.outcome_prices,
                active=market.is_active,
                volume=float(market.volume) if market.volume else 0.0,
                liquidity=float(market.liquidity) if market.liquidity else 0.0,
                clob_token_ids=clob_token_ids if isinstance(clob_token_ids, list) else None,
                created_at=market.created_at.isoformat() if market.created_at else None,
                updated_at=market.updated_at.isoformat() if market.updated_at else None,
                polymarket_url=market.polymarket_url,
                event_slug=market.event_slug
            ))

        return response_markets

    except Exception as e:
        logger.error(f"Error getting event markets by title: {e}")
        raise HTTPException(status_code=500, detail=f"Error getting event markets by title: {str(e)}")


@router.get("/by-condition-id/{condition_id}", response_model=MarketResponse)
async def get_market_by_condition_id(condition_id: str):
    """
    Get market by condition_id (used by WebSocket streamer)

    Supports SKIP_DB=true by using MarketService instead of direct DB access

    Args:
        condition_id: Condition ID (hash hex from Polymarket WebSocket)

    Returns:
        Market details
    """
    try:
        # Check cache first to prevent API spam (use condition_id as cache key)
        current_time = time.time()
        cache_key = f"condition_{condition_id}"
        if cache_key in _market_cache:
            cache_time, cached_data = _market_cache[cache_key]
            if current_time - cache_time < _CACHE_TTL:
                logger.debug(f"✅ [CACHE] Returning cached market data for condition_id {condition_id[:20]}...")
                return cached_data

        logger.debug(f"Searching market by condition_id: {condition_id[:30]}...")
        market_service = get_market_service()
        market = await market_service.get_market_by_condition_id(condition_id)

        if not market:
            logger.debug(f"Market not found by condition_id: {condition_id[:30]}...")
            raise HTTPException(status_code=404, detail=f"Market not found for condition_id: {condition_id[:30]}...")

        # Parse clob_token_ids if it's a JSON string
        clob_token_ids = market.get('clob_token_ids')
        if isinstance(clob_token_ids, str):
            try:
                clob_token_ids = json.loads(clob_token_ids)
            except (json.JSONDecodeError, TypeError):
                clob_token_ids = None

        # Create response
        response = MarketResponse(
            id=market.get('id', ''),
            title=market.get('title', ''),
            description=market.get('description'),
            category=market.get('category'),
            outcomes=market.get('outcomes'),
            outcome_prices=market.get('outcome_prices'),
            active=market.get('is_active', True),
            volume=market.get('volume'),
            liquidity=market.get('liquidity'),
            clob_token_ids=clob_token_ids if isinstance(clob_token_ids, list) else None,
            source=market.get('source'),  # Include source field for price formatting
            created_at=market.get('created_at'),
            updated_at=market.get('updated_at'),
            polymarket_url=market.get('polymarket_url'),
            event_slug=market.get('event_slug')
        )

        # Cache the response to prevent API spam
        _market_cache[cache_key] = (current_time, response)

        # Clean old cache entries (only log if cache is getting large)
        expired_keys = [k for k, (t, _) in _market_cache.items() if current_time - t > _CACHE_TTL]
        for k in expired_keys:
            del _market_cache[k]

        # Only log cache operations if cache is getting large (reduces log spam)
        if len(_market_cache) > 100:
            logger.debug(f"Cached market data for condition_id ({len(_market_cache)} items in cache)")
        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting market by condition_id {condition_id}: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Error getting market: {str(e)}")


@router.get("/by-token-id/{token_id}", response_model=MarketResponse)
async def get_market_by_token_id(token_id: str):
    """
    Get market by token_id (CLOB token ID)

    Used by WebSocket streamer when only token_id is available

    Args:
        token_id: CLOB token ID

    Returns:
        Market details
    """
    try:
        logger.debug(f"Searching market by token_id: {token_id[:30]}...")
        market_service = get_market_service()
        market = await market_service.get_market_by_token_id(token_id)

        if not market:
            logger.debug(f"Market not found by token_id: {token_id[:30]}...")
            raise HTTPException(status_code=404, detail=f"Market not found for token_id: {token_id[:30]}...")

        # Parse clob_token_ids if it's a JSON string
        clob_token_ids = market.get('clob_token_ids')
        if isinstance(clob_token_ids, str):
            try:
                clob_token_ids = json.loads(clob_token_ids)
            except (json.JSONDecodeError, TypeError):
                clob_token_ids = None

        return MarketResponse(
            id=market.get('id', ''),
            title=market.get('title', ''),
            description=market.get('description'),
            category=market.get('category'),
            outcomes=market.get('outcomes'),
            outcome_prices=market.get('outcome_prices'),
            active=market.get('is_active', True),
            volume=market.get('volume'),
            liquidity=market.get('liquidity'),
            clob_token_ids=clob_token_ids if isinstance(clob_token_ids, list) else None,
            source=market.get('source'),  # Include source field for price formatting
            created_at=market.get('created_at'),
            updated_at=market.get('updated_at'),
            polymarket_url=market.get('polymarket_url'),  # Include Polymarket URL
            event_slug=market.get('event_slug')  # Include event slug for URL construction
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting market by token_id {token_id}: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Error getting market: {str(e)}")


@router.get("/{market_id}", response_model=MarketResponse)
async def get_market(market_id: str):
    """
    Get market by ID

    Args:
        market_id: Market identifier

    Returns:
        Market details
    """
    try:
        # Check cache first to prevent API spam
        current_time = time.time()
        if market_id in _market_cache:
            cache_time, cached_data = _market_cache[market_id]
            if current_time - cache_time < _CACHE_TTL:
                logger.debug(f"✅ [CACHE] Returning cached market data for {market_id}")
                return cached_data

        market_service = get_market_service()
        market = await market_service.get_market_by_id(market_id)

        if not market:
            raise HTTPException(status_code=404, detail="Market not found")

        # Parse clob_token_ids if it's a JSON string
        clob_token_ids = market.get('clob_token_ids')
        if isinstance(clob_token_ids, str):
            try:
                clob_token_ids = json.loads(clob_token_ids)
            except (json.JSONDecodeError, TypeError):
                clob_token_ids = None

        # Create response
        response = MarketResponse(
            id=market.get('id', ''),
            title=market.get('title', ''),
            description=market.get('description'),
            category=market.get('category'),
            outcomes=market.get('outcomes'),
            outcome_prices=market.get('outcome_prices'),
            active=market.get('active', True),
            volume=market.get('volume'),
            liquidity=market.get('liquidity'),
            clob_token_ids=clob_token_ids if isinstance(clob_token_ids, list) else None,
            source=market.get('source'),  # Include source field for price formatting
            created_at=market.get('created_at'),
            updated_at=market.get('updated_at'),
            polymarket_url=market.get('polymarket_url'),
            event_slug=market.get('event_slug')
        )

        # Cache the response to prevent API spam
        _market_cache[market_id] = (current_time, response)

        # Clean old cache entries (only log if cache is getting large)
        expired_keys = [k for k, (t, _) in _market_cache.items() if current_time - t > _CACHE_TTL]
        for k in expired_keys:
            del _market_cache[k]

        # Only log cache operations if cache is getting large (reduces log spam)
        if len(_market_cache) > 100:
            logger.debug(f"Cached market data ({len(_market_cache)} items in cache)")
        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting market {market_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Error getting market: {str(e)}")


class BatchMarketsRequest(BaseModel):
    """Request model for batch market fetching"""
    market_ids: List[str]


class BatchMarketsResponse(BaseModel):
    """Response model for batch market fetching"""
    markets: List[MarketResponse]


@router.post("/batch", response_model=BatchMarketsResponse)
async def get_markets_batch(request: BatchMarketsRequest):
    """
    Get multiple markets by IDs in a single request (optimized for performance)

    Args:
        request: BatchMarketsRequest with list of market_ids

    Returns:
        BatchMarketsResponse with all found markets
    """
    try:
        if not request.market_ids:
            return BatchMarketsResponse(markets=[])

        # Limit batch size to prevent abuse
        MAX_BATCH_SIZE = 100
        market_ids = request.market_ids[:MAX_BATCH_SIZE]

        # Remove duplicates while preserving order
        seen = set()
        unique_market_ids = []
        for market_id in market_ids:
            if market_id not in seen:
                seen.add(market_id)
                unique_market_ids.append(market_id)

        # Check cache first for all markets
        current_time = time.time()
        cached_markets = []
        uncached_ids = []

        for market_id in unique_market_ids:
            if market_id in _market_cache:
                cache_time, cached_data = _market_cache[market_id]
                if current_time - cache_time < _CACHE_TTL:
                    cached_markets.append(cached_data)
                    continue
            uncached_ids.append(market_id)

        # Fetch uncached markets from database in a single query
        markets_dict = {}
        if uncached_ids:
            async with get_db() as db:
                from core.database.models import Market
                from sqlalchemy import select
                from core.services.market_service.market_service import _market_to_dict

                result = await db.execute(
                    select(Market).where(Market.id.in_(uncached_ids))
                )
                markets = result.scalars().all()

                for market in markets:
                    # Convert Market object to dict directly
                    market_dict = _market_to_dict(market)

                    # Parse clob_token_ids if needed
                    clob_token_ids = market_dict.get('clob_token_ids')
                    if isinstance(clob_token_ids, str):
                        try:
                            clob_token_ids = json.loads(clob_token_ids)
                        except (json.JSONDecodeError, TypeError):
                            clob_token_ids = None

                    # Create MarketResponse and cache it
                    market_response = MarketResponse(
                        id=market_dict.get('id', ''),
                        title=market_dict.get('title', ''),
                        description=market_dict.get('description'),
                        category=market_dict.get('category'),
                        outcomes=market_dict.get('outcomes'),
                        outcome_prices=market_dict.get('outcome_prices'),
                        active=market_dict.get('active', True),
                        volume=market_dict.get('volume'),
                        liquidity=market_dict.get('liquidity'),
                        clob_token_ids=clob_token_ids if isinstance(clob_token_ids, list) else None,
                        source=market_dict.get('source'),
                        created_at=market_dict.get('created_at'),
                        updated_at=market_dict.get('updated_at'),
                        polymarket_url=market_dict.get('polymarket_url'),
                        event_slug=market_dict.get('event_slug')
                    )

                    # Cache the response
                    _market_cache[market.id] = (current_time, market_response)
                    markets_dict[market.id] = market_response

        # Combine cached and fetched markets
        all_markets = cached_markets + list(markets_dict.values())

        # Clean old cache entries
        expired_keys = [k for k, (t, _) in _market_cache.items() if current_time - t > _CACHE_TTL]
        for k in expired_keys:
            del _market_cache[k]

        logger.debug(f"✅ [BATCH] Returned {len(all_markets)} markets (cached: {len(cached_markets)}, fetched: {len(markets_dict)})")
        return BatchMarketsResponse(markets=all_markets)

    except Exception as e:
        logger.error(f"Error getting markets batch: {e}")
        raise HTTPException(status_code=500, detail=f"Error getting markets batch: {str(e)}")


class UpdateMarketRequest(BaseModel):
    """Request model for updating market prices"""
    outcome_prices: Optional[List[float]] = None
    source: Optional[str] = None
    last_trade_price: Optional[float] = None
    last_mid_price: Optional[float] = None
    is_resolved: Optional[bool] = None
    resolved_outcome: Optional[str] = None


@router.put("/{market_id}", response_model=MarketResponse)
async def update_market(market_id: str, request: UpdateMarketRequest):
    """
    Update market prices (used by WebSocket streamer)

    Args:
        market_id: Market identifier
        request: Market update data

    Returns:
        Updated market details
    """
    try:
        from core.database.connection import get_db
        from core.database.models import Market
        from sqlalchemy import select, update
        from datetime import datetime, timezone

        async with get_db() as db:
            # Check if market exists
            result = await db.execute(
                select(Market).where(Market.id == market_id)
            )
            market = result.scalar_one_or_none()

            if not market:
                raise HTTPException(status_code=404, detail="Market not found")

            # Prepare update data
            update_data = {}
            if request.outcome_prices is not None:
                # ✅ CRITICAL: Ensure prices are stored as numbers (not strings) in JSONB
                # Convert to list of floats explicitly to avoid string serialization
                prices_as_numbers = [float(p) for p in request.outcome_prices] if request.outcome_prices else []
                update_data["outcome_prices"] = prices_as_numbers
            if request.source is not None:
                update_data["source"] = request.source
            if request.last_trade_price is not None:
                update_data["last_trade_price"] = float(request.last_trade_price)
            if request.last_mid_price is not None:
                update_data["last_mid_price"] = float(request.last_mid_price)
            if request.is_resolved is not None:
                update_data["is_resolved"] = request.is_resolved
                if request.is_resolved:
                    update_data["resolved_at"] = datetime.now(timezone.utc)
            if request.resolved_outcome is not None:
                update_data["resolved_outcome"] = request.resolved_outcome

            update_data["updated_at"] = datetime.now(timezone.utc)

            # Update market
            await db.execute(
                update(Market)
                .where(Market.id == market_id)
                .values(**update_data)
            )
            await db.commit()

            # Refresh market from DB
            result = await db.execute(
                select(Market).where(Market.id == market_id)
            )
            updated_market = result.scalar_one_or_none()

            # ✅ CRITICAL: Update positions for this market when prices change (microservices coherence)
            # This ensures positions are updated in DB when market prices change via WebSocket
            # The API service (SKIP_DB=false) handles position updates directly
            if request.outcome_prices is not None and len(request.outcome_prices) >= 2:
                try:
                    from core.services.position.position_service import position_service
                    from data_ingestion.streamer.market_updater.position.position_update_handler import PositionUpdateHandler

                    # Use PositionUpdateHandler to update positions (it handles DB updates)
                    # Note: PositionUpdateHandler skips updates if SKIP_DB=true, but API service has SKIP_DB=false
                    position_handler = PositionUpdateHandler(position_service=position_service)
                    await position_handler.update_positions_for_market(
                        market_id=market_id,
                        prices=request.outcome_prices
                    )
                    logger.debug(f"✅ Updated positions for market {market_id} after price change")
                except Exception as pos_error:
                    # Non-fatal: log but don't fail the market update
                    logger.warning(f"⚠️ Failed to update positions for market {market_id}: {pos_error}")

            # Invalidate cache
            # ✅ CRITICAL: Invalidate all cache keys for this market to ensure fresh data
            # This includes both internal cache keys and API client cache keys
            try:
                from core.services.cache_manager import CacheManager
                cache_manager = CacheManager()
                # Internal cache keys (used by MarketService)
                await cache_manager.delete(f"market:{market_id}")
                await cache_manager.delete(f"market_detail:{market_id}")
                await cache_manager.delete(f"price:{market_id}")
                if updated_market.condition_id:
                    await cache_manager.delete(f"market_by_condition:{updated_market.condition_id}")
                # API client cache keys (used by bot when SKIP_DB=true)
                await cache_manager.delete(f"api:market:{market_id}")
                await cache_manager.invalidate_pattern(f"api:markets:*")
                logger.debug(f"✅ Cache invalidated for market {market_id} (including API client cache)")
            except Exception as cache_error:
                logger.warning(f"⚠️ Cache invalidation failed: {cache_error}")

            # Parse clob_token_ids if needed
            clob_token_ids = updated_market.clob_token_ids
            if isinstance(clob_token_ids, str):
                try:
                    clob_token_ids = json.loads(clob_token_ids)
                except (json.JSONDecodeError, TypeError):
                    clob_token_ids = None

            return MarketResponse(
                id=updated_market.id,
                title=updated_market.title,
                description=updated_market.description,
                category=updated_market.category,
                outcomes=updated_market.outcomes,
                outcome_prices=updated_market.outcome_prices,
                active=updated_market.is_active,
                volume=float(updated_market.volume) if updated_market.volume else None,
                liquidity=float(updated_market.liquidity) if updated_market.liquidity else None,
                clob_token_ids=clob_token_ids if isinstance(clob_token_ids, list) else None,
                source=updated_market.source,  # Include source field for price formatting
                created_at=updated_market.created_at.isoformat() if updated_market.created_at else None,
                updated_at=updated_market.updated_at.isoformat() if updated_market.updated_at else None,
                polymarket_url=updated_market.polymarket_url,
                event_slug=updated_market.event_slug
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating market {market_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Error updating market: {str(e)}")


@router.post("/fetch/{market_id}", response_model=MarketResponse)
async def fetch_market_on_demand(market_id: str):
    """
    Fetch market from Gamma API and update DB on-demand
    Useful for accessing markets not in the top 500 (not polled automatically)

    Args:
        market_id: Market identifier from Polymarket

    Returns:
        Market details after fetching and updating DB

    Performance: ~0.07s (API fetch ~0.06s + DB upsert ~0.01s)
    """
    try:
        logger.info(f"🚀 fetch_market_on_demand called for market {market_id}")
        # Import locally to avoid module-level dependency in API service
        from data_ingestion.poller.base_poller import BaseGammaAPIPoller

        # Create a temporary poller instance to reuse upsert logic
        temp_poller = BaseGammaAPIPoller()

        # Fetch market from Gamma API
        api_url = settings.polymarket.gamma_api_base
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{api_url}/markets/{market_id}")

            if response.status_code == 404:
                raise HTTPException(status_code=404, detail=f"Market {market_id} not found in Polymarket API")

            response.raise_for_status()
            market_data = response.json()

        # Parse and prepare market data (similar to poller logic)
        # The API returns a single market object, not a list
        market_dict = {
            'id': market_data.get('id'),
            'question': market_data.get('question'),
            'description': market_data.get('description'),
            'category': market_data.get('category'),
            'outcomes': market_data.get('outcomes'),
            'outcomePrices': market_data.get('outcomePrices'),
            'events': market_data.get('events'),
            'volume': market_data.get('volume'),
            'liquidity': market_data.get('liquidity'),
            'lastTradePrice': market_data.get('lastTradePrice'),
            'clobTokenIds': market_data.get('clobTokenIds'),
            'conditionId': market_data.get('conditionId'),
            'resolvedBy': market_data.get('resolvedBy'),
            'closedTime': market_data.get('closedTime'),
            'closed': market_data.get('closed', False),
            'startDate': market_data.get('startDate'),
            'endDate': market_data.get('endDate'),
            'slug': market_data.get('slug'),
        }

        # Extract event info if present
        events = market_data.get('events', [])
        if events and len(events) > 0:
            event = events[0] if isinstance(events[0], dict) else events[0]
            market_dict['event_id'] = event.get('id')
            market_dict['event_slug'] = event.get('slug')
            market_dict['event_title'] = event.get('title')
        else:
            # If no event data in market, try to find it by searching events
            # This happens when /markets/{id} doesn't include event info
            market_dict['event_id'] = None
            market_dict['event_slug'] = None
            market_dict['event_title'] = None

            # Try to find event data by searching through events API
            try:
                # Get market question for matching
                market_question = market_dict.get('question', '').lower()
                logger.info(f"🔍 Checking event data for market {market_id}: '{market_question}'")

                # Search for Super Bowl pattern and try to match
                if 'super bowl' in market_question and 'win super bowl' in market_question:
                    logger.info(f"🎯 Super Bowl pattern detected for market {market_id}")
                    # This is likely a Super Bowl team market
                    # Search for Super Bowl 2026 event
                    async with httpx.AsyncClient(timeout=10.0) as event_client:
                        logger.info(f"📡 Fetching events from API for market {market_id}")
                        events_response = await event_client.get(
                            f"{settings.polymarket.gamma_api_base}/events",
                            params={
                                'limit': 50,
                                'closed': False,
                                'order': 'volume',
                                'ascending': False
                            }
                        )
                        events_response.raise_for_status()
                        events_data = events_response.json()
                        logger.info(f"📦 Received {len(events_data) if events_data else 0} events from API")

                        if events_data:
                            for event_item in events_data:
                                event_title = event_item.get('title', '').lower()
                                logger.info(f"🔍 Checking event: '{event_title}'")
                                if 'super bowl' in event_title and '2026' in event_title:
                                    # Found Super Bowl 2026 event
                                    market_dict['event_id'] = str(event_item.get('id'))
                                    market_dict['event_slug'] = event_item.get('slug')
                                    market_dict['event_title'] = event_item.get('title')
                                    logger.info(f"✅ Found event data for Super Bowl market {market_id}: {market_dict['event_id']} - {market_dict['event_title']}")
                                    break
                        else:
                            logger.warning(f"❌ No events data received from API for market {market_id}")

                # Could extend this for other event patterns (NFL, NBA, etc.)

            except Exception as event_error:
                logger.error(f"❌ Failed to fetch event data for market {market_id}: {event_error}")
                import traceback
                logger.error(f"   Traceback: {traceback.format_exc()}")
                # Continue without event data - not critical for market function

        # Upsert to DB using poller's upsert logic
        upserted = await temp_poller._upsert_markets([market_dict])

        if upserted == 0:
            logger.warning(f"Failed to upsert market {market_id} to DB")

        # Fetch from DB to return fresh data
        market_service = get_market_service()
        market = await market_service.get_market_by_id(market_id)

        if not market:
            raise HTTPException(status_code=500, detail="Market fetched but not found in DB after upsert")

        logger.info(f"✅ On-demand fetch completed for market {market_id}")

        # Parse clob_token_ids if it's a JSON string
        clob_token_ids = market.get('clob_token_ids')
        if isinstance(clob_token_ids, str):
            try:
                clob_token_ids = json.loads(clob_token_ids)
            except (json.JSONDecodeError, TypeError):
                clob_token_ids = None

        return MarketResponse(
            id=market.get('id', ''),
            title=market.get('title', ''),
            description=market.get('description'),
            category=market.get('category'),
            active=market.get('active', True),
            volume=market.get('volume'),
            liquidity=market.get('liquidity'),
            clob_token_ids=clob_token_ids if isinstance(clob_token_ids, list) else None,
            created_at=market.get('created_at'),
            updated_at=market.get('updated_at'),
            polymarket_url=market.get('polymarket_url'),
            event_slug=market.get('event_slug')
        )

    except HTTPException:
        raise
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error fetching market {market_id} from API: {e}")
        raise HTTPException(status_code=e.response.status_code, detail=f"Error fetching market from Polymarket API: {str(e)}")
    except Exception as e:
        logger.error(f"Error fetching market on-demand {market_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Error fetching market: {str(e)}")
