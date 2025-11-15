"""
Smart Wallet Position Tracker
Manages positions held by smart trading wallets
"""

from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from sqlalchemy import select, and_, desc, text

from core.database.connection import get_db
from infrastructure.logging.logger import get_logger

logger = get_logger(__name__)


class SmartWalletPositionTracker:
    """
    Service for tracking positions held by smart wallets
    """

    async def track_position(self, trade_data: Dict[str, Any]) -> bool:
        """
        Track a position from a smart wallet trade

        Args:
            trade_data: Dictionary containing trade information
                - market_id: Market identifier
                - smart_wallet_address: Smart wallet address
                - outcome: YES/NO
                - entry_price: Price at entry
                - size: Amount of tokens
                - amount_usdc: USDC value
                - position_id: Token ID from blockchain (optional)

        Returns:
            bool: True if position was tracked successfully
        """
        try:
            async with get_db() as db:
                # Check if position already exists
                existing_result = await db.execute(
                    text("""
                        SELECT id FROM smart_traders_positions
                        WHERE smart_wallet_address = :address
                        AND market_id = :market_id
                        AND outcome = :outcome
                        AND is_active = true
                    """),
                    {
                        'address': trade_data['smart_wallet_address'],
                        'market_id': trade_data['market_id'],
                        'outcome': trade_data['outcome']
                    }
                )
                existing = existing_result.scalar_one_or_none()

                if existing:
                    # Update existing position (accumulate)
                    await db.execute(
                        text("""
                            UPDATE smart_traders_positions
                            SET size = size + :size,
                                amount_usdc = amount_usdc + :amount_usdc,
                                entry_price = ((entry_price * size) + (:price * :size)) / (size + :size),
                                updated_at = :timestamp
                            WHERE id = :position_id
                        """),
                        {
                            'size': trade_data['size'],
                            'amount_usdc': trade_data['amount_usdc'],
                            'price': trade_data['entry_price'],
                            'timestamp': datetime.utcnow(),
                            'position_id': existing
                        }
                    )
                    logger.info(f"✅ Updated existing smart position for {trade_data['smart_wallet_address'][:8]}...")
                else:
                    # Create new position
                    await db.execute(
                        text("""
                            INSERT INTO smart_traders_positions
                            (market_id, smart_wallet_address, outcome, entry_price, size, amount_usdc, timestamp, position_id)
                            VALUES (:market_id, :address, :outcome, :price, :size, :amount_usdc, :timestamp, :position_id)
                        """),
                        {
                            'market_id': trade_data['market_id'],
                            'address': trade_data['smart_wallet_address'],
                            'outcome': trade_data['outcome'],
                            'price': trade_data['entry_price'],
                            'size': trade_data['size'],
                            'amount_usdc': trade_data['amount_usdc'],
                            'timestamp': datetime.utcnow(),
                            'position_id': trade_data.get('position_id')  # ✅ Store position_id
                        }
                    )
                    logger.info(f"✅ Created new smart position for {trade_data['smart_wallet_address'][:8]}...")

                await db.commit()
                return True

        except Exception as e:
            logger.error(f"❌ Error tracking smart position: {e}")
            return False

    async def get_wallet_positions(self, wallet_address: str) -> List[Dict[str, Any]]:
        """
        Get all active positions for a smart wallet

        Args:
            wallet_address: Smart wallet address

        Returns:
            List of position dictionaries
        """
        try:
            async with get_db() as db:
                result = await db.execute(
                    text("""
                        SELECT * FROM smart_traders_positions
                        WHERE smart_wallet_address = :address
                        AND is_active = true
                        ORDER BY timestamp DESC
                    """),
                    {'address': wallet_address}
                )
                rows = result.fetchall()

                positions = []
                for row in rows:
                    positions.append({
                        'id': row[0],
                        'market_id': row[1],
                        'smart_wallet_address': row[2],
                        'outcome': row[3],
                        'entry_price': float(row[4]),
                        'size': float(row[5]),
                        'amount_usdc': float(row[6]),
                        'timestamp': row[7],
                        'is_active': row[8],
                        'position_id': row[9]  # ✅ Include position_id in results
                    })

                logger.info(f"✅ Retrieved {len(positions)} positions for smart wallet {wallet_address[:8]}...")
                return positions

        except Exception as e:
            logger.error(f"❌ Error getting wallet positions for {wallet_address}: {e}")
            return []

    async def close_position(self, wallet_address: str, market_id: str, outcome: str) -> bool:
        """
        Mark a position as closed (inactive)

        Args:
            wallet_address: Smart wallet address
            market_id: Market identifier
            outcome: YES/NO outcome

        Returns:
            bool: True if position was closed successfully
        """
        try:
            async with get_db() as db:
                result = await db.execute(
                    text("""
                        UPDATE smart_traders_positions
                        SET is_active = false
                        WHERE smart_wallet_address = :address
                        AND market_id = :market_id
                        AND outcome = :outcome
                        AND is_active = true
                    """),
                    {
                        'address': wallet_address,
                        'market_id': market_id,
                        'outcome': outcome
                    }
                )

                await db.commit()

                if result.rowcount > 0:
                    logger.info(f"✅ Closed smart position for {wallet_address[:8]}... on {market_id}")
                    return True
                else:
                    logger.warning(f"⚠️ No active position found to close for {wallet_address[:8]}...")
                    return False

        except Exception as e:
            logger.error(f"❌ Error closing smart position: {e}")
            return False

    async def get_market_positions(self, market_id: str) -> List[Dict[str, Any]]:
        """
        Get all active positions for a specific market

        Args:
            market_id: Market identifier

        Returns:
            List of position dictionaries for the market
        """
        try:
            async with get_db() as db:
                result = await db.execute(
                    text("""
                        SELECT * FROM smart_traders_positions
                        WHERE market_id = :market_id
                        AND is_active = true
                        ORDER BY timestamp DESC
                    """),
                    {'market_id': market_id}
                )
                rows = result.fetchall()

                positions = []
                for row in rows:
                    positions.append({
                        'id': row[0],
                        'market_id': row[1],
                        'smart_wallet_address': row[2],
                        'outcome': row[3],
                        'entry_price': float(row[4]),
                        'size': float(row[5]),
                        'amount_usdc': float(row[6]),
                        'timestamp': row[7],
                        'is_active': row[8],
                        'position_id': row[9]  # ✅ Include position_id in results
                    })

                logger.info(f"✅ Retrieved {len(positions)} smart positions for market {market_id}")
                return positions

        except Exception as e:
            logger.error(f"❌ Error getting market positions for {market_id}: {e}")
            return []

    async def get_positions_stats(self) -> Dict[str, Any]:
        """
        Get statistics about smart wallet positions

        Returns:
            Dictionary with position statistics
        """
        try:
            async with get_db() as db:
                # Total active positions
                result = await db.execute(
                    text("SELECT COUNT(*) FROM smart_traders_positions WHERE is_active = true")
                )
                total_positions = result.scalar()

                # Total value locked
                result = await db.execute(
                    text("SELECT SUM(amount_usdc) FROM smart_traders_positions WHERE is_active = true")
                )
                total_value = float(result.scalar() or 0)

                # Unique markets with positions
                result = await db.execute(
                    text("SELECT COUNT(DISTINCT market_id) FROM smart_traders_positions WHERE is_active = true")
                )
                unique_markets = result.scalar()

                # Unique smart wallets with positions
                result = await db.execute(
                    text("SELECT COUNT(DISTINCT smart_wallet_address) FROM smart_traders_positions WHERE is_active = true")
                )
                unique_wallets = result.scalar()

                return {
                    'total_active_positions': total_positions,
                    'total_value_locked_usdc': total_value,
                    'unique_markets': unique_markets,
                    'unique_smart_wallets': unique_wallets
                }

        except Exception as e:
            logger.error(f"❌ Error getting position stats: {e}")
            return {
                'total_active_positions': 0,
                'total_value_locked_usdc': 0.0,
                'unique_markets': 0,
                'unique_smart_wallets': 0
            }
