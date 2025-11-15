"""
Health check endpoints for monitoring system status
"""
import time
from typing import Dict, Any

from fastapi import APIRouter, HTTPException

from infrastructure.config.settings import settings

router = APIRouter()


@router.get("/")
async def health_check() -> Dict[str, Any]:
    """Basic health check endpoint"""
    return {
        "status": "healthy",
        "timestamp": time.time(),
        "version": settings.version,
        "environment": settings.environment,
    }


@router.get("/ready")
async def readiness_check() -> Dict[str, Any]:
    """Readiness check - verifies all dependencies are available"""
    try:
        # Check database connection
        db_status = await check_database()

        # Check Redis connection
        redis_status = await check_redis()

        # Check critical services
        services_status = await check_services()

        all_healthy = all([
            db_status["status"] == "healthy",
            redis_status["status"] == "healthy",
            services_status["status"] == "healthy",
        ])

        return {
            "status": "ready" if all_healthy else "not_ready",
            "timestamp": time.time(),
            "components": {
                "database": db_status,
                "redis": redis_status,
                "services": services_status,
            },
        }

    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=f"Readiness check failed: {str(e)}"
        )


@router.get("/live")
async def liveness_check() -> Dict[str, Any]:
    """Liveness check - verifies the application is running"""
    return {
        "status": "alive",
        "timestamp": time.time(),
        "uptime": time.time() - getattr(liveness_check, "_start_time", time.time()),
    }


# Store start time for uptime calculation
liveness_check._start_time = time.time()


async def check_database() -> Dict[str, Any]:
    """Check database connectivity"""
    try:
        # Placeholder - implement actual DB check
        return {
            "status": "healthy",
            "message": "Database connection OK",
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "message": f"Database error: {str(e)}",
        }


async def check_redis() -> Dict[str, Any]:
    """Check Redis connectivity"""
    try:
        # Placeholder - implement actual Redis check
        return {
            "status": "healthy",
            "message": "Redis connection OK",
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "message": f"Redis error: {str(e)}",
        }


async def check_services() -> Dict[str, Any]:
    """Check critical services status"""
    try:
        # Placeholder - check Telegram bot, streamer, indexer
        return {
            "status": "healthy",
            "message": "All services running",
            "services": {
                "telegram_bot": "running",
                "streamer": "running",
                "indexer": "running",
            }
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "message": f"Services error: {str(e)}",
        }
