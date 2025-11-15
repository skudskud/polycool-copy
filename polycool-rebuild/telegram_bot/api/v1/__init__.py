"""
API v1 Routes
"""
from .markets import router as markets_router
from .positions import router as positions_router
from .smart_trading import router as smart_trading_router
from .copy_trading import router as copy_trading_router
from .wallet import router as wallet_router
from .users import router as users_router
from .referral import router as referral_router
from .admin import router as admin_router
from .subsquid import router as subsquid_router
from .trades import router as trades_router
from .websocket import router as websocket_router

__all__ = [
    "markets_router",
    "positions_router",
    "smart_trading_router",
    "copy_trading_router",
    "wallet_router",
    "users_router",
    "referral_router",
    "admin_router",
    "subsquid_router",
    "trades_router",
    "websocket_router",
]
