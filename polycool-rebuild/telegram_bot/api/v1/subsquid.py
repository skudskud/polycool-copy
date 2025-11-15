"""
Subsquid Integration Routes
Provides endpoints for indexer-ts integration
"""
from typing import List, Dict, Any
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database.connection import get_db
from core.database.models import WatchedAddress
from infrastructure.logging.logger import get_logger

logger = get_logger(__name__)

router = APIRouter()


@router.get("/watched_addresses", response_model=List[Dict[str, Any]])
async def get_watched_addresses(db: AsyncSession = Depends(get_db)) -> List[Dict[str, Any]]:
    """
    Get all watched addresses for indexer-ts
    Returns addresses that the indexer should monitor for trades
    """
    try:
        # Get all active watched addresses
        result = await db.execute(
            select(WatchedAddress)
            .where(WatchedAddress.is_active == True)
            .order_by(WatchedAddress.created_at)
        )
        watched_addresses = result.scalars().all()

        # Format for indexer (map types to indexer expectations)
        addresses = []
        for addr in watched_addresses:
            # Map address_type to what indexer expects
            indexer_type = addr.address_type
            if addr.address_type == 'copy_leader':
                indexer_type = 'external_leader'  # Indexer expects 'external_leader'
            # smart_wallet stays as 'smart_wallet'

            addresses.append({
                "address": addr.address.lower(),
                "type": indexer_type,  # Indexer expects 'type' field, not 'address_type'
                "created_at": addr.created_at.isoformat() if addr.created_at else None,
                "last_seen": addr.last_tracked_at.isoformat() if addr.last_tracked_at else None,
            })

        logger.info(f"📋 Returning {len(addresses)} watched addresses to indexer")
        return addresses

    except Exception as e:
        logger.error(f"❌ Error fetching watched addresses: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")
