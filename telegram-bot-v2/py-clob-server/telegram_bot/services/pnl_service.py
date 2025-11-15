#!/usr/bin/env python3
"""
P&L SERVICE
Enterprise-grade profit and loss calculation with blockchain-verified positions
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import asyncio
import aiohttp
import requests

from .transaction_service import get_transaction_service
from .market_service import market_service

logger = logging.getLogger(__name__)

class PnLService:
    """
    ENTERPRISE-GRADE P&L CALCULATION SERVICE

    Features:
    - Blockchain-verified position data (via Polymarket API)
    - Real-time unrealized P&L with current market prices
    - Realized P&L from completed trades
    - Position-level and portfolio-level analytics
    - Cost basis tracking from transaction history
    """

    def __init__(self):
        self.transaction_service = get_transaction_service()
        logger.info("✅ P&L Service initialized (blockchain-based)")

    async def _fetch_blockchain_positions(self, wallet_address: str) -> List[Dict]:
        """
        Fetch current positions from blockchain via Polymarket API (ASYNC)
        Uses Redis cache for performance (same as /positions command)

        Args:
            wallet_address: User's Polygon wallet address

        Returns:
            List of position dictionaries from blockchain
        """
        try:
            # Try Redis cache first
            from core.services.redis_price_cache import get_redis_cache
            redis_cache = get_redis_cache()

            cached_positions = redis_cache.get_user_positions(wallet_address)
            if cached_positions is not None:
                logger.info(f"🚀 CACHE HIT: Loaded {len(cached_positions)} positions from Redis")
                return cached_positions

            # Cache miss - fetch from blockchain (ASYNC)
            logger.info(f"💨 CACHE MISS: Fetching positions from blockchain API for {wallet_address[:10]}...")

            import aiohttp
            from core.utils.aiohttp_client import get_http_client
            session = await get_http_client()

            positions = []

            # 1. Fetch ACTIVE positions
            active_url = f"https://data-api.polymarket.com/positions?user={wallet_address}&limit=100"
            logger.debug(f"📡 Fetching active positions from {active_url}")

            async with session.get(active_url, timeout=aiohttp.ClientTimeout(total=10)) as active_response:
                if active_response.status == 200:
                    active_positions = await active_response.json()
                    positions.extend(active_positions)
                    logger.debug(f"✅ Found {len(active_positions)} active positions")
                else:
                    logger.error(f"❌ Failed to fetch active positions: HTTP {active_response.status}")

            # 2. Fetch CLOSED positions (for redemption detection)
            closed_url = f"https://data-api.polymarket.com/closed-positions?user={wallet_address}&limit=100"
            logger.debug(f"📡 Fetching closed positions from {closed_url}")

            async with session.get(closed_url, timeout=aiohttp.ClientTimeout(total=10)) as closed_response:
                if closed_response.status == 200:
                    closed_positions = await closed_response.json()

                    # Filter to only include positions with positive PnL (potential winners)
                    redeemable_closed = [pos for pos in closed_positions if pos.get('realizedPnl', 0) > 0]

                    # Add redeemable flag for closed positions with positive PnL
                    for pos in redeemable_closed:
                        pos['redeemable'] = True  # Mark as potentially redeemable
                        pos['closed'] = True      # Mark as closed position

                    positions.extend(redeemable_closed)
                    logger.debug(f"✅ Found {len(closed_positions)} closed positions, {len(redeemable_closed)} potentially redeemable")
                else:
                    logger.error(f"❌ Failed to fetch closed positions: HTTP {closed_response.status}")

            logger.info(f"📊 Total positions fetched: {len(positions)} (active + redeemable closed)")

            # Cache for 180 seconds (same as /positions)
            from config.config import POSITION_CACHE_TTL
            redis_cache.cache_user_positions(wallet_address, positions, ttl=POSITION_CACHE_TTL)

            logger.info(f"✅ Fetched {len(positions)} positions from blockchain (cached)")
            return positions

        except Exception as e:
            logger.error(f"❌ Error fetching blockchain positions: {e}")
            return []

    async def get_current_market_price(self, market_id: str, outcome: str) -> Optional[float]:
        """
        Get current market price for a specific outcome
        Uses PriceCalculator with WebSocket priority for real-time prices

        Args:
            market_id: Market identifier
            outcome: 'yes' or 'no'

        Returns:
            Current price or None if not available
        """
        try:
            # Use PriceCalculator with WebSocket priority for real-time prices
            from telegram_bot.services.price_calculator import PriceCalculator
            from py_clob_client import ClobClient

            # Get client for orderbook/API fallback
            client = ClobClient("", "", "", "")

            # Get token_id for this market outcome
            from database import db_manager, SubsquidMarketPoll

            with db_manager.get_session() as db:
                market = db.query(SubsquidMarketPoll).filter(
                    SubsquidMarketPoll.condition_id == market_id
                ).first()

                if market and market.clob_token_ids:
                    # Parse token IDs to find the right one for this outcome
                    import json
                    try:
                        token_ids = json.loads(market.clob_token_ids.replace('\\"', '"'))
                        if isinstance(token_ids, list) and len(token_ids) >= 2:
                            # Token IDs are usually [yes_token, no_token]
                            token_index = 0 if outcome.lower() == 'yes' else 1
                            if token_index < len(token_ids):
                                token_id = token_ids[token_index]

                                # Use PriceCalculator with WebSocket priority
                                price, source = PriceCalculator.get_price_for_position_display(
                                    client, token_id, outcome, None, market_id
                                )

                                if price:
                                    logger.info(f"✅ PnL PRICE ({source}): ${price:.6f} for {market_id} {outcome}")
                                    return price

                    except Exception as parse_err:
                        logger.warning(f"⚠️ Failed to parse token IDs for market {market_id}: {parse_err}")

            # Fallback to old method if token lookup fails
            logger.warning(f"💨 Token lookup failed for {market_id} {outcome}, using legacy method")
            return await self._get_legacy_market_price(market_id, outcome)

        except Exception as e:
            logger.error(f"❌ Error getting current market price: {e}")
            return None

    async def _get_legacy_market_price(self, market_id: str, outcome: str) -> Optional[float]:
        """
        Legacy method for getting market prices (fallback only)
        """
        try:
            # Try to get from market service first
            market = market_service.get_market_by_id(market_id)
            if market and market.get('outcome_prices'):
                outcome_prices = market['outcome_prices']
                if isinstance(outcome_prices, list) and len(outcome_prices) >= 2:
                    # outcome_prices is usually ["0.8955", "0.1045"] for [Yes, No]
                    if outcome.lower() == 'yes':
                        return float(outcome_prices[0])
                    elif outcome.lower() == 'no':
                        return float(outcome_prices[1])
                elif isinstance(outcome_prices, dict):
                    price_key = outcome.lower()
                    if price_key in outcome_prices:
                        return float(outcome_prices[price_key])

            # Fallback to Gamma API for real-time prices
            async with aiohttp.ClientSession() as session:
                url = f"https://gamma-api.polymarket.com/markets/{market_id}"
                async with session.get(url) as response:
                    if response.status == 200:
                        data = await response.json()
                        outcome_prices = data.get('outcome_prices', [])

                        # Find price for the specific outcome
                        for price_data in outcome_prices:
                            if price_data.get('outcome') == outcome.lower():
                                return float(price_data.get('price', 0))

            logger.warning(f"⚠️ Could not get current price for {market_id} {outcome}")
            return None

        except Exception as e:
            logger.error(f"❌ Error getting legacy market price: {e}")
            return None

    async def calculate_position_pnl(self, user_id: int, market_id: str, outcome: str) -> Dict:
        """
        Calculate P&L for a specific position

        Args:
            user_id: Telegram user ID
            market_id: Market identifier
            outcome: Position outcome

        Returns:
            Detailed P&L analysis for the position
        """
        try:
            # Get position history from transactions
            position_history = self.transaction_service.get_position_history(user_id, market_id, outcome)

            if not position_history:
                return {
                    'market_id': market_id,
                    'outcome': outcome,
                    'current_tokens': 0,
                    'realized_pnl': 0,
                    'unrealized_pnl': 0,
                    'total_pnl': 0,
                    'error': 'No position found'
                }

            current_tokens = position_history['current_tokens']
            realized_pnl = position_history['realized_pnl']

            # Calculate unrealized P&L if user still holds tokens
            unrealized_pnl = 0
            current_price = None

            if current_tokens > 0:
                current_price = await self.get_current_market_price(market_id, outcome)
                if current_price is not None:
                    # Calculate unrealized P&L
                    avg_buy_price = position_history['avg_buy_price']
                    unrealized_pnl = current_tokens * (current_price - avg_buy_price)

            total_pnl = realized_pnl + unrealized_pnl

            # Calculate performance metrics
            total_invested = position_history['total_cost']
            roi_percentage = (total_pnl / total_invested * 100) if total_invested > 0 else 0

            return {
                'market_id': market_id,
                'outcome': outcome,
                'current_tokens': current_tokens,
                'total_bought': position_history['total_bought'],
                'total_sold': position_history['total_sold'],
                'total_cost': position_history['total_cost'],
                'total_proceeds': position_history['total_proceeds'],
                'avg_buy_price': position_history['avg_buy_price'],
                'avg_sell_price': position_history['avg_sell_price'],
                'current_price': current_price,
                'realized_pnl': realized_pnl,
                'unrealized_pnl': unrealized_pnl,
                'total_pnl': total_pnl,
                'roi_percentage': roi_percentage,
                'transaction_count': position_history['transaction_count'],
                'first_trade': position_history['first_trade'],
                'last_trade': position_history['last_trade']
            }

        except Exception as e:
            logger.error(f"❌ Error calculating position P&L: {e}")
            return {
                'market_id': market_id,
                'outcome': outcome,
                'error': str(e)
            }

    async def calculate_portfolio_pnl(self, user_id: int) -> Dict:
        """
        Calculate total portfolio P&L for a user using BLOCKCHAIN positions

        NEW: Uses blockchain API (like /positions) for accurate position count
        Then enriches with database transaction history for P&L calculations

        Args:
            user_id: Telegram user ID

        Returns:
            Portfolio-wide P&L analysis with blockchain-verified position count
        """
        try:
            # Step 1: Get wallet address
            from core.services import user_service
            wallet = user_service.get_user_wallet(user_id)

            if not wallet:
                return {
                    'total_positions': 0,
                    'total_realized_pnl': 0,
                    'total_unrealized_pnl': 0,
                    'total_pnl': 0,
                    'total_invested': 0,
                    'portfolio_roi': 0,
                    'positions': [],
                    'error': 'No wallet found'
                }

            wallet_address = wallet['address']

            # Step 2: Fetch BLOCKCHAIN positions (real on-chain holdings)
            logger.info(f"📊 Fetching blockchain positions for user {user_id}...")
            blockchain_positions = await self._fetch_blockchain_positions(wallet_address)

            # DEBUG: Log what we actually received from blockchain
            if blockchain_positions:
                logger.info(f"🔍 DEBUG: Blockchain returned {len(blockchain_positions)} positions")
                for idx, pos in enumerate(blockchain_positions[:2]):  # Log first 2 for debugging
                    logger.info(f"🔍 DEBUG: Position {idx} keys: {list(pos.keys())}")
                    logger.info(f"🔍 DEBUG: Position {idx} sample: market={pos.get('market')}, conditionId={pos.get('conditionId')}, asset={pos.get('asset', '')[:20]}...")

            if not blockchain_positions:
                logger.info(f"📭 No blockchain positions found for user {user_id}")

                # Still calculate realized P&L from sold positions
                all_transactions = self.transaction_service.calculate_current_positions(user_id)
                total_realized = 0
                total_invested = 0

                # Check for fully closed positions (sold everything)
                for pos_key, pos in all_transactions.items():
                    if pos['tokens'] <= 0.001:  # Fully closed
                        history = self.transaction_service.get_position_history(
                            user_id, pos['market_id'], pos['outcome']
                        )
                        if history:
                            total_realized += history.get('total_proceeds', 0) - history.get('total_cost', 0)
                            total_invested += history.get('total_cost', 0)

                return {
                    'total_positions': 0,
                    'total_realized_pnl': total_realized,
                    'total_unrealized_pnl': 0,
                    'total_pnl': total_realized,
                    'total_invested': total_invested,
                    'portfolio_roi': (total_realized / total_invested * 100) if total_invested > 0 else 0,
                    'positions': []
                }

            # Step 3: Initialize portfolio stats
            portfolio_stats = {
                'total_positions': len(blockchain_positions),  # ACCURATE COUNT from blockchain
                'total_realized_pnl': 0,
                'total_unrealized_pnl': 0,
                'total_pnl': 0,
                'total_invested': 0,
                'portfolio_roi': 0,
                'positions': []
            }

            logger.info(f"✅ Found {len(blockchain_positions)} REAL positions on blockchain")

            # Step 4: For each blockchain position, calculate P&L from transaction history
            for bc_position in blockchain_positions:
                try:
                    # Extract market info from blockchain position
                    # Polymarket API can return different field structures:
                    # - "market": numeric ID like "559653"
                    # - "asset": hex token ID like "0x7d6c44..."
                    # - "conditionId": hex condition ID
                    # - "asset_id": alternative name for asset

                    # First, try to get the blockchain market identifier
                    blockchain_market_id = (
                        bc_position.get('market') or
                        bc_position.get('conditionId') or
                        bc_position.get('asset_id') or
                        bc_position.get('asset')
                    )
                    outcome = bc_position.get('outcome', '').lower()

                    if not blockchain_market_id or not outcome:
                        logger.warning(f"⚠️ Blockchain position missing identifiers: {list(bc_position.keys())}")
                        continue

                    logger.debug(f"🔍 Processing blockchain position: market={blockchain_market_id}, outcome={outcome}")

                    # CRITICAL FIX: Translate blockchain ID to database slug
                    # The blockchain returns numeric/hex IDs, but our database stores slug IDs
                    # Use market_service to get the full market data and extract the correct ID
                    market_data = None
                    database_market_id = None

                    # Try to get market by blockchain ID (market_service handles condition_id lookups)
                    if blockchain_market_id.startswith('0x'):
                        # It's a condition_id (hex), market_service can look it up
                        market_data = market_service.get_market_by_id(blockchain_market_id)
                    else:
                        # It's a numeric ID - we need to query database differently
                        # For now, log this case and skip (will add proper lookup if needed)
                        logger.warning(f"⚠️ Numeric market ID from blockchain: {blockchain_market_id} - trying as condition_id")
                        # Try it anyway - maybe it's stored as condition_id
                        market_data = market_service.get_market_by_id(blockchain_market_id)

                    if market_data:
                        # SUCCESS: Found the market, use its database ID (slug format)
                        database_market_id = market_data.get('id')
                        logger.info(f"✅ Translated blockchain ID {blockchain_market_id} → database ID {database_market_id}")
                    else:
                        # FALLBACK: Market not found in database
                        # This can happen if:
                        # 1. Market is too old (not in our database)
                        # 2. Market was never synced
                        # 3. ID format we don't support yet
                        logger.warning(f"⚠️ Could not find market in database for blockchain ID: {blockchain_market_id}")

                        # Try using the blockchain ID directly as last resort
                        database_market_id = blockchain_market_id

                    # Calculate P&L for this position using database market ID
                    position_pnl = await self.calculate_position_pnl(user_id, database_market_id, outcome)

                    if 'error' not in position_pnl:
                        portfolio_stats['total_realized_pnl'] += position_pnl['realized_pnl']
                        portfolio_stats['total_unrealized_pnl'] += position_pnl['unrealized_pnl']
                        portfolio_stats['total_invested'] += position_pnl['total_cost']

                        # Add market question for display
                        if not market_data:
                            market_data = market_service.get_market_by_id(database_market_id)
                        position_pnl['market_question'] = market_data.get('question') if market_data else "Unknown Market"

                        portfolio_stats['positions'].append(position_pnl)
                        logger.info(f"✅ P&L calculated for {database_market_id}: ${position_pnl['total_pnl']:.2f}")
                    else:
                        logger.warning(f"⚠️ Error calculating P&L for {database_market_id}: {position_pnl.get('error')}")

                except Exception as e:
                    logger.error(f"❌ Error processing blockchain position: {e}")
                    import traceback
                    logger.error(traceback.format_exc())
                    continue

            # Step 5: Calculate total P&L and ROI
            portfolio_stats['total_pnl'] = portfolio_stats['total_realized_pnl'] + portfolio_stats['total_unrealized_pnl']

            # Calculate portfolio ROI
            if portfolio_stats['total_invested'] > 0:
                portfolio_stats['portfolio_roi'] = (portfolio_stats['total_pnl'] / portfolio_stats['total_invested']) * 100

            logger.info(f"📊 PORTFOLIO P&L: User {user_id} - {portfolio_stats['total_positions']} positions, Total P&L: ${portfolio_stats['total_pnl']:.2f} ({portfolio_stats['portfolio_roi']:.1f}% ROI)")
            return portfolio_stats

        except Exception as e:
            logger.error(f"❌ Error calculating portfolio P&L: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return {
                'total_positions': 0,
                'total_realized_pnl': 0,
                'total_unrealized_pnl': 0,
                'total_pnl': 0,
                'total_invested': 0,
                'portfolio_roi': 0,
                'positions': [],
                'error': str(e)
            }

    def get_trading_statistics(self, user_id: int, days: int = 30) -> Dict:
        """
        Get trading statistics for a user

        Args:
            user_id: Telegram user ID
            days: Number of days to analyze

        Returns:
            Trading statistics and metrics
        """
        try:
            # Get recent transactions
            transactions = self.transaction_service.get_user_transactions(user_id, limit=1000)

            if not transactions:
                return {
                    'total_trades': 0,
                    'buy_trades': 0,
                    'sell_trades': 0,
                    'total_volume': 0,
                    'avg_trade_size': 0,
                    'most_active_day': None,
                    'trading_days': 0
                }

            # Filter transactions by date range
            cutoff_date = datetime.utcnow() - timedelta(days=days)
            recent_transactions = [
                tx for tx in transactions
                if datetime.fromisoformat(tx['executed_at'].replace('Z', '+00:00')) >= cutoff_date
            ]

            if not recent_transactions:
                return {
                    'total_trades': 0,
                    'period_days': days,
                    'message': f'No trades in the last {days} days'
                }

            # Calculate statistics
            buy_trades = [tx for tx in recent_transactions if tx['transaction_type'] == 'BUY']
            sell_trades = [tx for tx in recent_transactions if tx['transaction_type'] == 'SELL']

            total_volume = sum(tx['total_amount'] for tx in recent_transactions)
            avg_trade_size = total_volume / len(recent_transactions) if recent_transactions else 0

            # Find most active trading day
            trading_days = {}
            for tx in recent_transactions:
                trade_date = datetime.fromisoformat(tx['executed_at'].replace('Z', '+00:00')).date()
                trading_days[trade_date] = trading_days.get(trade_date, 0) + 1

            most_active_day = max(trading_days.items(), key=lambda x: x[1]) if trading_days else None

            return {
                'period_days': days,
                'total_trades': len(recent_transactions),
                'buy_trades': len(buy_trades),
                'sell_trades': len(sell_trades),
                'total_volume': total_volume,
                'avg_trade_size': avg_trade_size,
                'trading_days': len(trading_days),
                'most_active_day': {
                    'date': most_active_day[0].isoformat(),
                    'trades': most_active_day[1]
                } if most_active_day else None,
                'buy_volume': sum(tx['total_amount'] for tx in buy_trades),
                'sell_volume': sum(tx['total_amount'] for tx in sell_trades)
            }

        except Exception as e:
            logger.error(f"❌ Error calculating trading statistics: {e}")
            return {
                'error': str(e)
            }

# Global instance
pnl_service = PnLService()

def get_pnl_service():
    """Get the global P&L service"""
    return pnl_service
