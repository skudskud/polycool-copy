"""
Copy Trading Helper Functions
Shared utilities for copy trading operations
"""
import os
from typing import Dict, Optional
from core.database.connection import get_db
from core.database.models import WatchedAddress
from sqlalchemy import select

SKIP_DB = os.getenv("SKIP_DB", "true").lower() == "true"

if SKIP_DB:
    from core.services.api_client import get_api_client


async def get_leader_stats(
    watched_address_id: int,
    polygon_address: str
) -> Dict:
    """
    Get leader statistics - handles SKIP_DB automatically

    Args:
        watched_address_id: WatchedAddress ID
        polygon_address: Fallback address if not found

    Returns:
        Dict with leader stats containing:
        - address: Leader address
        - name: Leader name (optional)
        - total_trades: Total number of trades
        - win_rate: Win rate percentage (optional)
        - total_volume: Total volume traded
        - risk_score: Risk score (optional)
    """
    if SKIP_DB:
        api_client = get_api_client()
        watched_addr_data = await api_client.get_watched_address(watched_address_id)
        if watched_addr_data:
            return {
                'address': watched_addr_data.get('address', polygon_address),
                'name': watched_addr_data.get('name'),
                'total_trades': watched_addr_data.get('total_trades', 0),
                'win_rate': watched_addr_data.get('win_rate'),
                'total_volume': watched_addr_data.get('total_volume', 0.0),
                'risk_score': watched_addr_data.get('risk_score')
            }
    else:
        async with get_db() as db:
            result = await db.execute(
                select(WatchedAddress).where(WatchedAddress.id == watched_address_id)
            )
            watched_addr = result.scalar_one_or_none()

            if watched_addr:
                return {
                    'address': watched_addr.address,
                    'name': watched_addr.name,
                    'total_trades': watched_addr.total_trades or 0,
                    'win_rate': (watched_addr.win_rate * 100) if watched_addr.win_rate else None,
                    'total_volume': watched_addr.total_volume or 0.0,
                    'risk_score': watched_addr.risk_score
                }

    # Fallback if not found
    return {
        'address': polygon_address,
        'name': None,
        'total_trades': 0,
        'win_rate': None,
        'total_volume': 0.0,
        'risk_score': None
    }
