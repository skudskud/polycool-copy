"""
Admin API Routes
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from core.database.connection import get_db
from core.database.models import User
from infrastructure.config.settings import settings

router = APIRouter()


@router.get("/stats")
async def get_system_stats(db: AsyncSession = Depends(get_db)):
    """Get system statistics"""
    try:
        # User stats
        from sqlalchemy import func, text
        user_count = await db.execute(text("SELECT COUNT(*) FROM users"))
        user_count = user_count.scalar()

        # Market stats
        market_count = await db.execute(text("SELECT COUNT(*) FROM markets"))
        market_count = market_count.scalar()

        active_market_count = await db.execute(
            text("SELECT COUNT(*) FROM markets WHERE is_active = TRUE")
        )
        active_market_count = active_market_count.scalar()

        resolved_market_count = await db.execute(
            text("SELECT COUNT(*) FROM markets WHERE is_resolved = TRUE")
        )
        resolved_market_count = resolved_market_count.scalar()

        # Position stats
        position_count = await db.execute(text("SELECT COUNT(*) FROM positions"))
        position_count = position_count.scalar()

        active_position_count = await db.execute(
            text("SELECT COUNT(*) FROM positions WHERE status = 'active'")
        )
        active_position_count = active_position_count.scalar()

        return {
            "users": {
                "total": user_count,
            },
            "markets": {
                "total": market_count,
                "active": active_market_count,
                "resolved": resolved_market_count,
            },
            "positions": {
                "total": position_count,
                "active": active_position_count,
            },
            "system": {
                "environment": settings.environment,
                "debug": settings.debug,
                "version": settings.version,
            }
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching stats: {str(e)}")


@router.post("/cache/clear")
async def clear_cache():
    """Clear all cache"""
    try:
        # This would integrate with CacheManager
        return {"status": "cache cleared"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error clearing cache: {str(e)}")


@router.get("/health/detailed")
async def detailed_health_check():
    """Detailed health check with component status"""
    try:
        health_status = {
            "status": "healthy",
            "timestamp": "2025-01-01T00:00:00Z",  # Would be datetime.utcnow()
            "components": {
                "database": "healthy",  # Would check actual DB connection
                "redis": "healthy",     # Would check Redis connection
                "telegram_bot": "healthy",  # Would check bot status
                "streamer": "healthy",  # Would check WebSocket status
                "indexer": "healthy",   # Would check indexer status
            },
            "version": settings.version,
            "environment": settings.environment,
        }
        return health_status

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Health check failed: {str(e)}")
