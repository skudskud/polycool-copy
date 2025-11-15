#!/usr/bin/env python3
"""
Watched Markets API Server
Receives notifications from bot when markets need to be watched/unwatched
"""

import asyncio
import json
import logging
from typing import Dict, Any
from aiohttp import web
import aiohttp

from .config import settings
from .db.client import get_db_client

logger = logging.getLogger(__name__)


class WatchedMarketsAPI:
    """API server for watched markets management"""

    def __init__(self, port: int = 8082):
        self.port = port
        self.app = web.Application()
        self.runner = None
        self.site = None
        self.setup_routes()

    def setup_routes(self):
        """Setup API routes"""
        self.app.router.add_post('/watched-markets/add', self.add_watched_market)
        self.app.router.add_post('/watched-markets/remove', self.remove_watched_market)
        self.app.router.add_post('/watched-markets/update', self.update_watched_market)
        self.app.router.add_get('/health', self.health_check)

    async def add_watched_market(self, request: web.Request) -> web.Response:
        """Add a market to watched list"""
        try:
            data = await request.json()
            market_id = data.get('market_id')
            condition_id = data.get('condition_id')
            title = data.get('title')

            if not market_id:
                return web.json_response({"error": "market_id required"}, status=400)

            db = await get_db_client()
            success = await db.add_watched_market(market_id, condition_id, title)

            if success:
                logger.info(f"📈 Added watched market via API: {market_id}")
                return web.json_response({"status": "added", "market_id": market_id})
            else:
                return web.json_response({"error": "Failed to add market"}, status=500)

        except Exception as e:
            logger.error(f"❌ Error adding watched market: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def remove_watched_market(self, request: web.Request) -> web.Response:
        """Remove a market from watched list"""
        try:
            data = await request.json()
            market_id = data.get('market_id')

            if not market_id:
                return web.json_response({"error": "market_id required"}, status=400)

            db = await get_db_client()
            success = await db.remove_watched_market(market_id)

            if success:
                logger.info(f"📉 Removed watched market via API: {market_id}")
                return web.json_response({"status": "removed", "market_id": market_id})
            else:
                return web.json_response({"error": "Failed to remove market"}, status=500)

        except Exception as e:
            logger.error(f"❌ Error removing watched market: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def update_watched_market(self, request: web.Request) -> web.Response:
        """Update position count for a watched market"""
        try:
            data = await request.json()
            market_id = data.get('market_id')
            position_count = data.get('position_count', 0)

            if not market_id:
                return web.json_response({"error": "market_id required"}, status=400)

            db = await get_db_client()
            success = await db.update_watched_market_positions(market_id, position_count)

            if success:
                logger.info(f"🔄 Updated watched market via API: {market_id} ({position_count} positions)")
                return web.json_response({"status": "updated", "market_id": market_id, "positions": position_count})
            else:
                return web.json_response({"error": "Failed to update market"}, status=500)

        except Exception as e:
            logger.error(f"❌ Error updating watched market: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def health_check(self, request: web.Request) -> web.Response:
        """Health check endpoint"""
        return web.json_response({"status": "healthy", "service": "watched_markets_api"})

    async def start(self):
        """Start the API server"""
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        self.site = web.TCPSite(self.runner, '0.0.0.0', self.port)
        await self.site.start()
        logger.info(f"✅ Watched Markets API started on port {self.port}")

    async def stop(self):
        """Stop the API server"""
        if self.site:
            await self.site.stop()
        if self.runner:
            await self.runner.cleanup()
        logger.info("✅ Watched Markets API stopped")


# Global instance
_watched_markets_api = None

async def get_watched_markets_api() -> WatchedMarketsAPI:
    """Get or create global API instance"""
    global _watched_markets_api
    if _watched_markets_api is None:
        _watched_markets_api = WatchedMarketsAPI()
    return _watched_markets_api


async def start_watched_markets_api():
    """Start the watched markets API server"""
    api = await get_watched_markets_api()
    await api.start()


async def stop_watched_markets_api():
    """Stop the watched markets API server"""
    global _watched_markets_api
    if _watched_markets_api:
        await _watched_markets_api.stop()
        _watched_markets_api = None
