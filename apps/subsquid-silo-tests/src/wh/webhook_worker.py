"""
Webhook Worker Service
Exposes FastAPI endpoint /wh/market for receiving webhook events.
Upserts events to subsquid_markets_wh table.
"""

import logging
import asyncio
from datetime import datetime, timezone
from typing import Optional, Dict, Any
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel

from ..config import settings, validate_experimental_subsquid
from ..db.client import get_db_client, close_db_client

logger = logging.getLogger(__name__)

# ========================================
# FastAPI Setup
# ========================================
app = FastAPI(
    title="Subsquid Silo Webhook Worker",
    version="1.0.0",
    description="Receives webhook events and stores them in subsquid_markets_wh"
)

# ========================================
# Models
# ========================================
class WebhookEvent(BaseModel):
    """Webhook event model"""
    market_id: str
    event: str
    payload: Optional[Dict[str, Any]] = {}
    timestamp: Optional[datetime] = None


class WebhookResponse(BaseModel):
    """Standard webhook response"""
    status: str
    message: Optional[str] = None
    id: Optional[int] = None


# ========================================
# Metrics
# ========================================
class WebhookMetrics:
    """Track webhook metrics"""
    def __init__(self):
        self.event_count = 0
        self.success_count = 0
        self.error_count = 0
        self.last_event_time = None


metrics = WebhookMetrics()


# ========================================
# Endpoints
# ========================================

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "events_received": metrics.event_count,
        "success_count": metrics.success_count,
        "error_count": metrics.error_count,
    }


@app.post("/wh/market")
async def receive_webhook(event: WebhookEvent) -> WebhookResponse:
    """
    Receive webhook event for market.

    Expected payload:
    {
        "market_id": "0x...",
        "event": "market.status.active",
        "payload": {...},
        "timestamp": "2025-11-21T14:30:00Z"
    }
    """
    try:
        metrics.event_count += 1
        metrics.last_event_time = datetime.now(timezone.utc)

        # Validate required fields
        if not event.market_id:
            raise ValueError("market_id is required")
        if not event.event:
            raise ValueError("event is required")

        # Use provided timestamp or current time
        timestamp = event.timestamp or datetime.now(timezone.utc)

        # Insert into database
        db = await get_db_client()
        event_id = await db.insert_webhook_event(
            market_id=event.market_id,
            event=event.event,
            payload=event.payload or {},
            timestamp=timestamp
        )

        if event_id:
            metrics.success_count += 1
            logger.info(
                f"✅ Webhook event #{event_id} received: {event.event} for {event.market_id}"
            )
            return WebhookResponse(
                status="ok",
                message="Event stored successfully",
                id=event_id
            )
        else:
            metrics.error_count += 1
            logger.error(f"❌ Failed to store webhook event for {event.market_id}")
            raise HTTPException(status_code=500, detail="Failed to store event")

    except ValueError as e:
        metrics.error_count += 1
        logger.warning(f"⚠️ Validation error: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        metrics.error_count += 1
        logger.error(f"❌ Webhook processing error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/metrics")
async def get_metrics():
    """Get webhook metrics"""
    return {
        "event_count": metrics.event_count,
        "success_count": metrics.success_count,
        "error_count": metrics.error_count,
        "success_rate": (
            metrics.success_count / metrics.event_count * 100
            if metrics.event_count > 0 else 0
        ),
        "last_event_time": metrics.last_event_time.isoformat() if metrics.last_event_time else None,
    }


@app.get("/")
async def root():
    """Root endpoint - API documentation"""
    return {
        "name": "Subsquid Silo Webhook Worker",
        "version": "1.0.0",
        "endpoints": {
            "health": "GET /health",
            "webhook": "POST /wh/market",
            "metrics": "GET /metrics",
        }
    }


# ========================================
# Lifecycle Events
# ========================================

@app.on_event("startup")
async def startup_event():
    """Initialize on startup"""
    logger.info("🚀 Webhook worker starting up...")
    validate_experimental_subsquid()

    # Initialize database
    try:
        db = await get_db_client()
        logger.info("✅ Database initialized")
    except Exception as e:
        logger.error(f"❌ Failed to initialize database: {e}")
        raise


@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown"""
    logger.info("⏹️ Webhook worker shutting down...")
    await close_db_client()
    logger.info("✅ Database connection closed")


# ========================================
# Standalone Runner
# ========================================

class WebhookWorker:
    """Webhook worker orchestrator"""

    def __init__(self):
        self.enabled = settings.WEBHOOK_ENABLED
        self.host = settings.WEBHOOK_LISTEN_HOST
        self.port = settings.WEBHOOK_LISTEN_PORT

    async def start(self):
        """Start the webhook worker"""
        if not self.enabled:
            logger.warning("⚠️ Webhook worker disabled (WEBHOOK_ENABLED=false)")
            return

        validate_experimental_subsquid()
        logger.info(f"🚀 Starting webhook worker on {self.host}:{self.port}...")

        config = uvicorn.Config(
            app=app,
            host=self.host,
            port=self.port,
            log_level=settings.LOG_LEVEL.lower(),
        )
        server = uvicorn.Server(config)
        await server.serve()


# Global instance
_worker_instance: Optional[WebhookWorker] = None


async def get_webhook_worker() -> WebhookWorker:
    """Get or create webhook worker instance"""
    global _worker_instance
    if _worker_instance is None:
        _worker_instance = WebhookWorker()
    return _worker_instance


# ========================================
# Entry Point
# ========================================

if __name__ == "__main__":
    import sys

    logging.basicConfig(
        format=settings.LOG_FORMAT,
        level=settings.LOG_LEVEL
    )

    async def main():
        worker = await get_webhook_worker()
        await worker.start()

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Webhook worker stopped")
        sys.exit(0)
