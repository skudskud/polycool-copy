"""
Copy Trading Helper Functions
Shared utilities for copy trading operations that work with both SKIP_DB=true and SKIP_DB=false
"""
import os
from typing import List, Dict, Optional, Any
from datetime import datetime, timezone

from infrastructure.logging.logger import get_logger

logger = get_logger(__name__)

# Check if bot has DB access
SKIP_DB = os.getenv("SKIP_DB", "true").lower() == "true"

# Import API client only if SKIP_DB is true
if SKIP_DB:
    from core.services.api_client import get_api_client


async def get_user_allocations(user_id: int) -> List[Dict[str, Any]]:
    """
    Get all copy trading allocations for a user

    Args:
        user_id: Internal user ID

    Returns:
        List of allocation dictionaries
    """
    if SKIP_DB:
        api_client = get_api_client()
        return await api_client.get_copy_trading_allocations(user_id)
    else:
        from core.database.connection import get_db
        from core.database.models import CopyTradingAllocation
        from sqlalchemy import select, desc

        try:
            async with get_db() as db:
                result = await db.execute(
                    select(CopyTradingAllocation)
                    .where(CopyTradingAllocation.user_id == user_id)
                    .order_by(desc(CopyTradingAllocation.created_at))
                )
                allocations = result.scalars().all()
                return [allocation.__dict__ for allocation in allocations]
        except Exception as e:
            logger.error(f"Error getting user allocations: {e}")
            return []


async def get_allocation_by_id(allocation_id: int) -> Optional[Dict[str, Any]]:
    """
    Get a specific copy trading allocation by ID

    Args:
        allocation_id: Allocation ID

    Returns:
        Allocation dictionary or None
    """
    if SKIP_DB:
        api_client = get_api_client()
        return await api_client.get_copy_trading_allocation(allocation_id)
    else:
        from core.database.connection import get_db
        from core.database.models import CopyTradingAllocation
        from sqlalchemy import select

        try:
            async with get_db() as db:
                result = await db.execute(
                    select(CopyTradingAllocation)
                    .where(CopyTradingAllocation.id == allocation_id)
                )
                allocation = result.scalar_one_or_none()
                return allocation.__dict__ if allocation else None
        except Exception as e:
            logger.error(f"Error getting allocation by ID: {e}")
            return None


async def create_allocation(
    user_id: int,
    leader_address_id: int,
    allocation_type: str = 'percentage',
    allocation_value: float = 50.0,
    mode: str = 'proportional',
    sell_mode: str = 'proportional',
    is_active: bool = True
) -> Optional[Dict[str, Any]]:
    """
    Create a new copy trading allocation

    Args:
        user_id: Internal user ID
        leader_address_id: WatchedAddress ID for the leader
        allocation_type: 'percentage' or 'fixed'
        allocation_value: Allocation value (percentage or amount)
        mode: 'proportional' or 'fixed'
        sell_mode: 'proportional' or 'fixed'
        is_active: Whether allocation is active

    Returns:
        Created allocation dictionary or None
    """
    if SKIP_DB:
        api_client = get_api_client()
        return await api_client.create_copy_trading_allocation(
            user_id=user_id,
            leader_address_id=leader_address_id,
            allocation_type=allocation_type,
            allocation_value=allocation_value,
            mode=mode,
            sell_mode=sell_mode,
            is_active=is_active
        )
    else:
        from core.database.connection import get_db
        from core.database.models import CopyTradingAllocation

        try:
            async with get_db() as db:
                allocation = CopyTradingAllocation(
                    user_id=user_id,
                    leader_address_id=leader_address_id,
                    allocation_type=allocation_type,
                    allocation_value=allocation_value,
                    mode=mode,
                    sell_mode=sell_mode,
                    is_active=is_active,
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc)
                )
                db.add(allocation)
                await db.commit()
                await db.refresh(allocation)
                return allocation.__dict__
        except Exception as e:
            logger.error(f"Error creating allocation: {e}")
            return None


async def update_allocation(
    allocation_id: int,
    **updates
) -> Optional[Dict[str, Any]]:
    """
    Update a copy trading allocation

    Args:
        allocation_id: Allocation ID
        updates: Fields to update

    Returns:
        Updated allocation dictionary or None
    """
    if SKIP_DB:
        api_client = get_api_client()
        return await api_client.update_copy_trading_allocation(allocation_id, updates)
    else:
        from core.database.connection import get_db
        from core.database.models import CopyTradingAllocation
        from sqlalchemy import update

        try:
            async with get_db() as db:
                # Add updated_at timestamp
                updates['updated_at'] = datetime.now(timezone.utc)

                await db.execute(
                    update(CopyTradingAllocation)
                    .where(CopyTradingAllocation.id == allocation_id)
                    .values(**updates)
                )
                await db.commit()

                # Return updated allocation
                return await get_allocation_by_id(allocation_id)
        except Exception as e:
            logger.error(f"Error updating allocation: {e}")
            return None


async def get_or_create_watched_address(
    address: str,
    blockchain: str = 'polygon',
    address_type: str = 'copy_leader',
    name: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """
    Get or create a watched address

    Args:
        address: Blockchain address
        blockchain: Blockchain type
        address_type: Address type
        name: Optional name

    Returns:
        WatchedAddress dictionary or None
    """
    if SKIP_DB:
        api_client = get_api_client()
        return await api_client.get_or_create_watched_address(
            address=address,
            blockchain=blockchain,
            address_type=address_type,
            name=name
        )
    else:
        from core.database.connection import get_db
        from core.database.models import WatchedAddress
        from sqlalchemy import select

        try:
            async with get_db() as db:
                # Try to find existing
                result = await db.execute(
                    select(WatchedAddress)
                    .where(WatchedAddress.address == address.lower())
                )
                watched_address = result.scalar_one_or_none()

                if not watched_address:
                    # Create new
                    watched_address = WatchedAddress(
                        address=address.lower(),
                        blockchain=blockchain,
                        address_type=address_type,
                        name=name or f"Leader {address[:10]}...",
                        is_active=True,
                        created_at=datetime.now(timezone.utc),
                        updated_at=datetime.now(timezone.utc)
                    )
                    db.add(watched_address)
                    await db.flush()

                return watched_address.__dict__
        except Exception as e:
            logger.error(f"Error getting/creating watched address: {e}")
            return None


async def check_existing_allocation(
    user_id: int,
    leader_address_id: int
) -> Optional[Dict[str, Any]]:
    """
    Check if user already has an allocation for a leader

    Args:
        user_id: Internal user ID
        leader_address_id: WatchedAddress ID

    Returns:
        Existing allocation dictionary or None
    """
    if SKIP_DB:
        api_client = get_api_client()
        allocations = await api_client.get_copy_trading_allocations(user_id)
        for alloc in allocations:
            if alloc.get('leader_address_id') == leader_address_id:
                return alloc
        return None
    else:
        from core.database.connection import get_db
        from core.database.models import CopyTradingAllocation
        from sqlalchemy import select, and_

        try:
            async with get_db() as db:
                result = await db.execute(
                    select(CopyTradingAllocation)
                    .where(
                        and_(
                            CopyTradingAllocation.user_id == user_id,
                            CopyTradingAllocation.leader_address_id == leader_address_id
                        )
                    )
                )
                allocation = result.scalar_one_or_none()
                return allocation.__dict__ if allocation else None
        except Exception as e:
            logger.error(f"Error checking existing allocation: {e}")
            return None
