"""
Alert Channel Bot - Main Entry Point
FastAPI application for receiving trade notifications and sending to Telegram channel
"""
import logging
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from fastapi import FastAPI
from fastapi.responses import JSONResponse
import uvicorn

from config import settings
from webhook_handler import router as webhook_router
from poller import get_poller

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    # Startup
    logger.info("🚀 Starting Alert Channel Bot...")
    logger.info(f"📊 Configuration:")
    logger.info(f"   - Channel: {settings.telegram_channel_id}")
    logger.info(f"   - Poll Interval: {settings.poll_interval_seconds}s")
    logger.info(f"   - Rate Limit: {settings.rate_limit_max_per_hour}/hour")
    logger.info(f"   - Min Trade Value: ${settings.min_trade_value}")
    logger.info(f"   - Min Win Rate: {settings.min_win_rate * 100}%")
    logger.info(f"   - Min Smart Score: {settings.min_smart_score}")
    logger.info(f"   - Max Price: ${settings.max_price}")
    logger.info(f"   - Max Age: {settings.max_age_minutes} minutes")
    
    # Start poller (fallback mechanism)
    poller = get_poller()
    await poller.start()
    logger.info("✅ Poller started (fallback mechanism)")
    
    yield
    
    # Shutdown
    logger.info("🛑 Shutting down Alert Channel Bot...")
    await poller.stop()
    logger.info("✅ Shutdown complete")


# Create FastAPI app
app = FastAPI(
    title="Alert Channel Bot",
    description="Receives trade notifications and sends to Telegram alert channel",
    version="1.0.0",
    lifespan=lifespan
)

# Include routers
app.include_router(webhook_router)


@app.get("/health")
async def health_check():
    """Health check endpoint for Railway"""
    return JSONResponse({
        "status": "healthy",
        "service": "alert-channel-bot",
        "timestamp": str(datetime.now(timezone.utc))
    })


@app.get("/")
async def root():
    """Root endpoint"""
    return JSONResponse({
        "service": "alert-channel-bot",
        "status": "running",
        "endpoints": {
            "health": "/health",
            "webhook": "/api/v1/alert-channel/notify"
        }
    })


if __name__ == "__main__":
    import os
    # Railway sets PORT environment variable automatically
    port = int(os.getenv("PORT", settings.alert_webhook_port))
    logger.info(f"🌐 Starting server on port {port}...")
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        log_level=settings.log_level.lower(),
        reload=False
    )

