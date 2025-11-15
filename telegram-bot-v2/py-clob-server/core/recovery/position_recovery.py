"""
Position Recovery System
Recovers lost positions from Polymarket API trade history
"""

import logging
import time
import asyncio
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta

from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds, TradeParams
from py_clob_client.constants import POLYGON

from database import db_manager  # Position-related imports removed

logger = logging.getLogger(__name__)

class PositionRecoveryEngine:
    """Recovers lost positions from Polymarket API trade history"""

    def __init__(self):
        self.market_db = MarketDatabase()
        logger.info("🔧 Position Recovery Engine initialized")

    def recover_user_positions(self, user_id: int) -> Dict[str, Dict]:
        """
        Recover all positions for a user by analyzing their trade history
        This is the main recovery function!
        """
        logger.info(f"🔍 Starting position recovery for user {user_id}")

        try:
            # Get user's API credentials and wallet
            with db_manager.get_session() as db:
                api_key_record = db.query(UserApiKey).filter(UserApiKey.user_id == user_id).first()
                wallet_record = db.query(UserWallet).filter(UserWallet.user_id == user_id).first()

                if not api_key_record or not wallet_record:
                    logger.error(f"❌ No API credentials or wallet found for user {user_id}")
                    return {}

                # Create Polymarket client
                creds = ApiCreds(
                    api_key=api_key_record.api_key,
                    api_secret=api_key_record.api_secret,
                    api_passphrase=api_key_record.api_passphrase,
                )

                client = ClobClient(
                    host="https://clob.polymarket.com",
                    key=wallet_record.private_key,
                    chain_id=POLYGON,
                    creds=creds
                )

                logger.info(f"✅ Created Polymarket client for user {user_id}")

                # Get trade history
                recovered_positions = self._analyze_trade_history(client, wallet_record.address)

                # Save recovered positions to database
                if recovered_positions:
                    self._save_recovered_positions(user_id, recovered_positions)
                    logger.info(f"🎉 RECOVERED {len(recovered_positions)} positions for user {user_id}")
                else:
                    logger.warning(f"⚠️ No positions found to recover for user {user_id}")

                return recovered_positions

        except Exception as e:
            logger.error(f"❌ Position recovery failed for user {user_id}: {e}")
            return {}

    def _analyze_trade_history(self, client: ClobClient, wallet_address: str) -> Dict[str, Dict]:
        """Analyze trade history to reconstruct current positions"""
        logger.info(f"📊 Analyzing trade history for wallet {wallet_address}")

        try:
            # Try multiple approaches to get trade data

            # Approach 1: Get trades for this specific wallet
            logger.info("🔍 Attempting to get trades by maker address...")
            trades_response = client.get_trades(
                TradeParams(
                    maker_address=wallet_address,
                )
            )

            logger.info(f"📊 Trades response: {trades_response}")

            # Approach 2: If no maker trades, try without specific address (get all user trades)
            if not trades_response or 'data' not in trades_response or not trades_response['data']:
                logger.info("🔍 No maker trades found, trying general trades...")
                trades_response = client.get_trades()
                logger.info(f"📊 General trades response: {trades_response}")

            # Approach 3: Get orders instead of trades (might show more data)
            if not trades_response or 'data' not in trades_response or not trades_response['data']:
                logger.info("🔍 No trades found, trying orders...")
                try:
                    # Use get_orders without OrderParams - check what parameters it accepts
                    orders_response = client.get_orders()
                    logger.info(f"📊 Orders response: {orders_response}")

                    # Convert orders to trade-like format if they exist
                    if orders_response and 'data' in orders_response:
                        logger.info(f"📋 Found {len(orders_response['data'])} orders")
                        # For now, just log the orders - we'd need to process filled orders
                        for order in orders_response['data'][:3]:  # Show first 3
                            logger.info(f"📋 Order: {order}")
                except Exception as e:
                    logger.warning(f"⚠️ Could not get orders: {e}")

            if not trades_response or 'data' not in trades_response:
                logger.warning("⚠️ No trade data returned from API")
                logger.warning(f"⚠️ API Response: {trades_response}")
                return {}

            trades = trades_response['data']
            logger.info(f"📈 Found {len(trades)} trades in history")

            if not trades:
                logger.warning("⚠️ Empty trades list - user may not have made any trades yet")
                return {}

            # Group trades by market to calculate net positions
            market_positions = {}

            for trade in trades:
                try:
                    market_id = trade.get('market')
                    outcome = trade.get('outcome')
                    side = trade.get('side')  # 'buy' or 'sell'
                    size = float(trade.get('size', 0))
                    price = float(trade.get('price', 0))

                    logger.info(f"📊 Processing trade: {market_id} {outcome} {side} {size} @ {price}")

                    if not all([market_id, outcome, side, size > 0]):
                        logger.warning(f"⚠️ Skipping incomplete trade: {trade}")
                        continue

                    # Initialize market position tracking
                    if market_id not in market_positions:
                        market_positions[market_id] = {
                            'yes_tokens': 0,
                            'no_tokens': 0,
                            'yes_cost': 0,
                            'no_cost': 0,
                            'trades': []
                        }

                    # Track the trade
                    market_positions[market_id]['trades'].append({
                        'side': side,
                        'outcome': outcome,
                        'size': size,
                        'price': price,
                        'timestamp': trade.get('timestamp')
                    })

                    # Calculate net position
                    if side == 'buy':
                        if outcome == 'yes':
                            market_positions[market_id]['yes_tokens'] += size
                            market_positions[market_id]['yes_cost'] += size * price
                        else:  # outcome == 'no'
                            market_positions[market_id]['no_tokens'] += size
                            market_positions[market_id]['no_cost'] += size * price

                    elif side == 'sell':
                        if outcome == 'yes':
                            market_positions[market_id]['yes_tokens'] -= size
                            # Adjust cost proportionally
                            if market_positions[market_id]['yes_tokens'] > 0:
                                cost_ratio = market_positions[market_id]['yes_tokens'] / (market_positions[market_id]['yes_tokens'] + size)
                                market_positions[market_id]['yes_cost'] *= cost_ratio
                        else:  # outcome == 'no'
                            market_positions[market_id]['no_tokens'] -= size
                            if market_positions[market_id]['no_tokens'] > 0:
                                cost_ratio = market_positions[market_id]['no_tokens'] / (market_positions[market_id]['no_tokens'] + size)
                                market_positions[market_id]['no_cost'] *= cost_ratio

                except Exception as e:
                    logger.warning(f"⚠️ Error processing trade: {e}")
                    continue

            # Convert to final position format
            final_positions = {}

            for market_id, position_data in market_positions.items():
                # Check for active positions (net positive tokens)
                if position_data['yes_tokens'] > 0.001:  # Small threshold for floating point
                    avg_price = position_data['yes_cost'] / position_data['yes_tokens'] if position_data['yes_tokens'] > 0 else 0

                    # Get market data
                    market_data = self._get_market_data(market_id)

                    final_positions[market_id] = {
                        'outcome': 'yes',
                        'tokens': position_data['yes_tokens'],
                        'buy_price': avg_price,
                        'total_cost': position_data['yes_cost'],
                        'market': market_data,
                        'buy_time': time.time(),
                        'recovered': True,
                        'recovery_method': 'api_trade_history'
                    }

                elif position_data['no_tokens'] > 0.001:
                    avg_price = position_data['no_cost'] / position_data['no_tokens'] if position_data['no_tokens'] > 0 else 0

                    # Get market data
                    market_data = self._get_market_data(market_id)

                    final_positions[market_id] = {
                        'outcome': 'no',
                        'tokens': position_data['no_tokens'],
                        'buy_price': avg_price,
                        'total_cost': position_data['no_cost'],
                        'market': market_data,
                        'buy_time': time.time(),
                        'recovered': True,
                        'recovery_method': 'api_trade_history'
                    }

            logger.info(f"🎯 Reconstructed {len(final_positions)} active positions")
            return final_positions

        except Exception as e:
            logger.error(f"❌ Trade history analysis failed: {e}")
            return {}

    def _get_market_data(self, market_id: str) -> Optional[Dict]:
        """Get market data for a market ID"""
        try:
            markets = self.market_db.get_markets()
            for market in markets:
                if market.get('id') == market_id:
                    return market

            logger.warning(f"⚠️ Market data not found for {market_id}")
            return None

        except Exception as e:
            logger.error(f"❌ Error getting market data for {market_id}: {e}")
            return None

    def _save_recovered_positions(self, user_id: int, positions: Dict[str, Dict]):
        """Save recovered positions to PostgreSQL database"""
        logger.info(f"💾 Saving {len(positions)} recovered positions to database")

        try:
            with db_manager.get_session() as db:
                for market_id, position_data in positions.items():
                    # Check if position already exists
                    existing = db.query(UserPosition).filter(
                        UserPosition.user_id == user_id,
                        UserPosition.market_id == market_id,
                        UserPosition.is_active == True
                    ).first()

                    if not existing:
                        position = UserPosition(
                            user_id=user_id,
                            market_id=market_id,
                            outcome=position_data['outcome'],
                            tokens=position_data['tokens'],
                            buy_price=position_data['buy_price'],
                            total_cost=position_data['total_cost'],
                            market_data=position_data['market'],
                            buy_time=datetime.fromtimestamp(position_data['buy_time']),
                            is_active=True
                        )
                        db.add(position)
                        logger.info(f"💾 Saved recovered position: {position_data['tokens']} {position_data['outcome']} tokens in market {market_id}")

                db.commit()
                logger.info("✅ All recovered positions saved to database")

        except Exception as e:
            logger.error(f"❌ Failed to save recovered positions: {e}")

    def get_recovery_status(self, user_id: int) -> Dict[str, Any]:
        """Get recovery status for a user"""
        try:
            with db_manager.get_session() as db:
                positions = db.query(UserPosition).filter(
                    UserPosition.user_id == user_id,
                    UserPosition.is_active == True
                ).all()

                total_positions = len(positions)
                total_value = sum(pos.total_cost for pos in positions)

                return {
                    'user_id': user_id,
                    'total_positions': total_positions,
                    'total_invested': total_value,
                    'recovery_available': total_positions == 0,  # Can recover if no positions
                    'last_recovery': None  # TODO: Track recovery attempts
                }

        except Exception as e:
            logger.error(f"❌ Error getting recovery status: {e}")
            return {'error': str(e)}

# Global recovery engine instance
recovery_engine = PositionRecoveryEngine()
