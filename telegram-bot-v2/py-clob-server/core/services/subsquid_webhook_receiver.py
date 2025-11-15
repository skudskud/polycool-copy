#!/usr/bin/env python3
"""
Subsquid Webhook Receiver
Receives trade notifications from indexer-ts and broadcasts via Redis Pub/Sub for copy trading
"""

import asyncio
import logging
import json
from datetime import datetime
from typing import Optional
from decimal import Decimal

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
import redis.asyncio as redis

from database import db_manager, TrackedLeaderTrade
from config.config import REDIS_URL, WEBHOOK_SECRET

logger = logging.getLogger(__name__)

# ========================================
# In-Memory Cache for Watched Addresses
# ========================================
class WatchedAddressCache:
    """Cache watched addresses to avoid DB queries on every webhook"""
    def __init__(self):
        self.external_leaders = set()
        self.smart_wallets = set()
        self.last_refresh = 0
        self.ttl = 300  # 5 minutes

    def refresh(self):
        """Refresh cache from database"""
        import time
        now = time.time()

        # Skip if cache is still fresh
        if now - self.last_refresh < self.ttl:
            return

        try:
            with db_manager.get_session() as db:
                from database import ExternalLeader
                from core.persistence.models import SmartWallet

                leaders = db.query(ExternalLeader).all()
                wallets = db.query(SmartWallet).all()

                self.external_leaders = {
                    l.polygon_address.lower() for l in leaders if l.polygon_address
                }
                self.smart_wallets = {
                    w.address.lower() for w in wallets if w.address
                }

                self.last_refresh = now
                logger.info(f"🔄 Cache refreshed: {len(self.external_leaders)} leaders, {len(self.smart_wallets)} smart wallets")
        except Exception as e:
            logger.error(f"❌ Cache refresh failed: {e}")

    def get_address_type(self, address: str) -> Optional[str]:
        """Get address type from cache (no DB query)"""
        addr_lower = address.lower()
        if addr_lower in self.external_leaders:
            return 'external_leader'
        if addr_lower in self.smart_wallets:
            return 'smart_wallet'
        return None

# Global cache instance
watched_cache = WatchedAddressCache()

# ========================================
# FastAPI Setup
# ========================================
app = FastAPI(
    title="Subsquid Copy Trading Webhook",
    version="1.0.0",
    description="Receives trade notifications from subsquid indexer for instant copy trading"
)

# ========================================
# Models
# ========================================
class CopyTradeWebhook(BaseModel):
    """Webhook event from indexer-ts"""
    tx_id: str
    user_address: str
    position_id: Optional[str] = None
    market_id: Optional[str] = None
    outcome: Optional[int] = None
    tx_type: str  # BUY or SELL
    amount: str  # Decimal as string
    tx_hash: str
    block_number: Optional[str] = None
    timestamp: str  # ISO format
    price: Optional[str] = None  # Decimal as string
    taking_amount: Optional[str] = None  # Total USD amount from Subsquid (required for copy trading)


class WebhookResponse(BaseModel):
    """Standard webhook response"""
    status: str
    message: Optional[str] = None


# ========================================
# Metrics
# ========================================
class WebhookMetrics:
    """Track webhook performance"""
    def __init__(self):
        self.events_received = 0
        self.events_success = 0
        self.events_failed = 0
        self.last_event_time = None

metrics = WebhookMetrics()


# ========================================
# Cache for Watched Addresses (Prevent DB overload)
# ========================================
import time
from threading import Lock

class WatchedAddressCache:
    """In-memory cache to prevent DB query on every webhook"""
    def __init__(self, ttl_seconds: int = 300):  # 5 minutes TTL
        self.cache = {}  # address -> {'type': ..., 'id': ...}
        self.ttl = ttl_seconds
        self.last_full_refresh = 0
        self.lock = Lock()

    def get(self, address: str) -> Optional[dict]:
        """Get cached address info"""
        with self.lock:
            entry = self.cache.get(address.lower())
            if entry and (time.time() - entry['cached_at']) < self.ttl:
                return entry['data']
        return None

    def set(self, address: str, data: dict):
        """Cache address info"""
        with self.lock:
            self.cache[address.lower()] = {
                'data': data,
                'cached_at': time.time()
            }

    def refresh_all(self):
        """Refresh entire cache from DB (called periodically)"""
        now = time.time()
        if (now - self.last_full_refresh) < self.ttl:
            return  # Skip if refreshed recently

        try:
            with db_manager.get_session() as db:
                from database import ExternalLeader
                from core.persistence.models import SmartWallet

                # Load all external leaders
                leaders = db.query(ExternalLeader).all()
                for leader in leaders:
                    if leader.polygon_address:
                        self.set(leader.polygon_address, {
                            'type': 'external_leader',
                            'id': leader.virtual_id
                        })

                # Load all smart wallets
                smart_wallets = db.query(SmartWallet).all()
                for wallet in smart_wallets:
                    if wallet.address:
                        self.set(wallet.address, {'type': 'smart_wallet'})

            self.last_full_refresh = now
            logger.info(f"✅ Cache refreshed: {len(self.cache)} watched addresses")

        except Exception as e:
            logger.error(f"❌ Cache refresh failed: {e}")

# Global cache instance
watched_cache = WatchedAddressCache(ttl_seconds=300)

# ========================================
# Startup: Pre-warm cache
# ========================================
@app.on_event("startup")
async def startup_event():
    """Pre-warm cache on startup to avoid DB queries on first webhooks"""
    logger.info("🚀 Warming up watched addresses cache...")
    watched_cache.refresh_all()
    logger.info("✅ Cache ready")


# ========================================
# Helper Functions
# ========================================
def get_watched_address_info(user_address: str) -> dict:
    """
    Get info about watched address (external_leader or smart_wallet)
    Uses in-memory cache to prevent DB overload (refreshed every 5 min)

    Args:
        user_address: Blockchain wallet address

    Returns:
        Dict with 'type' field ('external_leader', 'smart_wallet', or None)
    """
    # Try cache first
    cached = watched_cache.get(user_address)
    if cached is not None:
        return cached

    # Cache miss - query DB
    try:
        # Check if address is an external leader
        with db_manager.get_session() as db:
            from database import ExternalLeader
            external = db.query(ExternalLeader).filter(
                ExternalLeader.polygon_address == user_address.lower()
            ).first()

            if external:
                data = {'type': 'external_leader', 'id': external.virtual_id}
                watched_cache.set(user_address, data)
                return data

        # Check if address is a smart wallet
        from core.persistence.models import SmartWallet
        with db_manager.get_session() as db:
            smart = db.query(SmartWallet).filter(
                SmartWallet.address == user_address.lower()
            ).first()

            if smart:
                data = {'type': 'smart_wallet'}
                watched_cache.set(user_address, data)
                return data

        # Not a watched address - cache negative result
        data = {'type': None}
        watched_cache.set(user_address, data)
        return data

    except Exception as e:
        logger.error(f"❌ Error checking watched address: {e}")
        return {'type': None}


# ========================================
# Endpoints
# ========================================

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "events_received": metrics.events_received,
        "events_success": metrics.events_success,
        "events_failed": metrics.events_failed,
    }


@app.post("/wh/copy_trade")
async def receive_copy_trade(event: CopyTradeWebhook, request: Request) -> WebhookResponse:
    """
    Receive trade from indexer → insert to tracked_leader_trades → broadcast Redis

    Flow:
    1. Validate webhook secret
    2. Validate event
    3. Insert to tracked_leader_trades
    4. Broadcast via Redis Pub/Sub for instant copy trading
    """
    logger.info(f"🎣 [WEBHOOK] Received {event.tx_type} trade webhook for {event.user_address[:10]}... (tx: {event.tx_id})")
    try:
        # ✅ WEBHOOKS RE-ENABLED - Redis cache now handles the load
        # With filtering active, we only receive ~3 webhooks/batch instead of 191
        # This is sustainable and won't overload the bot

        # Security: Verify webhook secret
        if WEBHOOK_SECRET:
            x_webhook_secret = request.headers.get("X-Webhook-Secret")
            if not x_webhook_secret or x_webhook_secret != WEBHOOK_SECRET:
                logger.warning(f"❌ Invalid webhook secret from {request.client.host}")
                return WebhookResponse(
                    status="error",
                    message="Invalid webhook secret"
                )

        metrics.events_received += 1
        metrics.last_event_time = datetime.utcnow()

        # Refresh cache periodically (non-blocking)
        watched_cache.refresh_all()

        # Get address info (external_leader or smart_wallet)
        address_info = get_watched_address_info(event.user_address)

        # Only process if it's a watched address
        if address_info['type'] is None:
            # Reduce log pollution: only log every 100th skip
            if metrics.events_received % 100 == 0:
                logger.debug(f"⏭️ Skipped {metrics.events_received} unwatched addresses so far")
            return WebhookResponse(
                status="ignored",
                message="Not a watched address"
            )

        # 1. Insert to tracked_leader_trades
        try:
            # Calculate price with fallback logic
            price = None
            if event.price is not None:
                # Use direct price if available
                try:
                    price = Decimal(event.price)
                    # Validate price range to prevent numeric overflow (NUMERIC(18,8) max: 99999999999999.99999999)
                    if price > Decimal('99999999999999.99999999') or price < Decimal('0'):
                        logger.warning(f"⚠️ [WEBHOOK] Price out of range: ${price}, setting to None")
                        price = None
                    else:
                        logger.debug(f"✅ [WEBHOOK] Using direct price: ${price}")
                except (ValueError, TypeError):
                    logger.warning(f"⚠️ [WEBHOOK] Invalid price format: {event.price}")
                    price = None

            elif hasattr(event, 'taking_amount') and event.taking_amount and event.amount:
                # Fallback: calculate price from taking_amount / amount
                try:
                    taking_amount = Decimal(event.taking_amount)
                    amount = Decimal(event.amount)
                    if amount > 0:
                        price = taking_amount / amount
                        logger.debug(f"✅ [WEBHOOK] Calculated price from taking_amount: ${price} (${taking_amount} / ${amount})")
                    else:
                        logger.warning(f"⚠️ [WEBHOOK] Invalid amount for price calculation: {event.amount}")
                except (ValueError, TypeError) as calc_error:
                    logger.warning(f"⚠️ [WEBHOOK] Could not calculate price from taking_amount: {calc_error}")
            else:
                # Final fallback: estimate price from market data in database
                try:
                    from telegram_bot.services.market_service import MarketService
                    market_service = MarketService()

                    if event.market_id:
                        # Try to get market data to estimate price
                        market = market_service.get_market_by_id(event.market_id)
                        if market and market.get('outcome_prices'):
                            outcome_prices = market['outcome_prices']
                            if isinstance(outcome_prices, list) and len(outcome_prices) >= 2:
                                # Use YES price for outcome 1, NO price for outcome 0
                                outcome_idx = 0 if event.outcome == 1 else 1  # YES=0, NO=1 in array
                                if outcome_idx < len(outcome_prices):
                                    price = Decimal(str(outcome_prices[outcome_idx]))
                                    logger.debug(f"✅ [WEBHOOK] Estimated price from market data: ${price} (outcome {event.outcome})")
                                else:
                                    logger.warning(f"⚠️ [WEBHOOK] Invalid outcome index {outcome_idx} for market {event.market_id}")
                            else:
                                logger.warning(f"⚠️ [WEBHOOK] Invalid outcome_prices format for market {event.market_id}")
                        else:
                            logger.warning(f"⚠️ [WEBHOOK] Market {event.market_id} not found or no price data")
                    else:
                        logger.warning(f"⚠️ [WEBHOOK] No market_id to estimate price for trade {event.tx_id}")
                except Exception as market_error:
                    logger.warning(f"⚠️ [WEBHOOK] Could not estimate price from market data: {market_error}")

                if price is None:
                    logger.warning(f"⚠️ [WEBHOOK] No price data available for trade {event.tx_id} - trade will be filtered")

            # Validate amount to prevent overflow
            amount = None
            if event.amount:
                try:
                    amount = Decimal(event.amount)
                    # Validate amount range to prevent numeric overflow (increased upper limit)
                    if amount > Decimal('9999999999.99999999') or amount < Decimal('0'):
                        logger.warning(f"⚠️ [WEBHOOK] Amount out of range: {amount}, setting to None")
                        amount = None
                except (ValueError, TypeError):
                    logger.warning(f"⚠️ [WEBHOOK] Invalid amount format: {event.amount}")
                    amount = None

            # Validate taking_amount (USDC amount) to prevent overflow
            amount_usdc = None
            if hasattr(event, 'taking_amount') and event.taking_amount:
                try:
                    amount_usdc = Decimal(event.taking_amount)
                    # Validate USDC amount range
                    if amount_usdc > Decimal('999999999.999999') or amount_usdc < Decimal('-999999999.999999'):
                        logger.warning(f"⚠️ [WEBHOOK] taking_amount out of range: {amount_usdc}, setting to None")
                        amount_usdc = None
                    else:
                        logger.debug(f"✅ [WEBHOOK] Using taking_amount: ${amount_usdc}")
                except (ValueError, TypeError):
                    logger.warning(f"⚠️ [WEBHOOK] Invalid taking_amount format: {event.taking_amount}")
                    amount_usdc = None

            with db_manager.get_session() as db:
                tracked = TrackedLeaderTrade(
                    id=event.tx_id,
                    tx_id=event.tx_id,
                    user_address=event.user_address.lower(),
                    market_id=event.market_id,
                    outcome=event.outcome,
                    tx_type=event.tx_type,
                    amount=amount,
                    price=price,
                    amount_usdc=amount_usdc,  # Store exact USDC amount
                    tx_hash=event.tx_hash,
                    timestamp=datetime.fromisoformat(event.timestamp.replace('Z', '+00:00')),
                    is_external_leader=(address_info['type'] == 'external_leader'),
                    is_smart_wallet=(address_info['type'] == 'smart_wallet')
                )

                db.merge(tracked)
                db.commit()

                # Reduce log pollution: only log for watched addresses
                logger.info(f"✅ Tracked: {event.tx_type} {event.user_address[:10]}... ({address_info['type']})")

                # 🚀 NEW: Instant sync for smart wallet trades (webhook-triggered)
                if address_info['type'] == 'smart_wallet':
                    try:
                        from core.services.smart_wallet_sync_service import get_smart_wallet_sync_service
                        sync_service = get_smart_wallet_sync_service()

                        # Trigger instant sync (non-blocking)
                        asyncio.create_task(sync_service.sync_single_trade_instant(event.tx_id))
                        logger.debug(f"⚡ [WEBHOOK] Triggered instant sync for smart wallet trade {event.tx_id[:16]}...")

                    except Exception as sync_error:
                        # Non-blocking: If instant sync fails, polling backup will catch it
                        logger.warning(f"⚠️ [WEBHOOK] Instant sync trigger failed: {sync_error}")

        except Exception as db_error:
            # Log detailed error for debugging
            logger.error(f"❌ Database insert failed: {db_error}", exc_info=True)
            metrics.events_failed += 1

            # Check if it's a numeric overflow error (should be fixed by migration, but handle gracefully)
            error_str = str(db_error)
            if "numeric field overflow" in error_str or "NumericValueOutOfRange" in error_str:
                logger.error(f"🔴 NUMERIC OVERFLOW ERROR - This trade cannot be saved: {event.tx_id}")
                logger.error(f"   Price: {price}, Amount: {amount}, Amount USDC: {amount_usdc}")
                # Return error response but don't block the bot
                return WebhookResponse(
                    status="error",
                    message=f"Numeric overflow: price or amount too large for database column"
                )

            # For other DB errors, return error but don't raise HTTPException to avoid blocking
            return WebhookResponse(
                status="error",
                message=f"Database error: {type(db_error).__name__}"
            )

        # 2. Broadcast via Redis Pub/Sub (for instant copy trading)
        try:
            logger.debug(f"🔄 [WEBHOOK_REDIS] Connecting to Redis for {event.tx_type} trade...")
            redis_client = await redis.from_url(REDIS_URL, decode_responses=True)

            # Publish to channel: copy_trade:{wallet_address}
            channel = f"copy_trade:{event.user_address.lower()}"
            message = json.dumps({
                'tx_id': event.tx_id,
                'user_address': event.user_address,
                'position_id': event.position_id,  # ✅ FIX: Include position_id (token_id) from indexer
                'market_id': event.market_id,
                'outcome': event.outcome,
                'tx_type': event.tx_type,
                'amount': event.amount,
                'price': event.price,
                'taking_amount': getattr(event, 'taking_amount', None),  # Total USD amount from Subsquid
                'tx_hash': event.tx_hash,
                'timestamp': event.timestamp,
                'address_type': address_info['type']
            })

            logger.info(f"📤 [WEBHOOK_REDIS] Publishing {event.tx_type} to channel: {channel}")
            result = await redis_client.publish(channel, message)
            logger.info(f"✅ [WEBHOOK_REDIS] Published to {channel}, subscribers reached: {result}")

            await redis_client.close()

        except Exception as redis_error:
            # Non-blocking: If Redis fails, we still have the DB record
            # The polling fallback will catch it
            logger.error(f"❌ [WEBHOOK_REDIS] Redis broadcast failed: {redis_error}", exc_info=True)

        metrics.events_success += 1

        return WebhookResponse(
            status="ok",
            message=f"Trade processed and broadcast for {address_info['type']}"
        )

    except HTTPException:
        raise
    except Exception as e:
        metrics.events_failed += 1
        logger.error(f"❌ Webhook processing error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/metrics")
async def get_metrics():
    """Get webhook performance metrics"""
    success_rate = (
        metrics.events_success / metrics.events_received * 100
        if metrics.events_received > 0 else 0
    )

    return {
        "events_received": metrics.events_received,
        "events_success": metrics.events_success,
        "events_failed": metrics.events_failed,
        "success_rate": round(success_rate, 2),
        "last_event_time": metrics.last_event_time.isoformat() if metrics.last_event_time else None,
    }


@app.get("/")
async def root():
    """Root endpoint - API documentation"""
    return {
        "name": "Subsquid Copy Trading Webhook",
        "version": "1.0.0",
        "endpoints": {
            "health": "GET /health",
            "webhook": "POST /wh/copy_trade",
            "metrics": "GET /metrics",
        }
    }
