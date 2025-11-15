"""
24/7 Polymarket Server: FastAPI + Telegram Bot
- Real-time market database with PostgreSQL (every 60 seconds)
- 24/7 Telegram trading bot for users
- Railway-ready deployment
"""
import sys
import os
print("🔍 MODULE: main.py module import starting...")
print(f"🔍 MODULE: Python version: {sys.version}")
print(f"🔍 MODULE: Current working directory: {os.getcwd()}")



import asyncio
import logging
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Silence SQLAlchemy query logging
logging.getLogger('sqlalchemy.engine').setLevel(logging.ERROR)
logging.getLogger('sqlalchemy.pool').setLevel(logging.WARNING)
logging.getLogger('apscheduler').setLevel(logging.WARNING)
logging.getLogger('core.persistence.db_manager').setLevel(logging.ERROR)
logging.getLogger('core.persistence').setLevel(logging.ERROR)
logging.getLogger('telegram_bot.services.price_monitor').setLevel(logging.WARNING)
logging.getLogger('telegram_bot.services.tpsl_service').setLevel(logging.WARNING)
logging.getLogger('core.services.redis_price_cache').setLevel(logging.INFO)  # ✅ ENABLE for cache debugging
logging.getLogger('core.services.copy_trading_monitor').setLevel(logging.INFO)  # ✅ ENABLE for copy trading debugging

# ✅ Disable uvicorn access logs completely
logging.getLogger('uvicorn.access').setLevel(logging.WARNING)
logging.getLogger('uvicorn.access').propagate = False

# 🔇 NUCLEAR OPTION: Silence httpx HTTP request spam
logging.getLogger('httpx').setLevel(logging.WARNING)

# 🔇 Silence notification ERROR spam - we know about chat_not_found errors
# The service tracks failures internally and logs summary every 5min as INFO
# Levels: DEBUG < INFO < WARNING < ERROR < CRITICAL
logging.getLogger('core.services.smart_trading_notification_service').setLevel(logging.CRITICAL)


from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

# FastAPI
from fastapi import FastAPI, HTTPException, BackgroundTasks, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger

# PostgreSQL persistence and services
from core.persistence import MarketRepository, get_db_session, Market
from core.services import MarketUpdaterService
from core.services.auto_approval_service import auto_approval_service
from core.services.redis_price_cache import RedisPriceCache

# SQLAlchemy
from sqlalchemy import func, and_, or_

# Configuration
from config.config import GAMMA_API_URL, CLOB_API_URL, BOT_TOKEN, MARKET_UPDATE_INTERVAL
from config.config import AUTO_APPROVAL_ENABLED, WALLET_CHECK_INTERVAL_SECONDS
from config.config import USE_SUBSQUID_MARKETS

# Import Telegram Bot
from telegram_bot import TelegramTradingBot
from telegram import error as telegram_error
from database import db_manager

# Set up logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
print("🔍 FASTAPI: Creating FastAPI app object...")
try:
    app = FastAPI(
        title="Polymarket Real-Time Database API",
        description="PostgreSQL-based market database with 60-second updates",
        version="2.0.0"
    )
    print("🔍 FASTAPI: FastAPI app created successfully")
except Exception as e:
    print(f"❌ FASTAPI: Failed to create FastAPI app: {e}")
    import traceback
    print(f"❌ FASTAPI: Traceback:\n{traceback.format_exc()}")
    raise

# Add CORS middleware for cross-origin requests
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure this properly for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ========================================
# SUBSQUID INDEXER ENDPOINTS
# ========================================
# IMPORTANT: Define BEFORE mounting webhook_app at /subsquid
# Otherwise these endpoints will be shadowed by the mounted app

@app.get("/subsquid/watched_addresses")
async def get_watched_addresses():
    """
    Return all addresses to watch for copy trading (from Redis cache)
    Ultra-fast response (<100ms) even with 10K addresses

    Fallback to DB if cache miss

    Returns:
        {
            "addresses": [
                {"address": "0x...", "type": "external_leader", "user_id": -123},
                {"address": "0x...", "type": "smart_wallet", "user_id": null}
            ],
            "total": 42,
            "timestamp": "2025-10-27T17:30:00Z",
            "cached": true
        }
    """
    try:
        # Try cache first (ultra fast)
        cached_data = await watched_addresses_cache_manager.get_cached_addresses()

        if cached_data:
            # Cache hit - return immediately
            logger.debug(
                f"[WATCHED_ADDRESSES] ✅ Cache hit: {cached_data['total']} addresses"
            )
            return cached_data

        # Cache miss - fetch from DB (fallback)
        logger.warning("[WATCHED_ADDRESSES] Cache miss, falling back to DB query")

        from database import ExternalLeader
        from core.persistence.models import SmartWallet

        with db_manager.get_session() as db:
            # Get active external leaders
            leaders = db.query(ExternalLeader).filter(
                ExternalLeader.is_active == True,
                ExternalLeader.polygon_address.isnot(None)
            ).all()

            # Get all smart wallets (no is_active field)
            smart_wallets = db.query(SmartWallet).filter(
                SmartWallet.address.isnot(None)
            ).all()

            addresses = []

            # Add external leaders
            for leader in leaders:
                addresses.append({
                    'address': leader.polygon_address.lower(),
                    'type': 'external_leader',
                    'user_id': leader.virtual_id
                })

            # Add smart wallets (no user_id)
            for wallet in smart_wallets:
                addresses.append({
                    'address': wallet.address.lower(),
                    'type': 'smart_wallet',
                    'user_id': None
                })

            logger.info(
                f"[WATCHED_ADDRESSES] ✅ DB fallback returned {len(addresses)} addresses "
                f"({len(leaders)} leaders, {len(smart_wallets)} smart wallets)"
            )

            return {
                'addresses': addresses,
                'total': len(addresses),
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'cached': False  # Indicate this was DB fallback
            }

    except Exception as e:
        logger.error(f"[WATCHED_ADDRESSES] ❌ Error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to fetch watched addresses: {str(e)}")


@app.get("/subsquid/stats")
async def get_indexer_stats():
    """
    Return statistics about watched addresses and recent trades
    Used for monitoring and debugging
    """
    try:
        from database import ExternalLeader, TrackedLeaderTrade
        from core.persistence.models import SmartWallet

        with db_manager.get_session() as db:
            # Count watched addresses
            external_leaders_count = db.query(ExternalLeader).filter(
                ExternalLeader.is_active == True
            ).count()

            smart_wallets_count = db.query(SmartWallet).count()

            # Count recent trades (last 24h)
            from sqlalchemy import func
            yesterday = datetime.now(timezone.utc) - timedelta(days=1)
            recent_trades_count = db.query(TrackedLeaderTrade).filter(
                TrackedLeaderTrade.timestamp >= yesterday
            ).count()

            # Get last trade timestamp
            last_trade = db.query(TrackedLeaderTrade).order_by(
                TrackedLeaderTrade.timestamp.desc()
            ).first()

            return {
                'watched_addresses': {
                    'external_leaders': external_leaders_count,
                    'smart_wallets': smart_wallets_count,
                    'total': external_leaders_count + smart_wallets_count
                },
                'trades': {
                    'last_24h': recent_trades_count,
                    'last_trade_at': last_trade.timestamp.isoformat() if last_trade else None
                },
                'timestamp': datetime.now(timezone.utc).isoformat()
            }

    except Exception as e:
        logger.error(f"[INDEXER_STATS] ❌ Error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to fetch stats: {str(e)}")


@app.get("/subsquid/cache/stats")
async def get_cache_stats():
    """
    Get watched addresses cache statistics
    Used for monitoring cache health

    Returns:
        {
            "cached": true,
            "total_addresses": 205,
            "breakdown": {"external_leaders": 2, "smart_wallets": 203},
            "cached_at": "2025-10-27T...",
            "ttl_seconds": 450,
            "expires_in": "7m 30s"
        }
    """
    try:
        stats = await watched_addresses_cache_manager.get_cache_stats()
        return stats
    except Exception as e:
        logger.error(f"[CACHE_STATS] Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/subsquid/cache/invalidate")
async def invalidate_cache():
    """
    Manually invalidate the cache (admin endpoint)
    Forces cache refresh on next request

    Returns:
        {"status": "ok", "message": "Cache invalidated"}
    """
    try:
        await watched_addresses_cache_manager.invalidate_cache()
        logger.info("[CACHE_INVALIDATE] Manual cache invalidation requested")
        return {"status": "ok", "message": "Cache invalidated, will refresh on next request"}
    except Exception as e:
        logger.error(f"[CACHE_INVALIDATE] Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Telegram Webhook Processing Queue
# Uses Redis to queue updates for async processing
import json
import asyncio
import threading
from typing import Dict, Any

# POLLING MODE: Bot polls directly from Telegram - no webhook endpoints needed

# Railway Health Check Endpoint
# CRITICAL: Railway requires this for deployment healthcheck
# IMPORTANT: This endpoint must work WITHOUT any external dependencies
@app.get("/health")
async def health_check():
    """Railway health check endpoint - must return 200 for deployment to succeed
    Ultra-minimal implementation - no external dependencies"""
    # Return 200 OK immediately with minimal response
    return {"status": "ok"}

# Mount Subsquid Webhook Receiver for instant copy trading
# IMPORTANT: Mount AFTER defining /subsquid/* endpoints above
# Otherwise the mount will shadow those endpoints
try:
    from core.services.subsquid_webhook_receiver import app as webhook_app
    app.mount("/subsquid", webhook_app)
    logger.info("✅ Mounted Subsquid webhook receiver at /subsquid")
except Exception as e:
    logger.warning(f"⚠️ Could not mount webhook receiver: {e}")

# Global instances - initialized lazily to avoid blocking module import
db_session_instance = None
market_repository = None
market_service = None

def _ensure_market_service_initialized():
    """Lazy initialization of market service to avoid blocking module import"""
    global db_session_instance, market_repository, market_service
    if market_service is None:
        db_session_instance = get_db_session()
        market_repository = MarketRepository(db_session_instance)
        market_service = MarketUpdaterService(market_repository, GAMMA_API_URL)
    return market_service

# Configure scheduler with AsyncIOExecutor for async coroutines
from apscheduler.executors.asyncio import AsyncIOExecutor
executors = {
    'default': AsyncIOExecutor()  # Use AsyncIO executor for async functions
}
job_defaults = {
    'coalesce': True,  # Combine multiple missed runs into one
    'max_instances': 1,  # Only one instance of each job at a time
    'misfire_grace_time': 600  # Allow 10 minutes grace for missed jobs
}
scheduler = AsyncIOScheduler(executors=executors, job_defaults=job_defaults)

# Import cache manager for watched addresses
from core.services.watched_addresses_cache import watched_addresses_cache_manager

# Add background job to refresh watched addresses cache every 1 minute
# (synchronized with indexer refresh interval for consistency)
scheduler.add_job(
    watched_addresses_cache_manager.refresh_cache,
    trigger=IntervalTrigger(minutes=1),
    id='refresh_watched_addresses_cache',
    name='Refresh Watched Addresses Cache',
    replace_existing=True,
    max_instances=1
)
logger.info("✅ Scheduled: Watched addresses cache refresh (every 1 minute)")

# Add filter processor for unified notification system
from core.services.smart_wallet_trades_filter_processor import get_filter_processor
from core.services.unified_push_notification_processor import get_push_processor

filter_processor = get_filter_processor()
scheduler.add_job(
    filter_processor.process_cycle,
    trigger=IntervalTrigger(seconds=30),
    id='smart_wallet_trades_filter_processor',
    name='Smart Wallet Trades Filter Processor',
    replace_existing=True,
    max_instances=1
)
logger.info("✅ Scheduled: Smart Wallet Trades Filter Processor (every 30 seconds)")

# Add push notification processor (will be initialized after bot is ready)
push_processor = get_push_processor()
scheduler.add_job(
    push_processor.process_cycle,  # ✅ AsyncIOScheduler handles async functions natively
    trigger=IntervalTrigger(seconds=30),
    id='unified_push_notification_processor',
    name='Unified Push Notification Processor',
    replace_existing=True,
    max_instances=1
)
logger.info("✅ Scheduled: Unified Push Notification Processor (every 30 seconds)")

telegram_bot = None  # Will be initialized at startup
smart_monitor = None  # Smart wallet monitor service
copy_trading_monitor = None  # Copy trading monitor service (Redis Pub/Sub + polling)

# Global progress tracker for backfill operations
backfill_progress = {
    "status": "idle",  # idle, running, completed, error
    "total": 0,
    "processed": 0,
    "categorized": 0,
    "skipped": 0,
    "errors": 0,
    "current_batch": 0,
    "total_batches": 0,
    "start_time": None,
    "end_time": None,
    "error_message": None
}

@app.on_event("startup")
async def startup_event():
    """Initialize the PostgreSQL database, Telegram bot, and start background tasks"""
    global telegram_bot, smart_monitor, copy_trading_monitor

    print("🚀 Starting 24/7 Polymarket Server (PostgreSQL + Telegram Bot)...")
    print("🔍 STARTUP: Beginning initialization sequence...")
    print("🔍 STARTUP: startup_event() function is now running!")

    # Initialize market service in background to avoid blocking
    async def init_market_service_async():
        """Initialize market service asynchronously"""
        try:
            await asyncio.sleep(0.5)  # Let HTTP server start first
            _ensure_market_service_initialized()
            logger.info("✅ Market service initialized (background)")
        except Exception as e:
            logger.error(f"❌ Failed to initialize market service: {e}")

    asyncio.create_task(init_market_service_async())

    # LIST ALL REGISTERED ROUTES (CRITICAL FOR WEBHOOK DEBUGGING)
    print("\n--- ROUTES REGISTERED ---")
    for route in app.routes:
        methods = getattr(route, 'methods', ['GET'])  # Default to GET if no methods
        print(f"  {route.path} - {methods}")
    print("-------------------------\n")

    # Run database migrations in background (non-blocking)
    async def run_migrations_background():
        """Run database migrations asynchronously to not block startup"""
        try:
            print("🔄 Running database migrations (background)...")
            from run_withdrawal_migration import run_migration
            if run_migration():
                print("✅ Database migrations completed")
            else:
                print("⚠️ Database migration failed, but continuing...")
        except Exception as e:
            logger.warning(f"Migration error (non-critical): {e}")

        try:
            print("🔄 Running copy trading external leaders migration...")
            import sys
            import os
            sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'migrations', '2025-10-21_copy_trading_external_leaders'))
            from run_migration import run_migration as run_external_leaders_migration
            if run_external_leaders_migration():
                print("✅ External leaders table migration completed")
            else:
                print("⚠️ External leaders migration failed")
        except Exception as e:
            logger.warning(f"External leaders migration error (non-critical): {e}")

    # Start migrations in background (don't block startup)
    asyncio.create_task(run_migrations_background())

    # Populate watched addresses cache in background (non-blocking)
    async def populate_cache_background():
        """Populate cache in background to avoid blocking startup"""
        try:
            print("🔄 Populating watched addresses cache (background)...")
            await asyncio.sleep(1)  # Small delay to let server start
            await watched_addresses_cache_manager.refresh_cache()
            print("✅ Initial watched addresses cache populated")
        except Exception as e:
            print(f"⚠️ Failed to populate initial cache (will retry in 1 min): {e}")

    # Start cache population in background
    print("🔍 STARTUP: Starting cache population background task...")
    asyncio.create_task(populate_cache_background())
    print("🔍 STARTUP: Cache population task started")

    # Run smart wallet migrations in background to avoid healthcheck timeout
    async def run_smart_wallet_migrations():
        """Run smart wallet migrations in background"""
        try:
            # Small delay to ensure main server is up
            await asyncio.sleep(2)

            print("🔄 Running smart wallet tables migration (background)...")
            from run_smart_wallet_migration import run_migration as run_smart_wallet_migration
            if run_smart_wallet_migration():
                print("✅ Smart wallet tables migration completed")
            else:
                print("⚠️ Smart wallet migration failed")

            print("🔄 Running smart wallet fix migration (background)...")
            from run_fix_market_id_migration import run_fix
            if run_fix():
                print("✅ Smart wallet fix migration completed")
            else:
                print("⚠️ Smart wallet fix migration failed")

        except Exception as e:
            print(f"⚠️ Smart wallet migration error: {e}")

    asyncio.create_task(run_smart_wallet_migrations())

    # CRITICAL: Move PostgreSQL connection test to background to avoid blocking healthcheck
    async def test_database_connection_async():
        """Test database connection asynchronously after HTTP server starts"""
        try:
            await asyncio.sleep(3)  # Wait for HTTP server to be ready

            # Test database connection with simple query
            from sqlalchemy import text
            with db_manager.get_session() as db:
                result = db.execute(text("SELECT 1"))
                logger.info("✅ PostgreSQL connected successfully")
        except Exception as e:
            logger.warning(f"⚠️ PostgreSQL connection issue: {e}")
            logger.info("🔄 Database will be retried by background services...")

    # Start database connection test in background (non-blocking)
    asyncio.create_task(test_database_connection_async())

    # Move Market model column check to background (can be slow)
    async def check_market_model_async():
        """Check Market model columns in background to avoid blocking startup"""
        try:
            await asyncio.sleep(2)  # Let HTTP server start first
            from database import Market
            model_columns = {col.name for col in Market.__table__.columns}
            has_event_cols = 'event_id' in model_columns and 'event_slug' in model_columns and 'event_title' in model_columns
            logger.info(f"🔍 Market model columns check: event_id={('event_id' in model_columns)}, event_slug={('event_slug' in model_columns)}, event_title={('event_title' in model_columns)}")
            if not has_event_cols:
                logger.warning("⚠️ WARNING: Market model is missing event columns! Deployment may have failed.")
                logger.warning(f"   Available columns: {sorted(model_columns)}")
        except Exception as e:
            logger.warning(f"⚠️ Could not check Market model columns: {e}")

    asyncio.create_task(check_market_model_async())

    # Start the scheduler asynchronously (CRITICAL: prevent blocking HTTP server)
    async def initialize_scheduler_async():
        """Initialize scheduler asynchronously to prevent blocking HTTP server startup"""
        try:
            scheduler.start()
            logger.info("⏰ Scheduler started asynchronously")
        except Exception as e:
            logger.error(f"❌ Scheduler initialization failed: {e}")
            # Don't crash - continue without scheduler
            return

        # Schedule all jobs after scheduler is started
        try:
            await schedule_all_jobs_async()
        except Exception as e:
            logger.error(f"❌ Job scheduling failed: {e}")

    async def schedule_all_jobs_async():
        """Schedule all background jobs asynchronously"""
        # Fetches 20 pages (~2,000 markets) to capture ALL new markets
        if not USE_SUBSQUID_MARKETS:
            scheduler.add_job(
                market_service.run_high_priority_update_cycle,
                IntervalTrigger(seconds=MARKET_UPDATE_INTERVAL),
                id="market_updater_high_priority",
                replace_existing=True,
                max_instances=1  # Prevent overlapping runs
            )
            print(f"🔥 HIGH PRIORITY market updater scheduled (every {MARKET_UPDATE_INTERVAL}s = {MARKET_UPDATE_INTERVAL//60} min - Fetches ALL new markets)")
        else:
            logger.info("⏭️ OLD HIGH PRIORITY market updater DISABLED (USE_SUBSQUID_MARKETS=true)")
            print("⏭️ OLD HIGH PRIORITY market updater DISABLED (using subsquid_markets_poll instead)")

        # Schedule LOW PRIORITY market updates (every hour)
        # Updates ALL markets with full pagination
        if not USE_SUBSQUID_MARKETS:
            scheduler.add_job(
                market_service.run_low_priority_update_cycle,
                IntervalTrigger(hours=1),
                id="market_updater_low_priority",
                replace_existing=True,
                max_instances=1  # Prevent overlapping runs
            )
            print(f"🌐 LOW PRIORITY market updater scheduled (every 1 hour - full database refresh)")
        else:
            logger.info("⏭️ OLD LOW PRIORITY market updater DISABLED (USE_SUBSQUID_MARKETS=true)")
            print("⏭️ OLD LOW PRIORITY market updater DISABLED (using subsquid_markets_poll instead)")

        # Initialize price updater (fast - just creates object, doesn't call API)
        from core.services import get_price_updater
        from config.config import PRICE_UPDATE_INTERVAL
        price_updater = get_price_updater()

        scheduler.add_job(
            price_updater.update_hot_prices,
            IntervalTrigger(seconds=PRICE_UPDATE_INTERVAL),
            id="price_updater_hot",
            replace_existing=True,
            max_instances=1
        )

        logger.info(f"✅ PRICE UPDATER JOB ADDED TO SCHEDULER")
        logger.info(f"   📅 Interval: {PRICE_UPDATE_INTERVAL}s")
        logger.info(f"   🎯 Function: {price_updater.update_hot_prices.__name__}")
        logger.debug(f"   🔍 Price updater object: {price_updater}")
        logger.debug(f"   🔍 Function callable: {callable(price_updater.update_hot_prices)}")

        # Price updater is now ENABLED
        if USE_SUBSQUID_MARKETS:
            logger.info("⏭️ SUBSQUID MODE: Price updater complements WebSocket + Poller")
        else:
            print("🔥 HOT PRICE updater scheduled (every 120s - Complements WebSocket with per-token precision)")
            print("   🎯 Complements: WebSocket + Poller")
            print("   💰 Cost: Low (DB + few API calls)")

    # Start scheduler in background (non-blocking)
    asyncio.create_task(initialize_scheduler_async())
    # Fetches 20 pages (~2,000 markets) to capture ALL new markets
    if not USE_SUBSQUID_MARKETS:
        _ensure_market_service_initialized()  # Initialize if needed
        scheduler.add_job(
            market_service.run_high_priority_update_cycle,
            IntervalTrigger(seconds=MARKET_UPDATE_INTERVAL),
            id="market_updater_high_priority",
            replace_existing=True,
            max_instances=1  # Prevent overlapping runs
        )
        print(f"🔥 HIGH PRIORITY market updater scheduled (every {MARKET_UPDATE_INTERVAL}s = {MARKET_UPDATE_INTERVAL//60} min - Fetches ALL new markets)")
    else:
        logger.info("⏭️ OLD HIGH PRIORITY market updater DISABLED (USE_SUBSQUID_MARKETS=true)")
        print("⏭️ OLD HIGH PRIORITY market updater DISABLED (using subsquid_markets_poll instead)")

    # Schedule LOW PRIORITY market updates (every hour)
    # Updates ALL markets with full pagination
    if not USE_SUBSQUID_MARKETS:
        scheduler.add_job(
            market_service.run_low_priority_update_cycle,
            IntervalTrigger(hours=1),
            id="market_updater_low_priority",
            replace_existing=True,
            max_instances=1  # Prevent overlapping runs
        )
        print(f"🌐 LOW PRIORITY market updater scheduled (every 1 hour - full database refresh)")
    else:
        logger.info("⏭️ OLD LOW PRIORITY market updater DISABLED (USE_SUBSQUID_MARKETS=true)")
        print("⏭️ OLD LOW PRIORITY market updater DISABLED (using subsquid_markets_poll instead)")

    # Initialize price updater (fast - just creates object, doesn't call API)
    from core.services import get_price_updater
    from config.config import PRICE_UPDATE_INTERVAL
    price_updater = get_price_updater()

    scheduler.add_job(
        price_updater.update_hot_prices,
        IntervalTrigger(seconds=PRICE_UPDATE_INTERVAL),
        id="price_updater_hot",
        replace_existing=True,
        max_instances=1  # Prevent overlapping runs
    )

    logger.info(f"✅ PRICE UPDATER JOB ADDED TO SCHEDULER")
    logger.info(f"   📅 Interval: {PRICE_UPDATE_INTERVAL}s")
    logger.info(f"   🎯 Function: {price_updater.update_hot_prices.__name__}")
    logger.debug(f"   🔍 Price updater object: {price_updater}")
    logger.debug(f"   🔍 Function callable: {callable(price_updater.update_hot_prices)}")

    # Price updater is now ENABLED
    if USE_SUBSQUID_MARKETS:
        print(f"🔥 HOT PRICE updater scheduled (every {PRICE_UPDATE_INTERVAL}s - Complements WebSocket with per-token precision)")
    else:
        print(f"🔥 HOT PRICE updater scheduled (every {PRICE_UPDATE_INTERVAL}s - Redis cache for TP/SL + positions)")
    print(f"   🎯 Complements: {'WebSocket + Poller' if USE_SUBSQUID_MARKETS else 'API only'}")
    print(f"   💰 Cost: {'Low (DB + few API calls)' if USE_SUBSQUID_MARKETS else 'Medium (API calls)'}")

    # Schedule NEW MARKETS DETECTION (every 5 minutes)
    # Fetches first 3 pages (1500 markets) to catch new markets quickly
    async def detect_new_markets():
        """
        Quick scan for new markets using Events API - first 3 pages (~300 events)
        Events API provides grouped markets (Win/Draw/Win) + individual markets
        Uses batch check (1 SQL query instead of 500) for performance
        """
        try:
            logger.info("🆕 Scanning for new markets (Events API)...")

            # Fetch events from Polymarket Events API
            events = await market_service.fetch_events_from_gamma(max_pages=3)

            # Extract all markets from events (includes event_id, event_slug, event_title)
            new_markets = market_service.extract_markets_from_events(events)

            if new_markets:
                # OPTIMIZED: Batch check existing IDs (1 SQL query instead of 500!)
                market_ids = [str(m.get('id')) for m in new_markets]
                existing_ids = market_repository.get_existing_ids(market_ids)

                # Filter out markets that already exist
                markets_to_add = [
                    market_service.transform_gamma_to_db(market)
                    for market in new_markets
                    if str(market.get('id')) not in existing_ids
                ]

                if markets_to_add:
                    market_repository.bulk_upsert(markets_to_add)
                    logger.info(f"✅ NEW MARKETS: Added {len(markets_to_add)} new markets from {len(events)} events (scanned {len(new_markets)} total)")
                else:
                    logger.debug(f"📭 No new markets found (scanned {len(new_markets)} markets from {len(events)} events)")
        except Exception as e:
            logger.error(f"❌ New market detection error: {e}")

    if not USE_SUBSQUID_MARKETS:
        scheduler.add_job(
            detect_new_markets,
            IntervalTrigger(minutes=5),
            id="new_market_detector",
            replace_existing=True,
            max_instances=1
        )
        print(f"🆕 NEW MARKET detector scheduled (every 5 min - Events API with batch check)")
    else:
        logger.info("⏭️ OLD NEW MARKET DETECTOR DISABLED (USE_SUBSQUID_MARKETS=true, handled by Poller)")
        print("⏭️ OLD NEW MARKET DETECTOR DISABLED (new market detection handled by subsquid Poller)")

    # ========================================
    # SUBSQUID MARKET AUTO-CATEGORIZER
    # ========================================
    # Auto-categorize NEW markets in subsquid_markets_poll (when USE_SUBSQUID_MARKETS=true)
    # Runs every 5 minutes, categorizes up to 20 uncategorized markets per cycle
    if USE_SUBSQUID_MARKETS:
        from core.services.subsquid_market_categorizer import get_subsquid_market_categorizer

        subsquid_categorizer = get_subsquid_market_categorizer()

        scheduler.add_job(
            subsquid_categorizer.categorize_new_markets,
            IntervalTrigger(minutes=5),
            id="subsquid_market_categorizer",
            replace_existing=True,
            max_instances=1,
            kwargs={'max_per_cycle': 20}  # Limit to 20 markets per cycle
        )
        logger.info("🏷️ SUBSQUID AUTO-CATEGORIZER enabled (every 5 min - max 20 markets/cycle)")
        print("🏷️ SUBSQUID AUTO-CATEGORIZER scheduled (every 5 min - auto-categorizes new markets, ~$0.0006/cycle)")

    # ========================================
    # MARKET CACHE PRELOADER (OPTIMIZATION)
    # ========================================
    # Preloads popular market pages to ensure instant /markets responses
    try:
        from core.services.market_cache_preloader import get_market_cache_preloader

        preloader = get_market_cache_preloader()

        # Initial cache warm-up (background task)
        async def warm_cache_on_startup():
            try:
                await asyncio.sleep(30)  # Wait for other services to initialize
                stats = preloader.warm_cache()
                logger.info(f"🔥 Cache warm-up complete: {stats}")
            except Exception as e:
                logger.error(f"❌ Cache warm-up error: {e}")

        asyncio.create_task(warm_cache_on_startup())

        # Schedule regular preload every 5 minutes
        scheduler.add_job(
            preloader.preload_popular_pages,
            IntervalTrigger(minutes=5),
            id="market_cache_preloader",
            replace_existing=True,
            max_instances=1
        )
        print("🔥 MARKET CACHE PRELOADER scheduled (every 5 min - preloads popular pages)")

    except Exception as e:
        logger.error(f"❌ Market cache preloader initialization error: {e}")

    # Schedule Auto-Approval Service (if enabled)
    if AUTO_APPROVAL_ENABLED:
        scheduler.add_job(
            auto_approval_service.monitor_unfunded_wallets,
            IntervalTrigger(seconds=WALLET_CHECK_INTERVAL_SECONDS),
            id="auto_approval_monitor",
            replace_existing=True,
            max_instances=1  # Prevent overlapping runs
        )
        print(f"⚡ AUTO-APPROVAL service scheduled (every {WALLET_CHECK_INTERVAL_SECONDS}s - wallet monitoring)")
    else:
        print("⚠️ Auto-approval service disabled in config")

    # Schedule SMART WALLET MONITOR (every 10 minutes)
    # Monitors trades from curated smart wallets and detects first-time market entries
    try:
        from core.services.smart_wallet_monitor_service import SmartWalletMonitorService
        from core.persistence.smart_wallet_repository import SmartWalletRepository
        from core.persistence.smart_wallet_trade_repository import SmartWalletTradeRepository

        smart_wallet_repo = SmartWalletRepository(db_session_instance)
        smart_trade_repo = SmartWalletTradeRepository(db_session_instance)

        # Initialize global smart_monitor instance
        smart_monitor = SmartWalletMonitorService(
            smart_wallet_repo,
            smart_trade_repo,
            "https://data-api.polymarket.com"
        )

        logger.info("✅ Smart wallet monitor service initialized")

        # ========================================
        # API POLLER DISABLED - NOV 4, 2025
        # ========================================
        # REASON: Causing duplicate alerts!
        # - Webhook system (subsquid) already captures trades instantly (with suffix: 0xabc_123)
        # - API poller inserts same trade WITHOUT suffix (0xabc) → creates duplicates
        # - Users get 2x alerts for same trade
        #
        # SOLUTION: Disable API poller, rely 100% on webhook → SmartWalletSyncService
        # - Webhook latency: <15 seconds
        # - SmartWalletSyncService enriches data from tracked_leader_trades
        # - No duplicates!
        #
        # NOTE: Keeping code below for emergency manual backfill if needed
        # ========================================

        # # Initial backfill (2 days) - ONLY IF FIRST TIME (empty database)
        # async def initial_smart_wallet_sync():
        #     try:
        #         # Wait 60 seconds for migrations to complete and server to be ready
        #         await asyncio.sleep(60)
        #
        #         # Check if we already have trades (not first time)
        #         existing_trades = smart_trade_repo.count_trades()
        #
        #         if existing_trades > 0:
        #             logger.info(f"📊 Smart wallet database already populated ({existing_trades} trades)")
        #             logger.info("⏭️ Skipping initial backfill (will sync new trades every 10 min)")
        #             return
        #
        #         logger.info("🔄 First startup detected - Starting initial backfill (background task)...")
        #
        #         csv_path = "insider_smart/curated active smart traders  - Feuille 1.csv"
        #         await smart_monitor.sync_smart_wallets_from_csv(csv_path)
        #
        #         logger.info("📊 CSV loaded, starting trade backfill (this will take 10-15 min)...")
        #         # Backfill last 2 days on first startup
        #         await smart_monitor.sync_all_wallets(since_minutes=2*24*60)  # 2 days in minutes
        #
        #         logger.info("✅ Initial smart wallet backfill complete!")
        #     except Exception as e:
        #         logger.error(f"Error in initial smart wallet sync: {e}")
        #
        # asyncio.create_task(initial_smart_wallet_sync())

        # # Schedule regular syncs every 10 minutes
        # # CRITICAL: Use the class method directly, like other services do
        # # This is the same pattern as market_service.run_high_priority_update_cycle
        # scheduler.add_job(
        #     smart_monitor.scheduled_sync,  # Call class method directly (like other services)
        #     IntervalTrigger(minutes=10),
        #     id="smart_wallet_monitor",
        #     replace_existing=True,
        #     misfire_grace_time=None  # CRITICAL: Always run missed jobs, no matter how late
        # )
        # print("📊 SMART WALLET Monitor scheduled (every 10 min - using class method like other services)")

        logger.info("⏭️ API Poller DISABLED - Using webhook system only (no duplicates!)")

        # ========================================
        # LEADERBOARD SCHEDULER
        # ========================================
        # Schedule leaderboard calculation every Sunday at midnight UTC
        try:
            from tasks.leaderboard_scheduler import schedule_leaderboard_calculation
            schedule_leaderboard_calculation(scheduler, debug_mode=False)
            logger.info("📊 Leaderboard scheduler configured (every Sunday midnight UTC)")
        except Exception as e:
            logger.error(f"❌ Leaderboard scheduler error: {e}")

        # ========================================
        # COPY TRADING MONITOR (Option 3 - Real-Time Sync)
        # ========================================
        # Monitors leader trades and triggers copies (2-5 sec latency for top leaders)
        try:
            from core.services.copy_trading_monitor import get_copy_trading_monitor

            copy_trading_monitor = get_copy_trading_monitor()

            # Start Redis Pub/Sub listener for instant webhook notifications
            # This provides <10s latency for copy trading
            asyncio.create_task(copy_trading_monitor.start_redis_listener())
            print("📢 COPY TRADING Redis Pub/Sub listener started (instant webhooks)")

            # Job 1: General polling every 120 seconds (ALL leaders) - FALLBACK
            # OPTIMIZED: Reduced from 10s → 60s → 120s to reduce Supabase load
            # Redis Pub/Sub handles instant (<10s), this is just safety net
            scheduler.add_job(
                copy_trading_monitor.poll_and_copy_trades,
                IntervalTrigger(seconds=120),
                id="copy_trading_general_poller",
                replace_existing=True,
                max_instances=1
            )
            print("🔄 COPY TRADING General Poller scheduled (every 120s - ULTRA OPTIMIZED, Redis handles instant)")

            # Job 2: Fast-track polling every 60 seconds (TOP 20 leaders for lower latency)
            # OPTIMIZED: Reduced from 10s → 30s → 60s to reduce Supabase load
            # Redis Pub/Sub handles instant, this is just backup
            scheduler.add_job(
                copy_trading_monitor.fast_track_top_leaders,
                IntervalTrigger(seconds=60),
                id="copy_trading_fast_track",
                replace_existing=True,
                max_instances=1
            )
            print("⚡ COPY TRADING Fast-Track scheduled (every 60s - ULTRA OPTIMIZED, Redis handles instant)")

            # Job 3: Update top leaders list every hour
            scheduler.add_job(
                copy_trading_monitor.update_top_leaders_list,
                IntervalTrigger(hours=1),
                id="copy_trading_update_leaders",
                replace_existing=True,
                max_instances=1
            )
            print("👑 COPY TRADING Top Leaders Updater scheduled (every 1h)")

            logger.info("✅ Copy trading monitor initialized and scheduled")

        except Exception as e:
            logger.error(f"❌ Copy trading monitor initialization error: {e}")
            import traceback
            logger.error(traceback.format_exc())

        # ========================================
        # SUBSQUID MIGRATION JOBS (Phases 3-5)
        # ========================================
        from config.config import (
            SUBSQUID_FILTER_ENABLED,
            SUBSQUID_CLEANUP_ENABLED,
            SUBSQUID_FILTER_INTERVAL,
            SUBSQUID_CLEANUP_INTERVAL
        )

        if SUBSQUID_FILTER_ENABLED:
            try:
                from core.services.subsquid_filter_service import get_subsquid_filter_service
                filter_service = get_subsquid_filter_service()
                # ULTRA OPTIMIZED: Use 120s (2min) interval - Webhook handles 99% of cases
                # This is just a fallback safety net for missed webhooks
                optimized_filter_interval = 120
                scheduler.add_job(
                    filter_service.run_filter_cycle,
                    IntervalTrigger(seconds=optimized_filter_interval),
                    id="subsquid_filter",
                    replace_existing=True,
                    max_instances=1
                )
                print(f"🔄 SUBSQUID FILTER job scheduled (every {optimized_filter_interval}s - ULTRA OPTIMIZED, webhook handles instant)")
            except Exception as e:
                logger.error(f"❌ Subsquid filter error: {e}")

        try:
            from core.services.smart_wallet_sync_service import get_smart_wallet_sync_service
            smart_sync_service = get_smart_wallet_sync_service()

            # Wrapper to handle async function in scheduler
            async def run_sync_with_error_handling():
                """Wrapper to properly handle async run_sync_cycle with error logging"""
                try:
                    logger.info("🔄 [SCHEDULER] Triggering smart wallet sync cycle...")
                    await smart_sync_service.run_sync_cycle()
                    logger.info("✅ [SCHEDULER] Smart wallet sync cycle completed")
                except Exception as e:
                    logger.error(f"❌ [SCHEDULER] run_sync_cycle failed: {e}")
                    import traceback
                    logger.error(traceback.format_exc())

                    # Clean up any lingering notification tasks on error
                    try:
                        await smart_sync_service.cleanup_notification_tasks()
                    except Exception as cleanup_error:
                        logger.warning(f"⚠️ [SCHEDULER] Failed to cleanup notification tasks: {cleanup_error}")

            # Schedule with async wrapper - every 180s (3 min)
            # Polling backup: Validates webhook data + fills gaps
            scheduler.add_job(
                run_sync_with_error_handling,
                IntervalTrigger(seconds=180),
                id="smart_wallet_sync",
                replace_existing=True,
                max_instances=1
            )
            print("🔄 SMART WALLET SYNC job scheduled (every 180s - Polling backup + validation)")
            logger.info("✅ Smart wallet sync scheduler configured with async wrapper")
        except Exception as e:
            logger.error(f"❌ Smart wallet sync setup error: {e}")
            import traceback
            logger.error(traceback.format_exc())

        if SUBSQUID_CLEANUP_ENABLED:
            async def cleanup_subsquid_transactions():
                try:
                    with db_manager.get_session() as db:
                        from database import SubsquidUserTransaction
                        from datetime import timezone, timedelta
                        cutoff = datetime.now(timezone.utc) - timedelta(days=2, hours=1)
                        deleted = db.query(SubsquidUserTransaction).filter(
                            SubsquidUserTransaction.timestamp < cutoff
                        ).delete()
                        db.commit()
                        logger.info(f"🗑️ [CLEANUP] Deleted {deleted} old subsquid records")
                except Exception as e:
                    logger.error(f"❌ [CLEANUP] Error: {e}")

            scheduler.add_job(
                cleanup_subsquid_transactions,
                IntervalTrigger(seconds=SUBSQUID_CLEANUP_INTERVAL),
                id="subsquid_cleanup",
                replace_existing=True
            )
            print(f"🗑️ SUBSQUID CLEANUP job scheduled (every {SUBSQUID_CLEANUP_INTERVAL//3600}h)")

        # ========================================
        # MARKET RESOLUTION MONITOR - DISABLED
        # Resolution now handled by dedicated resolution-worker cron on Railway
        # ========================================
        logger.info("ℹ️ Market resolution monitoring disabled - handled by resolution-worker")

        # ========================================
        # TWITTER BOT INITIALIZATION (BACKGROUND)
        # ========================================
        # Schedule Twitter bot to initialize ASYNCHRONOUSLY after 90 seconds
        # This prevents it from blocking the critical startup path
        async def init_twitter_bot_background():
            """Initialize Twitter bot in background to avoid startup delays"""
            try:
                # Wait 90 seconds for all critical services to stabilize
                await asyncio.sleep(90)

                logger.info("🐦 Initializing Twitter Bot Service (background)...")

                from core.services.twitter_bot_service import TwitterBotService
                from telegram_bot.services.market_service import MarketService

                twitter_enabled = os.getenv("TWITTER_ENABLED", "false").lower() == "true"

                if twitter_enabled or os.getenv("TWITTER_DRY_RUN", "true").lower() == "true":
                    try:
                        # Initialize market service for Polymarket links
                        market_service_for_twitter = MarketService()

                        # Initialize Twitter bot
                        twitter_bot = TwitterBotService(
                            trade_repo=smart_trade_repo,
                            wallet_repo=smart_wallet_repo,
                            db_session=db_session_instance,
                            market_service=market_service_for_twitter
                        )

                        # Schedule job every 2 minutes
                        scheduler.add_job(
                            twitter_bot.process_pending_trades,
                            IntervalTrigger(minutes=2),
                            id="twitter_bot",
                            replace_existing=True,
                            misfire_grace_time=None
                        )

                        status = twitter_bot.get_status()
                        logger.info(f"✅ Twitter Bot scheduled successfully (every 2 min) - Enabled: {status['enabled']}, Dry Run: {status['dry_run']}")
                        print(f"🐦 TWITTER BOT scheduled (every 2 min) - Enabled: {status.get('enabled', 'unknown')}")
                    except ImportError as ie:
                        logger.error(f"❌ Failed to import Twitter bot dependencies: {ie}")
                        print(f"⚠️ Twitter Bot dependencies missing: {ie}")
                    except Exception as e:
                        logger.error(f"❌ Error initializing Twitter Bot: {e}")
                        import traceback
                        logger.error(traceback.format_exc())
                        print(f"⚠️ Twitter Bot initialization failed: {e}")
                else:
                    logger.info("⏸️ Twitter Bot DISABLED (set TWITTER_ENABLED=true to enable)")
                    print("⏸️ TWITTER BOT disabled")
            except Exception as e:
                logger.error(f"❌ Background Twitter Bot initialization failed: {e}")

        # Schedule it ASYNCHRONOUSLY - doesn't block startup!
        asyncio.create_task(init_twitter_bot_background())
        print("📋 TWITTER BOT will initialize in background (90 seconds)")

        # Add a listener to log ALL scheduler events (not just errors)
        def scheduler_listener(event):
            from apscheduler.events import (
                EVENT_JOB_EXECUTED, EVENT_JOB_ERROR, EVENT_JOB_MISSED
            )

            if event.code == EVENT_JOB_ERROR:
                logger.error(f"❌ [SCHEDULER] Job '{event.job_id}' failed!")
                logger.error(f"Exception: {event.exception}")
                if event.traceback:
                    import traceback
                    logger.error("".join(traceback.format_tb(event.traceback)))
            elif event.code == EVENT_JOB_EXECUTED:
                logger.debug(f"✅ [SCHEDULER] Job '{event.job_id}' executed successfully")
            elif event.code == EVENT_JOB_MISSED:
                logger.warning(f"⚠️ [SCHEDULER] Job '{event.job_id}' missed!")

        from apscheduler.events import (
            EVENT_JOB_EXECUTED, EVENT_JOB_ERROR, EVENT_JOB_MISSED
        )
        scheduler.add_listener(
            scheduler_listener,
            EVENT_JOB_EXECUTED | EVENT_JOB_ERROR | EVENT_JOB_MISSED
        )

        # Store references globally for Telegram handler
        import telegram_bot.handlers.smart_trading_handler as smart_handler
        smart_handler.init_repositories(smart_wallet_repo, smart_trade_repo)

    except Exception as e:
        print(f"⚠️ Failed to initialize Smart Wallet Monitor: {e}")

    # Initialize and schedule Watched Markets Service
    try:
        from core.services.watched_markets_service import get_watched_markets_service
        watched_markets_service = get_watched_markets_service()

        # Schedule watched markets scan every 30 minutes
        async def scan_watched_markets():
            """Scan and update watched markets for streamer subscriptions"""
            try:
                result = await watched_markets_service.scan_and_update_watched_markets()
                logger.info(f"📈 Watched markets scan complete: {result}")
            except Exception as e:
                logger.error(f"❌ Watched markets scan failed: {e}")

        scheduler.add_job(
            scan_watched_markets,
            IntervalTrigger(minutes=30),
            id="watched_markets_scan",
            replace_existing=True,
            misfire_grace_time=300  # 5 minutes grace period
        )

        # ✅ NEW: Process pending watched markets every 10 seconds
        async def process_pending_markets():
            """Process cached pending markets into DB every 10 seconds"""
            try:
                processed = await watched_markets_service.process_pending_watched_markets()
                if processed > 0:
                    logger.debug(f"📦 Processed {processed} pending markets from cache")
            except Exception as e:
                logger.error(f"⚠️ Pending markets processing failed: {e}", exc_info=True)

        # Schedule pending markets processing every 10 seconds
        scheduler.add_job(
            process_pending_markets,
            IntervalTrigger(seconds=10),
            id="pending_markets_processing",
            replace_existing=True,
            misfire_grace_time=30
        )

        # DON'T trigger initial scan at startup - it blocks the bot for 100+ seconds
        # The scheduled job will run after 30 minutes
        # asyncio.create_task(scan_watched_markets())

        print("📊 WATCHED MARKETS SERVICE scheduled (every 30 min + pending processing every 10s)")
        logger.info("✅ Watched Markets Service initialized and scheduled (delayed first run)")

    except Exception as e:
        logger.error(f"❌ Failed to initialize Watched Markets Service: {e}")
        print(f"⚠️ Watched Markets Service initialization failed: {e}")

    # Initialize Telegram Bot in background to avoid blocking healthcheck
    async def initialize_telegram_bot_async():
        """Initialize Telegram bot asynchronously after HTTP server starts"""
        global telegram_bot
        try:
            await asyncio.sleep(1)  # Let HTTP server start first
            logger.info("🤖 Initializing Telegram bot (background)...")

            telegram_bot = TelegramTradingBot()

            # Initialize Smart Trading Notification Service
            try:
                from core.services.smart_trading_notification_service import (
                    SmartTradingNotificationService,
                    set_smart_trading_notification_service
                )
                notification_service = SmartTradingNotificationService(telegram_bot.app)
                set_smart_trading_notification_service(notification_service)
                logger.info("✅ Smart Trading Notification Service initialized")

                # Connect push processor to notification service
                push_processor.set_notification_service(notification_service)
                logger.info("✅ Push Processor connected to Notification Service")
            except Exception as notif_error:
                logger.error(f"❌ Failed to initialize notification service: {notif_error}")

            # Start Telegram bot in polling mode
            await start_telegram_bot()
            # NOTE: start_telegram_bot() now runs polling indefinitely, so this code won't be reached
        except Exception as e:
            logger.error(f"❌ Failed to initialize Telegram bot: {e}")
            import traceback
            logger.error(traceback.format_exc())

    if BOT_TOKEN:
        asyncio.create_task(initialize_telegram_bot_async())
        logger.info("📱 Telegram bot initialization scheduled (background)")
    else:
        logger.warning("⚠️ BOT_TOKEN not found, Telegram bot disabled")

    logger.info("✅ 24/7 Server startup complete! (PostgreSQL + Telegram Bot running)")
    logger.info("🚀 STARTUP: FastAPI ready - all background tasks launched")

    # CRITICAL: Extended delay to ensure HTTP server is fully bound
    logger.info("⏳ WAITING: Ensuring HTTP server is fully bound (5s delay)...")
    await asyncio.sleep(5)  # Extended delay for Railway

    logger.info("🔗 HTTP SERVER SHOULD BE READY: Railway healthcheck can now access /health")
    logger.info("🏥 HEALTH ENDPOINT: Available at /health (ultra-minimal response)")

print("🔍 MODULE: main.py module loaded successfully - end of file reached")

def start_telegram_bot_polling():
    """Start the Telegram bot polling in a separate thread"""
    async def run_polling():
        """Async function to run polling"""
        print("🔍 TELEGRAM_BOT: Starting bot in POLLING mode...")
        global telegram_bot

        try:
            if not telegram_bot:
                print("❌ ERROR: telegram_bot is None - bot initialization failed!")
                logger.error("❌ telegram_bot is None - initialization must have failed silently")
                return

            print("🤖 Initializing Telegram bot...")
            await telegram_bot.app.initialize()
            await telegram_bot.setup_bot_commands()

            # Start TP/SL Price Monitor
            await telegram_bot.price_monitor.start()
            print("🔄 TP/SL Price Monitor started - checking every 30 seconds")

            # Clear any existing webhook (important for polling mode)
            print("🧹 Clearing any existing webhook...")
            try:
                await asyncio.wait_for(
                    telegram_bot.app.bot.delete_webhook(drop_pending_updates=True),
                    timeout=5.0
                )
                print("✅ Webhook cleared - bot ready for polling")
            except Exception as e:
                print(f"⚠️ Could not clear webhook (may not exist): {e}")

            print("🎯 Starting Telegram polling...")
            print("🤖 Bot is now listening for commands!")

            # Start polling - this will run indefinitely
            await telegram_bot.app.run_polling(
                poll_interval=1,  # Check for updates every 1 second
                timeout=30,       # Timeout for long polling
                drop_pending_updates=True  # Clear any pending updates on startup
            )

        except Exception as e:
            print(f"❌ Telegram bot polling error: {e}")
            import traceback
            print(f"❌ Full traceback:\n{traceback.format_exc()}")

    # Create new event loop for the polling thread
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(run_polling())

async def start_telegram_bot():
    """Start the Telegram bot polling in background thread"""
    print("🚀 Starting Telegram bot polling in background thread...")
    polling_thread = threading.Thread(target=start_telegram_bot_polling, daemon=True)
    polling_thread.start()
    print("✅ Telegram bot polling thread started")

@app.on_event("shutdown")
async def shutdown_event():
    """Clean shutdown"""
    global telegram_bot

    print("🛑 Shutting down 24/7 server...")

    # Release bot instance lock
    try:
        from core.services.redis_price_cache import RedisPriceCache
        redis_cache = RedisPriceCache()
        if redis_cache.redis_client:
            lock_key = "telegram_bot_instance_lock"
            redis_cache.redis_client.delete(lock_key)
            print("🔓 Released bot instance lock")
    except Exception as e:
        print(f"⚠️ Error releasing bot lock: {e}")

    # Stop Telegram bot and Price Monitor
    if telegram_bot:
        try:
            # Stop Price Monitor first
            if telegram_bot.price_monitor and telegram_bot.price_monitor.is_running:
                await telegram_bot.price_monitor.stop()
                print("✅ TP/SL Price Monitor stopped")

            # Stop Telegram bot
            await telegram_bot.app.stop()
            print("✅ Telegram bot stopped")
        except Exception as e:
            print(f"⚠️ Error stopping Telegram bot: {e}")

    # Stop auto-approval service
    if AUTO_APPROVAL_ENABLED and auto_approval_service.is_running:
        auto_approval_service.is_running = False
        print("✅ Auto-approval service stopped")

    # Close smart wallet monitor HTTP client
    try:
        if 'smart_monitor' in globals():
            await smart_monitor.close()
            print("✅ Smart wallet monitor HTTP client closed")
    except Exception as e:
        print(f"⚠️ Error closing smart wallet monitor: {e}")

    # Stop scheduler
    scheduler.shutdown(wait=True)
    print("✅ Scheduler stopped")

    # Close database session
    from core.persistence import close_db_session
    close_db_session()
    print("✅ Database connections closed")

    print("✅ Server shutdown complete")

# API Endpoints
@app.get("/")
async def root():
    """Health check endpoint"""
    return {
        "service": "Polymarket Database API",
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": "1.0.0"
    }

@app.get("/markets")
async def get_markets(
    days_window: int = Query(30, description="Show markets from last N days"),
    limit: Optional[int] = Query(None, description="Max markets to return")
):
    """
    Get markets from PostgreSQL database

    Shows:
    - All active markets
    - Markets finished in last N days
    - Markets resolved in last N days
    """
    try:
        # Use MarketDataLayer (migrated from old markets table to subsquid_markets_poll)
        from core.services.market_data_layer import get_market_data_layer
        market_layer = get_market_data_layer()

        # Get markets using new subsquid system
        if limit:
            markets = market_layer.get_high_volume_markets(limit=limit)
        else:
            # Default limit for API to prevent huge responses
            markets = market_layer.get_high_volume_markets(limit=500)

        return {
            "markets": markets,
            "count": len(markets)
        }

    except Exception as e:
        logger.error(f"Failed to get markets: {e}")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

@app.get("/markets/tradeable")
async def get_tradeable_markets(
    limit: Optional[int] = Query(None, description="Max markets to return")
):
    """Get only tradeable markets from PostgreSQL"""
    try:
        markets = market_repository.get_tradeable_markets(limit)
        markets_data = [market.to_dict() for market in markets]

        return {
            "markets": markets_data,
            "count": len(markets_data)
        }
    except Exception as e:
        logger.error(f"Failed to get tradeable markets: {e}")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

@app.get("/markets/{market_id}")
async def get_market(market_id: str):
    """Get specific market by ID from PostgreSQL"""
    try:
        market = market_repository.get_by_id(market_id)

        if not market:
            raise HTTPException(status_code=404, detail=f"Market {market_id} not found")

        return market.to_dict()

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get market {market_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

@app.get("/performance")
async def performance_status():
    """Get detailed performance metrics"""
    try:
        import psutil
        import os

        # System metrics
        process = psutil.Process(os.getpid())
        memory_info = process.memory_info()

        # Get cache hit rates
        from core.services.redis_price_cache import get_redis_cache
        redis_cache = get_redis_cache()
        cache_stats = redis_cache.get_cache_stats()

        # Calculate hit rate
        total_requests = cache_stats.get('hits', 0) + cache_stats.get('misses', 0)
        hit_rate = (cache_stats.get('hits', 0) / total_requests * 100) if total_requests > 0 else 0

        # Get active sessions
        from telegram_bot.session_manager import session_manager
        active_sessions = len(session_manager.sessions)

        # Get scheduler job details
        jobs = scheduler.get_jobs()
        job_details = []
        for job in jobs:
            job_details.append({
                'id': job.id,
                'next_run': job.next_run_time.isoformat() if job.next_run_time else None,
                'trigger': str(job.trigger)
            })

        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "system": {
                "ram_mb": round(memory_info.rss / 1024 / 1024, 2),
                "ram_percent": round(process.memory_percent(), 2),
                "cpu_percent": round(process.cpu_percent(), 2)
            },
            "cache_performance": {
                "hit_rate_percent": round(hit_rate, 2),
                "total_requests": total_requests,
                "cache_hits": cache_stats.get('hits', 0),
                "cache_misses": cache_stats.get('misses', 0),
                "cache_errors": cache_stats.get('errors', 0)
            },
            "sessions": {
                "active_sessions": active_sessions
            },
            "scheduler": {
                "running": scheduler.running,
                "jobs_count": len(jobs),
                "jobs": job_details
            },
            "optimization_status": {
                "hot_price_interval": "60s (optimized from 20s)",
                "hot_price_limit": "50 markets (optimized from 100)",
                "cache_ttl_optimized": True
            }
        }
    except Exception as e:
        return {"error": str(e), "timestamp": datetime.now(timezone.utc).isoformat()}

@app.get("/search/{query}")
async def search_markets(
    query: str,
    limit: int = Query(100, description="Max results to return")
):
    """Search markets by keyword in PostgreSQL database"""
    try:
        # Validate input
        if len(query.strip()) < 2:
            raise HTTPException(
                status_code=400,
                detail="Search query must be at least 2 characters"
            )

        # Search PostgreSQL via repository
        results = market_repository.search_by_keyword(query.strip(), limit)
        results_data = [market.to_dict() for market in results]

        return {
            "query": query.strip(),
            "results": results_data,
            "count": len(results_data),
            "limit": limit
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Search failed for query '{query}': {e}")
        raise HTTPException(status_code=500, detail=f"Search error: {str(e)}")

@app.post("/markets/force-update")
async def force_update(background_tasks: BackgroundTasks):
    """Force immediate market update from Gamma API"""
    background_tasks.add_task(market_service.run_update_cycle)
    return {
        "message": "Market update scheduled",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

@app.post("/admin/run-migration")
async def run_migration():
    """
    Run the market grouping enhancement SQL migration
    ⚠️ ADMIN ONLY - Adds 40+ columns to markets table
    """
    try:
        from pathlib import Path
        import psycopg2

        # Get DATABASE_URL from environment
        database_url = os.getenv('DATABASE_URL')
        if not database_url:
            raise HTTPException(status_code=500, detail="DATABASE_URL not configured")

        # Read clean migration file (without RAISE NOTICE statements)
        migration_file = Path(__file__).parent / 'migrations/2025-10-06_market_grouping_enhancement/add_market_metadata_clean.sql'

        if not migration_file.exists():
            raise HTTPException(status_code=404, detail="Migration file not found")

        with open(migration_file, 'r') as f:
            sql_content = f.read()

        # Execute migration
        conn = psycopg2.connect(database_url)
        conn.set_session(autocommit=False)
        cursor = conn.cursor()

        cursor.execute(sql_content)

        # Collect notices
        notices = [notice.strip() for notice in conn.notices]

        # Commit
        conn.commit()

        # Verify by checking column count
        cursor.execute("""
            SELECT COUNT(*)
            FROM information_schema.columns
            WHERE table_name = 'markets'
        """)
        column_count = cursor.fetchone()[0]

        cursor.close()
        conn.close()

        return {
            "success": True,
            "message": "Migration completed successfully",
            "column_count": column_count,
            "notices": notices,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

    except psycopg2.Error as e:
        logger.error(f"Migration failed: {e}")
        raise HTTPException(status_code=500, detail=f"PostgreSQL error: {str(e)}")
    except Exception as e:
        logger.error(f"Migration error: {e}")
        raise HTTPException(status_code=500, detail=f"Migration error: {str(e)}")

@app.get("/markets/stats")
async def get_market_stats():
    """Get market statistics from PostgreSQL"""
    try:
        stats = market_repository.get_statistics()
        market_health = market_service.get_health_status()

        return {
            **stats,
            "last_update": market_health['last_update'],
            "update_frequency_seconds": MARKET_UPDATE_INTERVAL,
            "last_cycle_stats": market_health['last_stats']
        }
    except Exception as e:
        logger.error(f"Failed to get stats: {e}")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

@app.get("/status")
async def get_status():
    """Get detailed server status"""
    try:
        stats = market_repository.count_by_status()
        market_health = market_service.get_health_status()

        # Get Redis cache stats
        from core.services import get_redis_cache, get_price_updater, get_market_group_cache
        redis_cache = get_redis_cache()
        price_updater = get_price_updater()
        group_cache = get_market_group_cache()

        return {
            "server": {
                "status": "running",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "scheduler_running": scheduler.running
            },
            "database": {
                "type": "postgresql",
                "total_markets": stats['total'],
                "active_markets": stats['active'],
                "closed_markets": stats['closed'],
                "resolved_markets": stats['resolved']
            },
            "market_updater": market_health,
            "caches": {
                "redis_prices": redis_cache.get_cache_stats(),
                "redis_markets": {
                    "cached_markets": redis_cache.count_cached_markets(),
                    "enabled": redis_cache.enabled
                },
                "market_groups": group_cache.get_stats()
            },
            "price_updater": price_updater.get_health_status()
        }
    except Exception as e:
        logger.error(f"Failed to get status: {e}")
        raise HTTPException(status_code=500, detail=f"Status check failed: {str(e)}")

@app.get("/tpsl/monitor")
async def get_tpsl_monitor():
    """
    TP/SL Live Monitoring Dashboard

    Shows all active TP/SL orders with:
    - Current prices vs targets
    - Distance to trigger (percentage)
    - Last check timestamp
    - Position details
    - Recently triggered orders (last 24 hours)
    """
    try:
        from database import TPSLOrder
        from core.services.redis_price_cache import get_redis_cache
        from core.persistence.db_config import SessionLocal
        from sqlalchemy import desc

        # Get all active TP/SL orders
        session = SessionLocal()
        try:
            active_orders = session.query(TPSLOrder).filter(
                TPSLOrder.status == 'active'
            ).order_by(desc(TPSLOrder.last_price_check)).all()

            # Get recently triggered orders (last 24 hours)
            cutoff_time = datetime.utcnow() - timedelta(hours=24)
            triggered_orders = session.query(TPSLOrder).filter(
                TPSLOrder.status == 'triggered',
                TPSLOrder.triggered_at >= cutoff_time
            ).order_by(desc(TPSLOrder.triggered_at)).limit(50).all()

            # Get current prices for all tokens
            token_ids = [order.token_id for order in active_orders]
            current_prices = {}
            if token_ids:
                redis_cache = get_redis_cache()
                prices_dict = redis_cache.get_token_prices_batch(token_ids)
                current_prices = {tid: float(p) if p else None for tid, p in prices_dict.items()}

            # Build response
            orders_data = []
            for order in active_orders:
                current_price = current_prices.get(order.token_id)
                entry_price = float(order.entry_price)
                tp_price = float(order.take_profit_price) if order.take_profit_price else None
                sl_price = float(order.stop_loss_price) if order.stop_loss_price else None

                # Calculate distances to targets
                tp_distance = None
                sl_distance = None
                if current_price:
                    if tp_price:
                        tp_distance = ((tp_price - current_price) / current_price) * 100
                    if sl_price:
                        sl_distance = ((current_price - sl_price) / current_price) * 100

                # Determine status
                if current_price:
                    if tp_price and current_price >= tp_price:
                        trigger_status = "⚠️ TP TARGET HIT! Awaiting execution"
                    elif sl_price and current_price <= sl_price:
                        trigger_status = "⚠️ SL TARGET HIT! Awaiting execution"
                    elif tp_distance and tp_distance < 1:
                        trigger_status = f"🔥 Close to TP ({tp_distance:.2f}% away)"
                    elif sl_distance and sl_distance < 1:
                        trigger_status = f"🔥 Close to SL ({sl_distance:.2f}% away)"
                    else:
                        trigger_status = "✅ Monitoring"
                else:
                    trigger_status = "⚠️ Price unavailable"

                # Get market data
                market_data = order.market_data or {}
                market_question = market_data.get('question', 'Unknown Market')

                orders_data.append({
                    "order_id": order.id,
                    "user_id": order.user_id,
                    "market": market_question[:80],
                    "position": order.outcome.upper(),
                    "tokens": float(order.monitored_tokens),
                    "entry_transaction_id": order.entry_transaction_id,
                    "prices": {
                        "entry": entry_price,
                        "current": current_price,
                        "take_profit": tp_price,
                        "stop_loss": sl_price
                    },
                    "distances": {
                        "to_tp_percent": round(tp_distance, 2) if tp_distance else None,
                        "to_sl_percent": round(sl_distance, 2) if sl_distance else None
                    },
                    "trigger_status": trigger_status,
                    "last_check": order.last_price_check.isoformat() if order.last_price_check else None,
                    "created_at": order.created_at.isoformat()
                })

            # Build triggered orders data
            triggered_data = []
            slippage_values = []  # Track slippage for summary stats
            for order in triggered_orders:
                entry_price = float(order.entry_price)
                execution_price = float(order.execution_price) if order.execution_price else None
                monitored_tokens = float(order.monitored_tokens)

                # Calculate P&L
                if execution_price:
                    pnl = (execution_price - entry_price) * monitored_tokens
                    pnl_percent = ((execution_price - entry_price) / entry_price) * 100 if entry_price > 0 else 0
                else:
                    pnl = 0
                    pnl_percent = 0

                # CRITICAL FIX (Bug #9 - Phase 4): Calculate slippage (difference between target and execution)
                target_price = None
                slippage_dollars = None
                slippage_percent = None
                slippage_warning = False

                if execution_price:
                    if order.triggered_type == 'take_profit' and order.take_profit_price:
                        target_price = float(order.take_profit_price)
                    elif order.triggered_type == 'stop_loss' and order.stop_loss_price:
                        target_price = float(order.stop_loss_price)

                    if target_price:
                        slippage_dollars = abs(execution_price - target_price)
                        slippage_percent = (slippage_dollars / target_price * 100) if target_price > 0 else 0
                        slippage_warning = slippage_percent > 5.0  # Flag if >5% slippage
                        slippage_values.append(slippage_percent)

                # Get market data
                market_data = order.market_data or {}
                market_question = market_data.get('question', 'Unknown Market')

                # Format time ago
                time_ago = "Unknown"
                if order.triggered_at:
                    diff = datetime.utcnow() - order.triggered_at
                    if diff.days > 0:
                        time_ago = f"{diff.days}d ago"
                    elif diff.seconds >= 3600:
                        hours = diff.seconds // 3600
                        time_ago = f"{hours}h ago"
                    elif diff.seconds >= 60:
                        minutes = diff.seconds // 60
                        time_ago = f"{minutes}m ago"
                    else:
                        time_ago = "just now"

                triggered_data.append({
                    "order_id": order.id,
                    "user_id": order.user_id,
                    "market": market_question[:80],
                    "position": order.outcome.upper(),
                    "tokens": monitored_tokens,
                    "entry_transaction_id": order.entry_transaction_id,
                    "trigger_type": order.triggered_type,  # "take_profit" or "stop_loss"
                    "prices": {
                        "entry": entry_price,
                        "execution": execution_price,
                        "target": target_price
                    },
                    "pnl": {
                        "amount": round(pnl, 2),
                        "percent": round(pnl_percent, 2)
                    },
                    "slippage": {
                        "dollars": round(slippage_dollars, 4) if slippage_dollars else None,
                        "percent": round(slippage_percent, 2) if slippage_percent else None,
                        "warning": slippage_warning
                    },
                    "triggered_at": order.triggered_at.isoformat() if order.triggered_at else None,
                    "time_ago": time_ago
                })

            # Get cache stats if we have a redis instance
            cache_stats = redis_cache.get_cache_stats() if token_ids else {}

            # CRITICAL FIX (Bug #9 - Phase 4): Add slippage summary stats
            slippage_stats = {}
            if slippage_values:
                slippage_stats = {
                    "average_slippage_percent": round(sum(slippage_values) / len(slippage_values), 2),
                    "min_slippage_percent": round(min(slippage_values), 2),
                    "max_slippage_percent": round(max(slippage_values), 2),
                    "orders_with_high_slippage": sum(1 for s in slippage_values if s > 5.0),
                    "total_measured": len(slippage_values)
                }

            result = {
                "status": "success",
                "timestamp": datetime.utcnow().isoformat(),
                "summary": {
                    "total_active_orders": len(active_orders),
                    "total_triggered_24h": len(triggered_orders),
                    "monitoring_interval": "10 seconds",
                    "price_cache_status": cache_stats,
                    "slippage_stats_24h": slippage_stats  # NEW: Slippage monitoring
                },
                "active_orders": orders_data,
                "recently_triggered": triggered_data
            }
            return result
        finally:
            session.close()

    except Exception as e:
        logger.error(f"Failed to get TP/SL monitor data: {e}")
        raise HTTPException(status_code=500, detail=f"TP/SL monitor failed: {str(e)}")

@app.get("/monitor")
async def get_monitor_dashboard():
    """
    Market System Monitoring Dashboard

    Shows comprehensive statistics about market updates,
    new markets added, resolutions, and system health.
    """
    try:
        from sqlalchemy import func, and_
        from datetime import timedelta

        # Calculate time windows
        now = datetime.utcnow()
        one_hour_ago = now - timedelta(hours=1)
        one_day_ago = now - timedelta(days=1)
        seven_days_ago = now - timedelta(days=7)
        thirty_days_ago = now - timedelta(days=30)

        # Get basic stats
        stats = market_repository.count_by_status()
        market_health = market_service.get_health_status()

        # Count markets by time windows
        markets_1h = db_session_instance.query(func.count(Market.id)).filter(
            Market.created_at > one_hour_ago
        ).scalar()

        markets_24h = db_session_instance.query(func.count(Market.id)).filter(
            Market.created_at > one_day_ago
        ).scalar()

        markets_7d = db_session_instance.query(func.count(Market.id)).filter(
            Market.created_at > seven_days_ago
        ).scalar()

        # Count resolved markets by time windows
        resolved_1h = db_session_instance.query(func.count(Market.id)).filter(
            Market.resolved_at > one_hour_ago
        ).scalar()

        resolved_24h = db_session_instance.query(func.count(Market.id)).filter(
            Market.resolved_at > one_day_ago
        ).scalar()

        resolved_7d = db_session_instance.query(func.count(Market.id)).filter(
            Market.resolved_at > seven_days_ago
        ).scalar()

        # Count finished (closed) markets by time windows
        finished_1h = db_session_instance.query(func.count(Market.id)).filter(
            and_(
                Market.closed == True,
                Market.last_updated > one_hour_ago
            )
        ).scalar()

        finished_24h = db_session_instance.query(func.count(Market.id)).filter(
            and_(
                Market.closed == True,
                Market.last_updated > one_day_ago
            )
        ).scalar()

        # Count updated markets in last hour
        updated_1h = db_session_instance.query(func.count(Market.id)).filter(
            Market.last_updated > one_hour_ago
        ).scalar()

        return {
            "timestamp": now.isoformat(),
            "system": {
                "status": market_health['status'],
                "last_update": market_health['last_update'],
                "consecutive_errors": market_health['consecutive_errors'],
                "update_frequency_seconds": MARKET_UPDATE_INTERVAL
            },
            "database": {
                "total_markets": stats['total'],
                "active_markets": stats['active'],
                "closed_markets": stats['closed'],
                "resolved_markets": stats['resolved'],
                "tradeable_markets": stats['tradeable']
            },
            "last_cycle": market_health['last_stats'],
            "new_markets": {
                "last_hour": markets_1h,
                "last_24_hours": markets_24h,
                "last_7_days": markets_7d
            },
            "resolved_markets": {
                "last_hour": resolved_1h,
                "last_24_hours": resolved_24h,
                "last_7_days": resolved_7d
            },
            "finished_markets": {
                "last_hour": finished_1h,
                "last_24_hours": finished_24h
            },
            "activity": {
                "markets_updated_last_hour": updated_1h,
                "estimated_full_update_time": f"{(stats['total'] / 500) * (MARKET_UPDATE_INTERVAL / 60):.1f} minutes"
            }
        }

    except Exception as e:
        logger.error(f"Monitor dashboard error: {e}")
        raise HTTPException(status_code=500, detail=f"Monitor error: {str(e)}")


@app.post("/admin/enrichment/start")
async def start_enrichment():
    """
    Trigger full market enrichment to restore events data

    This is a LONG-RUNNING process (90-120 minutes) that fetches ALL events
    from Gamma API and updates markets with events data for proper grouping.

    Returns:
        Status and progress information
    """
    from telegram_bot.handlers.admin_enrichment import trigger_enrichment
    return await trigger_enrichment()

@app.get("/admin/enrichment/status")
async def enrichment_status():
    """
    Check enrichment progress

    Returns current status, events fetched, markets enriched
    """
    from telegram_bot.handlers.admin_enrichment import get_enrichment_status
    return await get_enrichment_status()

@app.get("/admin/market-database-monitor")
async def market_database_monitor(days: int = Query(30, description="Number of days of history to show")):
    """
    Market Database Daily Monitoring

    Tracks daily statistics with historical data:
    - New markets added per day (with category breakdown %)
    - Markets resolved per day
    - Markets finished per day
    - Historical trends over time

    Query params:
    - days: Number of days of history (default: 30, max: 365)
    """
    try:
        from sqlalchemy import func, and_, cast, Date
        from datetime import timedelta

        # Limit days to prevent performance issues
        days = min(days, 365)

        now = datetime.now(timezone.utc)
        start_date = now - timedelta(days=days)

        # Get daily new markets with category breakdown
        daily_new_markets = db_session_instance.query(
            cast(Market.created_at, Date).label('date'),
            func.count(Market.id).label('total'),
            Market.category
        ).filter(
            Market.created_at >= start_date
        ).group_by(
            cast(Market.created_at, Date),
            Market.category
        ).order_by(
            cast(Market.created_at, Date).desc()
        ).all()

        # Get daily resolved markets
        daily_resolved = db_session_instance.query(
            cast(Market.resolved_at, Date).label('date'),
            func.count(Market.id).label('count')
        ).filter(
            Market.resolved_at >= start_date
        ).group_by(
            cast(Market.resolved_at, Date)
        ).order_by(
            cast(Market.resolved_at, Date).desc()
        ).all()

        # Get daily finished markets (by end_date)
        daily_finished = db_session_instance.query(
            cast(Market.end_date, Date).label('date'),
            func.count(Market.id).label('count')
        ).filter(
            and_(
                Market.end_date >= start_date,
                Market.closed == True
            )
        ).group_by(
            cast(Market.end_date, Date)
        ).order_by(
            cast(Market.end_date, Date).desc()
        ).all()

        # Process daily new markets data with category breakdown
        daily_stats = {}

        for date, total, category in daily_new_markets:
            date_str = date.isoformat()
            if date_str not in daily_stats:
                daily_stats[date_str] = {
                    'date': date_str,
                    'new_markets': 0,
                    'categories': {},
                    'resolved': 0,
                    'finished': 0
                }

            daily_stats[date_str]['new_markets'] += total
            if category:
                daily_stats[date_str]['categories'][category] = total

        # Add resolved markets to daily stats
        for date, count in daily_resolved:
            date_str = date.isoformat()
            if date_str not in daily_stats:
                daily_stats[date_str] = {
                    'date': date_str,
                    'new_markets': 0,
                    'categories': {},
                    'resolved': count,
                    'finished': 0
                }
            else:
                daily_stats[date_str]['resolved'] = count

        # Add finished markets to daily stats
        for date, count in daily_finished:
            date_str = date.isoformat()
            if date_str not in daily_stats:
                daily_stats[date_str] = {
                    'date': date_str,
                    'new_markets': 0,
                    'categories': {},
                    'resolved': 0,
                    'finished': count
                }
            else:
                daily_stats[date_str]['finished'] = count

        # Calculate category percentages and format
        # Filter out future dates and only include dates within the requested period
        formatted_daily_stats = []
        today = now.date()
        start_date_only = start_date.date()

        for date_str in sorted(daily_stats.keys(), reverse=True):
            # Parse date and filter
            from datetime import datetime as dt
            date_obj = dt.fromisoformat(date_str).date()

            # Skip if date is in the future or outside the requested period
            if date_obj > today or date_obj < start_date_only:
                continue

            day_data = daily_stats[date_str]
            total_new = day_data['new_markets']

            # Calculate category percentages
            category_breakdown = []
            if total_new > 0:
                for cat, count in day_data['categories'].items():
                    category_breakdown.append({
                        'category': cat,
                        'count': count,
                        'percentage': round(100 * count / total_new, 2)
                    })
                # Sort by count
                category_breakdown.sort(key=lambda x: x['count'], reverse=True)

            formatted_daily_stats.append({
                'date': date_str,
                'new_markets': total_new,
                'category_breakdown': category_breakdown,
                'resolved_markets': day_data['resolved'],
                'finished_markets': day_data['finished']
            })

        # Calculate overall statistics for the period
        total_new = sum(d['new_markets'] for d in formatted_daily_stats)
        total_resolved = sum(d['resolved_markets'] for d in formatted_daily_stats)
        total_finished = sum(d['finished_markets'] for d in formatted_daily_stats)

        # Category totals for the period
        category_totals = {}
        for day in formatted_daily_stats:
            for cat_data in day['category_breakdown']:
                cat = cat_data['category']
                if cat not in category_totals:
                    category_totals[cat] = 0
                category_totals[cat] += cat_data['count']

        # Format category totals with percentages
        category_summary = []
        if total_new > 0:
            for cat, count in sorted(category_totals.items(), key=lambda x: x[1], reverse=True):
                category_summary.append({
                    'category': cat,
                    'count': count,
                    'percentage': round(100 * count / total_new, 2)
                })

        # Calculate averages
        avg_new_per_day = round(total_new / days, 1) if days > 0 else 0
        avg_resolved_per_day = round(total_resolved / days, 1) if days > 0 else 0
        avg_finished_per_day = round(total_finished / days, 1) if days > 0 else 0

        # Get current database totals
        total_markets = db_session_instance.query(func.count(Market.id)).scalar()
        active_markets = db_session_instance.query(func.count(Market.id)).filter(
            Market.active == True
        ).scalar()

        return {
            'timestamp': now.isoformat(),
            'period': {
                'days': days,
                'start_date': start_date.date().isoformat(),
                'end_date': now.date().isoformat()
            },
            'summary': {
                'total_new_markets': total_new,
                'total_resolved_markets': total_resolved,
                'total_finished_markets': total_finished,
                'average_new_per_day': avg_new_per_day,
                'average_resolved_per_day': avg_resolved_per_day,
                'average_finished_per_day': avg_finished_per_day,
                'category_distribution': category_summary
            },
            'database_current': {
                'total_markets': total_markets,
                'active_markets': active_markets,
                'growth_during_period': total_new
            },
            'daily_history': formatted_daily_stats
        }

    except Exception as e:
        logger.error(f"Market database monitor error: {e}")
        raise HTTPException(status_code=500, detail=f"Market database monitor error: {str(e)}")


@app.get("/admin/check-categories")
async def check_categories(top_n: int = Query(None, description="Check top N markets by volume")):
    """Check category coverage across all markets or top N by volume"""
    try:
        db_session_instance = get_db_session()

        if top_n:
            # Check top N markets by volume
            top_markets = db_session_instance.query(Market).order_by(Market.volume.desc()).limit(top_n).all()

            total = len(top_markets)
            with_category = sum(1 for m in top_markets if m.category and m.category != '')
            without_category = total - with_category

            # Get category breakdown for top N
            category_counts = {}
            for m in top_markets:
                if m.category and m.category != '':
                    category_counts[m.category] = category_counts.get(m.category, 0) + 1

            top_categories = [
                {
                    "category": cat,
                    "count": count,
                    "percentage": round(100 * count / total, 2) if total > 0 else 0
                }
                for cat, count in sorted(category_counts.items(), key=lambda x: x[1], reverse=True)
            ]

            # Sample markets without category from top N
            samples_without = [
                {
                    "id": m.id,
                    "question": m.question[:70] if m.question else "",
                    "volume": float(m.volume) if m.volume else 0,
                    "tradeable": m.tradeable,
                    "category": m.category
                }
                for m in top_markets if not m.category or m.category == ''
            ][:20]

            return {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "scope": f"Top {top_n} markets by volume",
                "overview": {
                    "total_markets": total,
                    "with_category": with_category,
                    "without_category": without_category,
                    "percentage_with_category": round(100 * with_category / total, 2) if total > 0 else 0
                },
                "top_categories": top_categories,
                "samples_without_category": samples_without
            }
        else:
            # Original behavior - all markets
            total = db_session_instance.query(func.count(Market.id)).scalar()

            # Markets with category
            with_category = db_session_instance.query(func.count(Market.id)).filter(
                and_(Market.category.isnot(None), Market.category != '')
            ).scalar()

            # Markets without category
            without_category = total - with_category

            # Category breakdown (top 20)
            category_stats = db_session_instance.query(
                Market.category,
                func.count(Market.id).label('count')
            ).filter(
                and_(Market.category.isnot(None), Market.category != '')
            ).group_by(Market.category).order_by(func.count(Market.id).desc()).limit(20).all()

            # Sample markets without category (top 10 by volume)
            samples_without = db_session_instance.query(
                Market.id, Market.question, Market.volume, Market.tradeable
            ).filter(
                or_(Market.category.is_(None), Market.category == '')
            ).order_by(Market.volume.desc()).limit(10).all()

            return {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "scope": "All markets",
                "overview": {
                    "total_markets": total,
                    "with_category": with_category,
                    "without_category": without_category,
                    "percentage_with_category": round(100 * with_category / total, 2) if total > 0 else 0
                },
                "top_categories": [
                    {
                        "category": cat,
                        "count": count,
                        "percentage": round(100 * count / total, 2) if total > 0 else 0
                    } for cat, count in category_stats
                ],
                "samples_without_category": [
                    {
                        "id": market_id,
                        "question": question[:70],
                        "volume": float(volume) if volume else 0,
                        "tradeable": tradeable
                    } for market_id, question, volume, tradeable in samples_without
                ]
            }

    except Exception as e:
        logger.error(f"Category check error: {e}")
        raise HTTPException(status_code=500, detail=f"Category check error: {str(e)}")


@app.get("/admin/check-winners")
async def check_winners():
    """Check winner field for resolved markets"""
    try:
        db_session_instance = get_db_session()

        # Resolved markets
        resolved_total = db_session_instance.query(func.count(Market.id)).filter(
            Market.resolved_at.isnot(None)
        ).scalar()

        # Resolved with winner
        resolved_with_winner = db_session_instance.query(func.count(Market.id)).filter(
            and_(
                Market.resolved_at.isnot(None),
                Market.winner.isnot(None),
                Market.winner != ''
            )
        ).scalar()

        # Resolved without winner
        resolved_without_winner = resolved_total - resolved_with_winner

        # Get sample resolved markets without winner
        samples = db_session_instance.query(
            Market.id, Market.question, Market.outcomes, Market.outcome_prices,
            Market.resolved_at, Market.closed, Market.winner
        ).filter(
            and_(
                Market.resolved_at.isnot(None),
                or_(Market.winner.is_(None), Market.winner == '')
            )
        ).order_by(Market.resolved_at.desc()).limit(20).all()

        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "overview": {
                "total_resolved": resolved_total,
                "with_winner": resolved_with_winner,
                "without_winner": resolved_without_winner,
                "percentage_with_winner": round(100 * resolved_with_winner / resolved_total, 2) if resolved_total > 0 else 0
            },
            "samples_without_winner": [
                {
                    "id": market_id,
                    "question": question[:60],
                    "outcomes": outcomes,
                    "outcome_prices": outcome_prices,
                    "resolved_at": resolved_at.isoformat() if resolved_at else None,
                    "closed": closed,
                    "current_winner": winner
                } for market_id, question, outcomes, outcome_prices, resolved_at, closed, winner in samples
            ]
        }

    except Exception as e:
        logger.error(f"Winner check error: {e}")
        raise HTTPException(status_code=500, detail=f"Winner check error: {str(e)}")


@app.post("/admin/backfill-winners")
async def backfill_winners(background_tasks: BackgroundTasks, dry_run: bool = Query(False)):
    """Backfill winners for resolved markets that don't have a winner set yet"""
    try:
        from py_clob_client.client import ClobClient

        async def run_backfill():
            import json
            db_session_instance = get_db_session()

            # Get resolved markets without a winner
            markets_to_fix = db_session_instance.query(Market).filter(
                and_(
                    Market.resolved_at.isnot(None),
                    or_(Market.winner.is_(None), Market.winner == '')
                )
            ).order_by(Market.resolved_at.desc()).all()

            logger.info(f"🔍 Found {len(markets_to_fix)} resolved markets without a winner")

            updated = 0
            no_winner = 0

            for market in markets_to_fix:
                try:
                    # Try to calculate winner from stored data
                    winner = None
                    outcomes = market.outcomes
                    outcome_prices = market.outcome_prices

                    logger.info(f"🔍 Market {market.id}: Raw outcomes type={type(outcomes)}, raw prices type={type(outcome_prices)}")

                    # Parse if they're JSON strings
                    if isinstance(outcomes, str):
                        try:
                            outcomes = json.loads(outcomes)
                            logger.info(f"  Parsed outcomes from string: {outcomes}")
                        except Exception as e:
                            logger.warning(f"  Failed to parse outcomes: {e}")
                            outcomes = None

                    if isinstance(outcome_prices, str):
                        try:
                            outcome_prices = json.loads(outcome_prices)
                            logger.info(f"  Parsed outcome_prices from string: {outcome_prices}")
                        except Exception as e:
                            logger.warning(f"  Failed to parse outcome_prices: {e}")
                            outcome_prices = None

                    logger.info(f"  After parsing: outcomes={outcomes}, prices={outcome_prices}")

                    if outcomes and outcome_prices and len(outcomes) == len(outcome_prices):
                        for i, price in enumerate(outcome_prices):
                            try:
                                price_float = float(price)
                                logger.info(f"  Checking outcome[{i}] '{outcomes[i]}': price={price_float}")
                                if price_float >= 0.95:
                                    winner = str(outcomes[i])
                                    logger.info(f"  ✅ Found winner: {winner} (price={price_float})")
                                    break
                            except (ValueError, TypeError) as e:
                                logger.warning(f"  Failed to convert price to float: {price} - {e}")
                                continue
                    else:
                        logger.warning(f"  Skipping: outcomes={bool(outcomes)}, prices={bool(outcome_prices)}, lengths match={bool(outcomes and outcome_prices and len(outcomes) == len(outcome_prices))}")

                    if winner:
                        if not dry_run:
                            # Use direct SQL update to avoid triggering full market validation
                            from sqlalchemy import text
                            db_session_instance.execute(
                                text("UPDATE markets SET winner = :winner, last_updated = NOW() WHERE id = :market_id"),
                                {"winner": winner, "market_id": market.id}
                            )
                            db_session_instance.commit()
                        updated += 1
                        logger.info(f"✅ Market {market.id}: Set winner={winner}")
                    else:
                        no_winner += 1
                        logger.info(f"⚠️ Market {market.id}: No clear winner (all prices < 95%)")

                except Exception as e:
                    logger.error(f"❌ Market {market.id}: Error: {e}")
                    import traceback
                    logger.error(traceback.format_exc())

            logger.info(f"📊 Backfill complete: {updated} updated, {no_winner} no clear winner")

        if dry_run:
            await run_backfill()
            return {"status": "dry_run_complete", "message": "Check logs for results"}
        else:
            background_tasks.add_task(run_backfill)
            return {"status": "started", "message": "Backfill task started in background. Check logs for progress."}

    except Exception as e:
        logger.error(f"Backfill error: {e}")
        raise HTTPException(status_code=500, detail=f"Backfill error: {str(e)}")


@app.post("/admin/normalize-categories")
async def normalize_categories():
    """
    Normalize existing categories to the 7 target categories using SQL updates
    This is faster than re-categorizing with OpenAI
    """
    try:
        from sqlalchemy import text

        # Category mappings - map old categories to our 7 target categories
        # Using ILIKE for case-insensitive matching
        CATEGORY_MAPPINGS = [
            # Map to Politics
            ('US-current-affairs', 'Politics'),
            ('US Politics', 'Politics'),
            ('Biden', 'Politics'),

            # Map to Sports
            ('NBA Playoffs', 'Sports'),
            ('NBA', 'Sports'),
            ('NFL', 'Sports'),
            ('MLB', 'Sports'),
            ('Olympics', 'Sports'),

            # Map to Crypto
            ('NFTs', 'Crypto'),
            ('Bitcoin', 'Crypto'),
            ('Ethereum', 'Crypto'),

            # Map to Business
            ('Coronavirus', 'Business'),
            ('Coronavirus-', 'Business'),
            ('Health', 'Business'),
            ('COVID', 'Business'),
            ('Pandemic', 'Business'),
            ('Science', 'Business'),
            ('Tech', 'Business'),
            ('Technology', 'Business'),
            ('AI', 'Business'),
            ('Space', 'Business'),
            ('Pop Culture', 'Business'),
            ('Pop-Culture', 'Business'),
            ('Pop-Culture ', 'Business'),
            ('Entertainment', 'Business'),
            ('Finance', 'Business'),
            ('Economics', 'Business'),
            ('Fed', 'Business'),
            ('Other', 'Business'),
        ]

        db_session_instance = get_db_session()
        results = {}
        total_updated = 0

        for old_cat, new_cat in CATEGORY_MAPPINGS:
            # Use ILIKE for case-insensitive matching and trim spaces
            result = db_session_instance.execute(
                text("UPDATE markets SET category = :new_cat, last_updated = NOW() WHERE TRIM(category) ILIKE :old_cat"),
                {"new_cat": new_cat, "old_cat": old_cat}
            )
            db_session_instance.commit()

            if result.rowcount > 0:
                results[old_cat] = {"mapped_to": new_cat, "count": result.rowcount}
                total_updated += result.rowcount
                logger.info(f"✅ Normalized '{old_cat}' → '{new_cat}' ({result.rowcount} markets)")

        # Get current category distribution
        cat_result = db_session_instance.execute(text("""
            SELECT category, COUNT(*) as count
            FROM markets
            WHERE category IS NOT NULL AND category != ''
            GROUP BY category
            ORDER BY count DESC
        """))

        categories = [{"category": row[0], "count": row[1]} for row in cat_result.fetchall()]

        return {
            "status": "complete",
            "total_updated": total_updated,
            "mappings": results,
            "current_categories": categories,
            "unique_categories": len(categories)
        }

    except Exception as e:
        logger.error(f"Category normalization error: {e}")
        raise HTTPException(status_code=500, detail=f"Normalization error: {str(e)}")


@app.get("/admin/backfill-progress")
async def get_backfill_progress():
    """Get real-time progress of category backfill operation"""
    global backfill_progress

    progress_copy = backfill_progress.copy()

    # Calculate percentage and ETA
    if progress_copy["total"] > 0:
        progress_copy["percentage"] = round(100 * progress_copy["processed"] / progress_copy["total"], 2)

        # Calculate ETA
        if progress_copy["start_time"] and progress_copy["status"] == "running" and progress_copy["processed"] > 0:
            from datetime import datetime, timezone
            elapsed = (datetime.now(timezone.utc) - datetime.fromisoformat(progress_copy["start_time"])).total_seconds()
            rate = progress_copy["processed"] / elapsed  # markets per second
            remaining = progress_copy["total"] - progress_copy["processed"]
            eta_seconds = int(remaining / rate) if rate > 0 else 0
            progress_copy["eta_seconds"] = eta_seconds
            progress_copy["eta_minutes"] = round(eta_seconds / 60, 1)
    else:
        progress_copy["percentage"] = 0

    return progress_copy


@app.post("/admin/backfill-categories")
async def backfill_categories(
    background_tasks: BackgroundTasks,
    batch_size: int = Query(500, description="Number of markets to process per batch"),
    top_n: int = Query(None, description="Only process top N markets by volume (None = all)"),
    force: bool = Query(False, description="Force re-categorization of ALL markets (even those with existing categories)"),
    dry_run: bool = Query(False)
):
    """
    Backfill categories for markets without a category using OpenAI
    Processes in batches to avoid hitting rate limits
    """
    try:
        from core.services.market_categorizer_service import MarketCategorizerService
        from sqlalchemy import text

        async def run_categorization_backfill():
            global backfill_progress

            db_session_instance = get_db_session()
            categorizer = MarketCategorizerService()

            if not categorizer.enabled:
                logger.error("❌ OpenAI API key not set - cannot run categorization backfill")
                backfill_progress["status"] = "error"
                backfill_progress["error_message"] = "OpenAI API key not set"
                return

            # Get markets to categorize, ordered by volume (prioritize important markets)
            if force:
                # Force mode: re-categorize ALL markets
                query = db_session_instance.query(Market).order_by(Market.volume.desc())
            else:
                # Normal mode: only markets without category
                query = db_session_instance.query(Market).filter(
                    or_(Market.category.is_(None), Market.category == '')
                ).order_by(Market.volume.desc())

            # Limit to top N if specified
            if top_n:
                query = query.limit(top_n)

            markets_to_categorize = query.all()

            total = len(markets_to_categorize)
            if force:
                if top_n:
                    logger.info(f"🔍 FORCE MODE: Re-categorizing top {top_n} markets by volume ({total} found)")
                else:
                    logger.info(f"🔍 FORCE MODE: Re-categorizing ALL {total} markets")
            else:
                if top_n:
                    logger.info(f"🔍 Found {total} markets without categories (limited to top {top_n} by volume)")
                else:
                    logger.info(f"🔍 Found {total} markets without categories")

            # Initialize progress tracker
            from datetime import datetime, timezone
            backfill_progress["status"] = "running"
            backfill_progress["total"] = total
            backfill_progress["processed"] = 0
            backfill_progress["categorized"] = 0
            backfill_progress["skipped"] = 0
            backfill_progress["errors"] = 0
            backfill_progress["total_batches"] = (total + batch_size - 1) // batch_size
            backfill_progress["current_batch"] = 0
            backfill_progress["start_time"] = datetime.now(timezone.utc).isoformat()
            backfill_progress["end_time"] = None
            backfill_progress["error_message"] = None

            categorized = 0
            skipped = 0
            errors = 0

            # Process in batches
            for i in range(0, total, batch_size):
                batch = markets_to_categorize[i:i + batch_size]
                batch_num = (i // batch_size) + 1
                total_batches = (total + batch_size - 1) // batch_size

                # Update current batch
                backfill_progress["current_batch"] = batch_num

                logger.info(f"📦 Processing batch {batch_num}/{total_batches} ({len(batch)} markets)")

                for market in batch:
                    try:
                        # Categorize using OpenAI
                        category = await categorizer.categorize_market(
                            question=market.question or '',
                            existing_category=None
                        )

                        if category:
                            if not dry_run:
                                # Use direct SQL update
                                db_session_instance.execute(
                                    text("UPDATE markets SET category = :category, last_updated = NOW() WHERE id = :market_id"),
                                    {"category": category, "market_id": market.id}
                                )
                                db_session_instance.commit()
                            categorized += 1
                            logger.info(f"✅ Market {market.id}: '{market.question[:50]}...' → {category}")
                        else:
                            skipped += 1
                            logger.warning(f"⚠️ Market {market.id}: Could not categorize")

                    except Exception as e:
                        errors += 1
                        logger.error(f"❌ Market {market.id}: Error: {e}")

                    # Update progress after each market
                    backfill_progress["processed"] = categorized + skipped + errors
                    backfill_progress["categorized"] = categorized
                    backfill_progress["skipped"] = skipped
                    backfill_progress["errors"] = errors

                # Progress update after each batch
                logger.info(f"📊 Progress: {categorized + skipped + errors}/{total} - {categorized} categorized, {skipped} skipped, {errors} errors")

                # Small delay between batches to respect rate limits
                import asyncio
                await asyncio.sleep(1)

            # Mark as completed
            backfill_progress["status"] = "completed"
            backfill_progress["end_time"] = datetime.now(timezone.utc).isoformat()
            logger.info(f"🎉 Categorization backfill complete: {categorized} categorized, {skipped} skipped, {errors} errors out of {total} total")

        if dry_run:
            await run_categorization_backfill()
            return {"status": "dry_run_complete", "message": "Check logs for results"}
        else:
            background_tasks.add_task(run_categorization_backfill)
            msg = f"Categorization backfill started in background with batch_size={batch_size}"
            if force:
                msg += " (FORCE MODE - re-categorizing all markets)"
            if top_n:
                msg += f", limited to top {top_n} markets by volume"
            return {
                "status": "started",
                "message": msg + ". Check logs for progress.",
                "batch_size": batch_size,
                "top_n": top_n,
                "force": force
            }

    except Exception as e:
        logger.error(f"Categorization backfill error: {e}")
        raise HTTPException(status_code=500, detail=f"Backfill error: {str(e)}")


# For Railway deployment
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))

    # ========================================
    # 🔍 REDIS CACHE DIAGNOSTIC
    # ========================================
    from core.services.redis_price_cache import get_redis_cache
    redis_cache = get_redis_cache()

    if redis_cache.enabled:
        logger.info("=" * 60)
        logger.info("✅ REDIS CACHE: ENABLED")
        logger.info(f"   Connection: Active")
        logger.info(f"   Position TTL: {os.getenv('POSITION_CACHE_TTL', '180')}s")
        logger.info("=" * 60)
    else:
        logger.warning("=" * 60)
        logger.warning("❌ REDIS CACHE: DISABLED")
        logger.warning("   ⚠️ ALL POSITIONS WILL USE SLOW API CALLS!")
        logger.warning("   Fix: Set REDIS_URL environment variable")
        logger.warning("=" * 60)

    # Disable uvicorn access logs (hide HTTP 200 OK spam)
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
        log_level="warning",  # Only show warnings and errors
        access_log=False  # Disable access logs completely
    )


# ========================================
# LEADERBOARD ADMIN ENDPOINTS
# ========================================

@app.post("/admin/leaderboard/recalculate")
async def admin_recalculate_leaderboard(
    period: str = Query("both", enum=["weekly", "alltime", "both"]),
    notify_users: bool = Query(False)
):
    """
    Admin endpoint to manually recalculate leaderboard rankings

    Args:
        period: Which leaderboard to recalculate
        notify_users: Whether to send notifications to users

    Returns:
        Recalculation results
    """
    try:
        from core.services.leaderboard_calculator import LeaderboardCalculator
        from decimal import Decimal

        db_session = get_db_session()
        results = {}

        if period in ["weekly", "both"]:
            weekly_lb = LeaderboardCalculator.calculate_weekly_leaderboard(
                db_session,
                min_volume=Decimal('10')
            )
            LeaderboardCalculator.save_leaderboard_entries(db_session, weekly_lb)
            results['weekly'] = len(weekly_lb)

        if period in ["alltime", "both"]:
            alltime_lb = LeaderboardCalculator.calculate_alltime_leaderboard(
                db_session,
                min_volume=Decimal('10')
            )
            LeaderboardCalculator.save_leaderboard_entries(db_session, alltime_lb)
            results['alltime'] = len(alltime_lb)

        if notify_users and period in ["weekly", "both"]:
            from tasks.leaderboard_scheduler import notify_users_of_ranking
            asyncio.create_task(notify_users_of_ranking(db_session, weekly_lb))

        db_session.close()

        return {
            "status": "success",
            "message": f"Leaderboard recalculated ({period})",
            "results": results,
            "notifications_sent": notify_users
        }

    except Exception as e:
        logger.error(f"Leaderboard recalculation error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/admin/leaderboard/status")
async def admin_leaderboard_status():
    """Get leaderboard scheduler status and next run time"""
    try:
        from tasks.leaderboard_scheduler import get_next_leaderboard_run
        from database import LeaderboardEntry

        db_session = get_db_session()

        # Get current counts
        weekly_count = db_session.query(LeaderboardEntry).filter(
            LeaderboardEntry.period == 'weekly'
        ).count()

        alltime_count = db_session.query(LeaderboardEntry).filter(
            LeaderboardEntry.period == 'all-time'
        ).count()

        db_session.close()

        next_run = get_next_leaderboard_run(scheduler)

        return {
            "status": "active",
            "weekly_entries": weekly_count,
            "alltime_entries": alltime_count,
            "next_run": next_run.isoformat() if next_run else None,
            "min_volume_threshold": 10.0
        }

    except Exception as e:
        logger.error(f"Leaderboard status error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/admin/cache/invalidate")
async def admin_invalidate_cache(filter_name: Optional[str] = None):
    """Invalidate Redis cache for markets"""
    try:
        from core.services.redis_price_cache import get_redis_cache
        redis_cache = get_redis_cache()

        if not redis_cache.enabled:
            raise HTTPException(status_code=503, detail="Redis cache disabled")

        success = redis_cache.invalidate_markets_cache(filter_name=filter_name)

        if success:
            logger.info(f"🗑️ Cache invalidated: {filter_name or 'ALL'}")
            return {"status": "success", "filter": filter_name}
        else:
            raise HTTPException(status_code=500, detail="Cache invalidation failed")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Cache error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
