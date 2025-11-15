"""
Smart Wallet Monitor Service
Monitors trades from curated smart wallets and tracks first-time market entries
"""

import logging
import csv
import os
import asyncio
import httpx
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Set

logger = logging.getLogger(__name__)


class SmartWalletMonitorService:
    """Service for monitoring smart wallet trading activity"""

    def __init__(self, wallet_repo, trade_repo, data_api_url: str):
        """
        Initialize the monitor service

        Args:
            wallet_repo: SmartWalletRepository instance
            trade_repo: SmartWalletTradeRepository instance
            data_api_url: Polymarket Data API base URL
        """
        self.wallet_repo = wallet_repo
        self.trade_repo = trade_repo
        self.data_api_url = data_api_url
        # Use async HTTP client instead of requests
        # Note: We keep the client open for reuse across scheduler runs
        self.client = httpx.AsyncClient(
            headers={
                'User-Agent': 'SmartWalletMonitor/1.0',
                'Accept': 'application/json'
            },
            timeout=15.0,
            # Add limits to prevent connection pool exhaustion
            limits=httpx.Limits(max_keepalive_connections=10, max_connections=50)
        )

    async def close(self):
        """Close the HTTP client properly"""
        if self.client:
            await self.client.aclose()
            logger.info("🔒 Smart wallet monitor HTTP client closed")

    async def sync_smart_wallets_from_csv(self, csv_path: str):
        """
        Load smart wallets from CSV file, deduplicate, and sync to database

        Args:
            csv_path: Path to CSV file (relative to main.py)
        """
        logger.info(f"📊 Loading smart wallets from {csv_path}")

        try:
            # Read and deduplicate wallets from CSV
            wallets_dict = {}  # Use dict to auto-deduplicate by address

            with open(csv_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    address = row.get('Adresse', '').strip()
                    if not address:
                        continue

                    # Keep first occurrence or update with latest data
                    if address not in wallets_dict:
                        wallets_dict[address] = {
                            'address': address,
                            'smartscore': float(row.get('Smartscore', 0)) if row.get('Smartscore') else None,
                            'win_rate': float(row.get('Win Rate', 0)) if row.get('Win Rate') else None,
                            'markets_count': int(row.get('Markets', 0)) if row.get('Markets') else None,
                            'realized_pnl': float(row.get('Realized PnL', 0)) if row.get('Realized PnL') else None,
                            'bucket_smart': row.get('Bucket smart', '').strip() or None,
                            'bucket_last_date': row.get('Bucket last date', '').strip() or None
                        }

            # Bulk upsert to database
            wallets_list = list(wallets_dict.values())
            count = self.wallet_repo.bulk_upsert_wallets(wallets_list)

            logger.info(f"✅ Synced {count} unique smart wallets to database (from {len(wallets_list)} in CSV)")

        except FileNotFoundError:
            logger.error(f"❌ CSV file not found: {csv_path}")
        except Exception as e:
            logger.error(f"❌ Error syncing wallets from CSV: {e}")

    async def fetch_and_store_wallet_trades(self, wallet_address: str, since_minutes: int = 10):
        """
        Fetch trades for a wallet from Polymarket API and store new ones

        Args:
            wallet_address: Ethereum wallet address
            since_minutes: Number of minutes to look back for trades (default: 10)
        """
        try:
            # Fetch trades from API using async client
            url = f"{self.data_api_url}/trades"
            params = {
                'user': wallet_address,
                'limit': 1000  # Max limit
            }

            response = await self.client.get(url, params=params)

            if response.status_code != 200:
                logger.debug(f"No trades for {wallet_address}: HTTP {response.status_code}")
                return

            all_trades = response.json()

            if not all_trades:
                logger.debug(f"No trades found for {wallet_address}")
                return

            # Filter trades by date (last N minutes)
            cutoff_date = datetime.now(timezone.utc) - timedelta(minutes=since_minutes)
            recent_trades = []

            for trade in all_trades:
                timestamp = trade.get('timestamp', 0)
                if timestamp == 0:
                    continue

                trade_date = datetime.fromtimestamp(timestamp, tz=timezone.utc)
                if trade_date >= cutoff_date:
                    recent_trades.append(trade)

            if not recent_trades:
                logger.debug(f"No recent trades ({since_minutes}min) for {wallet_address}")
                return

            # Get wallet's market history to determine first-time trades
            existing_markets = self.trade_repo.get_wallet_market_history(wallet_address)

            # Prepare trades for insertion
            trades_to_insert = []

            for trade in recent_trades:
                # Use transactionHash as unique ID (API doesn't provide 'id')
                trade_id = trade.get('transactionHash') or trade.get('id')
                market_id = trade.get('conditionId')

                if not trade_id or not market_id:
                    continue

                # Skip if trade already exists
                if self.trade_repo.trade_exists(trade_id):
                    continue

                # Determine if this is first-time on this market
                # It's first-time if the market is NOT in existing_markets
                is_first_time = market_id not in existing_markets

                # Calculate trade value with validation
                try:
                    price = float(trade.get('price', 0))
                    size = float(trade.get('size', 0))

                    # Validate ranges to prevent numeric overflow
                    if price > 999999.99999999 or price < 0:
                        logger.warning(f"⚠️ [SMART_WALLET] Price out of range: ${price}, skipping trade")
                        continue
                    if size > 999999999.99999999 or size < 0:
                        logger.warning(f"⚠️ [SMART_WALLET] Size out of range: {size}, skipping trade")
                        continue

                    value = price * size
                    if value > 999999999.99999999 or value < 0:
                        logger.warning(f"⚠️ [SMART_WALLET] Value out of range: ${value}, setting to 0")
                        value = 0

                except (ValueError, TypeError, OverflowError) as e:
                    logger.warning(f"⚠️ [SMART_WALLET] Invalid price/size for trade {trade_id}: {e}")
                    continue

                # Get market question (API provides 'title' field)
                market_question = trade.get('title', None)

                trade_data = {
                    'id': trade_id,
                    'wallet_address': wallet_address,
                    'market_id': market_id,
                    'side': trade.get('side', 'BUY').upper(),
                    'outcome': trade.get('outcome', None),
                    'price': price,
                    'size': size,
                    'value': value,
                    'timestamp': datetime.fromtimestamp(trade.get('timestamp', 0), tz=timezone.utc),
                    'is_first_time': is_first_time,
                    'market_question': market_question
                }

                trades_to_insert.append(trade_data)

                # Add market to existing markets set for subsequent trades
                existing_markets.add(market_id)

            # Bulk insert trades
            if trades_to_insert:
                inserted = self.trade_repo.bulk_add_trades(trades_to_insert)
                logger.info(f"✅ {wallet_address[:10]}... | Added {inserted} trades ({sum(1 for t in trades_to_insert if t['is_first_time'])} first-time)")

        except httpx.HTTPError as e:
            logger.debug(f"API error fetching trades for {wallet_address}: {e}")
        except Exception as e:
            logger.error(f"Error processing trades for {wallet_address}: {e}")

    async def sync_all_wallets(self, since_minutes: int = 10):
        """
        Sync trades for all monitored wallets

        Args:
            since_minutes: Number of minutes to look back (default: 10 for scheduler)
        """
        start_time = datetime.now(timezone.utc)
        logger.info(f"🔄 [SMART_WALLET_SYNC] Starting sync at {start_time.strftime('%Y-%m-%d %H:%M:%S UTC')}")
        logger.info(f"📊 [SMART_WALLET_SYNC] Looking back {since_minutes} minutes for new trades...")

        try:
            # Get all wallets from database
            wallets = self.wallet_repo.get_all_wallets()

            if not wallets:
                logger.warning("⚠️ [SMART_WALLET_SYNC] No smart wallets found in database")
                return

            logger.info(f"📊 [SMART_WALLET_SYNC] Syncing {len(wallets)} smart wallets...")

            total_synced = 0
            failed = 0
            total_new_trades_inserted = 0

            for i, wallet in enumerate(wallets, 1):
                try:
                    # Log progress every 50 wallets
                    if i % 50 == 0:
                        logger.info(f"📊 [SMART_WALLET_SYNC] Progress: {i}/{len(wallets)} wallets processed...")

                    # Fetch trades from last N minutes (not days!)
                    await self.fetch_and_store_wallet_trades(wallet.address, since_minutes=since_minutes)
                    total_synced += 1

                    # Rate limiting (300ms between requests) - use async sleep
                    await asyncio.sleep(0.3)

                except httpx.HTTPError as e:
                    logger.debug(f"⚠️ [SMART_WALLET_SYNC] HTTP error for {wallet.address[:10]}...: {e}")
                    failed += 1
                except Exception as e:
                    logger.error(f"❌ [SMART_WALLET_SYNC] Failed to sync {wallet.address[:10]}...: {e}")
                    failed += 1

            # Get stats
            total_trades = self.trade_repo.count_trades()
            first_time_trades = self.trade_repo.count_first_time_trades()

            end_time = datetime.now(timezone.utc)
            duration = (end_time - start_time).total_seconds()

            logger.info(f"✅ [SMART_WALLET_SYNC] Sync complete in {duration:.1f}s")
            logger.info(f"📊 [SMART_WALLET_SYNC] Results: {total_synced} synced, {failed} failed")
            logger.info(f"📊 [SMART_WALLET_SYNC] Database: {total_trades} total trades, {first_time_trades} first-time")

        except Exception as e:
            logger.error(f"❌ [SMART_WALLET_SYNC] Critical error in sync_all_wallets: {e}")
            import traceback
            logger.error(traceback.format_exc())
            # Re-raise to ensure scheduler knows there was a failure
            raise

    async def scheduled_sync(self):
        """
        Wrapper method for APScheduler to call every 10 minutes
        This is a class method that can be properly scheduled

        CRITICAL: Creates fresh database sessions for each run to avoid stale connections
        """
        from database import SessionLocal
        from core.persistence.smart_wallet_repository import SmartWalletRepository
        from core.persistence.smart_wallet_trade_repository import SmartWalletTradeRepository

        # Create FRESH session for this sync (don't reuse old one!)
        session = SessionLocal()

        try:
            logger.info("⏰ [SCHEDULER] Starting smart wallet sync (scheduled run)")

            # Create fresh repos with fresh session
            wallet_repo = SmartWalletRepository(session)
            trade_repo = SmartWalletTradeRepository(session)

            # Temporarily swap repos
            old_wallet_repo = self.wallet_repo
            old_trade_repo = self.trade_repo
            self.wallet_repo = wallet_repo
            self.trade_repo = trade_repo

            # Run sync
            await self.sync_all_wallets(since_minutes=10)

            # Restore old repos (for compatibility)
            self.wallet_repo = old_wallet_repo
            self.trade_repo = old_trade_repo

            logger.info("✅ [SCHEDULER] Smart wallet sync completed successfully")

        except Exception as e:
            logger.error(f"❌ [SCHEDULER] Smart wallet sync failed: {e}")
            import traceback
            logger.error(traceback.format_exc())
            raise
        finally:
            # Always close the fresh session
            try:
                session.close()
            except:
                pass
