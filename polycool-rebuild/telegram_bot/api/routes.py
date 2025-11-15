"""
API Routes for Polycool Telegram Bot
"""
from fastapi import APIRouter

from telegram_bot.api.v1 import (
    markets_router,
    positions_router,
    smart_trading_router,
    copy_trading_router,
    wallet_router,
    users_router,
    referral_router,
    admin_router,
    subsquid_router,
    trades_router,
    websocket_router,
)
from telegram_bot.api.v1.webhooks import webhook_router

# Main API router
api_router = APIRouter()

# Include versioned routers
api_router.include_router(
    markets_router,
    prefix="/markets",
    tags=["markets"],
)

api_router.include_router(
    positions_router,
    prefix="/positions",
    tags=["positions"],
)

api_router.include_router(
    smart_trading_router,
    prefix="/smart-trading",
    tags=["smart-trading"],
)

api_router.include_router(
    copy_trading_router,
    prefix="/copy-trading",
    tags=["copy-trading"],
)

api_router.include_router(
    wallet_router,
    prefix="/wallet",
    tags=["wallet"],
)

api_router.include_router(
    users_router,
    prefix="/users",
    tags=["users"],
)

api_router.include_router(
    referral_router,
    prefix="/referral",
    tags=["referral"],
)

api_router.include_router(
    admin_router,
    prefix="/admin",
    tags=["admin"],
)

# Webhook routes (no prefix, already has /webhooks)
api_router.include_router(webhook_router)

# Subsquid routes (for indexer-ts integration)
api_router.include_router(
    subsquid_router,
    prefix="/subsquid",
    tags=["subsquid"],
)

# Trades routes
api_router.include_router(
    trades_router,
    prefix="/trades",
    tags=["trades"],
)

# WebSocket routes
api_router.include_router(
    websocket_router,
    prefix="/websocket",
    tags=["websocket"],
)
