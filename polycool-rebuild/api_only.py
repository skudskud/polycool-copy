#!/usr/bin/env python3
"""
API-only entrypoint for Railway deployment.
Starts FastAPI without launching Telegram bot or background workers.
"""

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware

from core.database.connection import init_db
from core.services.cache_manager import CacheManager
from infrastructure.config.settings import settings
from infrastructure.logging.logger import setup_logging
from infrastructure.monitoring.health_checks import router as health_router
from telegram_bot.api.routes import api_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Initialize only the dependencies required for the HTTP API."""
    setup_logging(__name__)
    logger = logging.getLogger(__name__)

    logger.info("🚀 Starting Polycool API service (with watched_addresses endpoint)")
    logger.info(f"🔍 Database URL: {settings.database.effective_url}")

    if os.getenv("SKIP_DB", "false").lower() != "true":
        await init_db()
        logger.info("✅ Database initialized")
    else:
        logger.warning("⚠️ Database initialization skipped (SKIP_DB=true)")

    app.state.cache = CacheManager()
    logger.info("✅ Cache manager ready")
    logger.info("✅ API service startup complete")

    try:
        yield
    finally:
        logger.info("🛑 Shutting down Polycool API service")
        cache_manager = getattr(app.state, "cache", None)
        if cache_manager:
            try:
                cache_manager.redis.close()
            except Exception:  # pragma: no cover - defensive
                logger.warning("⚠️ Failed to close cache manager cleanly")


app = FastAPI(
    title="Polycool API",
    version=settings.version,
    description="HTTP API for the Polycool Telegram bot",
    lifespan=lifespan,
    debug=settings.debug,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if not settings.is_development:
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=["*"],
    )

app.include_router(
    health_router,
    prefix="/health",
    tags=["health"],
)

app.include_router(
    api_router,
    prefix=settings.api_prefix,
)


@app.get("/")
async def root() -> dict:
    """Root endpoint for quick diagnostics."""
    return {
        "name": settings.name,
        "version": settings.version,
        "environment": settings.environment,
        "status": "running",
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "api_only:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", 8000)),
        log_level=settings.logging.level.lower(),
    )
