"""
Subsquid API endpoints for indexer-ts integration
"""
from datetime import datetime, timezone
from typing import List, Dict, Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from data_ingestion.indexer.watched_addresses.manager import get_watched_addresses_manager
from infrastructure.logging.logger import get_logger

logger = get_logger(__name__)

router = APIRouter()


class WatchedAddressResponse(BaseModel):
    """Watched address item for indexer-ts"""
    address: str
    type: str  # 'external_leader' or 'smart_wallet'
    user_id: int | None = None


class WatchedAddressesResponse(BaseModel):
    """Response format for /subsquid/watched_addresses"""
    addresses: List[WatchedAddressResponse]
    total: int
    timestamp: str
    cached: bool


@router.get("/watched_addresses", response_model=WatchedAddressesResponse)
async def get_watched_addresses() -> WatchedAddressesResponse:
    """
    Return all addresses to watch for copy trading (from database, not cache)
    Used by indexer-ts to filter transactions at source.
    Format compatible with indexer-ts watched-addresses.ts

    Returns:
        {
            "addresses": [
                {"address": "0x...", "type": "external_leader", "user_id": null},
                {"address": "0x...", "type": "smart_wallet", "user_id": null}
            ],
            "total": 42,
            "timestamp": "2025-11-06T17:30:00Z",
            "cached": false
        }
    """
    try:
        # Import here to avoid circular imports
        from sqlalchemy import select
        from core.database.connection import get_db
        from core.database.models import WatchedAddress

        async with get_db() as db:
            # Get all active watched addresses
            result = await db.execute(
                select(WatchedAddress)
                .where(WatchedAddress.is_active == True)
                .order_by(WatchedAddress.created_at)
            )
            watched_addresses = result.scalars().all()

        # Format addresses for indexer-ts
        # Map: 'smart_trader' -> 'smart_wallet', 'copy_leader' -> 'external_leader'
        addresses: List[WatchedAddressResponse] = []

        for addr in watched_addresses:
            # Map address_type to what indexer expects
            indexer_type = addr.address_type
            if addr.address_type == 'copy_leader':
                indexer_type = 'external_leader'  # Indexer expects 'external_leader'
            # smart_wallet stays as 'smart_wallet'

            addresses.append(
                WatchedAddressResponse(
                    address=addr.address.lower(),
                    type=indexer_type,
                    user_id=addr.user_id
                )
            )

        timestamp = datetime.now(timezone.utc).isoformat()

        logger.info(f"[SUBSQUID] Watched addresses from DB: {len(addresses)} total")

        return WatchedAddressesResponse(
            addresses=addresses,
            total=len(addresses),
            timestamp=timestamp,
            cached=False  # Direct from database, not cached
        )

    except Exception as e:
        logger.error(f"❌ Error fetching watched addresses from DB: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch watched addresses: {str(e)}"
        )
