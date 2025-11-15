#!/usr/bin/env python3
"""
Watched Markets Service
Automatically adds markets with user positions to streamer watchlist
Ensures all user positions have real-time price data
"""

import logging
from typing import Dict, List, Set
from datetime import datetime, timezone

from database import db_manager

logger = logging.getLogger(__name__)


class WatchedMarketsService:
    """
    Service for managing markets that need to be watched due to user positions.
    Automatically discovers markets with active positions and adds them to streamer.
    """

    def __init__(self):
        self.last_scan = None
        self.last_cleanup = None
        logger.info("✅ Watched Markets Service initialized")

    async def scan_and_update_watched_markets(self) -> Dict[str, int]:
        """
        Scan all user positions and smart wallet trades, then update the watched markets list.
        Returns summary of changes.
        """
        try:
            logger.info("🔍 Scanning user positions and smart wallet trades for watched markets...")

            # Get all active positions from all users
            market_positions = await self._get_all_market_positions()

            # DISABLED: Smart wallet markets - causing too many false positives
            # TODO: Re-enable with proper filtering for active positions only
            smart_wallet_markets = {}
            # smart_wallet_markets = await self._get_smart_wallet_markets()

            # Merge the two sources
            for market_id, data in smart_wallet_markets.items():
                if market_id in market_positions:
                    # Market already exists from user positions, add the smart wallet activity
                    market_positions[market_id]["count"] += data.get("count", 1)
                    market_positions[market_id]["has_smart_wallet_activity"] = True
                else:
                    # New market from smart wallet activity
                    market_positions[market_id] = {
                        "condition_id": data.get("condition_id"),
                        "title": data.get("title", f"Smart Wallet Market {market_id[:20]}..."),
                        "count": data.get("count", 1),
                        "source": "smart_wallet"
                    }

            if not market_positions:
                logger.info("📭 No active positions or smart wallet trades found")
                return {"scanned": 0, "added": 0, "removed": 0}

            # Get current watched markets
            current_watched = await self._get_current_watched_markets()

            # Calculate changes
            markets_to_add = set(market_positions.keys()) - set(current_watched.keys())
            markets_to_update = set(market_positions.keys()) & set(current_watched.keys())
            markets_to_remove = set(current_watched.keys()) - set(market_positions.keys())

            changes = {"scanned": len(market_positions), "added": 0, "updated": 0, "removed": 0}

            # Add new markets
            for market_id in markets_to_add:
                position_count = market_positions[market_id]["count"]
                condition_id = market_positions[market_id]["condition_id"]
                title = market_positions[market_id]["title"]

                if await self._add_watched_market(market_id, condition_id, title, position_count):
                    changes["added"] += 1

            # Update existing markets
            for market_id in markets_to_update:
                position_count = market_positions[market_id]["count"]
                if await self._update_watched_market_positions(market_id, position_count):
                    changes["updated"] += 1

            # Remove markets with no positions
            for market_id in markets_to_remove:
                if await self._remove_watched_market(market_id):
                    changes["removed"] += 1

                    # 🚨 CRITICAL: Invalidate position cache for all users
                    # When a market is removed from watched_markets, positions may have changed
                    try:
                        from .position_cache_service import get_position_cache_service
                        cache_service = get_position_cache_service()

                        # Get all REAL user wallets and invalidate their caches (exclude virtual/external)
                        from database import db_manager, User
                        with db_manager.get_session() as db:
                            users = db.query(User).filter(
                                User.polygon_address.isnot(None),
                                User.username.isnot(None),
                                ~User.username.like('virtual%'),
                                ~User.username.like('external%')
                            ).all()
                            for user in users:
                                if user.polygon_address:
                                    cache_service.invalidate_cache(user.polygon_address)
                                    logger.debug(f"🗑️ Invalidated position cache for {user.polygon_address[:10]}...")

                        logger.info(f"🗑️ Invalidated position caches for {len(users)} real users due to market removal")
                    except Exception as e:
                        logger.warning(f"⚠️ Failed to invalidate position caches: {e}")

            # ✅ NEW: Remove resolved markets automatically
            resolved_removed = await self._remove_resolved_markets()
            if resolved_removed > 0:
                changes["resolved_removed"] = resolved_removed

            # ✅ NEW: Run hourly cleanup of inactive markets (no user positions)
            if self.last_cleanup is None or (datetime.now(timezone.utc) - self.last_cleanup).total_seconds() > 3600:
                # Run cleanup every hour
                removed = await self.cleanup_inactive_watched_markets()
                self.last_cleanup = datetime.now(timezone.utc)
                changes["inactive_removed"] = removed
                logger.info(f"🧹 Hourly cleanup: removed {removed} inactive watched markets")

            self.last_scan = datetime.now(timezone.utc)

            logger.info(f"✅ Watched markets scan complete: {changes}")
            return changes

        except Exception as e:
            logger.error(f"❌ Error scanning watched markets: {e}")
            return {"scanned": 0, "added": 0, "updated": 0, "removed": 0, "error": str(e)}

    async def _get_all_market_positions(self) -> Dict[str, Dict]:
        """
        Get all markets that have active user positions.
        Queries Polymarket API for all registered user wallets (with caching).
        Returns dict with market_id as key and position info as value.
        """
        try:
            from database import db_manager, User
            from .position_cache_service import get_position_cache_service

            cache_service = get_position_cache_service()

            # Get all REAL user wallets (exclude virtual/external users)
            with db_manager.get_session() as db:
                users = db.query(User).filter(
                    User.polygon_address.isnot(None),
                    User.username.isnot(None),
                    ~User.username.like('virtual%'),
                    ~User.username.like('external%')
                ).all()
                wallet_addresses = [user.polygon_address for user in users if user.polygon_address]

            if not wallet_addresses:
                logger.info("📭 No user wallets found")
                return {}

            logger.info(f"🔍 Scanning positions for {len(wallet_addresses)} user wallets...")

            # ✅ OPTIMIZATION: Batch fetch with cache (40% egress reduction)
            all_positions = await cache_service.batch_fetch_positions(wallet_addresses)

            # Aggregate by market
            market_positions = {}
            total_positions = 0

            for wallet, positions in all_positions.items():
                total_positions += len(positions)

                # ✅ FIX: Use condition_id as primary key (watched_markets.market_id should match condition_id)
                # This ensures proper JOIN with subsquid_markets_poll.condition_id
                for position in positions:
                    condition_id = position.get('conditionId', position.get('id', ''))
                    # Use condition_id as market_id for watched_markets (matches DB schema)
                    market_id = condition_id  # Always use condition_id for watched_markets

                    if condition_id:
                        # 🚨 CRITICAL FIX: Skip positions on already resolved markets
                        # These positions are "closed" and don't need real-time monitoring
                        try:
                            import asyncpg
                            import os

                            # Direct DB query to check if market is resolved
                            conn = await asyncpg.connect(dsn=os.getenv('DATABASE_URL'))
                            try:
                                market_row = await conn.fetchrow(
                                    "SELECT resolution_status FROM subsquid_markets_poll WHERE condition_id = $1",
                                    condition_id
                                )

                                if market_row and market_row['resolution_status'] == 'RESOLVED':
                                    logger.debug(f"⏭️ Skipping closed position on resolved market: {condition_id}")
                                    continue
                            finally:
                                await conn.close()

                        except Exception as e:
                            logger.warning(f"⚠️ Could not check market resolution for {condition_id}: {e}")
                            # Continue processing if DB check fails

                        # 🚨 NEW: Store detailed position data
                        try:
                            await self._store_detailed_position(wallet, position)
                        except Exception as e:
                            logger.warning(f"⚠️ Failed to store detailed position: {e}")

                        if market_id not in market_positions:
                            market_positions[market_id] = {
                                "condition_id": condition_id,
                                "title": position.get('title', 'Unknown Market'),
                                "count": 0
                            }
                        market_positions[market_id]["count"] += 1

            logger.info(f"✅ Found {len(market_positions)} unique markets with positions across {total_positions} total positions")
            return market_positions

        except Exception as e:
            logger.error(f"❌ Error getting market positions: {e}")
            return {}

    async def _store_detailed_position(self, wallet_address: str, position: Dict):
        """
        Store detailed position data in user_positions table
        """
        logger.info(f"🗂️ Storing position for wallet {wallet_address[:10]}...: {position.get('outcome', '')} on {position.get('conditionId', '')[:20]}...")
        try:
            # Get user_id from wallet_address
            import asyncpg
            import os
            conn = await asyncpg.connect(dsn=os.getenv('DATABASE_URL'))
            try:
                user_row = await conn.fetchrow(
                    "SELECT telegram_user_id FROM users WHERE polygon_address = $1",
                    wallet_address
                )
                if not user_row:
                    logger.warning(f"⚠️ User not found for wallet {wallet_address[:10]}...")
                    return

                user_id = str(user_row['telegram_user_id'])  # Convert to string for UUID compatibility
                logger.info(f"✅ Found user_id: {user_id} for wallet {wallet_address[:10]}...")
            finally:
                await conn.close()

            # Prepare position data
            from datetime import datetime

            # Convert end_date string to date object or None
            end_date_str = position.get('endDate', '')
            end_date = None
            if end_date_str:
                try:
                    end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
                except ValueError:
                    logger.warning(f"Invalid end_date format: {end_date_str}")
                    end_date = None

            position_data = {
                'user_id': user_id,
                'polygon_address': wallet_address,
                'condition_id': position.get('conditionId', ''),
                'market_id': '',  # Will be determined from condition_id
                'asset': position.get('asset', ''),
                'outcome': position.get('outcome', ''),
                'outcome_index': position.get('outcomeIndex', 0),
                'size': position.get('size', 0),
                'avg_price': position.get('avgPrice', 0),
                'cur_price': position.get('curPrice', 0),
                'initial_value': position.get('initialValue', 0),
                'current_value': position.get('currentValue', 0),
                'total_bought': position.get('totalBought', 0),
                'cash_pnl': position.get('cashPnl', 0),
                'percent_pnl': position.get('percentPnl', 0),
                'realized_pnl': position.get('realizedPnl', 0),
                'redeemable': position.get('redeemable', False),
                'mergeable': position.get('mergeable', False),
                'negative_risk': position.get('negativeRisk', False),
                'title': position.get('title', ''),
                'slug': position.get('slug', ''),
                'end_date': end_date
            }

            # Get market_id from condition_id
            try:
                import asyncpg
                import os
                conn = await asyncpg.connect(dsn=os.getenv('DATABASE_URL'))
                try:
                    market_row = await conn.fetchrow(
                        "SELECT market_id FROM subsquid_markets_poll WHERE condition_id = $1",
                        position_data['condition_id']
                    )
                    if market_row:
                        position_data['market_id'] = market_row['market_id']
                finally:
                    await conn.close()
            except Exception as e:
                logger.warning(f"⚠️ Could not get market_id for condition {position_data['condition_id']}: {e}")

            # Upsert position data
            logger.info(f"📝 Upserting position data for {position_data['outcome']}...")
            await self._upsert_user_position(position_data)

        except Exception as e:
            logger.warning(f"⚠️ Failed to store position data: {e}")

    async def _upsert_user_position(self, position_data: Dict):
        """
        Upsert position data into user_positions table
        """
        try:
            import asyncpg
            import os

            conn = await asyncpg.connect(dsn=os.getenv('DATABASE_URL'))

            try:
                await conn.execute("""
                    INSERT INTO user_positions (
                        user_id, polygon_address, condition_id, market_id, asset,
                        outcome, outcome_index, size, avg_price, cur_price,
                        initial_value, current_value, total_bought, cash_pnl,
                        percent_pnl, realized_pnl, redeemable, mergeable,
                        negative_risk, title, slug, end_date
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18, $19, $20, $21, $22)
                    ON CONFLICT (user_id, condition_id, outcome_index)
                    DO UPDATE SET
                        size = EXCLUDED.size,
                        cur_price = EXCLUDED.cur_price,
                        current_value = EXCLUDED.current_value,
                        cash_pnl = EXCLUDED.cash_pnl,
                        percent_pnl = EXCLUDED.percent_pnl,
                        realized_pnl = EXCLUDED.realized_pnl,
                        redeemable = EXCLUDED.redeemable,
                        mergeable = EXCLUDED.mergeable,
                        updated_at = NOW()
                """,
                position_data['user_id'],
                position_data['polygon_address'],
                position_data['condition_id'],
                position_data['market_id'],
                position_data['asset'],
                position_data['outcome'],
                position_data['outcome_index'],
                position_data['size'],
                position_data['avg_price'],
                position_data['cur_price'],
                position_data['initial_value'],
                position_data['current_value'],
                position_data['total_bought'],
                position_data['cash_pnl'],
                position_data['percent_pnl'],
                position_data['realized_pnl'],
                position_data['redeemable'],
                position_data['mergeable'],
                position_data['negative_risk'],
                position_data['title'],
                position_data['slug'],
                position_data['end_date']
                )

                logger.info(f"✅ Stored position: {position_data['outcome']} on {position_data['condition_id'][:20]}...")

            finally:
                await conn.close()

        except Exception as e:
            logger.error(f"❌ Failed to upsert user position: {e}")
            logger.error(f"❌ Position data: {position_data}")
            import traceback
            logger.error(f"❌ Traceback: {traceback.format_exc()}")

    async def _get_smart_wallet_markets(self) -> Dict[str, Dict]:
        """
        Get all markets that have been traded by smart wallets.
        Queries the smart_wallet_trades table for recent trading activity.
        Returns dict with market_id as key and market info as value.
        """
        try:
            with db_manager.get_session() as db:
                from database import SmartWalletTrade

                # Get distinct markets from smart wallet trades in the last 30 days
                # to avoid including very old inactive markets
                from datetime import timedelta
                cutoff_date = datetime.now(timezone.utc) - timedelta(days=30)

                # Query for distinct market_ids with counts
                query = db.query(
                    SmartWalletTrade.market_id,
                    SmartWalletTrade.condition_id,
                    SmartWalletTrade.market_question.label('title'),
                    db.func.count(SmartWalletTrade.id).label('trade_count')
                ).filter(
                    SmartWalletTrade.timestamp >= cutoff_date
                ).group_by(
                    SmartWalletTrade.market_id,
                    SmartWalletTrade.condition_id,
                    SmartWalletTrade.market_question
                ).order_by(
                    db.func.count(SmartWalletTrade.id).desc()  # Most active markets first
                )

                results = query.all()

                market_data = {}
                for row in results:
                    market_id = row.market_id
                    if market_id:  # Ensure market_id is not None
                        market_data[market_id] = {
                            "condition_id": row.condition_id or market_id,  # Fallback to market_id if no condition_id
                            "title": row.title or f"Smart Wallet Market {market_id[:20]}...",
                            "count": int(row.trade_count),
                            "source": "smart_wallet"
                        }

                logger.info(f"🔍 Found {len(market_data)} markets from smart wallet trades in last 30 days")
                return market_data

        except Exception as e:
            logger.error(f"❌ Error getting smart wallet markets: {e}")
            return {}

    async def _get_wallet_positions(self, wallet_address: str) -> List[Dict]:
        """
        Get positions for a specific wallet from Polymarket API.
        """
        try:
            from core.utils.aiohttp_client import get_http_client
            import aiohttp

            session = await get_http_client()
            url = f"https://data-api.polymarket.com/positions?user={wallet_address}&closed=false&limit=100"

            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status == 200:
                    positions = await response.json()
                    return positions if isinstance(positions, list) else []
                else:
                    logger.warning(f"⚠️ API error for wallet {wallet_address[:10]}...: {response.status}")
                    return []

        except Exception as e:
            logger.warning(f"⚠️ Error fetching positions for wallet {wallet_address[:10]}...: {e}")
            return []

    async def _get_current_watched_markets(self) -> Dict[str, Dict]:
        """Get currently watched markets from database."""
        try:
            with db_manager.get_session() as db:
                from database import WatchedMarkets
                markets = db.query(WatchedMarkets).all()
                return {m.market_id: {
                    "active_positions": m.active_positions,
                    "condition_id": m.condition_id,
                    "title": m.title
                } for m in markets}
        except Exception as e:
            logger.error(f"❌ Error getting current watched markets: {e}")
            return {}

    async def _add_watched_market(self, market_id: str, condition_id: str, title: str, position_count: int) -> bool:
        """Add a market to the watched list IMMEDIATELY (streamer will subscribe within 60s)."""
        try:
            # ✅ IMMEDIATE INSERT: Always insert directly to DB for instant availability
            # No batch delay - trades need immediate streaming
            from database import db_manager, WatchedMarkets
            from datetime import datetime
            from sqlalchemy import text

            with db_manager.get_session() as db:
                # ✅ PROTECTION RACE CONDITION: Upsert avec ON CONFLICT
                # Évite les erreurs si plusieurs trades simultanés sur le même marché
                now = datetime.utcnow()
                db.execute(text("""
                    INSERT INTO watched_markets (market_id, condition_id, title, active_positions, last_position_at, created_at, updated_at)
                    VALUES (:market_id, :condition_id, :title, :position_count, :now, :now, :now)
                    ON CONFLICT (market_id) DO UPDATE SET
                        active_positions = GREATEST(watched_markets.active_positions, :position_count),
                        last_position_at = :now,
                        updated_at = :now,
                        condition_id = COALESCE(EXCLUDED.condition_id, watched_markets.condition_id),
                        title = COALESCE(EXCLUDED.title, watched_markets.title)
                """), {
                    'market_id': market_id,
                    'condition_id': condition_id,
                    'title': title,
                    'position_count': position_count,
                    'now': now
                })
                db.commit()

                logger.debug(f"📈 [IMMEDIATE DB] Market {market_id} added/updated in watched_markets")

            # ✅ IMMEDIATE NOTIFICATION: Notify streamer immediately after DB insert
            try:
                import redis.asyncio as aioredis
                from config.config import REDIS_URL
                if REDIS_URL:
                    redis_client = await aioredis.from_url(REDIS_URL, decode_responses=True)
                    await redis_client.setex("streamer:watched_markets_changed", 60, "1")
                    await redis_client.close()
                    logger.debug(f"🔔 [IMMEDIATE] Notified streamer of watched_markets change")
            except Exception as redis_err:
                logger.debug(f"⚠️ Failed to notify streamer (non-critical): {redis_err}")

            return True

        except Exception as e:
            logger.error(f"❌ Error adding watched market {market_id}: {e}", exc_info=True)
            return False

    async def _update_watched_market_positions(self, market_id: str, position_count: int) -> bool:
        """Update position count for a watched market (streamer auto-subscribes)."""
        try:
            from database import db_manager, WatchedMarkets
            from datetime import datetime

            with db_manager.get_session() as db:
                market = db.query(WatchedMarkets).filter(WatchedMarkets.market_id == market_id).first()

                if market:
                    market.active_positions = position_count
                    market.last_position_at = datetime.utcnow()
                    market.updated_at = datetime.utcnow()
                    db.commit()
                    logger.debug(f"📊 Updated position count for watched market {market_id}: {position_count} positions")
                    return True
                else:
                    logger.warning(f"⚠️ Watched market {market_id} not found in DB - cannot update")
                    return False

        except Exception as e:
            logger.error(f"❌ Error updating watched market {market_id}: {e}", exc_info=True)
            return False

    async def _remove_watched_market(self, market_id: str) -> bool:
        """Remove a market from watched list (streamer will auto-unsubscribe on restart)."""
        try:
            from database import db_manager, WatchedMarkets

            with db_manager.get_session() as db:
                market = db.query(WatchedMarkets).filter(WatchedMarkets.market_id == market_id).first()

                if market:
                    db.delete(market)
                    db.commit()
                    logger.info(f"📉 Removed watched market from DB: {market_id} (streamer will auto-unsubscribe on next refresh)")
                    return True
                else:
                    logger.debug(f"⚠️ Watched market {market_id} not found in DB - already removed")
                    return True

        except Exception as e:
            logger.error(f"❌ Error removing watched market {market_id}: {e}", exc_info=True)
            return False

    async def _remove_resolved_markets(self) -> int:
        """
        Remove markets that have been resolved from watched_markets.
        Uses resolution_status from subsquid_markets_poll to identify resolved markets.
        """
        try:
            from database import db_manager, SubsquidMarketPoll, WatchedMarkets

            with db_manager.get_session() as db:
                # Find all watched markets that are now resolved
                resolved_markets = db.query(WatchedMarkets.market_id).join(
                    SubsquidMarketPoll,
                    WatchedMarkets.condition_id == SubsquidMarketPoll.condition_id
                ).filter(
                    SubsquidMarketPoll.resolution_status.in_(['RESOLVED', 'CANCELLED'])
                ).all()

                if not resolved_markets:
                    return 0

                resolved_market_ids = [row[0] for row in resolved_markets]

                # Delete resolved markets from watched_markets
                deleted_count = db.query(WatchedMarkets).filter(
                    WatchedMarkets.market_id.in_(resolved_market_ids)
                ).delete(synchronize_session=False)

                db.commit()

                if deleted_count > 0:
                    logger.info(f"🗑️ Removed {deleted_count} resolved markets from watched_markets: {resolved_market_ids[:3]}...")

                    # Notify streamer to unsubscribe from these markets
                    try:
                        import redis.asyncio as aioredis
                        from config.config import REDIS_URL

                        if REDIS_URL:
                            redis_client = await aioredis.from_url(REDIS_URL, decode_responses=True)
                            await redis_client.setex("streamer:watched_markets_changed", 60, "1")
                            await redis_client.close()
                            logger.debug("🔔 Notified streamer of resolved market cleanup")
                    except Exception as e:
                        logger.debug(f"⚠️ Failed to notify streamer of cleanup: {e}")

                return deleted_count

        except Exception as e:
            logger.error(f"❌ Error removing resolved markets: {e}")
            return 0

    async def cleanup_inactive_watched_markets(self) -> int:
        """
        Remove markets from watched_markets that don't have active user positions.
        This ensures WebSocket streamer only monitors markets where users actually have positions.

        Returns:
            Number of markets removed
        """
        try:
            from database import db_manager, WatchedMarkets, SessionLocal
            import aiohttp
            from core.services import user_service

            logger.info("🧹 [CLEANUP] Starting watched_markets cleanup for non-position markets...")

            # Get all users with wallets
            with SessionLocal() as db:
                from database import User
                users = db.query(User).filter(User.polygon_address.isnot(None)).all()

            # Collect all markets where users have open positions
            active_position_markets = set()

            connector = aiohttp.TCPConnector(limit=10, ttl_dns_cache=300)
            timeout = aiohttp.ClientTimeout(total=30)

            async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
                for user in users[:50]:  # Limit to 50 most recent users to avoid overload
                    try:
                        wallet = user.polygon_address
                        if not wallet:
                            continue

                        url = f"https://data-api.polymarket.com/positions?user={wallet}"
                        async with session.get(url) as response:
                            if response.status == 200:
                                positions = await response.json()
                                for pos in positions:
                                    if float(pos.get('size', 0)) >= 0.1:  # Non-dust positions
                                        condition_id = pos.get('conditionId')
                                        if condition_id:
                                            active_position_markets.add(condition_id)
                    except Exception as e:
                        logger.debug(f"⚠️ Could not fetch positions for user {user.id}: {e}")
                        continue

            logger.info(f"📊 [CLEANUP] Found {len(active_position_markets)} unique markets with active positions")

            # Remove watched markets NOT in active positions
            removed_count = 0
            with db_manager.get_session() as db:
                watched_markets = db.query(WatchedMarkets).all()

                for wm in watched_markets:
                    if wm.market_id not in active_position_markets:
                        db.delete(wm)
                        removed_count += 1
                        logger.debug(f"🗑️ [CLEANUP] Removed inactive watched market: {wm.market_id}")

                db.commit()

            logger.info(f"✅ [CLEANUP] Removed {removed_count} inactive markets from watched_markets")
            return removed_count

        except Exception as e:
            logger.error(f"❌ [CLEANUP] Error during watched_markets cleanup: {e}", exc_info=True)
            return 0

    async def _invalidate_streamer_cache(self):
        """Invalidate streamer cache to pick up watched market changes."""
        try:
            # This would need to call the streamer service to refresh its subscriptions
            # For now, just log
            logger.info("🔄 Streamer cache invalidation needed (not implemented yet)")
        except Exception as e:
            logger.error(f"❌ Error invalidating streamer cache: {e}")

    async def process_pending_watched_markets(self) -> int:
        """
        Process cached pending markets from Redis into DB (called every 10s).
        Reduces DB load by batching market additions.
        """
        try:
            import redis.asyncio as aioredis
            from config.config import REDIS_URL
            from database import db_manager, WatchedMarkets
            from datetime import datetime

            if not REDIS_URL:
                return 0

            redis_client = await aioredis.from_url(REDIS_URL, decode_responses=True)

            # Récupère tous les marchés en attente
            pending_keys = await redis_client.keys("pending_watched_markets:*")
            if not pending_keys:
                await redis_client.close()
                return 0

            # Extrait les market_ids
            market_ids = [key.replace("pending_watched_markets:", "") for key in pending_keys]

            logger.debug(f"📦 Processing {len(market_ids)} pending watched markets from cache")

            # Récupère les métadonnées pour ces marchés depuis subsquid_markets_poll
            with db_manager.get_session() as db:
                markets_data = db.query(SubsquidMarketPoll).filter(
                    SubsquidMarketPoll.market_id.in_(market_ids)
                ).all()

                processed_count = 0
                for market_data in markets_data:
                    try:
                        # Upsert dans watched_markets
                        now = datetime.utcnow()
                        db.execute("""
                            INSERT INTO watched_markets (market_id, condition_id, title, active_positions, last_position_at, created_at, updated_at)
                            VALUES (:market_id, :condition_id, :title, :position_count, :now, :now, :now)
                            ON CONFLICT (market_id) DO UPDATE SET
                                last_position_at = :now,
                                updated_at = :now
                        """, {
                            'market_id': market_data.market_id,
                            'condition_id': market_data.condition_id,
                            'title': market_data.title,
                            'position_count': 1,
                            'now': now
                        })

                        # Supprime du cache Redis
                        await redis_client.delete(f"pending_watched_markets:{market_data.market_id}")
                        processed_count += 1

                    except Exception as e:
                        logger.debug(f"⚠️ Failed to process pending market {market_data.market_id}: {e}")

                db.commit()

            await redis_client.close()

            if processed_count > 0:
                logger.info(f"✅ Processed {processed_count} pending watched markets from cache")

            return processed_count

        except Exception as e:
            logger.error(f"❌ Error processing pending watched markets: {e}")
            return 0

    async def force_refresh_watched_markets(self) -> Dict[str, int]:
        """
        Force a complete refresh of watched markets.
        Useful for manual triggering or after major position changes.
        """
        logger.info("🔄 Force refreshing watched markets...")
        return await self.scan_and_update_watched_markets()


# Singleton
_watched_markets_service = None

def get_watched_markets_service() -> WatchedMarketsService:
    """Get singleton instance of WatchedMarketsService."""
    global _watched_markets_service
    if _watched_markets_service is None:
        _watched_markets_service = WatchedMarketsService()
    return _watched_markets_service
